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

parent_suite = "kpex/2.5D Extraction Tests [PDK ihp-sg13g2 | mode CC]"
tags = ("PEX", "2.5D")


pex_whiteboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.IHP_SG13G2), pex_mode=PEXMode.CC, blackbox=False)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mim_cap__whiteboxed():
    # The device model gives cap_carea 1.5 fF/µm² * 6.99 µm * 6.99 µm = 73.29 fF
    # plus CJSW 40 aF/µm * 27.96 µm = 1.12 fF, the fringe to the bottom plate (Metal5) around the top plate (MIM)
    pex_whiteboxed.assert_expected_matches_obtained(
        'sg13g2_pr__cmim', 'cmim.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;$2;$3;74.784;
C2;$2;VSUBS;1.38;
C3;$3;VSUBS;0.878;"""
    )
