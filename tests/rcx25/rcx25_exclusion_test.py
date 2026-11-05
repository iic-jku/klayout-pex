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
import os
import shutil
from typing import *
from unittest import mock

import allure
import klayout.db as kdb
import numpy as np
import pytest
from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist
from klayout_pex.pex25d.diagnostics import ExitCode
from klayout_pex.rcx25.exclusion import ExclusionMarkerMode, Exclusions
from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.cli_runner import run_cli
from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction, effective_resistance, pair

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


def netlist_path_of(cli: KpexCLI) -> str:
    return f"{os.path.splitext(cli.rcx25_extracted_csv_path)[0]}.spice"


def netlist_ports(cli: KpexCLI) -> List[str]:
    return next(s for s in SpiceRCNetlist.read(netlist_path_of(cli)).scopes if s.name is not None).ports


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
def test_wire_ending_within_a_marker_has_the_values_of_its_part_outside():
    wire = Extraction('exclusion_wire_end', PEXMode.CC).run()
    assert capacitances(wire)[pair('VSUBS', 'W')] == \
           pytest.approx(capacitances(Extraction('exclusion_wire_end', PEXMode.CC).run(ExclusionMarkerMode.IGNORE))
                         [pair('VSUBS', 'W')] / 2.0, rel=1e-3)

    wire = Extraction('exclusion_wire_end', PEXMode.R).run()
    assert list(resistances(wire)) == [pair('W', 'W.P0.Metal3')]
    assert wire.rcx25_netlist_problems == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_wire_through_a_marker_stays_connected_without_resistance_within():
    ignored = resistances(Extraction('exclusion_wire_through', PEXMode.R).run(ExclusionMarkerMode.IGNORE))
    honored = Extraction('exclusion_wire_through', PEXMode.R).run()
    assert honored.rcx25_netlist_problems == []

    # NOTE: from each pin to the one node of the cuts and of the net, 19.5 µm each instead of 59 µm
    assert len(resistances(honored)) == 2
    assert sum(resistances(honored).values()) == pytest.approx(ignored[pair('A', 'B')] * 39.0 / 59.0, rel=0.02)

    # NOTE: and the capacitances of its parts outside go to their nodes
    honored_rc = Extraction('exclusion_wire_through', PEXMode.RC).run()
    assert honored_rc.rcx25_netlist_problems == []
    assert {n for key in capacitances(honored_rc) for n in key} == {'A', 'B', 'A,B', 'VSUBS'}
    assert sum(capacitances(honored_rc).values()) == pytest.approx(
        sum(capacitances(Extraction('exclusion_wire_through', PEXMode.CC).run()).values()), rel=1e-3)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('marker_mode', [ExclusionMarkerMode.TIE, ExclusionMarkerMode.PORTS])
def test_non_manhattan_cuts_of_a_wire(marker_mode: ExclusionMarkerMode):
    honored = Extraction('exclusion_wire_through_octagon', PEXMode.RC).run(marker_mode)
    assert honored.rcx25_netlist_problems == []
    honored_total = sum(resistances(honored).values())
    ignored = resistances(Extraction('exclusion_wire_through_octagon', PEXMode.RC).run(ExclusionMarkerMode.IGNORE))
    # NOTE: only the parts of the wire outside the octagon
    assert 0.0 < honored_total < 0.6 * max(ignored.values())


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
def test_via_within_a_marker_has_no_resistance():
    honored = Extraction('exclusion_via_stack', PEXMode.R).run()
    assert honored.rcx25_netlist_problems == []
    without_marker = Extraction('exclusion_via_stack_no_marker', PEXMode.R).run()
    via_resistance = 2.031
    assert via_resistance == pytest.approx(max(resistances(without_marker).values()), abs=0.001)
    assert max(resistances(honored).values()) < via_resistance / 4.0


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_via_across_a_marker_keeps_its_resistance_and_its_metal():
    honored = Extraction('exclusion_via_across', PEXMode.R).run()
    assert honored.rcx25_netlist_problems == []
    assert max(resistances(honored).values()) == pytest.approx(2.031, abs=0.001)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_stubs_only_joined_outside_a_marker_stay_apart():
    honored = Extraction('exclusion_stubs', PEXMode.R).run()
    assert honored.rcx25_netlist_problems == []
    values = resistances(honored)
    # NOTE: a tie of the stubs within the marker would short the metal outside it
    assert values[pair('A', 'S1')] == pytest.approx(values[pair('A', 'S2')])
    assert values[pair('A', 'S1')] > 0.5


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_marker_of_a_child_cell_applies_where_the_cell_is_placed():
    honored = Extraction('exclusion_marker_in_cell', PEXMode.R).run()
    assert honored.rcx25_netlist_problems == []
    # NOTE: only the part of the wire before the rotated child cell
    assert sorted(resistances(honored)) == [pair('A', 'A.P0.Metal3')]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.R, PEXMode.RC])
