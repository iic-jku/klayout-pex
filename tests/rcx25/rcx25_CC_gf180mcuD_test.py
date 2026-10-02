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

parent_suite = "kpex/2.5D Extraction Tests [PDK gf180mcuD | mode CC]"
tags = ("PEX", "2.5D")


pex_whiteboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.GF180MCUD), pex_mode=PEXMode.CC, blackbox=False)
pex_blackboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.GF180MCUD), pex_mode=PEXMode.CC, blackbox=True)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mim_cap__whiteboxed():
    # The device model cap_mim_2f0_m4m5_noshield gives c_cox 1.99 fF/µm² * A + c_capsw 0.2383 fF/µm * P:
    #   5 µm x 5 µm:   49.75 fF + 4.77 fF  = 54.52 fF  (TOP1 - BOT1)
    #   20 µm x 10 µm: 398.0 fF + 14.30 fF = 412.30 fF (TOP2 - BOT2)
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'cap_mim_m4m5.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;BOT1;BOT2;0.132;
C2;BOT1;TOP1;54.685;
C3;BOT1;TOP2;0.034;
C4;BOT1;VSUBS;0.836;
C5;BOT2;TOP1;0.024;
C6;BOT2;TOP2;412.805;
C7;BOT2;VSUBS;3.474;
C8;TOP1;TOP2;0.183;
C9;TOP1;VSUBS;0.449;
C10;TOP2;VSUBS;1.603;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mim_cap__blackboxed():
    # The black-box extraction leaves the MIM caps to the device model, with both of their plates,
    # FuseTop and the Metal4 under it (LVS layer metal4_cap), so there's no Metal5 over Metal4 under the top plates,
    # which added 8.758 fF to TOP2 - BOT2 (2 % of the device) and 1.28 fF to TOP1 - BOT1.
    # Between the plates, the fringe between Metal5 and the Metal4 around the bottom plates is left.
    pex_blackboxed.assert_expected_matches_obtained(
        'test_patterns', 'cap_mim_m4m5.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;BOT1;BOT2;0.15;
C2;BOT1;TOP1;0.884;
C3;BOT1;TOP2;0.031;
C4;BOT1;VSUBS;0.879;
C5;BOT2;TOP1;0.021;
C6;BOT2;TOP2;2.844;
C7;BOT2;VSUBS;3.112;
C8;TOP1;TOP2;0.118;
C9;TOP1;VSUBS;0.594;
C10;TOP2;VSUBS;2.763;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_well_diodes__blackboxed():
    # The well diodes of the PDK's KLayout pcells (2 µm x 4 µm, 3.3V), their models are diode_pw2dw, diode_dw2ps
    assert pex_blackboxed.written_device_lines('test_patterns', 'diode_pw2dw_dw2ps_03v3_w2_l4.gds.gz') == [
        'D$1 PW2DW_P PW2DW_N diode_pw2dw area=8e-12 pj=1.2e-05',
        'D$2 SUB DW2PS_N diode_dw2ps area=8e-12 pj=1.2e-05',
    ]
