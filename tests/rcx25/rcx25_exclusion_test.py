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

"""
The contract of the exclusion markers (kpex --exclusion-markers), on the test patterns:
what is outside the markers is extracted as without them, also what shields it within the markers,
and what is within them has no parasitics, but stays connected
"""

from __future__ import annotations

import csv
from typing import *
from unittest import mock

import allure
import klayout.db as kdb
import pytest
from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.pex25d.diagnostics import ExitCode
from klayout_pex.rcx25.exclusion import ExclusionMarkerMode, Exclusions
from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.cli_runner import run_cli
from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction, pair

parent_suite = "kpex/2.5D exclusion markers"
tags = ("PEX", "2.5D", "Exclusion")

Values = Dict[FrozenSet[str], float]


class Extraction:
    def __init__(self, cell_name: str, mode: PEXMode, blackbox: bool = False, pdk_name: PDKName = PDKName.IHP_SG13G2):
        self.pex = RCX25Extraction(pdk=PDKTestConfig(pdk_name), pex_mode=mode, blackbox=blackbox)
        self.path_components = ('test_patterns', f"{cell_name}.gds.gz")

    def run(self, marker_mode: ExclusionMarkerMode = ExclusionMarkerMode.TIE, *extra_args: str) -> KpexCLI:
        return self.pex.run_kpex(*self.path_components,
                                 extra_args=['--gds', self.pex.pdk.gds_path(*self.path_components),
                                             '--exclusion-markers', marker_mode, *extra_args])


def values_of(cli: KpexCLI, column: str) -> Values:
    """
    :return: the capacitances or the resistances of the written CSV netlist, by their nets
    """
    with open(cli.rcx25_extracted_csv_path, encoding='utf-8') as f:
        return {frozenset((row['Net1'], row['Net2'])): float(row[column])
                for row in csv.DictReader(f, delimiter=';') if row[column]}


def capacitances(cli: KpexCLI) -> Values:
    return values_of(cli, 'Capacitance [fF]')


def resistances(cli: KpexCLI) -> Values:
    return values_of(cli, 'Resistance [Ω]')


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.CC, PEXMode.RC])
def test_what_is_outside_a_marker_keeps_its_values(mode: PEXMode):
    # The plate P, just within the marker, shields and loads the wire N outside it, as without the marker,
    # and the wire keeps its capacitance to P, which only its capacitance to the substrate leaves
    extraction = Extraction('exclusion_plate_neighbor', mode)
    ignored = capacitances(extraction.run(ExclusionMarkerMode.IGNORE))
    honored_cli = extraction.run()
    honored = capacitances(honored_cli)

    assert honored[pair('N', 'P')] == ignored[pair('N', 'P')] > 0.0
    assert honored[pair('N', 'VSUBS')] == ignored[pair('N', 'VSUBS')] > 0.0
    assert pair('P', 'VSUBS') in ignored
    assert pair('P', 'VSUBS') not in honored
    assert honored_cli.rcx25_netlist_problems == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.CC, PEXMode.RC])
def test_capacitances_of_floating_metal_within_a_marker_go_to_the_substrate(mode: PEXMode):
    extraction = Extraction('exclusion_floating_plate_neighbor', mode)
    ignored = capacitances(extraction.run(ExclusionMarkerMode.IGNORE))
    honored = extraction.run()
    assert capacitances(honored) == {pair('N', 'VSUBS'): pytest.approx(sum(c for key, c in ignored.items()
                                                                           if 'N' in key), abs=0.002)}
    assert honored.rcx25_netlist_problems == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.CC, PEXMode.RC])
