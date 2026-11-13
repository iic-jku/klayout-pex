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

"""Source-sheet and per-cut laws survive CMOS5L catalog selection and real extraction."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Tuple

import allure
import numpy as np
import pytest

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist, SpiceScope
from klayout_pex.pdk_config import PDK
from klayout_pex.tech_info import TechInfo
from tests.common.cli_runner import run_cli
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.rc_networks import port_admittance
from tests.common.resistance_patterns import write_contact_array_lvsdb, write_strip_lvsdb
from tests.common.vacask import vacask_port_admittance, requires_vacask
from tests.common.xyce import xyce_port_admittance, requires_xyce


pytestmark = allure.parent_suite('Unit Tests')


@pytest.fixture(scope='module')
def extractions(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Tuple[Path, SpiceScope, float]]:
    work = tmp_path_factory.mktemp('cmos5l-resistance')
    technology = TechInfo.parse_tech_def(PDK.IHP_SG13CMOS5L.config.tech_pb_json_path)
    layers = {layer.name: layer for layer in technology.layers}
    corners = ('fixed-layout-low-r', 'nominal', 'fixed-layout-high-r')
    # Independent primary-source values in Ohm/square, including the ITF minimum
    # width and the adjacent database grid point to expose geometry corrections.
    rows = [
        ('GatPoly', 'poly_con', 'poly', 130, (6.2, 7.0, 7.8)),
        ('Metal1', 'metal1_n_mom', 'metal1', 160, (.085, .110, .135)),
        ('Metal2', 'metal2_n_mom', 'metal2', 200, (.073, .088, .103)),
        ('Metal3', 'metal3_n_mom', 'metal3', 200, (.073, .088, .103)),
        ('Metal4', 'metal4_n_mom', 'metal4', 200, (.073, .088, .103)),
        ('TopMetal1', 'topmetal1_con', 'topmetal1', 1640, (.015, .018, .021)),
    ]
    patterns = []
    for layer, drawing, prefix, width, values in rows:
        for actual_width in (width, width + 1):
            name = f'{layer}-{actual_width}'
            path = write_strip_lvsdb(work / f'{name}.lvsdb', layers[layer],
                                      (drawing, f'{prefix}_pin_con', f'{prefix}_text'), 10000, actual_width)
            patterns.append((name, path, tuple(value * 10000 / actual_width for value in values)))
    # The single-cut boundary and multiple parallel cuts test source RPV and its
    # conversion using 0.16um contacts versus the variant's 0.42um TopVia1 cuts.
    for poly_contact, label, values in ((True, 'poly-contact', (8., 15., 20.)),
                                       (False, 'TopVia1', (1., 2.2, 4.))):
        for count in (1, 2, 4):
            name = f'{label}-{count}'
            if poly_contact:
                lower, upper, cut, size, cut_lvs_name = 'GatPoly', 'Metal1', 'Cont', 160, 'cont_poly_con'
                lower_lvs = ('poly_con', 'poly_pin_con', 'poly_text')
                upper_lvs = ('metal1_n_mom', 'metal1_pin_con', 'metal1_text')
            else:
                lower, upper, cut, size, cut_lvs_name = 'Metal4', 'TopMetal1', 'TopVia1', 420, 'topvia1_n_cap'
                lower_lvs = ('metal4_n_mom', 'metal4_pin_con', 'metal4_text')
                upper_lvs = ('topmetal1_con', 'topmetal1_pin_con', 'topmetal1_text')
            path = write_contact_array_lvsdb(work / f'{name}.lvsdb', layers[lower], lower_lvs,
                                             layers[upper], upper_lvs, layers[cut], cut_lvs_name, size, count)
            patterns.append((name, path, tuple(value / count for value in values)))
    results = {}
    for name, source, values in patterns:
        for corner, expected in zip(corners, values):
            identity = f'{name}-{corner}'
            directory = work / identity
            destination = directory / 'extracted.spice'
            code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'ihp-sg13cmos5l',
                                                   '--2.5D', '--mode', 'R', '--corner', corner,
                                                   '--lvsdb', str(source), '--out-dir', str(directory),
                                                   '--out-netlist', str(destination)])
            assert code == 0, output
            scope = next(scope for scope in SpiceRCNetlist.read(str(destination)).scopes if scope.network.nodes())
            assert scope.ports == ['A', 'B']
            results[identity] = destination, scope, expected
    return results


def test_real_extraction_obeys_source_sheet_and_per_cut_laws(
        extractions: Dict[str, Tuple[Path, SpiceScope, float]]):
    for identity, (_, scope, resistance) in extractions.items():
        expected = np.array([[1, -1], [-1, 1]]) / resistance
        np.testing.assert_allclose(port_admittance(scope.network, scope.ports, 1e3), expected,
                                   rtol=1e-5, atol=0, err_msg=identity)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', [
    pytest.param(ngspice_port_admittance, marks=requires_ngspice, id='ngspice'),
    pytest.param(xyce_port_admittance, marks=requires_xyce, id='Xyce'),
    pytest.param(vacask_port_admittance, marks=requires_vacask, id='VACASK'),
])
def test_written_netlists_simulate_to_independent_source_laws(
        simulator: Callable, extractions: Dict[str, Tuple[Path, SpiceScope, float]], tmp_path: Path):
    for identity, (path, scope, resistance) in extractions.items():
        work = tmp_path / identity
        work.mkdir()
        _, matrices = simulator(str(path), scope.name, scope.ports, (3, 3), str(work))
        expected = np.array([[1, -1], [-1, 1]]) / resistance
        for matrix in matrices:
            np.testing.assert_allclose(matrix, expected, rtol=1e-5, atol=0, err_msg=identity)
