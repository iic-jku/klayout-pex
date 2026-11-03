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

from collections import Counter

import allure
import pytest
from unittest import mock

from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.pdk_config import PDK
from klayout_pex.rcx25.pex_mode import PEXMode
from klayout_pex.tech_info import TechInfo
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction
import klayout_pex_protobuf.kpex.r.r_network_pb2 as r_network_pb2


parent_suite = "kpex/2.5D Extraction Tests [PDK sky130A | mode R]"
tags = ("PEX", "2.5D", "MAGIC")


pex_whiteboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.R, blackbox=False)
pex_blackboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.R, blackbox=True)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_single_wire_li1():
    # MAGIC GIVES (8.3 revision 540):
    #_______________________________ NOTE: with halo=8µm __________________________________
    # R0 A B 840.534
    # R1 B A 840.534   # reported twice!
    # NOTE: the net A,B has labels only, so it is tied to the node of A (1 mΩ)
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_single_wire_li1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;A;A,B;;0.001
R2;A;B;;840.533"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_contact_1x1_minsize_mcon():
    # MAGIC GIVES (8.3 revision 540):
    #_______________________________ NOTE: with halo=8µm __________________________________
    # R0 TOP BOT 15.763     (why not 9? Magic takes the bottom-left of each port)
    #    but in the debug version we see 9.3 is calculated for the via
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_contact_1x1_minsize_mcon.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;BOT;BOT,TOP;;0.001
R2;BOT;TOP;;9.3"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_wire_voltage_divider_li1():
    # MAGIC GIVES (8.3 revision 540):
    #_______________________________ NOTE: with halo=8µm __________________________________
    # R0 A B 840.534
    # R1 B A 840.534   # reported twice!
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_wire_voltage_divider_li1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;A;A,B,C;;426.667
R2;A,B,C;B;;413.867
R3;A,B,C;C;;72.533"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_wire_same_label_at_both_ends_li1():
    # Same layout as r_wire_voltage_divider_li1, but pin A is at both ends of the wire
    # (and B at the stub in the middle). Both pins A are one node in the netlist,
    # so the two halves of the wire (426.667 Ω, 413.867 Ω) are in parallel, not in series (#211)
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_wire_same_label_at_both_ends_li1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;A;A,B;;210.085
R2;A,B;B;;72.533"""
        )

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_via_stack_1x1_minsize_poly_to_met5():
    # MAGIC GIVES (8.3 revision 540):
    #_______________________________ NOTE: with halo=8µm __________________________________
    # R0 li1.n3 poly 175.37       # poly contact, should be 152Ω
    # R1 li1.n4 li1.n3 9.3005     # mcon via, should be 9.3Ω
    # R2 li1.n3 li1 6.4005
    # R3 li1.n4 li1.n2 4.5005     # via, should be 4.5Ω
    # R7 met1 li1.n4 0.063
    # R4 li1.n1 li1.n0 3.4105     # via2, should be 3.41Ω
    # R8 li1.n2 met2 0.0545541
    # R6 li1.n0 met5 0.3834       # via4, should be 0.38Ω
    # R9 li1.n1 met3 0.0232879
    # R10 li1.n0 met4 0.00687288
    # R5 li1.n2 li1.n1 3.4105     # via3, should be 3.41Ω
    # (and some redundant listings of the same)
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_via_stack_1x1_minsize_poly_to_met5.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;li1;li1,met1,met2,met3,met4,met5,poly;;0.001
R2;li1;met1;;9.3
R3;li1;poly;;152.0
R4;met1;met2;;4.5
R5;met2;met3;;3.41
R6;met3;met4;;3.41
R7;met4;met5;;0.38"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_nfet_li1_redux():
    # MAGIC GIVES (8.3 revision 540):
    #_______________________________ NOTE: with halo=8µm __________________________________
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'nfet_li1_redux.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;$2;$2.$0.li1;;209.667
R2;$3;$3.$0.li1;;209.667
R3;G;G.$0.li1;;2.418
R4;G.$0.li1;G.$1.poly;;152.0
R5;G.$1.poly;G.P0.poly;;316.321"""
        )



