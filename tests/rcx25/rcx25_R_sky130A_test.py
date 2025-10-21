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
import pytest

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
R1;$0.16;$1.23;;9.3
R2;$0.16;BOT;;0.0
R3;$1.23;TOP;;0.0"""
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
R1;$1.16;A;;426.667
R2;$1.16;B;;413.867
R3;$1.16;C;;72.533"""
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
R1;$0.17;$1.18;;152.0
R2;$0.17;poly;;0.0
R3;$1.18;$2.18;;0.0
R4;$1.18;li1;;0.0
R5;$10.40;$11.27;;0.38
R6;$10.40;$9.40;;0.0
R7;$11.27;met5;;0.0
R8;$2.18;$3.25;;9.3
R9;$3.25;$4.25;;0.0
R10;$3.25;met1;;0.0
R11;$4.25;$5.26;;4.5
R12;$5.26;$6.26;;0.0
R13;$5.26;met2;;0.0
R14;$6.26;$7.43;;3.41
R15;$7.43;$8.43;;0.0
R16;$7.43;met3;;0.0
R17;$8.43;$9.40;;3.41
R18;$9.40;met4;;0.0"""
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
R1;$0.13;$1.18;;419.333
R2;$0.13;D;;0.0
R3;$0.13;S;;0.0
R4;$0.17;$1.18;;172.267
R5;$1.18;D;;47.059
R6;$1.18;G;;2.133
R7;$1.18;S;;68.894"""
        )

