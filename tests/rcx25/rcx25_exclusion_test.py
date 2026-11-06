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

from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.pdk_config import PDK
from klayout_pex.pex25d.diagnostics import ExitCode
from klayout_pex.rcx25.exclusion import CutLayers, CutRequest, ExclusionMarkerMode, Exclusions
from klayout_pex.rcx25.extractor import add_filled_diffusion_to_cut_cells, devices_of_cut_cells
from klayout_pex.rcx25.pex_mode import PEXMode
from klayout_pex.tech_info import TechInfo
from klayout_pex.types import GDSPair
from tests.common.cli_runner import run_cli
from tests.common.lvsdb_fixtures import committed_fixtures, lvsdb_fixture_path
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction, effective_resistance, netlist_path_of, netlist_ports, pair

parent_suite = "kpex/2.5D exclusion markers"
tags = ("PEX", "2.5D", "Exclusion")

Values = Dict[FrozenSet[str], float]

# draws over a design, with the layout, the top cell, a cell to cut, and the box of the design
DrawOverDesign = Callable[[kdb.Layout, kdb.Cell, kdb.Cell, kdb.Box], None]


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
def test_pin_within_a_marker_names_a_cut_that_vias_within_join_it_to():
    # NOTE: the pin P is on the Metal3 bridge, which the vias within the marker join to the Metal2 of both cuts,
    #       so it names the cut nearer to it, from A, and the other one is numbered
    honored = Extraction('exclusion_via_stack_pin_on_bridge', PEXMode.R).run(ExclusionMarkerMode.PORTS)
    assert honored.rcx25_netlist_problems == []
    assert netlist_ports(honored) == ['A', 'A_B_P__m0_0', 'B', 'P']
    values = resistances(honored)
    assert values[pair('A', 'P')] == pytest.approx(values[pair('A_B_P__m0_0', 'B')], abs=0.001)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_label_in_a_child_cell_names_the_cut_of_its_marker():
    # NOTE: e.g. of an inductor in a child cell, whose labels are the pins of its model (#403)
    extraction = Extraction('label_in_child_cell_within_marker', PEXMode.R)
    assert sorted(netlist_ports(extraction.run(ExclusionMarkerMode.PORTS))) == ['inner', 'outer']
    assert netlist_ports(extraction.run(ExclusionMarkerMode.IGNORE)) == ['outer']
    assert netlist_ports(extraction.run(ExclusionMarkerMode.TIE)) == ['outer']


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
    # NOTE: though LVS has all of this on one net, the leads are apart in the netlist, so they have a capacitance
    assert capacitances(honored)[pair('OSCN', 'OSCP')] > 0.0


# NOTE: the wires are apart in the netlist in both, whether something within the marker joins them or not
@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('joined_cell_name, apart_cell_name', [
    # NOTE: one polygon, so their capacitance is between parts of it
    ('exclusion_hairpin', 'exclusion_hairpin_open'),
    # NOTE: polygons of one net
    ('exclusion_hairpin_bridge_m2', 'exclusion_hairpin_bridge_m2_open'),
    # NOTE: on two layers, with an overlap and a fringe
    ('exclusion_stacked_wires', 'exclusion_stacked_wires_open'),
])
def test_wires_only_a_model_joins_have_the_capacitances_of_two_nets(joined_cell_name: str, apart_cell_name: str):
    joined = Extraction(joined_cell_name, PEXMode.RC).run(ExclusionMarkerMode.PORTS)
    assert joined.rcx25_netlist_problems == []
    assert pair('A_B__m0_0', 'A_B__m0_1') in capacitances(joined)

    # NOTE: the cuts of a net are numbered from the bottom up, where A is
    node_of_two_nets = {'A_B__m0_0': 'A__m0_0', 'A_B__m0_1': 'B__m0_0'}
    joined_values = {frozenset(node_of_two_nets.get(node, node) for node in key): value
                     for key, value in capacitances(joined).items()}

    apart = Extraction(apart_cell_name, PEXMode.RC).run(ExclusionMarkerMode.PORTS)
    assert apart.rcx25_netlist_problems == []
    assert joined_values == pytest.approx(capacitances(apart), abs=0.001)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode, marker_mode', [
    (PEXMode.RC, ExclusionMarkerMode.TIE),  # NOTE: they are one net in the netlist, like without a marker
    (PEXMode.CC, ExclusionMarkerMode.PORTS),  # NOTE: a net is one node, so there are no ports
])
def test_wires_of_a_net_have_no_capacitance_where_the_netlist_has_them_on_one_net(mode: PEXMode,
                                                                                  marker_mode: ExclusionMarkerMode):
    honored = Extraction('exclusion_hairpin', mode).run(marker_mode)
    assert honored.rcx25_netlist_problems == []
    assert capacitances(honored)
    assert all('VSUBS' in key for key in capacitances(honored)), capacitances(honored)


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
    ('cut_coil', ExclusionMarkerMode.IGNORE, ('--cut', 'coil')),
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


def exclusions_of_cell_of_layers(pdk_name: PDKName,
                                 path_components: Sequence[str],
                                 is_of_cell: Callable[[GDSPair], bool],
                                 over_design: Sequence[GDSPair] = (),
                                 over_design_of_cell: Sequence[GDSPair] = (),
                                 draw: Optional[DrawOverDesign] = None) \
        -> Tuple[Exclusions, KLayoutExtractionContext, TechInfo]:
    """
    :param path_components: of a design
    :param is_of_cell: which layers of the design go to a cell that is cut, the others stay in the top cell
    :param over_design: the layers on which the top cell also has a shape over the design (e.g. a wire, a boundary)
    :param over_design_of_cell: the same of the cell
    :param draw: draws more with the layout, the top cell, the cell, and the box of the design
    :return: the exclusions of the cell, with the context and tech info of the design, without running LVS
             on the hierarchy of the design, which LVS flattens
    """
    extraction = RCX25Extraction(pdk=PDKTestConfig(pdk_name), pex_mode=PEXMode.CC, blackbox=True)
    lvsdb = extraction.read_lvsdb(*path_components)
    tech_info = TechInfo.from_json(PDK.from_string(extraction.pdk.name).config.tech_pb_json_path,
                                   dielectric_filter=None)
    cell_name = lvsdb.internal_top_cell().name
    context = KLayoutExtractionContext.prepare_extraction(lvsdb=lvsdb, top_cell=cell_name, tech=tech_info,
                                                          blackbox_devices=True)

    design = kdb.Layout()
    design.read(extraction.pdk.gds_path(*path_components))
    layout = kdb.Layout()
    layout.dbu = design.dbu
    top = layout.create_cell(cell_name)
    cell = layout.create_cell('block')
    for layer_index in design.layer_indexes():
        info = design.get_info(layer_index)
        target = cell if is_of_cell((info.layer, info.datatype)) else top
        target.shapes(layout.layer(info.layer, info.datatype)) \
            .insert(kdb.Region(design.top_cell().begin_shapes_rec(layer_index)))
    top.insert(kdb.CellInstArray(cell.cell_index(), kdb.Trans()))
    box = design.top_cell().bbox().enlarged(1000, 1000)
    for target, gds_pairs in ((top, over_design), (cell, over_design_of_cell)):
        for gds_pair in gds_pairs:
            target.shapes(layout.layer(*gds_pair)).insert(box)
    if draw is not None:
        draw(layout, top, cell, design.top_cell().bbox())

    exclusions = Exclusions.from_layout(layout, cell_name, marker_layers=[], dbu=context.dbu, ports=True,
                                        cut_requests=[CutRequest('block')], cut_layers=CutLayers.of_tech(tech_info))
    return exclusions, context, tech_info