def test_device_within_a_marker_stays_on_its_nets(mode: PEXMode):
    honored = Extraction('exclusion_nmos_diode2', mode).run()
    assert honored.rcx25_netlist_problems == []
    with open(netlist_path_of(honored), encoding='utf-8') as f:
        devices = [line.split() for line in f.read().replace('\n+', '').splitlines() if line.startswith('X')]
    assert [device[5] for device in devices] == ['sg13_lv_nmos']
    # NOTE: its terminals are on the nodes of the ideal layers within the marker, but the bulk on the substrate
    assert all(terminal.endswith('.excluded') for terminal in devices[0][1:4]), devices
    assert devices[0][4] == 'sub!', devices


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.R, PEXMode.RC])
def test_inductor_of_the_pdk_keeps_its_terminals_at_its_leads(mode: PEXMode):
    # NOTE: its marker has the coil, which the deck leaves out anyway, and no wires, so the netlist has the same nets
    extraction = Extraction('inductor2_w2u_d15u48_tm2_wires_50u', mode, blackbox=True)
    ignored = resistances(extraction.run(ExclusionMarkerMode.IGNORE))
    honored = extraction.run()
    assert honored.rcx25_netlist_problems == []
    assert ignored and resistances(honored) == ignored


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_cuts_of_a_net_are_ports():
    honored = Extraction('exclusion_wire_through', PEXMode.R).run(ExclusionMarkerMode.PORTS)
    assert honored.rcx25_netlist_problems == []
    assert netlist_ports(honored) == ['A', 'A_B__m0_0', 'A_B__m0_1', 'B']
    # NOTE: and the parts of the wire aren't joined, but for the tie of the node of the net to its first port
    values = resistances(honored)
    assert values[pair('A', 'A_B__m0_0')] == pytest.approx(values[pair('A_B__m0_1', 'B')], abs=0.001)
    assert sorted(values) == sorted([pair('A', 'A,B'), pair('A', 'A_B__m0_0'), pair('A_B__m0_1', 'B')], key=sorted)

    honored = Extraction('exclusion_wire_through', PEXMode.RC).run(ExclusionMarkerMode.PORTS)
    assert honored.rcx25_netlist_problems == []
    assert netlist_ports(honored) == ['A', 'A_B__m0_0', 'A_B__m0_1', 'B', 'sub!']
    assert {n for key in capacitances(honored) for n in key} == {'A', 'A_B__m0_0', 'A_B__m0_1', 'B', 'VSUBS'}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_cuts_are_named_after_the_nearest_pins_within_the_marker():
    honored = Extraction('exclusion_stubs', PEXMode.R).run(ExclusionMarkerMode.PORTS)
    assert honored.rcx25_netlist_problems == []
    assert netlist_ports(honored) == ['A', 'S1', 'S2']
    values = resistances(honored)
    assert values[pair('A', 'S1')] == pytest.approx(values[pair('A', 'S2')])


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_pin_within_a_marker_names_the_cut_on_its_layer():
    # NOTE: the cuts of the Metal2 and of the Metal3 are at the via across the marker, the pin is on the Metal3
    honored = Extraction('exclusion_via_across', PEXMode.R).run(ExclusionMarkerMode.PORTS)
    assert honored.rcx25_netlist_problems == []
    assert netlist_ports(honored) == ['A', 'A_B__m0_0', 'B']
    # NOTE: from A along the Metal2 to the via, the via, and the short piece of Metal3 to the cut, which is B
    assert resistances(honored) == {pair('A', 'A_B__m0_0'): pytest.approx(0.418, abs=0.001),
                                    pair('A,B', 'A_B__m0_0'): pytest.approx(2.031, abs=0.001),
                                    pair('A,B', 'B'): pytest.approx(0.02, abs=0.001)}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.R, PEXMode.RC])
