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
import unittest

import klayout.db as kdb

from klayout_pex.klayout.lvsdb_extractor import DEVICE_CAPACITOR_PLATE_PROPERTY
from klayout_pex.rcx25.c.device_capacitor_plates import DeviceCapacitorPlates


def netlist() -> kdb.Netlist:
    """
    A MOM cap between the nets A and B, and an nmos between A and C
    """
    netlist = kdb.Netlist()
    circuit = kdb.Circuit()
    circuit.name = 'chip'
    netlist.add(circuit)
    nets = {name: circuit.create_net(name) for name in ('A', 'B', 'C')}
    for device_class, class_name, device_name, terminal_nets in (
            (kdb.DeviceClassCapacitor(), 'mom', 'C1', {'A': 'A', 'B': 'B'}),
            (kdb.DeviceClassMOS4Transistor(), 'nmos', 'M1', {'D': 'A', 'S': 'C'})):
        device_class.name = class_name
        netlist.add(device_class)
        device = circuit.create_device(device_class, device_name)
        for terminal, net_name in terminal_nets.items():
            device.connect_terminal(terminal, nets[net_name])
    return netlist


def shape(net: str, plate: bool) -> kdb.PolygonWithProperties:
    properties = {'net': net, DEVICE_CAPACITOR_PLATE_PROPERTY: True} if plate else {'net': net}
    return kdb.PolygonWithProperties(kdb.Polygon(kdb.Box(0, 0, 100, 100)), properties)


@allure.parent_suite("Unit Tests")
@allure.tag("RCX25", "Capacitance", "Device Capacitor Plates")
class Test(unittest.TestCase):
    def test_terminal_nets_of_the_capacitor_devices(self):
        chip = netlist()
        plates = DeviceCapacitorPlates.from_circuit(chip.circuit_by_name('chip'), device_class_names={'mom'})
        self.assertEqual({frozenset(('A', 'B'))}, plates.terminal_net_pairs)

    def test_plates_of_a_device(self):
        chip = netlist()
        plates = DeviceCapacitorPlates.from_circuit(chip.circuit_by_name('chip'), device_class_names={'mom'})
        self.assertTrue(plates.are_plates_of_a_device(shape('A', plate=True), 'A', shape('B', plate=True), 'B'))
        # e.g. a wire of the net B, outside of the device
        self.assertFalse(plates.are_plates_of_a_device(shape('A', plate=True), 'A', shape('B', plate=False), 'B'))
        # e.g. a wire of the net C across the device, on its plate layers too
        self.assertFalse(plates.are_plates_of_a_device(shape('A', plate=True), 'A', shape('C', plate=True), 'C'))
