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
import csv
import pytest

from rcx25_test_helpers import *

parent_suite = "kpex/2.5D Extraction Tests [PDK gf180mcuD | mode R]"
tags = ("PEX", "2.5D")


pex_whiteboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.GF180MCUD), pex_mode=PEXMode.R, blackbox=False)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_single_wire_m1():
    # Metal1: 90 mΩ/sq, (9.885 - 0.115) µm / 0.23 µm = 42.5 sq
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_single_wire_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;A;B;;3.823"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_wire_voltage_divider_m1():
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_wire_voltage_divider_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;A;A,B,C;;1.912
R2;A,B,C;B;;1.912
R3;A,B,C;C;;0.346"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_contact_1x1_minsize_via1():
    # Via1: 4500 mΩ per cut
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_contact_1x1_minsize_via1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;BOT;TOP;;4.5"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_nfet_m1():
    # contacts: 6300 mΩ (N+), 5900 mΩ (poly) per cut, Poly2: 7300 mΩ/sq
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'nfet_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;D;D.$1.Metal1;;0.208
R2;D.$1.Metal1;D.P0.Nplus;;6.3
R3;G;G.$1.Metal1;;0.156
R4;G.$0.Poly2;G.$1.Metal1;;5.9
R5;G.$0.Poly2;G.P0.Poly2;;12.514
R6;S;S.$1.Metal1;;0.208
R7;S.$1.Metal1;S.P0.Nplus;;6.3"""
    )


def obtained_resistances(*path_components) -> List[float]:
    """
    The resistances, sorted (for patterns with many internal nodes, whose names are not stable)
    """
    _, csv_path, _ = pex_whiteboxed.run_rcx25d_single_cell(*path_components)
    with open(csv_path) as f:
        return sorted(float(row['Resistance [Ω]']) for row in csv.DictReader(f, delimiter=';')
                      if row['Resistance [Ω]'])


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_contact_2x2_minsize_via1():
    # 4 cuts in parallel, each 4500 mΩ (2 cuts each join the same nodes, so they are one resistor)
    assert obtained_resistances('test_patterns', 'r_contact_2x2_minsize_via1.gds.gz') == \
           [0.026] * 4 + [2.25] * 2


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_via_stack_1x1_minsize_poly_to_metal5():
    # poly contact 5900 mΩ, Via1-Via4 4500 mΩ per cut
    assert obtained_resistances('test_patterns', 'r_via_stack_1x1_minsize_poly_to_metal5.gds.gz') == \
           [4.5] * 4 + [5.9]
