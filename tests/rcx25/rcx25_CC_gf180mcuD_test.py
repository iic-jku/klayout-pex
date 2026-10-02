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
