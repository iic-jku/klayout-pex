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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
# --------------------------------------------------------------------------------
#
"""Fixed-layout SKY130 sensitivity bounds, kept distinct from correlated process corners."""

from pathlib import Path
from typing import Callable, Tuple

import allure
import klayout.db as kdb
import klayout.pex as klp
import numpy as np
import pytest

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.netlist.rc_network import RCNetwork
from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist, SpiceScope
from klayout_pex.pdk_config import PDK
from klayout_pex.tech_catalog import load_technology_catalog
from klayout_pex.tech_info import TechDefError, TechInfo
from scripts.gen_tech_pb.corner_data import TABLE_DIRECTORY, write_bundled_corner_catalog
from scripts.gen_tech_pb.resistance_corners import load_corner_resistances
from tests.common.cli_runner import run_cli
from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.common.rc_networks import build_network, port_admittance, spice_subcircuit
from tests.common.vacask import vacask_port_admittance, requires_vacask
from tests.common.xyce import xyce_port_admittance, requires_xyce


pytestmark = allure.parent_suite('Unit Tests')
STYLES = ('hrhc', 'hrlc', 'lrhc', 'lrlc')
# Independent source values in Ohm: each row is rnw, rcvia3, rcvia4 in the
# maintained discrete models at 29b55153fd9f4badef05a02667184b81789d1f61.
MODEL_VALUES = {
    'hrhc': (2022.0, 6.623, 0.7377),
    'hrlc': (2160.0, 8.0, 0.891),
    'lrhc': (1240.0, 0.5, 0.012),
    'lrlc': (1378.0, 1.373, 0.1224),
}
SIMULATORS = [
    pytest.param(ngspice_port_admittance, marks=requires_ngspice, id='ngspice'),
    pytest.param(xyce_port_admittance, marks=requires_xyce, id='Xyce'),
    pytest.param(vacask_port_admittance, marks=requires_vacask, id='VACASK'),
]


@pytest.fixture(scope='module')
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp('sky130-resistance') / 'catalog.pb.json'
    nominal = TechInfo.parse_tech_def(PDK.SKY130A.config.tech_pb_json_path)
    write_bundled_corner_catalog(nominal, path)
    return path


def selected(catalog: Path, style: str) -> TechInfo:
    resolved = load_technology_catalog(catalog, style + '-mim-bound')
    return TechInfo(resolved.tech, dielectric_filter=None)


@pytest.mark.parametrize('style', STYLES)
def test_every_adopted_source_row_and_unit(style: str):
    nominal = TechInfo.parse_tech_def(PDK.SKY130A.config.tech_pb_json_path)
    before = nominal.SerializeToString()
    datasets = {d.id: d for d in load_corner_resistances(nominal, TABLE_DIRECTORY / 'sky130A-resistance.json')}
    data = datasets[style + '-mim-bound'].resistance
    high = style.startswith('hr')
    expected_layers = dict(zip(('poly', 'li1', 'met1', 'met2', 'met3', 'met4', 'met5', 'capm', 'capm2'),
                              (55800, 17000, 145, 145, 56, 56, 36, 6800, 6800) if high else
                              (42200, 10500, 105, 105, 38, 38, 21, 4800, 4800)))
    rnw, via3, via4 = MODEL_VALUES[style]
    expected_layers['nwell'] = rnw * 1000
    assert {r.layer_name: r.resistance for r in data.layers} == expected_layers
    expected_contacts = dict(zip(('licon_nsd_con', 'licon_psd_con', 'licon_poly_con', 'licon_ntap_con'),
                                (280000, 840000, 252000, 280000) if high else (95000, 345000, 52000, 95000)))
    assert {r.contact_name: r.resistance for r in data.contacts} == expected_contacts
    expected_vias = dict(zip(('mcon', 'via', 'via2'), (23000, 15000, 8000) if high else (1600, 2000, 500)))
    expected_vias.update(via3=via3 * 1000, via4=via4 * 1000)
    assert {r.via_name: r.resistance for r in data.vias} == pytest.approx(expected_vias, rel=1e-14, abs=0)
    assert nominal.SerializeToString() == before