def classes_of_devices_of_cell_of_layers(pdk_name: PDKName,
                                         path_components: Sequence[str],
                                         is_of_cell: Callable[[GDSPair], bool],
                                         over_design: Sequence[GDSPair] = (),
                                         over_design_of_cell: Sequence[GDSPair] = (),
                                         draw: Optional[DrawOverDesign] = None) \
        -> Tuple[List[str], List[str]]:
    """
    :return: the device classes of the devices the design has, and of those of the cell
             (see exclusions_of_cell_of_layers)
    """
    exclusions, context, tech_info = exclusions_of_cell_of_layers(pdk_name, path_components, is_of_cell,
                                                                  over_design, over_design_of_cell, draw)
    device_ids = devices_of_cut_cells(exclusions, context, tech_info)
    return ([device.device_class().name for device in context.top_circuit.each_device()],
            [device.device_class().name for device in context.top_circuit.each_device() if device.id() in device_ids])


def devices_of_cell_of_layers(pdk_name: PDKName,
                              path_components: Sequence[str],
                              is_of_cell: Callable[[GDSPair], bool],
                              over_design: Sequence[GDSPair] = (),
                              over_design_of_cell: Sequence[GDSPair] = (),
                              draw: Optional[DrawOverDesign] = None) \
        -> Tuple[int, int]:
    """
    :return: how many devices the design has, and how many of them are of the cell
             (see classes_of_devices_of_cell_of_layers)
    """
    device_classes, device_classes_of_cell = classes_of_devices_of_cell_of_layers(
        pdk_name, path_components, is_of_cell, over_design, over_design_of_cell, draw)
    return len(device_classes), len(device_classes_of_cell)


def fill_squares(layout: kdb.Layout, cell: kdb.Cell, box: kdb.Box, gds_pairs: Sequence[GDSPair]):
    """
    Squares of 1 µm with a pitch of 1.5 µm around the box and over it, on the layers, at a DBU of 1 nm
    """
    around = box.enlarged(3000, 3000)
    for gds_pair in gds_pairs:
        for x in range(around.left, around.right, 1500):
            for y in range(around.bottom, around.top, 1500):
                cell.shapes(layout.layer(*gds_pair)).insert(kdb.Box(x, y, x + 1000, y + 1000))


def ring_around(layout: kdb.Layout, cell: kdb.Cell, box: kdb.Box, gds_pairs: Sequence[GDSPair], width: int = 300):
    for gds_pair in gds_pairs:
        for side in (kdb.Box(box.left, box.bottom, box.left + width, box.top),
                     kdb.Box(box.right - width, box.bottom, box.right, box.top),
                     kdb.Box(box.left, box.bottom, box.right, box.bottom + width),
                     kdb.Box(box.left, box.top - width, box.right, box.top)):
            cell.shapes(layout.layer(*gds_pair)).insert(side)


