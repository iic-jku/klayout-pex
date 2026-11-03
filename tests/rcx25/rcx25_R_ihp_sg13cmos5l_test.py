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

from __future__ import annotations

from typing import *

import allure
import pytest

from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction

parent_suite = "kpex/2.5D Extraction Tests [PDK ihp-sg13cmos5l | mode R]"
tags = ("PEX", "2.5D")

pex_blackboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.IHP_SG13CMOS5L), pex_mode=PEXMode.R, blackbox=True)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('path_components, metal_range', [
    # NOTE: the Metal4 wire across it doesn't count, the default of the model is Metal1 … Metal4
    (('test_patterns', 'cap_cmomf_w5u_l5u_m2_m3_m4_wire.gds.gz'), 'mmin=2 mmax=3'),
    (('cap_cmomf_w5u_l5u_m1_m4', 'cap_cmomf_w5u_l5u_m1_m4.gds.gz'), 'mmin=1 mmax=4'),
])
def test_mom_cap_is_written_with_its_metal_range(path_components: Tuple[str, str], metal_range: str):
    line, = pex_blackboxed.written_device_lines(*path_components)
    assert ' cap_cmomf ' in line and f" {metal_range}" in line
