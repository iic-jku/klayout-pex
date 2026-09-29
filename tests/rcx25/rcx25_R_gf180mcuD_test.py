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

import allure
import pytest

from rcx25_test_helpers import *

parent_suite = "kpex/2.5D Extraction Tests [PDK gf180mcuD | mode R]"
tags = ("PEX", "2.5D")


pex_whiteboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.GF180MCUD), pex_mode=PEXMode.R, blackbox=False)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_single_wire_m1():
    # Metal1: 90 mΩ/sq
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_single_wire_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;A;B;;5.91"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_wire_voltage_divider_m1():
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_wire_voltage_divider_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;A;A,B,C.$1.14;;3.0
R2;A,B,C.$1.14;B;;2.91
R3;A,B,C.$1.14;C;;0.51"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_contact_1x1_minsize_via1():
    # Via1: 4500 mΩ per cut
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_contact_1x1_minsize_via1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;BOT;BOT,TOP.$0.14;;0.0
R2;BOT,TOP.$0.14;BOT,TOP.$1.15;;4.5
R3;BOT,TOP.$1.15;TOP;;0.0"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_nfet_m1():
    # contacts: 6300 mΩ (N+), 5900 mΩ (poly) per cut, Poly2: 7300 mΩ/sq
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'nfet_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;D;D.$1.15;;0.282
R2;D.$0.9;D.$1.15;;6.3
R3;D.$0.9;D.P0.9;;0.0
R4;G;G.$3.15;;0.128
R5;G.$0.14;G.$1.15;;5.9
R6;G.$0.14;G.P0.14;;12.514
R7;G.$1.15;G.$3.15;;0.313
R8;G.$2.14;G.$3.15;;5.9
R9;G.$2.14;G.P0.14;;12.514
R10;S;S.$1.15;;0.294
R11;S.$0.9;S.$1.15;;6.3
R12;S.$0.9;S.P0.9;;0.0"""
    )
