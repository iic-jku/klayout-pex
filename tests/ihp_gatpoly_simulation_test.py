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
"""Extracted GatPoly strips obey the independently specified sheet law in circuit simulators."""

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
from tests.common.resistance_patterns import write_strip_lvsdb
from tests.common.vacask import vacask_port_admittance, requires_vacask
from tests.common.xyce import xyce_port_admittance, requires_xyce

pytestmark = allure.parent_suite('Unit Tests')


@pytest.fixture(params=[PDK.IHP_SG13G2, PDK.IHP_SG13CMOS5L], ids=str)
def strips(request: pytest.FixtureRequest, tmp_path: Path) -> Dict[Tuple[str, int], Tuple[Path, SpiceScope]]:
    pdk = request.param
    technology = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    layer = next(layer for layer in technology.layers if layer.name == 'GatPoly')
    result = {}
    # 130nm is the published interconnect minimum; 500nm is the resistor-device
    # minimum. Just-above boundaries and a wider strip expose any accidental device
    # width correction: R*W/L must stay constant at every width for an RPSQ component.
    for width in (130, 131, 500, 501, 2000):
        source = write_strip_lvsdb(tmp_path / f'wire-{width}.lvsdb', layer,
                                  ('poly_con', 'poly_pin_con', 'poly_text'), 10000, width)
        for corner in ('nominal', 'gatpoly-low-sheet', 'gatpoly-high-sheet'):
            directory = tmp_path / f'{corner}-{width}'
            destination = directory / 'strip.spice'
            code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', str(pdk), '--2.5D', '--mode', 'R',
                                                   '--corner', corner, '--lvsdb', str(source),
                                                   '--out-dir', str(directory), '--out-netlist', str(destination)])
            assert code == 0, output
            scope = next(s for s in SpiceRCNetlist.read(str(destination)).scopes if s.network.nodes())
            assert scope.ports == ['A', 'B']
            result[corner, width] = destination, scope
    return result


def test_real_extraction_keeps_sheet_law_and_does_not_project_device_widths(strips: Dict[Tuple[str, int], Tuple[Path, SpiceScope]]):
    for (corner, width), (_, scope) in strips.items():
        sheet = {'nominal': 7.0, 'gatpoly-low-sheet': 6.2, 'gatpoly-high-sheet': 7.8}[corner]
        expected_r = sheet * 10000 / width
        expected_y = np.array([[1, -1], [-1, 1]]) / expected_r
        # The written netlist rounds resistances to six significant figures.
        np.testing.assert_allclose(port_admittance(scope.network, scope.ports, 1e3), expected_y, rtol=1e-5, atol=0)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', [
    pytest.param(ngspice_port_admittance, marks=requires_ngspice, id='ngspice'),
    pytest.param(xyce_port_admittance, marks=requires_xyce, id='Xyce'),
    pytest.param(vacask_port_admittance, marks=requires_vacask, id='VACASK'),
])
def test_written_corner_strips_simulate_to_the_independent_sheet_law(simulator: Callable, strips: Dict[Tuple[str, int], Tuple[Path, SpiceScope]], tmp_path: Path):
    for (corner, width), (path, scope) in strips.items():
        sheet = {'nominal': 7.0, 'gatpoly-low-sheet': 6.2, 'gatpoly-high-sheet': 7.8}[corner]
        expected = np.array([[1, -1], [-1, 1]]) / (sheet * 10000 / width)
        work = tmp_path / f'simulate-{corner}-{width}'
        work.mkdir()
        _, matrices = simulator(str(path), scope.name, scope.ports, (3, 3), str(work))
        for matrix in matrices:
            np.testing.assert_allclose(matrix, expected, rtol=1e-5, atol=0)