CMOMI = ('test_patterns', 'cap_cmomi_w5u_l5u_m4_m5_none.gds.gz')
INDUCTOR2 = ('test_patterns', 'inductor2_w2u_d15u48_tm2_wires_50u.gds.gz')
BJTS = ('test_patterns', 'bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa.gds.gz')
ANTENNA_DIODES = ('test_patterns', 'diode_dantenna_dpantenna.gds.gz')
ESD_DIODE = ('test_patterns', 'esd_diodevss_2kv.gds.gz')
GF_DIFFUSION_RESISTORS = ('test_patterns', 'res_diffusion_w1_l4.gds.gz')
GF_DIODES = ('test_patterns', 'diode_pw2dw_dw2ps_03v3_w2_l4.gds.gz')
CMIM = ('test_patterns', 'cap_cmim_20um_x_20um_over_m4_wire.gds.gz')
SKY_VPP = ('cap_vpp_04p4x04p6_l1m1m2_noshield', 'cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz')
SKY_MIM = ('cap_mim_m3_w18p9_l5p1', 'cap_mim_m3_w18p9_l5p1.gds.gz')
GF_MIM = ('test_patterns', 'cap_mim_m4m5.gds.gz')
GF_DNWELL: GDSPair = (12, 0)
GF_METAL1: GDSPair = (34, 0)
IHP_BOUNDARY: GDSPair = (189, 4)
IHP_METAL1: GDSPair = (8, 0)
IHP_METAL5: GDSPair = (67, 0)
IHP_TOP_METAL2: GDSPair = (134, 0)
IHP_ACTIV: GDSPair = (1, 0)
IHP_PSD: GDSPair = (14, 0)
IHP_NWELL: GDSPair = (31, 0)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk_name, design, wires', [
    (PDKName.GF180MCUD, GF_DIFFUSION_RESISTORS, GF_METAL1),
    (PDKName.GF180MCUD, GF_DIODES, GF_METAL1),
    (PDKName.IHP_SG13G2, CMOMI, IHP_METAL5),
    (PDKName.IHP_SG13G2, INDUCTOR2, IHP_TOP_METAL2),
    (PDKName.IHP_SG13G2, ANTENNA_DIODES, IHP_METAL1),
])
def test_cell_of_the_wires_on_terminals_has_no_devices(pdk_name: PDKName, design: Sequence[str], wires: GDSPair):
    devices, of_cell = devices_of_cell_of_layers(pdk_name, design, lambda gds_pair: gds_pair == wires)
    assert devices > 0
    assert of_cell == 0


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk_name, design, wires', [
    (PDKName.GF180MCUD, GF_DIFFUSION_RESISTORS, GF_METAL1),
    (PDKName.GF180MCUD, GF_DIODES, GF_METAL1),
    (PDKName.IHP_SG13G2, BJTS, IHP_METAL1),
    (PDKName.IHP_SG13G2, ANTENNA_DIODES, IHP_METAL1),
    (PDKName.IHP_SG13G2, ESD_DIODE, IHP_METAL1),
    (PDKName.IHP_SG13CMOS5L, ('inductor3_w2u_d25u85_2_turns', 'inductor3_w2u_d25u85_2_turns.gds.gz'), IHP_TOP_METAL2),
])
def test_wire_of_the_top_on_terminals_leaves_the_devices_to_the_cell(pdk_name: PDKName,
                                                                     design: Sequence[str],
                                                                     wires: GDSPair):
    devices, of_cell = devices_of_cell_of_layers(pdk_name, design, lambda _: True, over_design=[wires])
    assert (devices, of_cell) == (devices, devices)
    assert devices > 0


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk_name, cell_name', [
    (PDKName.GF180MCUD, 'cut_diffusion_resistors_wire_on_pad'),
    (PDKName.IHP_SG13G2, 'cut_bjts_wire_on_collector'),
])
def test_wire_of_the_top_on_a_terminal_found_by_lvs_leaves_the_device_to_the_cell(pdk_name: PDKName, cell_name: str):
    cut = Extraction(cell_name, PEXMode.R, blackbox=True, pdk_name=pdk_name).run(ExclusionMarkerMode.IGNORE,
                                                                                 '--cut', 'block=X')
    assert devices_of(cut) == []
    assert cut.rcx25_netlist_problems == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_diffusion_that_lvs_fills_up_for_a_device_of_a_cut_cell_is_of_the_cell():
    extraction = Extraction('cut_ldmos_pair', PEXMode.RC, pdk_name=PDKName.GF180MCUD)
    cut = extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []
    assert not [port for port in netlist_ports(cut) if port.startswith('X__')], netlist_ports(cut)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_devices_on_a_well_go_by_what_else_is_drawn_there():
    def is_dnwell(gds_pair: GDSPair) -> bool:
        return gds_pair == GF_DNWELL

    assert devices_of_cell_of_layers(PDKName.GF180MCUD, GF_DIODES, is_dnwell) == (2, 0)
    assert devices_of_cell_of_layers(PDKName.GF180MCUD, GF_DIODES, lambda gds_pair: not is_dnwell(gds_pair)) == (2, 2)
    assert devices_of_cell_of_layers(PDKName.GF180MCUD, GF_DIODES, lambda _: False,
                                     over_design_of_cell=[GF_DNWELL]) == (2, 0)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('design', [
    ('test_patterns', 'device_pcells.gds.gz'),
    CMOMI,
    INDUCTOR2,
])
def test_boundary_tells_no_devices(design: Sequence[str]):
    devices, of_cell = devices_of_cell_of_layers(PDKName.IHP_SG13G2, design, lambda _: False,
                                                 over_design_of_cell=[IHP_BOUNDARY])
    assert (devices > 0, of_cell) == (True, 0)
    devices, of_cell = devices_of_cell_of_layers(PDKName.IHP_SG13G2, design, lambda _: True,
                                                 over_design=[IHP_BOUNDARY])
    assert (devices > 0, of_cell) == (True, devices)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk_name, design, fill', [
    (PDKName.IHP_SG13G2, CMIM, [(1, 22), (5, 22)]),
    (PDKName.IHP_SG13G2, CMOMI, [(1, 22), (5, 22)]),
    (PDKName.SKY130A, SKY_VPP, [(62, 24)]),
    (PDKName.SKY130A, SKY_MIM, [(62, 24)]),
    (PDKName.GF180MCUD, GF_MIM, [(34, 4), (36, 4)]),
])
def test_fill_of_the_top_leaves_the_devices_to_the_cell(pdk_name: PDKName,
                                                        design: Sequence[str],
                                                        fill: Sequence[GDSPair]):
    device_count, of_cell = devices_of_cell_of_layers(
        pdk_name, design, lambda gds_pair: True,
        draw=lambda layout, top, cell, box: fill_squares(layout, top, box, fill))
    assert of_cell == device_count > 0


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk_name, design, boundary', [
    (PDKName.IHP_SG13G2, BJTS, IHP_BOUNDARY),
    (PDKName.SKY130A, SKY_VPP, (235, 4)),
    (PDKName.SKY130A, SKY_MIM, (235, 4)),
])
def test_boundary_of_the_top_within_the_cell_leaves_the_devices_to_it(pdk_name: PDKName,
                                                                      design: Sequence[str],
                                                                      boundary: GDSPair):
    def draw(layout: kdb.Layout, top: kdb.Cell, cell: kdb.Cell, box: kdb.Box):
        top.shapes(layout.layer(*boundary)).insert(box.enlarged(-100, -100))

    device_count, of_cell = devices_of_cell_of_layers(pdk_name, design, lambda gds_pair: True, draw=draw)
    assert of_cell == device_count > 0


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_cell_of_a_guard_ring_with_fill_blocks_has_no_device_within_it():
    def draw(layout: kdb.Layout, top: kdb.Cell, cell: kdb.Cell, box: kdb.Box):
        ring_around(layout, cell, box.enlarged(3000, 3000), [IHP_METAL1])
        for gds_pair in ((1, 23), (5, 23), (8, 23), (10, 23)):
            cell.shapes(layout.layer(*gds_pair)).insert(box.enlarged(2000, 2000))

    assert devices_of_cell_of_layers(PDKName.IHP_SG13G2, CMOMI, lambda gds_pair: False, draw=draw) == (1, 0)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_guard_ring_below_the_ports_of_a_mom_cap_tells_nothing_of_it():
    def ring_of(target: Callable[[kdb.Cell, kdb.Cell], kdb.Cell]) -> Callable[..., None]:
        def draw(layout: kdb.Layout, top: kdb.Cell, cell: kdb.Cell, box: kdb.Box):
            ring_around(layout, target(top, cell), box.enlarged(-200, -200), [IHP_ACTIV])
            ring_around(layout, target(top, cell), box.enlarged(-100, -100), [IHP_PSD], width=500)
        return draw

    assert devices_of_cell_of_layers(PDKName.IHP_SG13G2, CMOMI, lambda gds_pair: False,
                                     draw=ring_of(lambda top, cell: cell)) == (1, 0)
    assert devices_of_cell_of_layers(PDKName.IHP_SG13G2, CMOMI, lambda gds_pair: True,
                                     draw=ring_of(lambda top, cell: top)) == (1, 1)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_devices_of_the_top_stay_beside_the_diffusion_of_a_cell():
    def draw(layout: kdb.Layout, top: kdb.Cell, cell: kdb.Cell, box: kdb.Box):
        for polygon in kdb.Region(top.shapes(layout.layer(*IHP_ACTIV))).merged().each():
            polygon_box = polygon.bbox()
            cell.shapes(layout.layer(*IHP_ACTIV)).insert(kdb.Box(polygon_box.right, polygon_box.bottom,
                                                                 polygon_box.right + 100, polygon_box.top))

    device_classes, of_cell = classes_of_devices_of_cell_of_layers(
        PDKName.IHP_SG13G2, ('test_patterns', 'device_pcells.gds.gz'), lambda gds_pair: False, draw=draw)
    assert {'ntap1', 'ptap1'} <= set(device_classes)
    assert of_cell == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_tap_of_the_top_at_a_device_of_a_cell_tells_nothing_of_it():
    # NOTE: the p-taps of the design go to the top cell (e.g. a guard ring around the cell),
    #       also the one of the varicap, which its terminal SUB is on
    def draw(layout: kdb.Layout, top: kdb.Cell, cell: kdb.Cell, box: kdb.Box):
        activ = layout.layer(*IHP_ACTIV)
        activ_of_cell = kdb.Region(cell.shapes(activ))
        p_taps = activ_of_cell & kdb.Region(cell.shapes(layout.layer(*IHP_PSD))) - \
            kdb.Region(cell.shapes(layout.layer(*IHP_NWELL)))
        cell.shapes(activ).clear()
        cell.shapes(activ).insert(activ_of_cell - p_taps)
        top.shapes(activ).insert(p_taps)

    _, of_cell = classes_of_devices_of_cell_of_layers(
        PDKName.IHP_SG13G2, ('test_patterns', 'device_pcells.gds.gz'), lambda gds_pair: True, draw=draw)
    assert 'sg13_hv_svaricap' in of_cell


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_ring_of_a_device_is_no_diffusion_of_a_cut_cell():
    exclusions, context, tech_info = exclusions_of_cell_of_layers(
        PDKName.IHP_SG13G2, ('test_patterns', 'device_pcells.gds.gz'), lambda gds_pair: True)
    exclusions.removed_device_blocks = devices_of_cut_cells(exclusions, context, tech_info)
    assert 'schottky_nbl1' in [device.device_class().name for device in context.top_circuit.each_device()
                               if device.id() in exclusions.removed_device_blocks]
    area = exclusions.mask('Activ').area()
    add_filled_diffusion_to_cut_cells(exclusions, context, tech_info)
    assert exclusions.mask('Activ').area() == area


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_diffusion_of_a_cell_tells_nothing_of_an_isolbox_of_the_top_over_it():
    device_classes, of_cell = classes_of_devices_of_cell_of_layers(
        PDKName.IHP_SG13G2, ('test_patterns', 'cut_cell_of_devices.gds.gz'), lambda gds_pair: False,
        over_design_of_cell=[IHP_ACTIV, IHP_METAL1])
    assert 'isolbox' in device_classes
    assert 'isolbox' not in of_cell


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk_name', [PDKName.IHP_SG13G2, PDKName.SKY130A, PDKName.GF180MCUD])
def test_cell_of_a_design_has_all_its_devices_the_top_cell_none(pdk_name: PDKName):
    designs = [fixture.relative_gds_path for fixture in committed_fixtures() if fixture.pdk.value == pdk_name.value]
    assert designs
    for design in designs:
        path_components = design.split(os.sep)
        device_count, of_cell = devices_of_cell_of_layers(pdk_name, path_components, lambda gds_pair: True)
        assert of_cell == device_count, design
        assert devices_of_cell_of_layers(pdk_name, path_components, lambda gds_pair: False)[1] == 0, design