def test_plates_within_two_markers_keep_their_capacitance_those_within_one_not(mode: PEXMode):
    assert list(capacitances(Extraction('exclusion_plates_2_markers', mode).run())) == [pair('P', 'Q')]
    assert capacitances(Extraction('exclusion_plates_1_marker', mode).run()) == {}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_warns_of_nets_across_markers():
    with mock.patch('klayout_pex.rcx25.extractor.warning') as warning_mock:
        Extraction('exclusion_wire_through', PEXMode.CC).run()
    assert any('partly within exclusion markers' in c.args[0] and 'A,B: Metal3' in c.args[0]
               for c in warning_mock.call_args_list)

    with mock.patch('klayout_pex.rcx25.extractor.warning') as warning_mock:
        Extraction('exclusion_plate_neighbor', PEXMode.CC).run()
    assert not any('partly within exclusion markers' in c.args[0] for c in warning_mock.call_args_list)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_marker_of_a_layer_keeps_the_values_of_the_wires_around_it():
    # The plate P is within the marker of its layer only, so it's left out, while the wires over and under it are not,
    # which is what the geometry staying is for: they keep all of their values, with P as a shield between them
    extraction = Extraction('exclusion_plate_noqrc', PEXMode.CC)
    ignored = capacitances(extraction.run(ExclusionMarkerMode.IGNORE))
    honored = capacitances(extraction.run(ExclusionMarkerMode.TIE, '--exclusion-marker-layer', 'Metal3.noqrc'))
    assert {pair('A', 'B'), pair('A', 'P'), pair('B', 'P'),
            pair('A', 'VSUBS'), pair('B', 'VSUBS'), pair('P', 'VSUBS')} \
           == set(ignored)
    assert honored == {key: value for key, value in ignored.items() if key != pair('P', 'VSUBS')}

    # NOTE: and it isn't on by default, as the pcell of the rfcmim draws it
    assert capacitances(extraction.run()) == ignored


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('cell_name, left_out', [
    ('exclusion_plate_pair_m2m3', pair('A', 'P')),
    ('exclusion_plate_pair_m3sub', pair('P', 'VSUBS')),
])
def test_capacitance_pair_marker_leaves_out_only_the_capacitances_between_its_layers(cell_name: str,
                                                                                     left_out: FrozenSet[str]):
    extraction = Extraction(cell_name, PEXMode.CC)
    ignored = capacitances(extraction.run(ExclusionMarkerMode.IGNORE))
    # NOTE: on by default
    honored = capacitances(extraction.run())
    assert {key: value for key, value in honored.items() if key != left_out} == \
           {key: value for key, value in ignored.items() if key != left_out}
    # NOTE: what stays is the fringe to the part of a wire beyond the marker
    assert honored.get(left_out, 0.0) < ignored[left_out] / 5.0


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_marker_layer_needs_the_option_of_the_markers(tmp_path):
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    gds_path = pdk.gds_path('test_patterns', 'exclusion_wire_end.gds.gz')
    code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D', '--gds', gds_path,
                                                    '--lvsdb', lvsdb_fixture_path(pdk.name, gds_path),
                                                    '--exclusion-marker-layer', 'Metal3.noqrc'))
    assert code != 0, output
    assert 'needs --exclusion-markers' in ' '.join(output.split()), output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_invalid_marker_layer_is_an_error_listing_the_valid_ones(tmp_path):
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    gds_path = pdk.gds_path('test_patterns', 'exclusion_wire_end.gds.gz')
    code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D', '--gds', gds_path,
                                                    '--lvsdb', lvsdb_fixture_path(pdk.name, gds_path),
                                                    '--exclusion-markers', 'tie',
                                                    '--exclusion-marker-layer', 'nope'))
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert 'NoRCX.drawing' in output and 'Metal3.noqrc' in output, output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_layout_without_markers_has_the_values_without_the_option_and_a_warning():
    extraction = Extraction('exclusion_via_stack_no_marker', PEXMode.RC)
    ignored = extraction.run(ExclusionMarkerMode.IGNORE)
    ignored_values = resistances(ignored), capacitances(ignored)
    with mock.patch('klayout_pex.kpex_cli.warning') as warning_mock:
        honored = extraction.run()
    assert (resistances(honored), capacitances(honored)) == ignored_values
    assert any('no shapes on the exclusion markers' in c.args[0] for c in warning_mock.call_args_list)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_warns_of_whiteboxed_devices_within_markers():
    # NOTE: the test pattern of the wires has no devices, this one a MOM cap, whose marker is another one
    cell_name = 'cmomi_w5u_l5u_m1_m5'
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    path_components = (cell_name, f"{cell_name}.gds.gz")
    layout_path = pdk.gds_path(*path_components)
    with mock.patch('klayout_pex.rcx25.extractor.warning') as warning_mock, \
         mock.patch('klayout_pex.kpex_cli.Exclusions.from_layout', side_effect=_marker_over_layout):
        RCX25Extraction(pdk=pdk, pex_mode=PEXMode.CC, blackbox=False) \
            .run_kpex(*path_components, extra_args=['--gds', layout_path, '--exclusion-markers', 'tie'])
    assert any('loses these devices' in c.args[0] for c in warning_mock.call_args_list)


