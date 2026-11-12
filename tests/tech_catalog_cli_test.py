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

"""CLI corner selection reaches extraction, metadata and solver capability checks."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Tuple
from unittest import mock

import allure
import klayout.db as kdb
import numpy as np
import pytest

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist, SpiceScope
from klayout_pex.pdk_config import PDK
from klayout_pex.pex25d.reader import read_pex25d_text
from klayout_pex.tech_info import TechInfo
from klayout_pex_protobuf.kpex.tech.tech_catalog_pb2 import TechnologyDataset
from tests.common.cli_runner import run_cli
from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.common.rc_networks import port_admittance
from tests.common.tech_catalog import add_scenario, edit_dataset, write_test_catalog
from tests.common.xyce import xyce_port_admittance, requires_xyce


pytestmark = allure.parent_suite('Unit Tests')


@pytest.fixture
def custom_catalog(tmp_path: Path) -> Path:
    path = tmp_path / 'tech/catalog.pb.json'
    tech = TechInfo.parse_tech_def(PDK.SKY130A.config.tech_pb_json_path)
    # A synthetic area-only C model has an exact linear scaling invariant. General fringe
    # fits also use the overlap coefficient in their spatial decay, so scaling every
    # coefficient would change both amplitude and shape, not simply double all capacitors.
    for row in tech.process_parasitics.capacitance.substrates:
        row.perimeter_capacitance = 0.0
    for rows in (tech.process_parasitics.capacitance.sidewalls, tech.process_parasitics.capacitance.sideoverlaps):
        for row in rows:
            row.capacitance = 0.0
    write_test_catalog(tech, path)

    def scale_resistance(dataset: TechnologyDataset):
        for rows in (dataset.resistance.layers, dataset.resistance.contacts, dataset.resistance.vias):
            for row in rows:
                row.resistance *= 3.0

    def scale_capacitance(dataset: TechnologyDataset):
        capacitance = dataset.capacitance.capacitance
        for row in capacitance.substrates:
            row.area_capacitance *= 2.0
            row.perimeter_capacitance *= 2.0
        for rows in (capacitance.overlaps, capacitance.sidewalls, capacitance.sideoverlaps):
            for row in rows:
                row.capacitance *= 2.0

    edit_dataset(path, 'resistance', scale_resistance, new_id='r3')
    edit_dataset(path, 'capacitance', scale_capacitance, new_id='c2')
    add_scenario(path, name='r3-c2', resistance='r3', capacitance='c2')
    return path


@pytest.mark.parametrize('command', ['extract', 'pex25d'])
@pytest.mark.parametrize('corner', ['', 'unknown'])
def test_unknown_corner_fails_before_loading_layout(command: str, corner: str, tmp_path: Path):
    with mock.patch.object(kdb.LayoutVsSchematic, 'read', side_effect=AssertionError('must not load LVSDB')):
        code, output = run_cli(KpexCLI().main, ['kpex', command, '--pdk', 'sky130A', '--corner', corner,
                                               '--lvsdb', '/nonexistent/layout.lvsdb', '--out-dir', str(tmp_path)])
    assert code == 1, output
    assert 'valid corners: nominal' in output


@pytest.mark.parametrize('options, message', [
    (['pex25d'], 'no matching physical stack'),
    (['extract', '--fastcap'], 'no matching physical stack'),
    (['extract', '--fastercap'], 'no matching physical stack'),
    (['extract', '--2.5D', '--blackbox', 'y', '--check-device-caps', '--gds', '/nonexistent/input.gds'],
     'no device-capacitance reference dataset'),
])
def test_unavailable_corner_capabilities_fail_before_layout_loading(options: List[str], message: str,
                                                                    custom_catalog: Path, tmp_path: Path):
    with mock.patch.object(kdb.LayoutVsSchematic, 'read', side_effect=AssertionError('must not load LVSDB')):
        code, output = run_cli(KpexCLI().main, ['kpex', *options, '--pdk', 'sky130A',
                                               '--tech-catalog', str(custom_catalog), '--corner', 'r3-c2',
                                               '--lvsdb', '/nonexistent/layout.lvsdb', '--out-dir', str(tmp_path)])
    assert code == 1, output
    assert message in ' '.join(output.split()), output


def test_magic_never_silently_uses_a_different_corner(tmp_path: Path):
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--magic', '--corner', 'nominal',
                                           '--gds', '/nonexistent/input.gds', '--out-dir', str(tmp_path)])
    assert code == 1, output
    assert 'MAGIC uses its own technology' in output


@pytest.fixture
def corner_extractions(custom_catalog: Path, tmp_path: Path) -> Dict[str, Tuple[Path, SpiceScope, KpexCLI]]:
    gds = PDKTestConfig(PDKName.SKY130A).gds_path('test_patterns', 'r_wire_voltage_divider_li1.gds.gz')
    paths = {}
    for corner in ('nominal', 'r3-c2'):
        destination = tmp_path / f'{corner}.spice'
        cli = KpexCLI()
        code, output = run_cli(cli.main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', '--mode', 'RC',
                                          '--tech-catalog', str(custom_catalog), '--corner', corner,
                                          '--lvsdb', lvsdb_fixture_path('sky130A', gds),
                                          '--out-netlist', str(destination), '--out-dir', str(tmp_path / corner)])
        assert code == 0, output
        scope = next(scope for scope in SpiceRCNetlist.read(str(destination)).scopes if scope.network.nodes())
        paths[corner] = (destination, scope, cli)
    return paths


def test_selected_r_and_c_datasets_reach_the_written_netlist_and_result(corner_extractions: Dict):
    _, nominal, nominal_cli = corner_extractions['nominal']
    _, changed, changed_cli = corner_extractions['r3-c2']
    assert nominal.ports == changed.ports
    assert nominal.resistors_read > 0 and nominal.capacitors_read > 0
    for node1, node2, branch in nominal.network.edges():
        a = changed.network.find_node(nominal.network.name(node1))
        b = changed.network.find_node(nominal.network.name(node2))
        actual = changed.network.branch(a, b)
        assert actual is not None
        assert actual.conductance == pytest.approx(branch.conductance / 3.0, rel=1e-10, abs=0.0)
        # C is written with six significant digits, independently in the two runs.
        assert actual.capacitance == pytest.approx(branch.capacitance * 2.0, rel=1e-5, abs=0.0)
    before = nominal_cli.run_result.to_json()['technology_selection']
    after = changed_cli.run_result.to_json()['technology_selection']
    assert before['scenario_id'] == 'nominal' and after['scenario_id'] == 'r3-c2'
    assert before['datasets']['process_stack'] == after['datasets']['process_stack']
    assert before['datasets']['resistance']['sha256'] != after['datasets']['resistance']['sha256']
    assert before['datasets']['capacitance']['sha256'] != after['datasets']['capacitance']['sha256']
    assert after['datasets']['device_references'] is None
    assert after['physical_stack_matches'] is False
    assert after['catalog_provenance']['data_revision'] == 'test-1'
    assert after['datasets']['resistance']['provenance']['sources'][0]['uri'] == 'urn:kpex:test:two-metals'
    assert after['datasets']['capacitance']['provenance']['assumptions'][0]['id'] == 'synthetic'
    assert before['resolved_technology_sha256'] != after['resolved_technology_sha256']


@pytest.mark.slow
@pytest.mark.parametrize('simulator', [pytest.param(ngspice_port_admittance, marks=requires_ngspice, id='ngspice'),
                                       pytest.param(xyce_port_admittance, marks=requires_xyce, id='Xyce')])
def test_selected_corner_simulates_as_independently_scaled_nominal_network(simulator: Callable,
                                                                          corner_extractions: Dict, tmp_path: Path):
    _, nominal, _ = corner_extractions['nominal']
    path, changed, _ = corner_extractions['r3-c2']
    frequencies, admittance = simulator(str(path), changed.name, changed.ports, (8, 11), str(tmp_path))
    # R'=3R and C'=2C imply Y'(f)=Y(6f)/3 even after elimination of all internal nodes.
    # The reference uses the separately extracted nominal network, not the selected output's elements.
    for frequency, obtained in zip(frequencies, admittance):
        expected = port_admittance(nominal.network, nominal.ports, 6.0 * frequency) / 3.0
        assert np.linalg.norm(obtained - expected) <= 1e-5 * np.linalg.norm(expected), frequency


def test_pex25d_metadata_identifies_the_selected_physical_scenario(tmp_path: Path):
    gds = PDKTestConfig(PDKName.SKY130A).gds_path('test_patterns', 'r_wire_voltage_divider_li1.gds.gz')
    path = tmp_path / 'nominal.pex25d'
    code, output = run_cli(KpexCLI().main, ['kpex', 'pex25d', '--pdk', 'sky130A', '--corner', 'nominal',
                                           '--lvsdb', lvsdb_fixture_path('sky130A', gds), '--out-file', str(path),
                                           '--out-dir', str(tmp_path)])
    assert code == 0, output
    artifact = read_pex25d_text(path.read_bytes(), str(path))
    metadata = {entry.key: entry.value for entry in artifact.metadata}
    assert metadata['process_corner'] == 'nominal'


def test_explicit_empty_catalog_never_falls_back_to_nominal(tmp_path: Path):
    with mock.patch.object(kdb.LayoutVsSchematic, 'read', side_effect=AssertionError('must not load LVSDB')):
        code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D',
                                               '--tech-catalog', '', '--lvsdb', '/nonexistent/layout.lvsdb',
                                               '--out-dir', str(tmp_path)])
    assert code == 1, output
    assert '--tech-catalog requires a nonempty file path' in output