def test_net_without_a_label_has_a_port_at_its_cut(mode: PEXMode):
    honored = Extraction('exclusion_wire_end_no_label', mode).run(ExclusionMarkerMode.PORTS)
    assert honored.rcx25_netlist_problems == []
    ports = [port for port in netlist_ports(honored) if port != 'sub!']
    assert len(ports) == 1 and ports[0].endswith('__m0_0') and '$' not in ports[0], ports


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.R, PEXMode.RC])
def test_device_terminals_within_a_marker_are_ports(mode: PEXMode):
    honored = Extraction('exclusion_nmos_diode2', mode).run(ExclusionMarkerMode.PORTS)
    assert honored.rcx25_netlist_problems == []
    with open(netlist_path_of(honored), encoding='utf-8') as f:
        devices = [line.split() for line in f.read().replace('\n+', '').splitlines() if line.startswith('X')]
    assert [device[5] for device in devices] == ['sg13_lv_nmos']
    ports = netlist_ports(honored)
    assert all(terminal in ports and '__m0_' in terminal for terminal in devices[0][1:4]), (devices, ports)
    assert len(set(devices[0][1:4])) == 3
    assert devices[0][4] == 'sub!', devices


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_inductor_of_the_pdk_has_no_ports_at_its_marker():
    extraction = Extraction('inductor2_w2u_d15u48_tm2_wires_50u', PEXMode.R, blackbox=True)
    ignored = extraction.run(ExclusionMarkerMode.IGNORE)
    ignored_ports, ignored_values = netlist_ports(ignored), resistances(ignored)
    honored = extraction.run(ExclusionMarkerMode.PORTS)
    assert honored.rcx25_netlist_problems == []
    assert netlist_ports(honored) == ignored_ports
    assert resistances(honored) == ignored_values


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_wire_under_the_coil_of_the_pdk_is_within_its_marker():
    extraction = Extraction('exclusion_inductor2_wire_under', PEXMode.R, blackbox=True)
    ignored = resistances(extraction.run(ExclusionMarkerMode.IGNORE))
    honored = extraction.run(ExclusionMarkerMode.PORTS)
    assert honored.rcx25_netlist_problems == []
    assert {'Y1', 'Y2', 'Y1_Y2__m0_0', 'Y1_Y2__m0_1'} <= set(netlist_ports(honored))
    assert sum(r for key, r in resistances(honored).items() if key & {'Y1', 'Y2'} and r > 0.01) < \
           sum(r for key, r in ignored.items() if key & {'Y1', 'Y2'} and r > 0.01) / 3.0


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_coil_with_guard_ring_has_ports_of_its_labels_near_its_cuts():
    extraction = Extraction('exclusion_coil_guard_ring', PEXMode.CC)
    ignored = capacitances(extraction.run(ExclusionMarkerMode.IGNORE))
    coil = 'OSCN,OSCP,VCT,ct,ind1,ind2'
    # NOTE: the wire and the guard ring keep their capacitances, also to the metal of the coil within the marker
    honored = capacitances(extraction.run(ExclusionMarkerMode.PORTS))
    for key in (pair('VC', 'VSUBS'), pair('VDD', 'VSUBS'), pair('VDD', coil), pair('VC', coil), pair('VC', 'VDD')):
        assert honored[key] == ignored[key] > 0.0
    assert honored[pair(coil, 'VSUBS')] < ignored[pair(coil, 'VSUBS')] / 2.0

    extraction = Extraction('exclusion_coil_guard_ring', PEXMode.RC)
    honored = extraction.run(ExclusionMarkerMode.PORTS)
    assert honored.rcx25_netlist_problems == []
    assert set(netlist_ports(honored)) == {'OSCP', 'OSCN', 'VCT', 'ind1', 'ind2', 'ct', 'VC', 'VDD', 'sub!'}
    values = resistances(honored)
    assert pair('ind1', 'OSCP') in values and pair('ind2', 'OSCN') in values and pair('ct', 'VCT') in values
    # NOTE: and only the leads and the tap have resistances, not the loop within the marker
    assert pair('ind1', 'ind2') not in values and pair('ct', 'ind1') not in values


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@requires_ngspice
@pytest.mark.parametrize('mode', [PEXMode.R, PEXMode.RC])
def test_model_between_the_ports_gives_the_flat_extraction(mode: PEXMode, tmp_path):
    # The part within the marker, extracted on its own, stands for its model.
    # NOTE: the capacitance to the substrate differs by the fringe of that part on its own at the cuts,
    #       where the flat wire has no edges: 2.3 % of this wire
    def extracted_copy(cell_name: str, marker_mode: ExclusionMarkerMode) -> str:
        path = str(tmp_path / f"{cell_name}_{marker_mode}.spice")
        shutil.copyfile(netlist_path_of(Extraction(cell_name, mode).run(marker_mode)), path)
        return path

    substrate = ' sub!' if mode == PEXMode.RC else ''
    composite_path = str(tmp_path / 'composite.spice')
    with open(composite_path, 'w', encoding='utf-8') as f:
        f.write(f".include {extracted_copy('exclusion_wire_through', ExclusionMarkerMode.PORTS)}\n"
                f".include {extracted_copy('exclusion_wire_middle', ExclusionMarkerMode.IGNORE)}\n"
                f".SUBCKT composite A B{substrate}\n"
                f"Xoutside A cut1 cut2 B{substrate} exclusion_wire_through\n"
                f"Xmodel cut1 cut2{substrate} exclusion_wire_middle\n"
                f".ENDS composite\n")
    flat_path = extracted_copy('exclusion_wire_through', ExclusionMarkerMode.IGNORE)

    ports = ['A', 'B'] + (['sub!'] if mode == PEXMode.RC else [])
    _, flat = ngspice_port_admittance(flat_path, 'exclusion_wire_through', ports, (6, 10), str(tmp_path))
    _, composite = ngspice_port_admittance(composite_path, 'composite', ports, (6, 10), str(tmp_path))
    assert np.abs(composite) == pytest.approx(np.abs(flat), rel=0.03)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('cell_name, marker_mode, arguments', [
    ('exclusion_wire_through', ExclusionMarkerMode.PORTS, ()),
])
def test_warns_of_ports_that_a_netlist_without_nodes_cannot_have(cell_name: str,
                                                                 marker_mode: ExclusionMarkerMode,
                                                                 arguments: Tuple[str, ...]):
    def warnings_of(mode: PEXMode) -> List[str]:
        with mock.patch('klayout_pex.rcx25.extractor.warning') as warning_mock:
            Extraction(cell_name, mode).run(marker_mode, *arguments)
        return [c.args[0] for c in warning_mock.call_args_list]

    assert any('--mode CC has one node per net' in message for message in warnings_of(PEXMode.CC))
    assert not any('one node per net' in message for message in warnings_of(PEXMode.RC))


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
def test_marker_of_a_layer_has_no_resistance_within_it_on_that_layer_only():
    extraction = Extraction('exclusion_plate_noqrc', PEXMode.R)
    ignored = extraction.run(ExclusionMarkerMode.IGNORE)
    assert ignored.rcx25_netlist_problems == []
    honored = extraction.run(ExclusionMarkerMode.TIE, '--exclusion-marker-layer', 'Metal3.noqrc')
    assert honored.rcx25_netlist_problems == []
    # NOTE: the plate has a pin only, and the wires have no pins at their other ends
    assert resistances(honored) == resistances(extraction.run(ExclusionMarkerMode.IGNORE)) == {}


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
@pytest.mark.parametrize('pdk_name, metal', [(PDKName.SKY130A, 'met2'), (PDKName.GF180MCUD, 'Metal2')])
def test_pdk_without_markers_takes_markers_of_the_user(pdk_name: PDKName, metal: str):
    extraction = Extraction('exclusion_user_marker_wire', PEXMode.R, pdk_name=pdk_name)
    ignored = resistances(extraction.run(ExclusionMarkerMode.IGNORE))
    honored = extraction.run(ExclusionMarkerMode.TIE, '--exclusion-marker-layer', '200/0')
    assert honored.rcx25_netlist_problems == []
    assert sum(resistances(honored).values()) == pytest.approx(ignored[pair('A', 'B')] * 39.0 / 59.0, rel=0.02)

    # NOTE: a marker of another layer has nothing to do with this wire
    other_layer = 'met3' if pdk_name == PDKName.SKY130A else 'Metal3'
    assert resistances(extraction.run(ExclusionMarkerMode.TIE, '--exclusion-marker-layer', f"200/0:{other_layer}")) \
           == ignored
    assert sum(resistances(extraction.run(ExclusionMarkerMode.TIE, '--exclusion-marker-layer', f"200/0:{metal}"))
               .values()) == sum(resistances(honored).values())


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
@pytest.mark.parametrize('mode', [PEXMode.R, PEXMode.RC])
def test_pin_within_a_marker_of_a_label_also_outside_is_not_the_port_of_the_cut(mode: PEXMode):
    # NOTE: the pin outside and the port at the cut with the same name would be one node
    with_label = Extraction('exclusion_same_label_within', mode).run(ExclusionMarkerMode.PORTS)
    assert with_label.rcx25_netlist_problems == []
    assert {'A', 'A__m0_0'} <= set(netlist_ports(with_label))
    assert resistances(with_label)[pair('A', 'A__m0_0')] > 0.5


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_substrate_net_stays_a_port_with_ports_at_markers():
    cli = Extraction('exclusion_tap_wire_through', PEXMode.RC).run(ExclusionMarkerMode.PORTS)
    assert cli.rcx25_netlist_problems == []
    assert 'sub!' in netlist_ports(cli), netlist_ports(cli)
    assert [port for port in netlist_ports(cli) if '__m0_' in port]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('marker_mode', [ExclusionMarkerMode.TIE, ExclusionMarkerMode.PORTS])
