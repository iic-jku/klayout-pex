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
The devices of a schematic, in the LVS device classes of the extracted netlist (#345)
"""

from __future__ import annotations

import unittest

import allure

from klayout_pex.netlist.spice_reader import SpiceReader
from klayout_pex.schematic_devices import schematic_devices
from tests.common.device_model_mappings import NMOS, RPPD, device_models

DEVICE_MODELS = device_models({**NMOS, 'model_name': 'sg13_lv_nmos'}, RPPD)


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "Schematic")
class SchematicDevicesTest(unittest.TestCase):
    def test_devices_of_the_subcircuit_of_the_cell_and_its_subcircuits(self):
        # NOTE: not the elements outside of subcircuits, e.g. of a testbench
        netlist = SpiceReader().parse("""\
.subckt half a b
XR1 a b rppd w=0.5u l=2u
.ends half
.subckt chip a b g
XM1 a g b b sg13_lv_nmos w=1u l=0.13u
X1 a b half
X2 a b half
.ends chip
XR2 a b rppd w=0.5u l=2u
Xdut a b g chip
""")
        schematic = schematic_devices(netlist=netlist, device_models=DEVICE_MODELS, top_cell_name='CHIP')
        self.assertEqual({'nmos': ['XM1'], 'rppd': ['X1.XR1', 'X2.XR1']}, schematic.device_names_by_class_name)

    def test_devices_of_the_subcircuits_no_other_one_calls_and_outside_of_them(self):
        netlist = SpiceReader().parse("""\
.subckt half a b
XR1 a b rppd w=0.5u l=2u
.ends half
.subckt other a b g
XM1 a g b b sg13_lv_nmos w=1u l=0.13u
X1 a b half
.ends other
XR2 a b rppd w=0.5u l=2u
""")
        schematic = schematic_devices(netlist=netlist, device_models=DEVICE_MODELS, top_cell_name='chip')
        self.assertEqual({'nmos': ['XM1'], 'rppd': ['X1.XR1', 'XR2']}, schematic.device_names_by_class_name)

    def test_devices_of_models_without_mapping(self):
        # NOTE: e.g. a standard cell, which the schematic calls, but doesn't define; elements without model don't count
        netlist = SpiceReader().parse("""\
.subckt chip a b
Xinv a b sg13g2_inv_1
R1 a b 1k
.ends chip
""")
        schematic = schematic_devices(netlist=netlist, device_models=DEVICE_MODELS, top_cell_name='chip')
        self.assertEqual({}, schematic.device_names_by_class_name)
        self.assertEqual({'sg13g2_inv_1': ['Xinv']}, schematic.device_names_by_unknown_model)
