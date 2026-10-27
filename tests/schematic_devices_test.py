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

    def test_devices_with_their_lvs_parameters_and_m(self):
        # NOTE: by the device model mapping in reverse, e.g. W in µm of w in m
        netlist = SpiceReader().parse("""\
.subckt chip a b g
XM1 a g b b sg13_lv_nmos w=2u l=0.13u ng=2 m=3
.ends
""")
        device = schematic_devices(netlist=netlist, device_models=DEVICE_MODELS,
                                   top_cell_name='chip').devices_by_class_name['nmos'][0]
        self.assertEqual(('XM1', ['L', 'W'], 3.0), (device.name, sorted(device.lvs_parameters), device.m))
        self.assertAlmostEqual(2.0, device.lvs_parameters['W'], places=12)
        self.assertAlmostEqual(0.13, device.lvs_parameters['L'], places=12)

    def test_devices_of_parameterized_subcircuits(self):
        # NOTE: as BAG writes them (#330), the M lines of the LVS device class
        netlist = SpiceReader().parse("""\
.subckt inverter VDD I Q VSS
Xnmos Q I VSS VSS nmos4_lvt w=3.9u l=130n nf=4
Xdummy VSS VSS VSS VSS nmos4_lvt w=3.9u l=130n nf=2
.ends
.subckt nmos4_lvt D G S B w=150n l=130n nf=4
MM1 D G S B nmos w=w*nf l=l ng=nf
.ends
""")
        schematic = schematic_devices(netlist=netlist, device_models=DEVICE_MODELS, top_cell_name='inverter')
        self.assertEqual({'nmos': ['Xnmos.MM1', 'Xdummy.MM1']}, schematic.device_names_by_class_name)

    def test_devices_with_expressions_of_their_parameters(self):
        # NOTE: as xschem writes the MOS of sky130A
        netlist = SpiceReader().parse("""\
.subckt chip a b g
XM1 a g b b sg13_lv_nmos L=0.13 W=1 nf=1 ad='int((nf+1)/2) * W/nf * 0.29' m=1
.ends
""")
        schematic = schematic_devices(netlist=netlist, device_models=DEVICE_MODELS, top_cell_name='chip')
        self.assertEqual({'nmos': ['XM1']}, schematic.device_names_by_class_name)

    def test_cell_called_outside_of_subcircuits_counts_once(self):
        # NOTE: e.g. by a testbench, without subcircuit of the layout's cell
        netlist = SpiceReader().parse("""\
.subckt chip a b g
XM1 a g b b sg13_lv_nmos w=1u l=0.13u
.ends chip
Xdut a b g chip
""")
        schematic = schematic_devices(netlist=netlist, device_models=DEVICE_MODELS, top_cell_name='other')
        self.assertEqual({'nmos': ['Xdut.XM1']}, schematic.device_names_by_class_name)
