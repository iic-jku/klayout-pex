#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/klayout-pex).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
# --------------------------------------------------------------------------------
#

"""Real field solves and independent circuit checks of saved matrix semantics."""

import json
import math
from pathlib import Path
import shutil
from typing import Any, Callable, Dict

import numpy as np
import pytest
from klayout_pex.tech_info import TechInfo

from klayout_pex.calibration.artifacts import read_message
from klayout_pex.calibration.patterns import read_patterns
from klayout_pex.calibration.prepare import prepare_calibration
from klayout_pex.calibration.solve import SolveOptions, solve_calibration
from klayout_pex.calibration.collect import collect_calibration
from klayout_pex.fastercap.result_collection import collect_fastercap_matrix
from klayout_pex_protobuf.kpex.calibration.solving_pb2 import CalibrationCollection
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.xyce import xyce_port_admittance, requires_xyce
from tests.common.vacask import vacask_port_admittance, requires_vacask


@pytest.mark.slow
@pytest.mark.fastercap
@pytest.mark.skipif(shutil.which('FasterCap') is None, reason='FasterCap is not installed')
def test_all_pattern_families_solve_and_recollect(tmp_path: Path, tech_info: TechInfo, pattern_data: Dict[str, Any]):
    pattern_data['patterns'].extend([
        {'id': 'substrate', 'substrate': {'layer': 'M1'}, 'width_um': '2', 'length_um': '4', 'role': 'TRAINING'},
        {'id': 'fringe_up', 'directional_fringe': {'edge_layer': 'M1', 'receiver_layer': 'M2',
         'receiver_width_um': '3', 'lateral_offset_um': '-1'}, 'width_um': '2', 'length_um': '4', 'role': 'TRAINING'},
        {'id': 'fringe_down', 'directional_fringe': {'edge_layer': 'M2', 'receiver_layer': 'M1',
         'receiver_width_um': '1', 'lateral_offset_um': '0'}, 'width_um': '2', 'length_um': '4', 'role': 'VALIDATION'},
    ])
    source = tmp_path / 'patterns.json'
    source.write_text(json.dumps(pattern_data), encoding='utf-8')
    preparation = prepare_calibration(tech_info, read_patterns(source), tmp_path / 'patterns')
    result = solve_calibration(preparation.manifest_path, tmp_path / 'runs', options=SolveOptions(
        jobs=1, mesh_refinement=0.05, gmres_tolerance=1e-7, solver_timeout_seconds=180))
    data = read_message(result.collection_path, CalibrationCollection())
    assert result.successful_cases == 5, data
    for case in data.cases:
        values = np.array([row.values for row in case.native_matrix.rows])
        assert np.isfinite(values).all()
        assert np.all(np.diag(values) > 0)
        # Independent invariants detect invalid units/order/signs without a
        # platform-specific golden matrix or claiming convergence qualification.
        assert np.linalg.eigvalsh((values + values.T) / 2).min() > 0
        assert list(case.measured_matrix.grounded_conductor_ids) == ['substrate']
        expected = 1 if case.case_id == 'substrate' else 2
        assert len(case.measured_matrix.rows) == expected
    again = collect_calibration(result.manifest_path, tmp_path / 'collected')
    assert read_message(again.manifest_path, CalibrationCollection()) == data


@pytest.mark.slow
@pytest.mark.parametrize('simulator', [pytest.param(ngspice_port_admittance, marks=requires_ngspice, id='ngspice'),
                                     pytest.param(xyce_port_admittance, marks=requires_xyce, id='Xyce'),
                                     pytest.param(vacask_port_admittance, marks=requires_vacask, id='VACASK')])
@pytest.mark.parametrize('single', [False, True])
def test_collected_grounded_matrix_matches_circuit(tmp_path: Path, simulator: Callable, single: bool):
    log = tmp_path / 'solver.log'
    if single:
        log.write_text('Capacitance matrix is:\nDimension 2 x 2\n'
                       'g1_G 6e-9 -3e-9\ng2_A -3e-9 7e-9\n', encoding='utf-8')
        circuit = '.subckt dut A\nCag A 0 3f\nCa_exterior A 0 4f\n.ends\n'
        signals = ['A']
    else:
        log.write_text('Capacitance matrix is:\nDimension 3 x 3\n'
                       'g1_B 5e-9 -2e-9 -1e-9\ng2_G -2e-9 6e-9 -3e-9\ng3_A -1e-9 -3e-9 7e-9\n', encoding='utf-8')
        circuit = ('.subckt dut A B\nCag A 0 3f\nCbg B 0 2f\nCab A B 1f\n'
                   'Ca_exterior A 0 3f\nCb_exterior B 0 2f\n.ends\n')
        signals = ['A', 'B']
    native, measured = collect_fastercap_matrix(log, signals, 'G')
    netlist = tmp_path / 'known-circuit.spice'
    netlist.write_text(circuit, encoding='utf-8')
    frequencies, actual = simulator(str(netlist), 'dut', signals, (3, 10), str(tmp_path))
    matrix = np.array([row.values for row in measured.rows])
    expected = (1j * math.tau * frequencies)[:, None, None] * matrix
    np.testing.assert_allclose(actual, expected, rtol=5e-6, atol=1e-20)
    # Grounding keeps the diagonal including exterior coupling. Taking only
    # -C[A,G], or eliminating G as floating, yields a different capacitance.
    assert matrix[0, 0] == pytest.approx(7e-15)
