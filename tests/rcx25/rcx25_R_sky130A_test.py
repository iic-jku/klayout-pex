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
        'test_patterns', 'single_plate_100um_x_100um_li1_over_substrate.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;A,B;A,B;;840.533"""
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
        'test_patterns', 'single_plate_100um_x_100um_li1_over_substrate.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;$0.17;$1.18;;152.0
R2;$0.17;li1,met1,met2,met3,met4,met5,poly;;0.0
R3;$1.18;$2.18;;0.0
R4;$1.18;li1,met1,met2,met3,met4,met5,poly;;0.0
R5;$2.18;$3.25;;9.3
R6;$4.26;$5.38;;3.41
R7;$5.38;$8.38;;0.0
R8;$6.36;$7.27;;0.38
R9;$6.36;$9.36;;0.0
R10;$8.38;$9.36;;3.41"""
        )

