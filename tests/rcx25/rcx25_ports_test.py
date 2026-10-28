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

"""
The ports of the netlists of test patterns: a port for each pin label, also of a net without devices,
which KLayout's LVS netlist has no pin for
"""

from __future__ import annotations

import os
from typing import *

import allure
import pytest

from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist
from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction

parent_suite = "kpex/2.5D netlist ports"
tags = ("PEX", "2.5D", "Ports")


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('gds_name, mode, ports', [
    # NOTE: the wire of the pins A, B and C is the net A,B,C, which has a port per label in R and RC mode
    #       (#211 §11), and one node in CC mode
    ('r_wire_voltage_divider_li1.gds.gz', PEXMode.CC, ['A|B|C', 'sky130_gnd']),
    ('r_wire_voltage_divider_li1.gds.gz', PEXMode.R, ['A', 'B', 'C']),
    ('r_wire_voltage_divider_li1.gds.gz', PEXMode.RC, ['A', 'B', 'C', 'sky130_gnd']),
    # NOTE: the met2 wire D under the MIM cap has no device, the plates A and B have
    ('cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz', PEXMode.R, ['A', 'B', 'D']),
    ('cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz', PEXMode.RC, ['A', 'B', 'D', 'sky130_gnd']),
])
def test_nets_without_devices_have_the_ports_of_their_pins(gds_name: str, mode: PEXMode, ports: List[str]):
    cli = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=mode, blackbox=False) \
        .run_kpex('test_patterns', gds_name)
    netlist_path = f"{os.path.splitext(cli.rcx25_extracted_csv_path)[0]}.spice"
    scope = next(s for s in SpiceRCNetlist.read(netlist_path).scopes if s.name is not None)
    assert scope.ports == ports
    assert cli.rcx25_netlist_problems == []