@pytest.mark.parametrize('style', STYLES)
def test_sensitivity_selection_exposes_assumption_and_rejects_unqualified_capabilities(catalog: Path, style: str):
    resolved = load_technology_catalog(catalog, style + '-mim-bound')
    assert resolved.selection.capacitance.id == ('high' if style.endswith('hc') else 'low')
    assumptions = {a['id']: a for a in resolved.selection.resistance.provenance['assumptions']}
    assert 'engineering combination' in assumptions['mim-spec-bound']['reason']
    assert 'dimension shifts' in assumptions['fixed-layout-material-law']['reason']
    with pytest.raises(TechDefError, match='no matching physical stack'):
        resolved.selection.require_physical_stack()
    with pytest.raises(TechDefError, match='no device-capacitance reference'):
        resolved.selection.require_device_references()
    # The original nominal is still the default; short source-style names do not
    # accidentally advertise a qualified correlated process corner.
    assert load_technology_catalog(catalog).selection.scenario_id == 'nominal'
    with pytest.raises(TechDefError, match='valid corners'):
        load_technology_catalog(catalog, style)


def extracted_strip(tech: TechInfo, layer: str, width: int, length: int) -> RCNetwork:
    rex = klp.RExtractorTech()
    conductor = klp.RExtractorTechConductor()
    conductor.layer = 0
    conductor.algorithm = klp.Algorithm.SquareCounting
    conductor.resistance = tech.milliohm_to_ohm(tech.layer_resistance_by_layer_name[layer].resistance)
    rex.add_conductor(conductor)
    network = klp.RNetExtractor(0.001).extract(
        rex, {0: kdb.Region(kdb.Box(0, 0, length, width))},
        {0: [kdb.Point(0, width // 2), kdb.Point(length, width // 2)]}, {})
    names = {node.object_id(): ('A' if node.port_index() == 0 else 'B') for node in network.each_node()}
    return build_network([(names[edge.a().object_id()], names[edge.b().object_id()],
                           1.0 / edge.resistance(), 0.0) for edge in network.each_element()], ['A', 'B'])


@pytest.mark.parametrize('style', STYLES)
@pytest.mark.parametrize('layer', ['capm', 'capm2'])
@pytest.mark.parametrize('width,length', [(1000, 1000), (1000, 10000), (2000, 10000)])
def test_mim_sheet_bounds_keep_square_counting_geometry(catalog: Path, style: str, layer: str,
                                                       width: int, length: int):
    # One square, a long strip, and double width expose unit errors and hidden
    # application of the compact model's dimension bias to this fixed-layout law.
    network = extracted_strip(selected(catalog, style), layer, width, length)
    resistance = (6.8 if style.startswith('hr') else 4.8) * length / width
    expected = np.array([[1, -1], [-1, 1]]) / resistance
    np.testing.assert_allclose(port_admittance(network, ['A', 'B'], 1.0), expected, rtol=1e-13, atol=0)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', SIMULATORS)
@pytest.mark.parametrize('style', STYLES)
@pytest.mark.parametrize('layer', ['capm', 'capm2'])
def test_mim_bound_strip_simulates_with_published_sheet_resistance(catalog: Path, style: str, layer: str,
                                                                 simulator: Callable, tmp_path: Path):
    network = extracted_strip(selected(catalog, style), layer, width=2000, length=10000)
    path = tmp_path / 'strip.spice'
    path.write_text(spice_subcircuit(network, 'strip', ['A', 'B']), encoding='utf-8')
    _, measured = simulator(str(path), 'strip', ['A', 'B'], (0, 2), str(tmp_path))
    resistance = (6.8 if style.startswith('hr') else 4.8) * 5.0
    for matrix in measured:
        np.testing.assert_allclose(matrix, np.array([[1, -1], [-1, 1]]) / resistance, rtol=1e-7, atol=0)


def extracted_mim_cuts(tech: TechInfo, via_name: str, count: int) -> RCNetwork:
    contact = tech.contact_by_contact_lvs_layer_name[via_name + '_cap']
    width = round(contact.width / 0.001)
    rex = klp.RExtractorTech()
    # Ideal landing pads isolate the per-cut law from the separately tested sheet
    # resistance. Both MIM cut sizes must yield the source Ohm/cut, not Ohm/um2.
    for layer in (0, 1):
        conductor = klp.RExtractorTechConductor()
        conductor.layer = layer
        conductor.algorithm = klp.Algorithm.SquareCounting
        conductor.resistance = 0.0
        rex.add_conductor(conductor)
    via = klp.RExtractorTechVia()
    via.cut_layer, via.bottom_conductor, via.top_conductor = 2, 0, 1
    via.resistance = tech.milliohm_per_cut_to_ohm_um2_for_via(contact, tech.via_resistance_by_layer_name[via_name])
    rex.add_via(via)
    cuts = kdb.Region()
    for index in range(count):
        x = 1000 + 2 * width * index
        cuts.insert(kdb.Box(x, 1000, x + width, 1000 + width))
    pad = kdb.Region(kdb.Box(0, 0, 10000, 10000))
    network = klp.RNetExtractor(0.001).extract(
        rex, {0: pad, 1: pad, 2: cuts},
        {0: [kdb.Point(5000, 5000)], 1: [kdb.Point(5000, 5000)]}, {})
    names = {node.object_id(): ('A' if node.layer() == 0 else 'B') for node in network.each_node()}
    return build_network([(names[edge.a().object_id()], names[edge.b().object_id()],
                           1.0 / edge.resistance(), 0.0) for edge in network.each_element()], ['A', 'B'])


@pytest.mark.parametrize('style', STYLES)
@pytest.mark.parametrize('via_name,source_index', [('via3', 1), ('via4', 2)])
@pytest.mark.parametrize('count', [1, 4])
def test_mim_contact_aliases_preserve_source_cut_resistance_and_parallel_count(
        catalog: Path, style: str, via_name: str, source_index: int, count: int):
    network = extracted_mim_cuts(selected(catalog, style), via_name, count)
    resistance = MODEL_VALUES[style][source_index] / count
    expected = np.array([[1, -1], [-1, 1]]) / resistance
    np.testing.assert_allclose(port_admittance(network, ['A', 'B'], 1.0), expected, rtol=1e-13, atol=0)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', SIMULATORS)
@pytest.mark.parametrize('style', STYLES)
@pytest.mark.parametrize('via_name,source_index', [('via3', 1), ('via4', 2)])
def test_parallel_mim_cuts_simulate_with_source_style_resistance(catalog: Path, style: str, via_name: str,
                                                               source_index: int, simulator: Callable, tmp_path: Path):
    network = extracted_mim_cuts(selected(catalog, style), via_name, count=4)
    path = tmp_path / 'cuts.spice'
    path.write_text(spice_subcircuit(network, 'cuts', ['A', 'B']), encoding='utf-8')
    _, measured = simulator(str(path), 'cuts', ['A', 'B'], (0, 2), str(tmp_path))
    resistance = MODEL_VALUES[style][source_index] / 4.0
    for matrix in measured:
        np.testing.assert_allclose(matrix, np.array([[1, -1], [-1, 1]]) / resistance, rtol=1e-7, atol=0)


@pytest.fixture
def via_stack(catalog: Path, tmp_path: Path, style: str) -> Tuple[Path, SpiceScope]:
    gds = PDKTestConfig(PDKName.SKY130A).gds_path('test_patterns', 'r_via_stack_1x1_minsize_poly_to_met5.gds.gz')
    path = tmp_path / 'via-stack.spice'
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', '--mode', 'R',
                                           '--tech-catalog', str(catalog), '--corner', style + '-mim-bound',
                                           '--lvsdb', lvsdb_fixture_path('sky130A', gds),
                                           '--out-netlist', str(path), '--out-dir', str(tmp_path / 'extract')])
    assert code == 0, output
    scope = next(s for s in SpiceRCNetlist.read(str(path)).scopes if s.network.nodes())
    return path, scope


def expected_via_stack(style: str) -> RCNetwork:
    # This layout has one cut at each step and pin centers at the cut centers,
    # so there is no intervening wire length. These are independent source values.
    high = style.startswith('hr')
    _, via3, via4 = MODEL_VALUES[style]
    values = (252.0, 23.0, 15.0, 8.0, via3, via4) if high else (52.0, 1.6, 2.0, 0.5, via3, via4)
    layers = ('poly', 'li1', 'met1', 'met2', 'met3', 'met4', 'met5')
    return build_network([(a, b, 1.0 / r, 0.0) for a, b, r in zip(layers, layers[1:], values)], layers)


@pytest.mark.parametrize('style', STYLES)
def test_source_style_overrides_reach_extracted_via_stack(style: str, via_stack: Tuple[Path, SpiceScope]):
    _, scope = via_stack
    expected = port_admittance(expected_via_stack(style), scope.ports, 1.0)
    actual = port_admittance(scope.network, scope.ports, 1.0)
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', SIMULATORS)
@pytest.mark.parametrize('style', STYLES)
def test_source_style_via_stack_simulates_as_independent_cut_network(style: str, via_stack: Tuple[Path, SpiceScope],
                                                                    simulator: Callable, tmp_path: Path):
    path, scope = via_stack
    _, measured = simulator(str(path), scope.name, scope.ports, (0, 2), str(tmp_path))
    expected = port_admittance(expected_via_stack(style), scope.ports, 1.0)
    for matrix in measured:
        np.testing.assert_allclose(matrix, expected, rtol=1e-7, atol=1e-10)