def devices_of(cli: KpexCLI) -> List[List[str]]:
    with open(netlist_path_of(cli), encoding='utf-8') as f:
        return [line.split() for line in f.read().replace('\n+', '').splitlines() if line.startswith('X')]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.R, PEXMode.RC])
def test_cut_cell_has_ports_named_after_its_labels(mode: PEXMode):
    cli = Extraction('cut_coil', mode).run(ExclusionMarkerMode.IGNORE, '--cut', 'coil=xind', '--cut-keep-net', 'VDD')
    assert cli.rcx25_netlist_problems == []
    assert {'OSCP', 'OSCN', 'VCT', 'xind__LA', 'xind__LB', 'xind__CT', 'VC', 'VDD'} <= set(netlist_ports(cli))
    values = resistances(cli)
    assert all(key in values for key in (pair('OSCP', 'xind__LA'), pair('OSCN', 'xind__LB'), pair('VCT', 'xind__CT')))
    # NOTE: the coil is left to the model
    assert not {key for key in values if len(key & {'xind__LA', 'xind__LB', 'xind__CT'}) == 2}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_routing_over_a_cut_cell_stays_extracted():
    # NOTE: what isn't a shape of the cell, unlike with a marker over all layers, so the Metal5 wire VC under the coil,
    #       and the net VDD of its guard ring, keep all of their capacitances, also to the coil, which is on its ports
    extraction = Extraction('cut_coil', PEXMode.CC)
    ignored = capacitances(extraction.run(ExclusionMarkerMode.IGNORE))
    cut = capacitances(extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'coil', '--cut-keep-net', 'VDD'))
    coil = 'OSCN,OSCP,VCT'
    assert set(ignored) == set(cut)
    for key, value in ignored.items():
        if key == pair(coil, 'VSUBS'):
            assert cut[key] < value / 2.0
        else:
            assert cut[key] == value, key


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_shapes_of_a_kept_net_are_no_shapes_of_the_cut_cell():
    extraction = Extraction('cut_coil', PEXMode.RC)
    without_keep = extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'coil=xind')
    assert without_keep.rcx25_netlist_problems == []
    # NOTE: the guard ring is left to the model, where the net enters the cell there is a port
    assert 'xind__VDD_0' in netlist_ports(without_keep)
    ring_left_out = capacitances(without_keep)[pair('VDD', 'VSUBS')]

    with_keep = extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'coil=xind', '--cut-keep-net', 'V?D')
    assert with_keep.rcx25_netlist_problems == []
    assert 'xind__VDD_0' not in netlist_ports(with_keep)
    assert capacitances(with_keep)[pair('VDD', 'VSUBS')] > ring_left_out * 5.0


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_devices_of_a_cut_cell_are_left_out():
    cut = Extraction('cut_block_with_mos', PEXMode.RC).run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []
    assert devices_of(cut) == []
    # NOTE: the labels of the cell don't make pins of the top cell, but ports of the model
    assert set(netlist_ports(cut)) == {'A', 'B', 'R', 'X__VDD', 'X__VSS', 'sub!'}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_devices_of_a_class_the_tech_info_does_not_know_stay_with_a_warning():
    with mock.patch.object(TechInfo, 'device_gds_pairs', return_value=None), \
         mock.patch('klayout_pex.rcx25.extractor.warning') as warning_mock:
        cut = Extraction('cut_block_with_mos', PEXMode.R).run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []
    assert [device[5] for device in devices_of(cut)] == ['sg13_lv_nmos']
    assert [c.args[0] for c in warning_mock.call_args_list if 'device classes' in c.args[0]] == [
        "The tech info doesn't tell what LVS makes these device classes from, so the netlist keeps their devices, "
        "also of the cut cells: sg13_lv_nmos"
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_devices_outside_a_cut_cell_stay():
    extraction = Extraction('cut_block_beside_mos', PEXMode.R)
    both = devices_of(extraction.run(ExclusionMarkerMode.IGNORE))
    assert len(both) == 2
    cut = extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'block')
    assert cut.rcx25_netlist_problems == []
    assert len(devices_of(cut)) == 1


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_terminals_of_a_removed_device_on_the_metal_of_the_top_cell_are_ports():
    cut = Extraction('cut_inductor2_leads_in_top', PEXMode.R, blackbox=True).run(ExclusionMarkerMode.IGNORE,
                                                                                 '--cut', 'ind=xind')
    assert cut.rcx25_netlist_problems == []
    assert devices_of(cut) == []
    ports = netlist_ports(cut)
    assert {'A', 'B'} <= set(ports), ports
    ports_of_inductor = [port for port in ports if port.startswith('xind__')]
    assert len(ports_of_inductor) == 2, ports
    values = resistances(cut)
    assert sorted(max(key - {'A', 'B'}) for key in values if key & {'A', 'B'}) == sorted(ports_of_inductor)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('specification, expected', [
    ('coil', ['coil_0__LA', 'coil_1__LA']),
    ('c?il', ['coil_0__LA', 'coil_1__LA']),
    ('coil=x', ['x_0__LA', 'x_1__LA']),
])
def test_instances_of_a_cut_cell_have_ports_of_their_own(specification: str, expected: List[str]):
    cut = Extraction('cut_coil_x2', PEXMode.R).run(ExclusionMarkerMode.IGNORE, '--cut', specification)
    assert cut.rcx25_netlist_problems == []
    assert set(expected) <= set(netlist_ports(cut))


