#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/martinjankoehler/klayout-pex).
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

from __future__ import annotations

from typing import *
from unittest import mock

import allure
import klayout.db as kdb
import pytest

from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.pdk_config import PDK
from klayout_pex.rcx25.pex_mode import PEXMode
from klayout_pex.tech_info import TechInfo
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction, read_lvsdb

parent_suite = "kpex/2.5D Extraction Tests [PDK ihp-sg13g2 | mode R]"
tags = ("PEX", "2.5D", "RF MOS")

pex_whiteboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.IHP_SG13G2), pex_mode=PEXMode.R, blackbox=False)
pex_blackboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.IHP_SG13G2), pex_mode=PEXMode.R, blackbox=True)


def extraction_context(lvsdb: kdb.LayoutVsSchematic,
                       cell_name: str,
                       blackbox_devices: bool) -> KLayoutExtractionContext:
    tech = TechInfo.from_json(PDK.IHP_SG13G2.config.tech_pb_json_path, dielectric_filter=None)
    return KLayoutExtractionContext.prepare_extraction(lvsdb=lvsdb,
                                                       top_cell=cell_name,
                                                       tech=tech,
                                                       blackbox_devices=blackbox_devices)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_rf_mos_keeps_its_layout_geometry():
    # The IHP LVS script replaced each extracted RF MOS by a newly created device
    # of the base class (sg13_lv_nmos with rfmode=1), which has no layout geometry,
    # so the resistance extraction could not connect it (#211)
    cell_name = 'rfnmos_w1u_l0u72'
    _, csv_path = pex_whiteboxed.run_rcx25d_single_cell('rfnmos', f"{cell_name}.gds.gz")
    lvsdb = read_lvsdb(csv_path, cell_name)

    assert [c.name for c in lvsdb.internal_layout().top_cells()] == [cell_name]

    pex_context = extraction_context(lvsdb, cell_name, blackbox_devices=False)
    devices = list(pex_context.devices_by_name.values())
    assert [(d.device_class_name, d.device_abstract_name) for d in devices] == [('rfnmos', 'D$rfnmos')]
    assert {t.name: [r.layer.canonical_layer_name for r in t.region_by_layer] for t in devices[0].terminals} \
           == {'S': ['nSD'], 'G': ['GatPoly'], 'D': ['nSD'], 'B': ['PWell']}


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_device_terminals_without_tech_layer_are_where_they_overlap_their_net():
    # The terminals of the MOM capacitor are on its ports (cap_cmomi_m5_ports, the Metal5 pins within its marker),
    # an LVS layer the tech info has no layer for (#217), so they are where they overlap the Metal5 of their nets
    cell_name = 'cmomi_w5u_l5u_m1_m5'
    with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning') as warning_mock:
        _, csv_path = pex_whiteboxed.run_rcx25d_single_cell(cell_name, f"{cell_name}.gds.gz")

    assert [c.args[0] for c in warning_mock.call_args_list if 'device terminals' in c.args[0]] == []

    pex_context = extraction_context(read_lvsdb(csv_path, cell_name), cell_name, blackbox_devices=True)
    mom_cap, = [d for d in pex_context.devices_by_name.values() if d.device_class_name == 'cap_cmomi']
    assert {t.name: [r.layer.canonical_layer_name for r in t.region_by_layer] for t in mom_cap.terminals} \
           == {'mim_top': ['Metal5'], 'mim_btm': ['Metal5']}


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
@pytest.mark.parametrize('design_dir, cell_name, substrate_net_name', [
    # no label names the substrate, so it's the global net sub! of the PEX-LVS script
    ('rfnmos', 'rfnmos_w1u_l0u72', 'sub!'),
    # the taps connect the substrate to VSS, which names it, so it's found by pwell_sub
    ('sg13g2_a21o_1', 'sg13g2_a21o_1', 'VSS'),
])
def test_substrate_net_is_found_by_its_name_or_its_layer(design_dir: str, cell_name: str, substrate_net_name: str):
    _, csv_path = pex_whiteboxed.run_rcx25d_single_cell(design_dir, f"{cell_name}.gds.gz")
    pex_context = extraction_context(read_lvsdb(csv_path, cell_name), cell_name, blackbox_devices=False)
    assert pex_context.substrate_net_name == substrate_net_name


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_contacts_over_the_taps_are_known():
    # The contacts over the n-taps and the p-taps join Metal1 to the nwell (no sheet resistance) and the substrate,
    # which are no conductors of the resistance network, so they are part of the taps,
    # rather than contact shapes the tech info doesn't know (#294)
    with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning') as warning_mock:
        pex_whiteboxed.run_rcx25d_single_cell('sg13g2_a21o_1', 'sg13g2_a21o_1.gds.gz')
    assert [c.args[0] for c in warning_mock.call_args_list if 'leaves out these LVS layers' in c.args[0]] == []


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_tie_of_tap_device_is_behind_its_contacts():
    # The tie of the ptap1 tap device is the same p+ Activ as the source/drain of the FETs,
    # so its 4 contacts are cont_psd_con (17 Ω each, two groups of 2), with the TIE terminal on the tie,
    # rather than contact shapes the tech info doesn't know, with the TIE terminal on the Metal1 over them (#294)
    cell_name = 'cap_vpp_04p4x04p6_m1m2m3_substrate_pin'
    csv_lines, spice_lines = pex_whiteboxed.written_netlist_lines(cell_name, f"{cell_name}.gds.gz")

    # NOTE: without the device names (R1, ...), which depend on the other nets
    assert [line.split(';', 1)[1] for line in csv_lines if 'SUB' in line] == [
        'SUB;SUB.$0.Metal1;;0.04',
        'SUB;SUB.$1.Metal1;;0.035',
        'SUB.$0.Metal1;SUB.P0.pSD;;8.5',
        'SUB.$1.Metal1;SUB.P0.pSD;;8.5',
    ]
    ptap1_line, = [line for line in spice_lines if line.split()[-1:] == ['ptap1']]
    assert ptap1_line.split()[1:3] == ['SUB.P0.pSD', 'sub!']


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_bipolar_transistors_are_on_the_metal1_over_their_contacts():
    # The contacts over the terminals of the bipolar transistors (and the emitter windows of the npn13G2
    # and the npn13G2L) are within the devices, whose models have their resistances (e.g. re, rbx, rcx),
    # so the terminals are on the Metal1 over them, rather than on LVS layers the tech info doesn't know (#350)
    cell_name = 'bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa'
    with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning') as warning_mock:
        _, csv_path = pex_whiteboxed.run_rcx25d_single_cell('test_patterns', f"{cell_name}.gds.gz")
    assert [c.args[0] for c in warning_mock.call_args_list if 'leaves out these LVS layers' in c.args[0]] == []

    pex_context = extraction_context(read_lvsdb(csv_path, cell_name), cell_name, blackbox_devices=False)
    # NOTE: the substrate terminal S stays on its net, as the substrate is no conductor of the resistance network,
    #       and so do the base and collector of the pnpMPA, on the nwell and substrate taps
    npn_terminals = {'C': ['Metal1'], 'B': ['Metal1'], 'E': ['Metal1'], 'S': []}
    assert {d.device_class_name: {t.name: [r.layer.canonical_layer_name for r in t.region_by_layer]
                                  for t in d.terminals}
            for d in pex_context.devices_by_name.values()} == {
        'npn13G2': npn_terminals,
        'npn13G2l': npn_terminals,
        'npn13G2v': npn_terminals,
        'pnpMPA': {'C': ['Activ'], 'B': ['Activ'], 'E': ['Metal1']},
    }