@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_nfet_terminals_are_on_the_resistor_network():
    # The transistor is connected to the nodes of its terminals (#211 §6): the gate to the end of the poly,
    # drain and source to the nodes that carry the names of their nets (which have no pin)
    _, lines = pex_whiteboxed.written_netlist_lines('test_patterns', 'nfet_li1_redux.gds.gz')
    nfet_line, = [l for l in lines if l.startswith('X$1 ')]
    assert nfet_line.split()[1:5] == ['\\$3', 'G.P0.poly', '\\$2', 'sky130_gnd']  # D G S B


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_nwell_pfet_ntap_li1():
    # The bulk of the PMOS is on the nwell, which the licon over the ntap at its far end joins to VPWR.
    # The extraction left out both, so the bulk was on VPWR, without resistance:
    #   - licon over ntap: 185 Ω per cut, 1 cut
    #   - nwell: 1700 Ω/sq, from the licon to the middle of the gate (9.25 µm) along the 3 µm wide nwell, 3.083 sq
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_nwell_pfet_ntap_li1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;D;D.P0.psdm;;585.0
R2;G;G.P0.poly;;363.107
R3;S;S.P0.psdm;;585.0
R4;VPWR;VPWR.$1.nwell;;185.0
R5;VPWR.$1.nwell;VPWR.P0.nwell;;5241.667"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_pin_node_is_at_its_label():
    # Each pin's node is at its label: KLayout located the gate's 60 nm below its label (at 1750, 2690),
    # and where it locates such a node can differ from run to run,
    # and so would the nodes the capacitances near it go to (#286)
    results, _ = pex_whiteboxed.run_rcx25d_single_cell('test_patterns', 'r_nwell_pfet_ntap_li1.gds.gz')
    assert sorted((n.node_name, n.location.point.x, n.location.point.y)
                  for network in results.r_extraction_result.networks for n in network.nodes
                  if n.node_kind == r_network_pb2.RNode.Kind.KIND_PIN) == \
           [('D', 2215, 1500), ('G', 1750, 2750), ('S', 1285, 1500), ('VPWR', 11000, 1500)]  # the labels


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_nwell_joined_by_a_label_only():
    # Like r_nwell_pfet_ntap_li1, without the licon over the ntap, but with the label VPWR on the nwell,
    # which joins it to VPWR. So the nwell is a piece of the resistance network that joins nothing else,
    # and the extraction leaves it out, so that the bulk of the PMOS is on VPWR, without resistance
    with mock.patch('klayout_pex.rcx25.r.r_extractor.warning') as warning_mock:
        pex_whiteboxed.assert_expected_matches_obtained(
            'test_patterns', 'r_nwell_pfet_label_li1.gds.gz',
            expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;D;D.P0.psdm;;585.0
R2;G;G.P0.poly;;363.107
R3;S;S.P0.psdm;;585.0"""
        )
    assert [c.args[0] for c in warning_mock.call_args_list] == [
        "The resistance network leaves out the wells of these nets, as no contact joins them "
        "to the rest of their net (e.g. a label of the net on the well does), "
        "so the device terminals on them (e.g. the PMOS bulks) are ideally on their nets: VPWR"
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_no_resistor_between_pins_with_the_same_label():
    # Output Y has two labels, which are one node in the netlist, so the resistance between them is shorted.
    # It used to be a resistor from Y to Y, with a warning "Invalid attempt to create resistor ... between same net"
    with mock.patch('klayout_pex.rcx25.netlist_expander.warning') as warning_mock:
        results, _ = pex_whiteboxed.run_rcx25d_single_cell('sky130_fd_sc_hd__inv_1', 'sky130_fd_sc_hd__inv_1.gds.gz')
    warning_mock.assert_not_called()
    assert [k for k in results.summarize().resistances.keys() if k.net1 == k.net2] == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_vias_within_mom_cap_l1m1m2():
    # The vias within the MOM capacitor (mcon_vpp, via1_vpp) are on the GDS pairs of the regular vias,
    # so they are part of the resistance network (#228 reported them as unmodeled)
    results, _ = pex_whiteboxed.run_rcx25d_single_cell('cap_vpp_04p4x04p6_l1m1m2_noshield',
                                                          'cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz')
    assert {n.net_name for n in results.r_extraction_result.networks} >= {'C0', 'C1'}
    assert results.summarize().resistances


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_device_terminals_overlapping_no_conductor_of_their_net_are_reported_once():
    # Without its layer in the tech info, the substrate terminal B of the MOM capacitor (vpp_sub, the marker
    # of the capacitor) is on an unknown LVS layer, and it overlaps no conductor of its net,
    # as the substrate is none (#217)
    cell_name = 'cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5'
    tech = TechInfo.parse_tech_def(PDK.SKY130A.config.tech_pb_json_path)
    tech.lvs_computed_layers.remove(next(l for l in tech.lvs_computed_layers if l.layer_info.name == 'vpp_sub'))
    pex_context = KLayoutExtractionContext.prepare_extraction(lvsdb=pex_whiteboxed.read_lvsdb(cell_name,
                                                                                              f"{cell_name}.gds.gz"),
                                                              top_cell=cell_name,
                                                              tech=TechInfo(tech=tech, dielectric_filter=None),
                                                              blackbox_devices=False)
    with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning') as warning_mock:
        assert pex_context.devices_by_name
    assert [c.args[0] for c in warning_mock.call_args_list] == [
        "The resistance network has no nodes for these device terminals, "
        "as the tech info has no layer for their LVS layer, "
        "and they neither overlap nor abut a conductor of their net "
        "(e.g. a terminal on the substrate or a well):\n"
        "  - sky130_fd_pr__cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5 terminal B on LVS layer vpp_sub: $1"
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('design_dir, gds_name', [
    ('cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5', 'cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5.gds.gz'),
    ('test_patterns', 'rf_inductors_03_90_05_125_05_220.gds.gz'),
])
def test_substrate_terminals_of_vpp_caps_and_rf_inductors_have_no_warnings(design_dir: str, gds_name: str):
    # The substrate is no conductor of the resistance network, so these terminals rightly stay on their nets
    assert pex_whiteboxed.device_layer_warnings(design_dir, gds_name) == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_licons_over_the_p_taps_are_known():
    # The licons over the p-taps join li1 to the substrate, which is no conductor of the resistance network,
    # so they are part of the p-taps (licon_ptap_con), rather than LVS shapes the tech info doesn't know (#294)
    with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning') as warning_mock:
        pex_whiteboxed.run_rcx25d_single_cell('inv', 'inv.gds.gz')
    assert [c.args[0] for c in warning_mock.call_args_list if 'leaves out these LVS layers' in c.args[0]] == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_device_terminals_without_a_net_stay_unconnected():
    # The bulk terminal W of the varactor is the gate on the hole of a ptap ring (varactor_bulk_lvt), but there's
    # no ring around it, so the LVS netlist leaves W unconnected (as in iic-sar-adc/adc_comp_latch).
    # The extraction crashed on it with an AttributeError
    with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning') as warning_mock:
        pex_whiteboxed.run_rcx25d_single_cell('test_patterns', 'cap_var_lvt_without_ptap_ring.gds.gz')
    messages = [c.args[0] for c in warning_mock.call_args_list if 'device terminals' in c.args[0]]
    assert messages == [
        "These device terminals are unconnected in the LVS netlist, "
        "so they stay unconnected in the extracted netlist:\n"
        "  - sky130_fd_pr__cap_var_lvt terminal W: $1"
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_via_without_conductor_below_is_an_error():
    # The via1 has no met1 below it, so it joins nothing there. The extraction report crashed on it with a KeyError,
    # as with gf180mcuD before #229, whose tech info put the layer below its vias on another GDS pair
    with mock.patch('klayout_pex.kpex_cli.error') as error_mock, pytest.raises(SystemExit):
        pex_whiteboxed.run_rcx25d_single_cell('test_patterns', 'r_via1_without_met1.gds.gz')
    assert [c.args[0] for c in error_mock.call_args_list if 'vias' in c.args[0]] == [
        "These vias have no conductor to join on one side, "
        "so their connections would be missing from the resistance network:\n"
        "  - via (LVS via1_con): the layer below it, met1 (68, 20), has no shapes"
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_vias_within_mom_cap_l1m1m2m3m4():
    # via3_vpp and via4_vpp must be on the GDS pairs of via3_ncap and via4_ncap
    results, _ = pex_whiteboxed.run_rcx25d_single_cell('cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5',
                                                          'cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5.gds.gz')
    assert {n.net_name for n in results.r_extraction_result.networks} >= {'C0', 'C1'}
    assert results.summarize().resistances


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mim_cap__whiteboxed():
    # The white-box extraction keeps the MIM cap layers, so the top plate (capm) is a conductor of its net,
    # joined to met4 by the vias on it (via3_cap). It stopped with "unhandled layer purpose PURPOSE_MIM_CAP"
    results, _ = pex_whiteboxed.run_rcx25d_single_cell('cap_mim_m3_w18p9_l5p1', 'cap_mim_m3_w18p9_l5p1.gds.gz')
    networks = {n.net_name: n for n in results.r_extraction_result.networks}
    assert {node.layer_name for node in networks['mimcap_top'].nodes} == {'capm', 'met3', 'met4'}
    assert {node.layer_name for node in networks['mimcap_bot'].nodes} == {'met3', 'met4'}

    top_layer_by_node_id = {node.node_id: node.layer_name for node in networks['mimcap_top'].nodes}
    assert [e for e in networks['mimcap_top'].elements
            if {top_layer_by_node_id[e.node_a.node_id], top_layer_by_node_id[e.node_b.node_id]} == {'capm', 'met4'}]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mim_cap__blackboxed():
    # The black-box extraction keeps the plates of the MIM cap, so its terminals are on their nodes.
    # The bottom plate (met3_cap) was left out, so its terminal was on the pin node of A, with a warning
    assert pex_blackboxed.written_device_lines('test_patterns', 'cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz') == [
        'X$1 B.P0.capm A.P0.met3 sky130_fd_pr__cap_mim_m3_1 w=20 l=20',
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mom_cap__blackboxed():
    # The black-box extraction keeps the fingers of the VPP cap, so its terminals are on their nodes.
    # The fingers (met2_vpp, …) were left out, so its terminals were on the pin nodes of C0 and C1, with a warning
    assert pex_blackboxed.written_device_lines('test_patterns', 'cap_vpp_04p4x04p6_l1m1m2_noshield_m2_wire.gds.gz') == [
        'X$1 C0.P0.met2 C1.P0.met2 SUB sky130_fd_pr__cap_vpp_04p4x04p6_l1m1m2_noshield',
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sonosfet_with_deep_nwell():
    # The SONOS FET has a deep nwell, which is no conductor of the resistance network
    # (no via joins it to the nwell over it). It used to stop the extraction (#292).
    # Its source/drain (sonos_nsd) is the n+ diffusion of nsd, so the licon on it is licon_nsd_con (185 Ω),
    # rather than a contact shape the tech info doesn't know (#294)
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sonosfet_star_w0p45_l0p22.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;D;D.$0.li1;;185.0
R2;D.$0.li1;D.$2.met1;;9.3
R3;G;G.$6.poly;;73.395
R4;G;G.$7.poly;;73.395
R5;G.$0.li1;G.$4.met1;;9.3
R6;G.$0.li1;G.$6.poly;;152.0
R7;G.$2.li1;G.$5.met1;;9.3
R8;G.$2.li1;G.$7.poly;;152.0
R9;S;S.$0.li1;;185.0
R10;S.$0.li1;S.$2.met1;;9.3"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_rf_inductors_are_subcircuits_at_the_ends_of_their_leads():
    # The PEX-LVS extracts the RF inductors of the PDK (its cells sky130_fd_pr__rf_test_coil1, 2 and 3)
    # as their models, which have their coils, so the met2, met3 and via2 within their markers are left out.
    # They used to vanish: LVS cut their coils out of the metal, but didn't extract them,
    # so the ends of their leads were nets of their own, and so were the vias within their markers
    csv_lines, spice_lines = pex_whiteboxed.written_netlist_lines('test_patterns',
                                                                  'rf_inductors_03_90_05_125_05_220.gds.gz')
    assert csv_lines == ['Device;Net1;Net2;Capacitance [fF];Resistance [Ω]']
    assert [line for line in spice_lines if line.startswith('X')] == [
        'X$1 A1 B1 CT1 sky130_gnd sky130_fd_pr__ind_03_90',
        'X$2 A2 B2 CT2 sky130_gnd sky130_fd_pr__ind_05_125',
        'X$3 A3 B3 CT3 sky130_gnd sky130_fd_pr__ind_05_220',
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_p_taps_are_nets_of_their_own():
    # NOTE: the deck has no substrate around the p-taps, so the substrate doesn't join them, unlike in other PDKs
    results, _ = pex_whiteboxed.run_rcx25d_single_cell('test_patterns', 'r_ptap_pair_li1_m1.gds.gz')
    assert sorted(network.net_name for network in results.r_extraction_result.networks) == ['$1', '$2']
    assert results.nets_joined_by_substrate() == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_wires_on_one_p_tap_are_on_their_net():
    # NOTE: only the p-tap joins them, which is no conductor of the resistance network, its resistance is neglected
    rows = pex_whiteboxed.written_netlist_rows('test_patterns', 'r_ptap_li1_m1_two_wires.gds.gz')
    assert sorted(row['Net2'] for row in rows if row['Net1'] == '$2') == ['$2.$1.li1', '$2.$10.met1',
                                                                          '$2.$15.met1', '$2.$6.li1']
    # li1: 12.8 Ω/sq, met1: 125 mΩ/sq, 1 µm / 0.34 µm = 2.94 sq, mcon: 9.3 Ω: the same for both wires
    assert Counter(row['Resistance [Ω]'] for row in rows) == {'37.647': 8, '0.368': 8, '9.3': 10}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_n_taps_in_one_nwell_are_joined_by_its_sheet_resistance():
    # nwell: 1700 Ω/sq, 10 µm / 7 µm = 1.43 sq between the n-taps
    # NOTE: the nwell is a conductor of the resistance network, so nothing is left to join ideally
    results, csv_path = pex_whiteboxed.run_rcx25d_single_cell('test_patterns', 'r_ntap_pair_nwell_li1_m1.gds.gz')
    assert results.nets_joined_by_substrate() == []
    with open(csv_path, encoding='utf-8') as f:
        assert 'R32;$1.$30.nwell;$1.$35.nwell;;2428.571' in f.read().splitlines()


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_nwells_that_only_a_deep_nwell_joins_are_on_their_net():
    # NOTE: at a node of each nwell, so the licons (185 Ω) and the nwell stay between the wires and the net
    rows = pex_whiteboxed.written_netlist_rows('test_patterns', 'r_ntap_pair_two_nwells_over_dnwell_li1_m1.gds.gz')
    assert [(row['Net2'], row['Resistance [Ω]']) for row in rows if row['Net1'] == '$1'] == [
        ('$1.$0.li1', '185.0'),
        ('$1.$10.li1', '185.0'),
        ('$1.$31.nwell', '680.0'),
        ('$1.$36.nwell', '680.0'),
    ]