def flat_and_composite_of_coil(mode: PEXMode, work_dir: str) -> Tuple[List[str], np.ndarray, np.ndarray]:
    """
    :return: the ports, and Y of the flat extraction of cut_coil, and of the one with the coil cut,
             with the coil on its own as its model, at 1 GHz
    """
    def extracted_copy(name: str, cli: KpexCLI) -> Tuple[str, List[str]]:
        path = os.path.join(work_dir, f"{name}.spice")
        shutil.copyfile(netlist_path_of(cli), path)
        return path, netlist_ports(cli)

    flat_path, ports = extracted_copy('flat', Extraction('cut_coil', mode).run(ExclusionMarkerMode.IGNORE))
    cut_path, cut_ports = extracted_copy('cut', Extraction('cut_coil', mode).run(ExclusionMarkerMode.IGNORE,
                                                                                 '--cut', 'coil=xind',
                                                                                 '--cut-keep-net', 'VDD'))
    model = Extraction('cut_coil_model', mode).run(ExclusionMarkerMode.IGNORE)
    model_path, model_ports = extracted_copy('model', model)

    composite_path = os.path.join(work_dir, 'composite.spice')
    connections_of_model = ' '.join(f"xind__{port}" if port != 'sub!' else port for port in model_ports)
    with open(composite_path, 'w', encoding='utf-8') as f:
        f.write(f".include {cut_path}\n"
                f".include {model_path}\n"
                f".SUBCKT composite {' '.join(ports)}\n"
                f"Xoutside {' '.join(cut_ports)} cut_coil\n"
                f"Xmodel {connections_of_model} cut_coil_model\n"
                f".ENDS composite\n")

    _, flat = ngspice_port_admittance(flat_path, 'cut_coil', ports, (9, 9), work_dir)
    _, composite = ngspice_port_admittance(composite_path, 'composite', ports, (9, 9), work_dir)
    return ports, flat[0], composite[0]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@requires_ngspice
def test_model_of_a_cut_cell_gives_the_resistances_of_the_flat_extraction(tmp_path):
    # The coil, extracted on its own, stands for its model
    _, flat, composite = flat_and_composite_of_coil(PEXMode.R, str(tmp_path))
    assert np.abs(flat).max() > 0.1
    assert np.abs(composite) == pytest.approx(np.abs(flat), rel=1e-3)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@requires_ngspice
def test_model_of_a_cut_cell_gives_the_capacitances_of_the_flat_extraction(tmp_path):
    ports, flat, composite = flat_and_composite_of_coil(PEXMode.RC, str(tmp_path))
    coil = [ports.index(name) for name in ('OSCP', 'OSCN', 'VCT')]
    around = [ports.index(name) for name in ('VC', 'VDD')]
    substrate = ports.index('sub!')

    # NOTE: what is outside of the cell is what it was, so the resistances of the coil
    assert np.abs(composite[np.ix_(coil, coil)]) == pytest.approx(np.abs(flat[np.ix_(coil, coil)]), rel=1e-3)
    assert np.abs(composite[np.ix_(around, around)]) == pytest.approx(np.abs(flat[np.ix_(around, around)]), rel=1e-3)
    assert np.abs(composite[np.ix_(around, [substrate])]) == pytest.approx(np.abs(flat[np.ix_(around, [substrate])]),
                                                                           rel=1e-3)

    # NOTE: the wires around the coil couple to the same metal, in sum over the coil,
    #       at the ports of the cut instead of along the coil, which the coil's low resistance hides
    assert np.abs(composite[np.ix_(coil, around)].sum(axis=0)) == \
           pytest.approx(np.abs(flat[np.ix_(coil, around)].sum(axis=0)), rel=1e-3)

    # NOTE: the model on its own has no shielding by these wires, which is the error of such a model
    composite_to_substrate = np.abs(composite[np.ix_(coil, [substrate])].sum())
    flat_to_substrate = np.abs(flat[np.ix_(coil, [substrate])].sum())
    assert composite_to_substrate == pytest.approx(flat_to_substrate * 1.1, rel=0.03)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_cut_of_a_cell_beside_a_marker_without_ports_is_a_port():
    # NOTE: the lead LA goes on from the marker into the cell, without metal outside both between them
    extraction = Extraction('cut_coil_beside_marker', PEXMode.R)
    without_marker = resistances(extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'coil=xind',
                                                '--cut-keep-net', 'VDD'))
    cli = extraction.run(ExclusionMarkerMode.TIE, '--cut', 'coil=xind', '--cut-keep-net', 'VDD')
    assert cli.rcx25_netlist_problems == []
    assert 'xind__LA' in netlist_ports(cli)
    # NOTE: half of the wire from OSCP to the cell is within the marker
    assert resistances(cli)[pair('OSCP', 'xind__LA')] == pytest.approx(without_marker[pair('OSCP', 'xind__LA')] / 2.0,
                                                                       rel=0.05)
    assert resistances(cli)[pair('OSCN', 'xind__LB')] == without_marker[pair('OSCN', 'xind__LB')]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.R, PEXMode.RC])
def test_devices_of_a_cut_cell_with_a_terminal_on_a_kept_net_are_left_out(mode: PEXMode):
    # NOTE: the model has the device, whatever net its terminals are on, and the net needs a port at them
    cli = Extraction('cut_block_with_mos', mode).run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X',
                                                     '--cut-keep-net', 'B')
    assert cli.rcx25_netlist_problems == []
    assert devices_of(cli) == []
    assert any(port.startswith('X__') and port != 'X__VSS' for port in netlist_ports(cli)), netlist_ports(cli)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_wire_between_parts_of_a_net_shields_them_from_each_other():
    # NOTE: the wire M ends in front of the bridge of the wires, or its gap, which changes the capacitances of M,
    #       but the wires only see each other beyond its end, as two nets do
    joined = capacitances(Extraction('exclusion_hairpin_around_wire', PEXMode.RC).run(ExclusionMarkerMode.PORTS))
    apart = capacitances(Extraction('exclusion_hairpin_around_wire_open', PEXMode.RC).run(ExclusionMarkerMode.PORTS))
    assert pair('A', 'M') in joined and pair('A', 'M') in apart
    assert pair('A', 'B') not in joined and pair('A', 'B') not in apart
    assert joined[pair('A_B__m0_0', 'A_B__m0_1')] == pytest.approx(apart[pair('A__m0_0', 'B__m0_0')], abs=0.001)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_label_names_the_port_of_the_shapes_it_is_on_only():
    # NOTE: the strips of the cell are joined only by a wire of the top cell, so one port would short that wire
    cli = Extraction('cut_two_strips', PEXMode.R).run(ExclusionMarkerMode.IGNORE, '--cut', 'blk')
    assert cli.rcx25_netlist_problems == []
    ports = netlist_ports(cli)
    assert 'blk_0__X' in ports and 'blk_0__T_0' in ports, ports
    values = resistances(cli)
    assert values[pair('T', 'blk_0__X')] == pytest.approx(values[pair('T', 'blk_0__T_0')], rel=0.05)
    assert values[pair('T', 'blk_0__X')] > 2.0


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
def test_marker_without_ports_beside_a_cut_cell_keeps_the_capacitances_of_the_parts_of_the_net():
    # NOTE: the wires are one net only by the cell, and the wire from B has nothing to do with the marker on the other
    extraction = Extraction('cut_bend_beside_marker', PEXMode.RC)
    cut = capacitances(extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'bend'))
    with_marker_cli = extraction.run(ExclusionMarkerMode.TIE, '--cut', 'bend')
    assert with_marker_cli.rcx25_netlist_problems == []
    with_marker = capacitances(with_marker_cli)

    def total_of(values: Values, nets: Set[str]) -> float:
        return sum(value for key, value in values.items() if 'VSUBS' in key and key & nets)

    assert pair('A', 'B') in cut and pair('A', 'B') in with_marker
    b_nodes = {'B', 'bend_0__B_0'}
    assert total_of(with_marker, b_nodes) == pytest.approx(total_of(cut, b_nodes), rel=1e-3)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.CC, PEXMode.RC])