def subckt_ports(spice_lines: List[str]) -> List[str]:
    subckt_line, = [line for line in spice_lines if line.startswith('.SUBCKT ')]
    return [port.replace('\\', '') for port in subckt_line.split()[2:]]


def ports_touching_nothing(spice_lines: List[str]) -> List[str]:
    element_nodes: Set[str] = set()
    for line in spice_lines:
        tokens = line.split()
        if not tokens or tokens[0][0] not in 'CRX':
            continue
        if tokens[0][0] == 'X':  # the nodes, the subcircuit, then the parameters
            nodes = tokens[1:next(i for i, t in enumerate(tokens) if '=' in t) - 1]
        else:
            nodes = tokens[1:3]
        element_nodes.update(node.replace('\\', '') for node in nodes)
    return [port for port in subckt_ports(spice_lines) if port not in element_nodes]


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_nets_of_the_same_name_stay_apart():
    # Two transistors, each with its own metal islands labelled D and S, which are not connected
    # (like the islands of a supply, joined only in the parent). The IHP LVS script connects no nets implicitly,
    # so they are distinct nets of the same name, which KLayout's SPICE writer calls D, D$1, S, S$1 (#211 §10)
    csv_lines, _ = pex_whiteboxed.written_netlist_lines('test_patterns', 'nmos_metal1_redux_twice.gds.gz')
    assert csv_lines == """Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;$1;$1.$0.GatPoly;;33.654
R2;$1.$0.GatPoly;$1.$1.Metal1;;15.0
R3;$4;$4.$0.GatPoly;;33.654
R4;$4.$0.GatPoly;$4.$1.Metal1;;15.0
R5;D;D.$0.Metal1;;0.488
R6;D$1;D$1.$0.Metal1;;0.488
R7;D$1.$0.Metal1;D$1.P0.nSD;;17.0
R8;D.$0.Metal1;D.P0.nSD;;17.0
R9;S;S.$0.Metal1;;0.598
R10;S$1;S$1.$0.Metal1;;0.598
R11;S$1.$0.Metal1;S$1.P0.nSD;;17.0
R12;S.$0.Metal1;S.P0.nSD;;17.0""".splitlines()


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_a_net_of_several_labels_has_a_port_per_label():
    # The drain wire of the transistor has the labels D and X at its ends, so LVS has one net D,X with one pin,
    # which the netlist replaces by the ports D and X at the labels, where the parent connects (#211 §11)
    csv_lines, spice_lines = pex_whiteboxed.written_netlist_lines('test_patterns', 'nmos_metal1_redux_two_drain_labels.gds.gz')
    assert csv_lines == """Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;$1;$1.$0.GatPoly;;33.654
R2;$1.$0.GatPoly;$1.$1.Metal1;;15.0
R3;D;D,X.$0.Metal1;;0.488
R4;D,X;D,X.$0.Metal1;;17.0
R5;D,X.$0.Metal1;X;;0.089
R6;S;S.$0.Metal1;;0.598
R7;S.$0.Metal1;S.P0.nSD;;17.0""".splitlines()
    assert subckt_ports(spice_lines) == ['D', 'X', 'S', 'sub!']  # sub!: the substrate, the bulk of the transistor
    assert ports_touching_nothing(spice_lines) == []


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_labels_on_one_node_are_tied():
    # The labels D and X are on the same pin of the drain wire, so both ports are on one node,
    # tied by 1 mΩ, rather than one of them touching nothing (#211 §11)
    csv_lines, spice_lines = pex_whiteboxed.written_netlist_lines('test_patterns', 'nmos_metal1_redux_two_labels_one_node.gds.gz')
    assert csv_lines == """Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;$1;$1.$0.GatPoly;;33.654
R2;$1.$0.GatPoly;$1.$1.Metal1;;15.0
R3;D;D,X.$0.Metal1;;0.488
R4;D;X;;0.001
R5;D,X;D,X.$0.Metal1;;17.0
R6;S;S.$0.Metal1;;0.598
R7;S.$0.Metal1;S.P0.nSD;;17.0""".splitlines()
    assert subckt_ports(spice_lines) == ['D', 'X', 'S', 'sub!']  # sub!: the substrate, the bulk of the transistor
    assert ports_touching_nothing(spice_lines) == []


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_mim_cap__whiteboxed():
    # The white-box extraction keeps the MIM cap layers, so the top plate (MIM, LVS layer cmim_top) is a conductor
    # of its net, joined to TopMetal1 by the TopVia1 on it (mim_via), 5 cuts per row (2.2 Ω / 5).
    # It stopped with "unhandled layer purpose PURPOSE_MIM_CAP".
    # The bottom plate (Metal5) has no network, as nothing connects to it
    results, _ = pex_whiteboxed.run_rcx25d_single_cell('sg13g2_pr__cmim', 'cmim.gds.gz')

    # NOTE: the nets have no labels, so their names ($1, $2, ...) depend on the LVS run
    network, = [n for n in results.r_extraction_result.networks if n.elements]
    assert {node.layer_name for node in network.nodes} == {'MIM', 'TopMetal1'}
    assert sorted(round(r, 3) for r in results.summarize().resistances.values()) == \
           [0.004] * 4 + [0.44] * 5 + [2.408] * 4


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_rf_mim_cap__whiteboxed():
    # The TopVia1 on the top plate of the rfcmim (mim_via) join it to TopMetal1
    results, _ = pex_whiteboxed.run_rcx25d_single_cell('sg13g2_pr__rfcmim', 'rfcmim.gds.gz')

    # NOTE: the nets have no labels, so their names ($1, $2, ...) depend on the LVS run
    network, = [n for n in results.r_extraction_result.networks if n.elements]
    assert {node.layer_name for node in network.nodes} == {'MIM', 'TopMetal1'}
    layer_by_node_id = {node.node_id: node.layer_name for node in network.nodes}
    assert [e for e in network.elements
            if {layer_by_node_id[e.node_a.node_id], layer_by_node_id[e.node_b.node_id]} == {'MIM', 'TopMetal1'}]


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_mim_cap__blackboxed():
    # The black-box extraction keeps the plates of the MIM cap, so its terminals are on their nodes.
    # The bottom plate (metal5_cap) was left out, so its terminal was on the pin node of A, with a warning
    assert pex_blackboxed.written_device_lines('test_patterns', 'cap_cmim_20um_x_20um_over_m4_wire.gds.gz') == [
        'X$1 B.P0.MIM A.P0.Metal5 cap_cmim w=2e-05 l=2e-05 m=1',
    ]


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_rf_mim_cap__blackboxed():
    # The black-box extraction keeps the plates of the rfcmim, so its terminals are on their nodes.
    # The plates (rfmim_top, metal5_rfcap) were left out, so the bottom terminal was on the pin node of MINUS,
    # with a warning
    assert pex_blackboxed.written_device_lines('test_patterns', 'cap_rfcmim_w7u_l7u_over_m4_wire.gds.gz') == [
        'X$1 PLUS.P0.MIM MINUS.P0.Metal5 sub! cap_rfcmim w=7e-06 l=7e-06 m=1 wfeed=3e-06',
    ]


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_wire_over_deep_nwell():
    # The nBuLay (the deep n-well) is no conductor of the resistance network, as the deep nwell of sky130A and
    # gf180mcuD (no via joins it to the nwell over it). It stopped the extraction, as the tech info had no layer
    # for it (#331). Between the pins, the wire has 19 squares of Metal1
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_wire_over_nbulay_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;A;A,B;;0.001
R2;A;B;;2.09"""
    )
