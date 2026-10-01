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

import allure
import glob
import os
import pytest
from unittest import mock

from rcx25_test_helpers import *


CSVPath = str
PNGPath = str
parent_suite = "kpex/2.5D Extraction Tests [PDK sky130A | mode R]"
tags = ("PEX", "2.5D", "MAGIC")


pex_whiteboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.R, blackbox=False)
pex_blackboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.R, blackbox=True)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_single_wire_li1():
    # MAGIC GIVES (8.3 revision 540):
    #_______________________________ NOTE: with halo=8µm __________________________________
    # R0 A B 840.534
    # R1 B A 840.534   # reported twice!
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_single_wire_li1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;A;B;;840.533"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_contact_1x1_minsize_mcon():
    # MAGIC GIVES (8.3 revision 540):
    #_______________________________ NOTE: with halo=8µm __________________________________
    # R0 TOP BOT 15.763     (why not 9? Magic takes the bottom-left of each port)
    #    but in the debug version we see 9.3 is calculated for the via
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_contact_1x1_minsize_mcon.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;BOT;TOP;;9.3"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
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
@pytest.mark.slow
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
@pytest.mark.slow
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
R1;li1;met1;;9.3
R2;li1;poly;;152.0
R3;met1;met2;;4.5
R4;met2;met3;;3.41
R5;met3;met4;;3.41
R6;met4;met5;;0.38"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_nfet_li1_redux():
    # MAGIC GIVES (8.3 revision 540):
    #_______________________________ NOTE: with halo=8µm __________________________________
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'nfet_li1_redux.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;$2;$2.$1.li1;;209.667
R2;$3;$3.$1.li1;;209.667
R3;G;G.$1.li1;;2.418
R4;G.$0.poly;G.$1.li1;;152.0
R5;G.$0.poly;G.P0.poly;;316.321"""
        )



@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_nfet_terminals_are_on_the_resistor_network():
    # The transistor is connected to the nodes of its terminals (#211 §6): the gate to the end of the poly,
    # drain and source to the nodes that carry the names of their nets (which have no pin)
    pex_whiteboxed.run_rcx25d_single_cell('test_patterns', 'nfet_li1_redux.gds.gz')
    output_dir_path = os.path.realpath(os.path.join(__file__, '..', '..', '..', f"output_{pex_whiteboxed.pdk.name}"))
    netlist_path, = glob.glob(os.path.join(output_dir_path, 'nfet_li1_redux__*', '*_k25d_pex_netlist.spice'))
    with open(netlist_path) as f:
        lines = f.read().replace('\n+', ' ').splitlines()
    nfet_line, = [l for l in lines if l.startswith('X$1 ')]
    assert nfet_line.split()[1:5] == ['\\$3', 'G.P0.poly', '\\$2', 'sky130_gnd']  # D G S B


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_no_resistor_between_pins_with_the_same_label():
    # Output Y has two labels, which are one node in the netlist, so the resistance between them is shorted.
    # It used to be a resistor from Y to Y, with a warning "Invalid attempt to create resistor ... between same net"
    with mock.patch('klayout_pex.rcx25.netlist_expander.warning') as warning_mock:
        results, _, _ = pex_whiteboxed.run_rcx25d_single_cell('sky130_fd_sc_hd__inv_1', 'sky130_fd_sc_hd__inv_1.gds.gz')
    warning_mock.assert_not_called()
    assert [k for k in results.summarize().resistances.keys() if k.net1 == k.net2] == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_vias_within_mom_cap_l1m1m2():
    # The vias within the MOM capacitor (mcon_vpp, via1_vpp) are on the GDS pairs of the regular vias,
    # so they are part of the resistance network (#228 reported them as unmodeled)
    results, _, _ = pex_whiteboxed.run_rcx25d_single_cell('cap_vpp_04p4x04p6_l1m1m2_noshield',
                                                          'cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz')
    assert {n.net_name for n in results.r_extraction_result.networks} >= {'C0', 'C1'}
    assert results.summarize().resistances


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_device_terminals_overlapping_no_conductor_of_their_net_are_reported_once():
    # The substrate terminal B of the MOM capacitor (vpp_sub, the marker of the capacitor) is on an LVS layer
    # the tech info has no layer for, and it overlaps no conductor of its net, as the substrate is none (#217)
    with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning') as warning_mock:
        pex_whiteboxed.run_rcx25d_single_cell('cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5',
                                              'cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5.gds.gz')
    messages = [c.args[0] for c in warning_mock.call_args_list if 'device terminals' in c.args[0]]
    assert messages == [
        "The resistance network has no nodes for these device terminals, "
        "as the tech info has no layer for their LVS layer, and they overlap no conductor of their net "
        "(e.g. a terminal on the substrate or a well):\n"
        "  - sky130_fd_pr__cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5 terminal B on LVS layer vpp_sub: $1"
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_vias_within_mom_cap_l1m1m2m3m4():
    # via3_vpp and via4_vpp must be on the GDS pairs of via3_ncap and via4_ncap
    results, _, _ = pex_whiteboxed.run_rcx25d_single_cell('cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5',
                                                          'cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5.gds.gz')
    assert {n.net_name for n in results.r_extraction_result.networks} >= {'C0', 'C1'}
    assert results.summarize().resistances
