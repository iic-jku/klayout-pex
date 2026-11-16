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

"""GF180 sheet and cut sensitivities reach extracted and simulated circuits."""

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
from tests.common.rc_networks import port_admittance, spice_subcircuit
from tests.common.resistance_patterns import extracted_strip, write_contact_array_lvsdb
from tests.common.vacask import vacask_port_admittance, requires_vacask
from tests.common.xyce import xyce_port_admittance, requires_xyce

pytestmark = allure.parent_suite('Unit Tests')
SCENARIOS = ('fixed-layout-low-r-ideal-contacts', 'fixed-layout-reference-r', 'fixed-layout-high-r')
SIMULATORS = [pytest.param(ngspice_port_admittance, marks=requires_ngspice, id='ngspice'),
              pytest.param(xyce_port_admittance, marks=requires_xyce, id='Xyce'),
              pytest.param(vacask_port_admittance, marks=requires_vacask, id='VACASK')]
# Independent source values in Ohm/square, before the catalog's milliohm conversion.
SHEET_ROWS = {'Poly2': (1., 7.3, 15.), 'Metal1': (.076, .09, .104),
              'Metal2': (.076, .09, .104), 'Metal3': (.076, .09, .104),
              'Metal4': (.076, .09, .104), 'Metal5': (.031, .04, .049),
              'Nwell': (800., 1000., 1200.), 'FuseTop': (.153, .18, .207)}


@pytest.mark.parametrize('scenario,index', list(zip(SCENARIOS, range(3))))
@pytest.mark.parametrize('layer', SHEET_ROWS)
@pytest.mark.parametrize('width,length', [(1000, 1000), (1000, 10000), (1001, 10000)])
def test_selected_sheet_resistance_obeys_square_counting_at_geometry_boundaries(
        scenario: str, index: int, layer: str, width: int, length: int):
    # A square, a long strip and the next grid width distinguish unit conversion
    # from a hidden width bias; these are fixed-layout sensitivities, not DRC tests.
    info = TechInfo.from_catalog(PDK.GF180MCUD.config.tech_catalog_path, None, scenario_id=scenario)
    network = extracted_strip(info, layer, width, length)
    expected = np.array([[1, -1], [-1, 1]]) / (SHEET_ROWS[layer][index] * length / width)
    np.testing.assert_allclose(port_admittance(network, ['A', 'B'], 1e3), expected, rtol=1e-13, atol=0)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', SIMULATORS)
def test_sheet_sensitivities_simulate_against_independent_source_laws(simulator: Callable, tmp_path: Path):
    for index, scenario in enumerate(SCENARIOS):
        info = TechInfo.from_catalog(PDK.GF180MCUD.config.tech_catalog_path, None, scenario_id=scenario)
        for layer, values in SHEET_ROWS.items():
            work = tmp_path / f'{scenario}-{layer}'
            work.mkdir()
            network = extracted_strip(info, layer, width=1000, length=10000)
            path = work / 'strip.spice'
            path.write_text(spice_subcircuit(network, 'strip', ['A', 'B']), encoding='utf-8')
            _, matrices = simulator(str(path), 'strip', ['A', 'B'], (0, 2), str(work))
            for actual in matrices:
                np.testing.assert_allclose(actual, np.array([[1, -1], [-1, 1]]) / (values[index] * 10),
                                           rtol=1e-7, atol=0, err_msg=f'{scenario}-{layer}')


@pytest.fixture(scope='module')
def cut_extractions(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Tuple[Path, SpiceScope, float]]:
    work = tmp_path_factory.mktemp('gf180-resistance-cuts')
    technology = TechInfo.parse_tech_def(PDK.GF180MCUD.config.tech_pb_json_path)
    layers = {layer.name: layer for layer in technology.layers}
    patterns = [
        ('poly-contact', 'Poly2', 'poly2_con', 'poly2_label', 'Metal1', 'metal1_con', 'metal1_label',
         'Contact', 'contact_poly_con', 220, (0., 5.9, 15.)),
        ('Via1', 'Metal1', 'metal1_con', 'metal1_label', 'Metal2', 'metal2_con', 'metal2_label',
         'Via1', 'via1', 260, (0., 4.5, 15.)),
        ('Via4', 'Metal4', 'metal4_n_cap', 'metal4_label', 'Metal5', 'metal5_con', 'metal5_label',
         'Via4', 'via4_n_cap', 260, (0., 4.5, 15.)),
    ]
    results = {}
    for name, lower, lower_lvs, lower_label, upper, upper_lvs, upper_label, cut, cut_lvs, size, values in patterns:
        for count in (1, 2, 4):
            identity = f'{name}-{count}'
            path = write_contact_array_lvsdb(work / f'{identity}.lvsdb', layers[lower],
                (lower_lvs, lower_lvs, lower_label), layers[upper],
                (upper_lvs, upper_lvs, upper_label), layers[cut], cut_lvs, size, count)
            for scenario, cut_resistance in zip(SCENARIOS, values):
                key = f'{identity}-{scenario}'
                directory = work / key
                destination = directory / 'extracted.spice'
                code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'gf180mcuD',
                    '--2.5D', '--mode', 'R', '--corner', scenario, '--lvsdb', str(path),
                    '--out-dir', str(directory), '--out-netlist', str(destination)])
                assert code == 0, output
                scope = next(scope for scope in SpiceRCNetlist.read(str(destination)).scopes if scope.network.nodes())
                assert scope.ports == ['A', 'B']
                # Exact ideal contacts merge internal nodes. Separately named
                # output ports retain the existing 1mOhm SPICE label tie; it is
                # not a physical contact minimum and does not divide with Ncuts.
                expected = cut_resistance / count if cut_resistance else .001
                results[key] = destination, scope, expected
    return results


def test_real_contact_extraction_preserves_parallel_law_and_ideal_port_ties(
        cut_extractions: Dict[str, Tuple[Path, SpiceScope, float]]):
    for identity, (_, scope, expected) in cut_extractions.items():
        np.testing.assert_allclose(port_admittance(scope.network, scope.ports, 1e3),
                                   np.array([[1, -1], [-1, 1]]) / expected,
                                   rtol=1e-12, atol=0, err_msg=identity)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', SIMULATORS)
def test_contact_netlists_simulate_parallel_counts_and_ideal_port_ties(
        simulator: Callable, cut_extractions: Dict[str, Tuple[Path, SpiceScope, float]], tmp_path: Path):
    for identity, (path, scope, expected) in cut_extractions.items():
        work = tmp_path / identity
        work.mkdir()
        _, matrices = simulator(str(path), scope.name, scope.ports, (0, 2), str(work))
        for actual in matrices:
            np.testing.assert_allclose(actual, np.array([[1, -1], [-1, 1]]) / expected,
                                       rtol=1e-7, atol=0, err_msg=identity)
