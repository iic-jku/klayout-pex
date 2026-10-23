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

from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction

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
    # The black-box extraction keeps the plates of the MIM caps, FuseTop and the Metal4 under it (LVS layer metal4_cap),
    # as conductors, and leaves the capacitance between them to the device model: the overlap and the fringe
    # from the edge of FuseTop. So the other capacitances are the white-box ones, and between the plates,
    # the fringe between Metal5 and the Metal4 around the bottom plates is left.
    pex_blackboxed.assert_expected_matches_obtained(
        'test_patterns', 'cap_mim_m4m5.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;BOT1;BOT2;0.132;
C2;BOT1;TOP1;0.296;
C3;BOT1;TOP2;0.034;
C4;BOT1;VSUBS;0.836;
C5;BOT2;TOP1;0.024;
C6;BOT2;TOP2;0.888;
C7;BOT2;VSUBS;3.474;
C8;TOP1;TOP2;0.183;
C9;TOP1;VSUBS;0.449;
C10;TOP2;VSUBS;1.603;"""
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


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_plates_over_isolated_pwell_and_dnwell():
    # The isolated p-well (LVPWELL within DNWELL) is a net of its own, W by its p-tap, and so is the DNWELL
    # around it, D by its n-tap: the plates couple to the wells below them, their fringes to the other well
    # and, beyond the DNWELL, to the substrate (VSUBS). It was the substrate: A–VSUBS 2.402 fF, B–VSUBS 2.172 fF (#337)
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'plates_m1_over_isolated_pwell_and_dnwell.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;B;0.055;
C2;A;D;0.204;
C3;A;VSUBS;0.086;
C4;A;W;2.114;
C5;B;D;1.707;
C6;B;VSUBS;0.313;
C7;B;W;0.152;
C8;D;VSUBS;0.013;
C9;D;W;0.014;
C10;VSUBS;W;0.004;"""
    )