def test_excluded_net_keeps_its_capacitance_to_a_well_of_another_net(mode: PEXMode):
    extraction = Extraction('exclusion_wire_over_nwell', mode)
    ignored = capacitances(extraction.run(ExclusionMarkerMode.IGNORE))
    excluded = capacitances(extraction.run(ExclusionMarkerMode.IGNORE, '--exclude-net', 'W'))
    assert ignored[pair('NW', 'W')] > 0.0
    assert excluded[pair('NW', 'W')] == ignored[pair('NW', 'W')]


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
@pytest.mark.parametrize('cell_name, cut', [('cut_rotated_cell', 'seg'), ('cut_rotated_child', 'block')])
def test_cell_at_any_angle_is_an_error(cell_name: str, cut: str, tmp_path):
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    gds_path = pdk.gds_path('test_patterns', f"{cell_name}.gds.gz")
    code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D', '--gds', gds_path,
                                                    '--lvsdb', lvsdb_fixture_path(pdk.name, gds_path),
                                                    '--cut', cut))
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert 'an instance of the cell seg has an angle of 30' in ' '.join(output.split()), output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_capacitances_of_a_wire_over_a_well_stay_on_its_side_of_a_marker():
    extraction = Extraction('exclusion_wire_beside_marker_over_nwell', PEXMode.RC, pdk_name=PDKName.SKY130A)
    arguments = ('--exclusion-marker-layer', '200/0')
    tied = extraction.run(ExclusionMarkerMode.TIE, *arguments)
    ported = extraction.run(ExclusionMarkerMode.PORTS, *arguments)
    assert ported.rcx25_netlist_problems == []

    def to_well(cli: KpexCLI) -> float:
        return sum(value for nodes, value in capacitances(cli).items() if 'N' in nodes and 'VSUBS' not in nodes
                   and any(node.startswith('VPWR') for node in nodes))

    values = capacitances(ported)
    assert 0.0 < values[pair('N', 'VPWR__m0_1')]
    assert pair('N', 'VPWR__m0_0') not in values
    assert to_well(ported) == pytest.approx(to_well(tied), rel=1e-2)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('marker_mode, arguments', [
    (ExclusionMarkerMode.IGNORE, ('--cut', 'block=X')),
    (ExclusionMarkerMode.PORTS, ()),
])
def test_port_along_a_wire_does_not_short_it(marker_mode: ExclusionMarkerMode, arguments: Tuple[str, ...]):
    extraction = Extraction('cut_strip_along_wire', PEXMode.R)
    flat = effective_resistance(resistances(extraction.run(ExclusionMarkerMode.IGNORE)), 'A', 'B')
    cut = extraction.run(marker_mode, *arguments)
    assert cut.rcx25_netlist_problems == []
    assert len([port for port in netlist_ports(cut) if '__' in port]) == 1, netlist_ports(cut)
    # NOTE: half the width along half the length
    assert effective_resistance(resistances(cut), 'A', 'B') >= flat * 1.45


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_pin_of_the_substrate_within_a_marker_is_one_port_of_the_netlist():
    ported = Extraction('exclusion_substrate_pin_within', PEXMode.R).run(ExclusionMarkerMode.PORTS)
    ports = netlist_ports(ported)
    assert 'VSS' in ports
    assert len(set(ports)) == len(ports), ports


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_net_kept_out_of_a_cut_cell_keeps_its_well():
    extraction = Extraction('cut_ntaps_in_one_nwell', PEXMode.R, pdk_name=PDKName.SKY130A)
    flat = resistances(extraction.run(ExclusionMarkerMode.IGNORE))
    assert effective_resistance(flat, 'VL', 'VR') > 2000.0

    kept = extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X', '--cut-keep-net', 'VL,VR')
    assert not [port for port in netlist_ports(kept) if port.startswith('X__')]
    assert resistances(kept) == flat


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.R, PEXMode.RC])
def test_label_of_a_cut_cell_and_the_top_cell_stays_a_pin(mode: PEXMode):
    cut = Extraction('cut_pad_with_same_label_in_top', mode).run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []
    assert set(netlist_ports(cut)) - {'sub!'} == {'W', 'P', 'X__P'}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_no_warning_of_lost_plates_if_a_cut_cell_only_draws_wires_on_one():
    extraction = Extraction('cap_cmim_20um_x_20um_metal5_routes_in_cells', PEXMode.RC)
    with mock.patch('klayout_pex.rcx25.extractor.warning') as warning_mock:
        extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'ROUTE*')
    assert not [c.args[0] for c in warning_mock.call_args_list if 'capacitances of their plates' in c.args[0]]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_net_labelled_like_a_piece_stays_apart_from_it():
    def values(cell_name: str) -> List[float]:
        extraction = Extraction(cell_name, PEXMode.RC)
        return sorted(capacitances(extraction.run(ExclusionMarkerMode.PORTS)).values())

    assert values('exclusion_wire_beside_label_of_piece') == \
        pytest.approx(values('exclusion_wire_beside_label_of_other_net'), rel=1e-3)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('cell_name', ['cut_pfets_sharing_diffusion', 'cut_pfet_drain_with_contacts_in_top'])