def test_any_angle_wire_is_cut_at_a_marker(marker_mode: ExclusionMarkerMode):
    # NOTE: rounded differently, slivers along the cuts would join what is on both sides of the marker
    cli = Extraction('exclusion_slanted_wire', PEXMode.R).run(marker_mode)
    assert cli.rcx25_netlist_problems == []
    values = resistances(cli)
    assert max(values.values()) < 10.0, values
    # NOTE: the capacitances of each side of the cut are on its side, not of the whole net
    assert len(values) >= 2


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_pin_of_the_substrate_within_a_marker_is_one_port_of_the_netlist():
    ported = Extraction('exclusion_substrate_pin_within', PEXMode.R).run(ExclusionMarkerMode.PORTS)
    ports = netlist_ports(ported)
    assert 'VSS' in ports
    assert len(set(ports)) == len(ports), ports


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_failure_of_the_resistance_extraction_names_the_net(tmp_path):
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    gds_path = pdk.gds_path('test_patterns', 'exclusion_wire_end.gds.gz')
    with mock.patch('klayout_pex.rcx25.r.r_extractor.klp.RNetExtractor') as extractor_mock:
        extractor_mock.return_value.extract.side_effect = RuntimeError('Internal error')
        code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D', '--mode', 'R', '--gds', gds_path,
                                                        '--lvsdb', lvsdb_fixture_path(pdk.name, gds_path)))
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert 'extraction fails for net W: Internal error' in ' '.join(output.split()), output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_net_entirely_within_a_marker_has_a_port_at_its_pin():
    cli = Extraction('exclusion_nmos_diode2_all', PEXMode.RC).run(ExclusionMarkerMode.PORTS)
    assert cli.rcx25_netlist_problems == []
    assert {'VDD', 'VSS'} <= set(netlist_ports(cli)), netlist_ports(cli)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk_name', [PDKName.SKY130A, PDKName.GF180MCUD])