def _marker_over_layout(layout, cell_name: str, substrate_layer_name: str, **_):
    return Exclusions.from_region(kdb.Region(layout.cell(cell_name).bbox()), substrate_layer_name)


def cli_args(tmp_path, *args: str) -> List[str]:
    return ['kpex', 'extract', '--pdk', 'ihp-sg13g2', '--out-dir', str(tmp_path), *args]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_needs_the_layout_with_the_markers(tmp_path):
    cell_name = 'exclusion_wire_end'
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    lvsdb_path = lvsdb_fixture_path(pdk.name, pdk.gds_path('test_patterns', f"{cell_name}.gds.gz"))
    code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D', '--lvsdb', lvsdb_path,
                                                    '--exclusion-markers', 'tie'))
    assert code != 0, output
    assert 'needs --gds' in ' '.join(output.split()), output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_does_not_apply_to_magic(tmp_path):
    cell_name = 'exclusion_wire_end'
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    gds_path = pdk.gds_path('test_patterns', f"{cell_name}.gds.gz")
    code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D', '--magic', '--gds', gds_path,
                                                    '--lvsdb', lvsdb_fixture_path(pdk.name, gds_path),
                                                    '--exclusion-markers', 'tie'))
    assert code != 0, output
    message = 'applies to the 2.5D engine, not to MAGIC'
    assert message in ' '.join(output.split()), output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_option_values_are_listed(tmp_path):
    code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D', '--exclusion-markers', 'nope'))
    assert code != 0
    assert all(value in output for value in ('ignore', 'tie')), output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_pdk_without_markers_is_an_error(tmp_path):
    pdk = PDKTestConfig(PDKName.SKY130A)
    gds_path = pdk.gds_path('test_patterns', 'r_wire_voltage_divider_li1.gds.gz')
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--out-dir', str(tmp_path),
                                            '--2.5D', '--gds', gds_path,
                                            '--lvsdb', lvsdb_fixture_path(pdk.name, gds_path),
                                            '--exclusion-markers', 'tie'])
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert 'no exclusion markers, give them with --exclusion-marker-layer' in ' '.join(output.split()), output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_lvsdb_of_another_cell_than_the_gds_is_an_error(tmp_path):
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    code, output = run_cli(KpexCLI().main, cli_args(
        tmp_path, '--2.5D',
        '--gds', pdk.gds_path('test_patterns', 'exclusion_wire_end.gds.gz'),
        '--lvsdb', lvsdb_fixture_path(pdk.name, pdk.gds_path('test_patterns', 'exclusion_wire_through.gds.gz'))))
    assert code != 0, output
    assert 'exclusion_wire_through' in output and 'exclusion_wire_end' in output, output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_lvsdb_bypasses_lvs_also_with_gds(tmp_path):
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    gds_path = pdk.gds_path('test_patterns', 'exclusion_wire_end.gds.gz')
    with mock.patch('klayout_pex.kpex_cli.LVSRunner.run_klayout_lvs') as lvs_mock:
        code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D', '--gds', gds_path,
                                                        '--lvsdb', lvsdb_fixture_path(pdk.name, gds_path)))
    assert code == 0, output
    lvs_mock.assert_not_called()