def test_diffusion_of_the_top_stays_extracted_beside_a_device_of_a_cut_cell(cell_name: str):
    extraction = Extraction(cell_name, PEXMode.R, blackbox=True, pdk_name=PDKName.SKY130A)
    flat = extraction.run(ExclusionMarkerMode.IGNORE)
    nodes_of_flat = [node for device in devices_of(flat) for node in device[1:5]]
    resistances_of_flat = resistances(flat)
    cut = extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []
    # NOTE: the pin D reaches the drain, on one port, as the flat extraction has it
    assert [port for port in netlist_ports(cut) if port.startswith('X__D')] == ['X__D']
    drain_of_flat = next(node for node in nodes_of_flat if node.startswith('D.P'))
    assert effective_resistance(resistances(cut), 'D', 'X__D') == \
           pytest.approx(effective_resistance(resistances_of_flat, 'D', drain_of_flat), rel=1e-3)
    # NOTE: and a device that stays has its terminal on that drain there too
    assert all('X__D' in device for device in devices_of(cut))


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_resistor_of_the_top_between_those_of_a_cut_cell_stays():
    cut = Extraction('cut_resistors_in_series', PEXMode.R, blackbox=True, pdk_name=PDKName.SKY130A) \
        .run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []
    with open(netlist_path_of(cut), encoding='utf-8') as f:
        assert f.read().count('sky130_fd_pr__res_generic_m1') == 1


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_capacitances_of_a_well_within_a_cut_cell_go_to_the_ports_of_its_net():
    extraction = Extraction('cut_well_under_wire', PEXMode.RC, pdk_name=PDKName.SKY130A)
    flat = capacitances(extraction.run(ExclusionMarkerMode.IGNORE))
    cut = extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []
    values = capacitances(cut)
    assert not [nodes for nodes in values if any('#' in node for node in nodes)], values
    assert values[pair('W', 'X__VDD_0')] == pytest.approx(sum(value for nodes, value in flat.items()
                                                              if 'W' in nodes and 'VSUBS' not in nodes
                                                              and 'sky130_gnd' not in nodes), rel=0.05)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_terminals_of_two_devices_of_a_cut_cell_are_two_ports():
    extraction = Extraction('cut_nfets_wired_in_top', PEXMode.R, blackbox=True, pdk_name=PDKName.SKY130A)
    flat = extraction.run(ExclusionMarkerMode.IGNORE)
    resistances_to_sources_of_flat = sorted(effective_resistance(resistances(flat), 'VSS', device[3])
                                            for device in devices_of(flat))
    cut = extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []
    ports = [port for port in netlist_ports(cut) if port.startswith('X__S')]
    assert ports == ['X__S_0', 'X__S_1']
    assert sorted(effective_resistance(resistances(cut), 'VSS', port) for port in ports) == \
           pytest.approx(resistances_to_sources_of_flat, rel=1e-3)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_fill_of_a_cut_cell_is_left_out_with_it():
    cut = Extraction('cut_plate_with_fill', PEXMode.CC).run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert list(capacitances(cut)) == [pair('VSUBS', 'W')]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_instances_of_cut_cells_are_checked_before_lvs(tmp_path):
    gds_path = PDKTestConfig(PDKName.IHP_SG13G2).gds_path('test_patterns', 'cut_rotated_cell.gds.gz')
    with mock.patch.object(KpexCLI, 'create_lvsdb', side_effect=AssertionError('LVS runs')):
        code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D', '--gds', gds_path, '--cut', 'seg'))
    assert code != 0, output
    assert 'has an angle of 30' in ' '.join(output.split()), output
    assert 'LVS runs' not in output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('cell_name', ['cut_nfet_finger_beside_top', 'cut_nfet_finger_beside_sibling'])
def test_finger_beside_a_cut_cell_on_merged_polygons_stays(cell_name: str):
    extraction = Extraction(cell_name, PEXMode.R, blackbox=True, pdk_name=PDKName.SKY130A)
    assert len(devices_of(extraction.run(ExclusionMarkerMode.IGNORE))) == 2
    cut = extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []
    assert len(devices_of(cut)) == 1


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_terminal_of_a_device_across_a_cut_keeps_its_port_for_the_model():
    cut = Extraction('cut_half_of_gate', PEXMode.R, blackbox=True, pdk_name=PDKName.SKY130A) \
        .run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []
    devices = devices_of(cut)
    assert len(devices) == 1
    # NOTE: without it, the model of the block would only reach the gate through the poly beside it
    assert devices[0][2] in netlist_ports(cut)
    # NOTE: a port of its own, apart from the one of the cut that the gate touches, X__G_0
    assert devices[0][2] == 'X__G_1'
    assert sorted(netlist_ports(cut)) == ['G', 'X__G_0', 'X__G_1', 'sky130_gnd']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_ports_of_instances_on_a_diffusion_of_the_top_are_named_after_their_blocks():
    cut = Extraction('cut_instances_sharing_diffusion_in_top', PEXMode.R, blackbox=True, pdk_name=PDKName.SKY130A) \
        .run(ExclusionMarkerMode.IGNORE, '--cut', 'unit=U')
    assert cut.rcx25_netlist_problems == []
    assert cut.rcx25_extraction_results.summarize().exclusion_ports == {'L': ['U_0__S'],
                                                                        'M0': ['U_0__D', 'U_1__S'],
                                                                        'M1': ['U_1__D', 'U_2__S'],
                                                                        'R': ['U_2__D']}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_numbered_port_stays_apart_from_a_label_of_its_name():
    cut = Extraction('cut_wires_with_label_like_numbered_port', PEXMode.R, pdk_name=PDKName.SKY130A) \
        .run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []
    values = resistances(cut)
    # NOTE: 2 wires, of 2 µm each with a part of the wire that joins them
    assert values[pair('VDD', 'X__VDD_0')] == pytest.approx(values[pair('VDD', 'X__VDD_1')], rel=0.2)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_label_without_a_pin_shape_stays_a_port_beside_those_of_a_cut():
    cut = Extraction('cut_wire_with_label_without_pin', PEXMode.R, blackbox=True, pdk_name=PDKName.SKY130A) \
        .run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []
    assert {'A', 'X__A_0'} <= set(netlist_ports(cut))


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('cell_name', ['cut_taps_with_labels_a_b', 'cut_taps_with_labels_b_a'])
def test_net_of_a_pin_and_a_port_only_the_substrate_joins_stays_on_the_pin(cell_name: str):
    cut = Extraction(cell_name, PEXMode.R, blackbox=True, pdk_name=PDKName.GF180MCUD) \
        .run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []


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
def test_warns_of_a_net_through_abutting_cut_cells():
    with mock.patch('klayout_pex.rcx25.r.r_extractor.warning') as warning_mock:
        cli = Extraction('cut_abutting_wires', PEXMode.R).run(ExclusionMarkerMode.IGNORE, '--cut', 'seg')
    assert cli.rcx25_netlist_problems == []
    assert any('seg_0, seg_1, where they abut' in c.args[0] for c in warning_mock.call_args_list)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('cell_name', ['cut_boundary_over_devices', 'cut_boundary_over_inductor'])
def test_devices_under_a_shape_of_a_cut_cell_are_no_devices_of_it(cell_name: str):
    extraction = Extraction(cell_name, PEXMode.R, blackbox=True)
    flat = devices_of(extraction.run(ExclusionMarkerMode.IGNORE))
    assert flat
    cut = extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'block')
    assert cut.rcx25_netlist_problems == []
    assert len(devices_of(cut)) == len(flat)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('cell_name, pdk_name', [('cut_cell_of_devices', PDKName.IHP_SG13G2),
                                                 ('cut_ldmos_pair', PDKName.GF180MCUD)])
def test_devices_of_a_cut_cell_on_other_layers_than_their_shapes_are_left_out(cell_name: str, pdk_name: PDKName):
    # NOTE: terminals on the wells only, on layers only LVS knows, and on diffusion that LVS fills up
    extraction = Extraction(cell_name, PEXMode.R, blackbox=True, pdk_name=pdk_name)
    assert devices_of(extraction.run(ExclusionMarkerMode.IGNORE))
    cut = extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'block')
    assert cut.rcx25_netlist_problems == []
    assert devices_of(cut) == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_neighbor_under_the_overhang_of_a_cut_cell_has_no_ports():
    # NOTE: the nets of the rails enter the cell, the nets within its neighbors under its NWell and pSD don't
    extraction = Extraction('cut_abutting_std_cells', PEXMode.R, blackbox=True)
    flat = devices_of(extraction.run(ExclusionMarkerMode.IGNORE))
    cut = extraction.run(ExclusionMarkerMode.IGNORE, '--cut', 'middle=X')
    assert cut.rcx25_netlist_problems == []
    assert len(devices_of(cut)) == len(flat) * 2 // 3
    assert sorted(port for port in netlist_ports(cut) if port.startswith('X__')) == ['X__VDD', 'X__VSS']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.R, PEXMode.RC])