def test_well_cut_between_device_and_tap_keeps_its_port_and_resistance(pdk_name: PDKName):
    extraction = Extraction('exclusion_nwell_between_pfet_and_tap', PEXMode.R, pdk_name=pdk_name)
    arguments = ('--exclusion-marker-layer', '200/0')
    tied = extraction.run(ExclusionMarkerMode.TIE, *arguments)
    ported = extraction.run(ExclusionMarkerMode.PORTS, *arguments)
    assert ported.rcx25_netlist_problems == []
    ports = [port for port in netlist_ports(ported) if '__m0_' in port]
    assert len(ports) == 2, netlist_ports(ported)
    values = resistances(ported)
    assert all(any(port in nodes for nodes in values) for port in ports)
    assert sum(values.values()) == pytest.approx(sum(resistances(tied).values()), rel=1e-6)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk_name, label', [(PDKName.SKY130A, 'VPWR'), (PDKName.GF180MCUD, 'VDD')])
def test_bulk_within_a_marker_does_not_bypass_its_model(pdk_name: PDKName, label: str):
    extraction = Extraction('exclusion_pfet_between_taps', PEXMode.R, pdk_name=pdk_name)
    arguments = ('--exclusion-marker-layer', '200/0')
    tied = effective_resistance(resistances(extraction.run(ExclusionMarkerMode.TIE, *arguments)), 'A', label)

    with mock.patch('klayout_pex.rcx25.extractor.warning') as warning_mock:
        ported = extraction.run(ExclusionMarkerMode.PORTS, *arguments)
    assert not [c.args[0] for c in warning_mock.call_args_list if 'joins pieces' in c.args[0]]
    assert ported.rcx25_netlist_problems == []
    ports = [port for port in netlist_ports(ported) if port.startswith(f"A_{label}__m0_")]
    assert len(ports) == 3, netlist_ports(ported)
    values = resistances(ported)
    assert effective_resistance(values, 'A', label) == float('inf')
    assert effective_resistance(values, 'A', label, joined=ports) == pytest.approx(tied, rel=1e-6)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk_name, arguments', [
    (PDKName.IHP_SG13G2, ()),
    (PDKName.SKY130A, ('--exclusion-marker-layer', '200/0')),
    (PDKName.GF180MCUD, ('--exclusion-marker-layer', '200/0')),
])
def test_taps_and_wells_do_not_bypass_the_model_of_a_rail(pdk_name: PDKName, arguments: Tuple[str, ...]):
    extraction = Extraction('exclusion_rail_between_taps', PEXMode.R, pdk_name=pdk_name)
    flat = effective_resistance(resistances(extraction.run(ExclusionMarkerMode.IGNORE)), 'A', 'B')
    tied = effective_resistance(resistances(extraction.run(ExclusionMarkerMode.TIE, *arguments)), 'A', 'B')
    assert tied == pytest.approx(flat * 280.0 / 300.0, rel=0.02)

    ported = extraction.run(ExclusionMarkerMode.PORTS, *arguments)
    assert ported.rcx25_netlist_problems == []
    ports = [port for port in netlist_ports(ported) if '__m0_' in port]
    assert len(ports) == 2, netlist_ports(ported)
    assert effective_resistance(resistances(ported), 'A', 'B', joined=ports) == pytest.approx(tied, rel=1e-6)
    assert effective_resistance(resistances(ported), 'A', 'B') == float('inf')


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


def _marker_over_layout(layout, cell_name: str, ports: bool, substrate_layer_name: str, **_):
    return Exclusions.from_region(kdb.Region(layout.cell(cell_name).bbox()), ports, substrate_layer_name)


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
    assert all(value in output for value in ('ignore', 'tie', 'ports')), output


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