def test_label_of_a_cut_cell_under_a_via_from_above_names_the_port(mode: PEXMode):
    cut = Extraction('cut_pad_via_on_label', mode).run(ExclusionMarkerMode.IGNORE, '--cut', 'block=X')
    assert cut.rcx25_netlist_problems == []
    assert set(netlist_ports(cut)) - {'sub!'} == {'W', 'X__P'}


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
def test_metal_of_a_tap_within_a_marker_without_ports_is_on_its_net():
    # NOTE: only the substrate joins the metal of the taps, the one of B is within the marker, so it has no resistance
    extraction = Extraction('exclusion_ptap_within_marker', PEXMode.R)
    ignored = resistances(extraction.run(ExclusionMarkerMode.IGNORE))
    tied = extraction.run(ExclusionMarkerMode.TIE)
    assert tied.rcx25_netlist_problems == []
    assert effective_resistance(resistances(tied), 'A', 'B') == \
           pytest.approx(effective_resistance(ignored, 'A', 'A,B'), abs=0.002)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('arguments, message', [
    (('--cut', 'nope'), 'no such cell below cut_coil, which has: coil'),
    (('--cut', '=x'), 'expected CELL or CELL=PREFIX'),
    (('--cut', 'coil='), 'expected CELL or CELL=PREFIX'),
    (('--cut', 'coil=x y'), 'may only have letters, digits and _'),
    (('--cut', 'coil=x', '--cut', 'other=x'), 'given several times: x'),
    (('--cut-keep-net', 'VDD'), '--cut-keep-net VDD needs --cut'),
    (('--cut', 'coil=a', '--cut', 'coil=b'), '--cut coil=b: all instances of its cells are of another --cut'),
    (('--cut', 'coil', '--magic'), 'applies to the 2.5D engine, FasterCap and FastCap2, not to MAGIC'),
])
def test_invalid_cut_is_an_error_listing_the_valid_values(tmp_path, arguments: Tuple[str, ...], message: str):
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    gds_path = pdk.gds_path('test_patterns', 'cut_coil.gds.gz')
    code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D', '--gds', gds_path,
                                                    '--lvsdb', lvsdb_fixture_path(pdk.name, gds_path), *arguments))
    assert code != 0, output
    assert message in ' '.join(output.split()), output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_cut_needs_the_layout(tmp_path):
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    gds_path = pdk.gds_path('test_patterns', 'cut_coil.gds.gz')
    code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D',
                                                    '--lvsdb', lvsdb_fixture_path(pdk.name, gds_path),
                                                    '--cut', 'coil'))
    assert code != 0, output
    assert 'needs --gds' in ' '.join(output.split()), output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_unknown_kept_net_is_an_error_listing_the_nets(tmp_path):
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    gds_path = pdk.gds_path('test_patterns', 'cut_coil.gds.gz')
    code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D', '--gds', gds_path,
                                                    '--lvsdb', lvsdb_fixture_path(pdk.name, gds_path),
                                                    '--cut', 'coil', '--cut-keep-net', 'nope'))
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert 'no such net' in ' '.join(output.split()) and 'VDD' in output, output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.CC, PEXMode.RC])
@pytest.mark.parametrize('pattern', ['P', 'P*'])
def test_excluded_net_has_no_capacitance_to_the_substrate_but_keeps_the_ones_of_other_nets(mode: PEXMode, pattern: str):
    extraction = Extraction('exclusion_plate_neighbor', mode)
    ignored = capacitances(extraction.run(ExclusionMarkerMode.IGNORE))
    excluded_cli = extraction.run(ExclusionMarkerMode.IGNORE, '--exclude-net', pattern)
    excluded = capacitances(excluded_cli)

    assert ignored[pair('P', 'VSUBS')] > 0.0
    assert pair('P', 'VSUBS') not in excluded
    assert excluded[pair('N', 'P')] == ignored[pair('N', 'P')] > 0.0
    assert excluded[pair('N', 'VSUBS')] == ignored[pair('N', 'VSUBS')] > 0.0
    assert excluded_cli.rcx25_netlist_problems == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_excluded_net_has_no_resistance():
    ignored = resistances(Extraction('exclusion_wire_through', PEXMode.R).run(ExclusionMarkerMode.IGNORE))
    assert ignored

    cli = Extraction('exclusion_wire_through', PEXMode.R).run(ExclusionMarkerMode.IGNORE, '--exclude-net', 'A,B')
    assert resistances(cli) == {}
    assert cli.rcx25_netlist_problems == []
    # NOTE: the one node of the net, as in --mode CC, a SPICE name can't have a comma
    assert netlist_ports(cli) == ['A|B']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_excluded_nets_keep_the_capacitances_between_them_and_their_devices():
    extraction = Extraction('exclusion_nmos_diode2', PEXMode.RC)
    ignored_cli = extraction.run(ExclusionMarkerMode.IGNORE)
    ignored = capacitances(ignored_cli)
    ignored_devices = devices_of(ignored_cli)
    assert len(ignored_devices) == 1

    cli = extraction.run(ExclusionMarkerMode.IGNORE, '--exclude-net', 'VDD', '--exclude-net', 'VSS')
    assert cli.rcx25_netlist_problems == []
    assert resistances(cli) == {}
    # NOTE: the terminals of the device are on the one node of each net
    assert set(devices_of(cli)[0][1:4]) <= {'VDD', 'VSS', 'sub!'}
    values = capacitances(cli)
    assert set(values) == {pair('VDD', 'VSS')}
    total_between_nets = sum(value for key, value in ignored.items()
                             if any(net.startswith('VDD') for net in key) and any(net.startswith('VSS') for net in key))
    assert values[pair('VDD', 'VSS')] == pytest.approx(total_between_nets, abs=0.01)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_excluded_net_needs_no_layout(tmp_path):
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    gds_path = pdk.gds_path('test_patterns', 'exclusion_plate_neighbor.gds.gz')
    code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D', '--mode', 'CC',
                                                    '--lvsdb', lvsdb_fixture_path(pdk.name, gds_path),
                                                    '--exclude-net', 'P'))
    assert code == 0, output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_unknown_excluded_net_is_an_error_listing_the_nets(tmp_path):
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    gds_path = pdk.gds_path('test_patterns', 'exclusion_plate_neighbor.gds.gz')
    code, output = run_cli(KpexCLI().main, cli_args(tmp_path, '--2.5D',
                                                    '--lvsdb', lvsdb_fixture_path(pdk.name, gds_path),
                                                    '--exclude-net', 'nope'))
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert '--exclude-net nope: no such net, the nets are: N, P' in ' '.join(output.split()), output


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
    message = 'applies to the 2.5D engine, FasterCap and FastCap2, not to MAGIC'
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
