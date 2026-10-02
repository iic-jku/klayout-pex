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

import allure
from typing import *
import unittest

import klayout.db as kdb

from klayout_pex.klayout.parasitic_device_classes import (
    PARASITIC_CAPACITOR_CLASS_NAME,
    PARASITIC_RESISTOR_CLASS_NAME,
)
from klayout_pex.rcx25.extraction_results import DeviceTerminalKey, ExtractionSummary, NetCoupleKey
from klayout_pex.rcx25.netlist_checks import check_rc_netlist


def lvs_netlist(mim_cap: bool = False) -> kdb.Netlist:
    """
    An nmos M1, with a pin on D, G and S

    :param mim_cap: with a MIM cap C1 between G and S, before M1
    """
    netlist = kdb.Netlist()
    circuit = kdb.Circuit()
    circuit.name = 'chip'
    netlist.add(circuit)
    nmos = kdb.DeviceClassMOS4Transistor()
    nmos.name = 'nmos'
    netlist.add(nmos)
    if mim_cap:
        mim = kdb.DeviceClassCapacitor()
        mim.name = 'mim'
        netlist.add(mim)
        c1 = circuit.create_device(mim, 'C1')
    m1 = circuit.create_device(nmos, 'M1')
    for cluster_id, terminal in enumerate(('D', 'G', 'S', 'B'), start=1):
        net = circuit.create_net(terminal)
        net.cluster_id = cluster_id  # like extracted nets
        m1.connect_terminal(terminal, net)
        if terminal != 'B':
            circuit.connect_pin(circuit.create_pin(terminal), net)
    if mim_cap:
        c1.connect_terminal('A', circuit.net_by_name('G'))
        c1.connect_terminal('B', circuit.net_by_name('S'))
    return netlist


class RCNetlist:
    """
    The LVS netlist, with parasitic resistors and capacitors added, like the netlist expansion does
    """
    def __init__(self, lvs: kdb.Netlist):
        self.netlist = lvs.dup()
        self.circuit = self.netlist.circuit_by_name('chip')
        self.res = kdb.DeviceClassResistor()
        self.res.name = PARASITIC_RESISTOR_CLASS_NAME
        self.netlist.add(self.res)
        self.cap = kdb.DeviceClassCapacitor()
        self.cap.name = PARASITIC_CAPACITOR_CLASS_NAME
        self.netlist.add(self.cap)

    def net(self, name: str) -> kdb.Net:
        return self.circuit.net_by_name(name) or self.circuit.create_net(name)

    def add(self, device_class: kdb.DeviceClass, net_a: str, net_b: str, parameter: str, value: float):
        device = self.circuit.create_device(device_class, '')
        device.connect_terminal('A', self.net(net_a))
        device.connect_terminal('B', self.net(net_b))
        device.set_parameter(parameter, value)

    def add_resistor(self, net_a: str, net_b: str, resistance: float = 10.0):
        self.add(self.res, net_a, net_b, 'R', resistance)

    def add_capacitor(self, net_a: str, net_b: str, capacitance_femto: float):
        self.add(self.cap, net_a, net_b, 'C', capacitance_femto / 1e15)

    def connect(self, device_name: str, terminal: str, net_name: str):
        self.circuit.device_by_name(device_name).connect_terminal(terminal, self.net(net_name))


@allure.parent_suite("Unit Tests")
@allure.tag("RCX25", "Netlist Checks")
class Test(unittest.TestCase):
    @staticmethod
    def check(rc: RCNetlist,
              capacitances: Dict[Tuple[str, str], float],
              device_terminal_nodes: Optional[Dict[str, str]] = None,
              substrate_net_name: Optional[str] = None) -> List[str]:
        """
        :param device_terminal_nodes: the node of the port of each terminal of M1 (e.g. D),
                                      or of another device (e.g. C1.A)
        """
        def key(terminal: str) -> DeviceTerminalKey:
            device_name, terminal = terminal.split('.') if '.' in terminal else ('M1', terminal)
            # NOTE: the device IDs of the summary are the ones of the LVS netlist
            device = rc.lvs.circuit_by_name('chip').device_by_name(device_name)
            return DeviceTerminalKey(device.id(), device.device_class().terminal_id(terminal))

        summary = ExtractionSummary(
            capacitances={NetCoupleKey(*k): c for k, c in capacitances.items()},
            resistances={},
            device_terminal_nodes={key(terminal): node for terminal, node in (device_terminal_nodes or {}).items()}
        )
        return check_rc_netlist(lvs_netlist=rc.lvs, rc_netlist=rc.netlist, top_cell_name='chip', summary=summary,
                                substrate_net_name=substrate_net_name)

    def rc_netlist(self, mim_cap: bool = False) -> RCNetlist:
        lvs = lvs_netlist(mim_cap)
        rc = RCNetlist(lvs)
        rc.lvs = lvs
        return rc

    def test_consistent_netlist(self):
        # the drain is on the end of the drain wire, the wire has a capacitance to the gate
        rc = self.rc_netlist()
        rc.add_resistor('D', 'D.$1.li1')
        rc.add_resistor('D.$1.li1', 'D.P0.nsdm')
        rc.connect('M1', 'D', 'D.P0.nsdm')
        rc.add_capacitor('D.$1.li1', 'G', 1.0)
        self.assertEqual([], self.check(rc, {('D.$1.li1', 'G'): 1.0}, {'D': 'D.P0.nsdm'}))

    def test_devices_after_a_whiteboxed_one(self):
        # the whiteboxed C1 is removed, the devices after it keep their IDs, the ones of the LVS netlist
        # NOTE: a copy of the RC netlist numbers them anew, which would make M1 the C1 of the LVS netlist
        rc = self.rc_netlist(mim_cap=True)
        rc.circuit.remove_device(rc.circuit.device_by_name('C1'))
        rc.add_resistor('D', 'D.P0.nsdm')
        rc.add_resistor('G', 'G.P0.metal1')
        rc.connect('M1', 'D', 'D.P0.nsdm')
        self.assertEqual([], self.check(rc, {}, {'D': 'D.P0.nsdm', 'C1.A': 'G.P0.metal1'}))

    def test_floating_resistor_network(self):
        # like #211 §6, on a net without a pin: the drain on the net, its wire floating
        rc = self.rc_netlist()
        rc.add_resistor('D.$1.li1', 'D.P0.nsdm')
        self.assertEqual(['resistors of the nodes D.$1.li1, D.P0.nsdm touch no net',
                          'terminal D of device M1 is not on the node D.P0.nsdm of its port'],
                         self.check(rc, {}, {'D': 'D.P0.nsdm'}))

    def test_terminal_not_on_its_port(self):
        # like #211 §6, on a net with a pin: the drain on the pin, not the end of its wire
        rc = self.rc_netlist()
        rc.add_resistor('D', 'D.P0.nsdm')
        self.assertEqual(['terminal D of device M1 is not on the node D.P0.nsdm of its port'],
                         self.check(rc, {}, {'D': 'D.P0.nsdm'}))

    def test_terminal_on_another_net(self):
        rc = self.rc_netlist()
        rc.add_resistor('D', 'D.$1.li1')
        rc.add_resistor('S', 'S.$1.li1')
        rc.connect('M1', 'D', 'S.$1.li1')
        self.assertEqual(['terminal D of device M1 is not on the resistor network of its net D'],
                         self.check(rc, {}))

    def test_resistors_joining_nets(self):
        rc = self.rc_netlist()
        rc.add_resistor('D', 'S')
        problems = self.check(rc, {})
        self.assertIn('resistors join the nets D and S', problems)
        self.assertIn('terminal S of device M1 is not on the resistor network of its net S', problems)

    def test_port_touching_nothing(self):
        # like #211 §11: the pin of D replaced by a port on a node of nothing
        rc = self.rc_netlist()
        pin_d = rc.circuit.pin_by_name('D')
        rc.circuit.disconnect_pin(pin_d.id())
        rc.circuit.connect_pin(pin_d.id(), rc.net('X'))
        self.assertEqual(['port D touches nothing', 'net D has no port'], self.check(rc, {}))

    def test_lost_capacitance(self):
        rc = self.rc_netlist()
        rc.add_capacitor('D', 'G', 1.0)
        self.assertEqual(['the capacitance between D and G is 1 fF, but 1.5 fF in the summary',
                          'the capacitance between D and S is 0 fF, but 0.5 fF in the summary'],
                         self.check(rc, {('D', 'G'): 1.5, ('D', 'S'): 0.5}))

    def test_nets_of_the_same_name(self):
        # like #211 §10: the islands of D, joined only in the parent
        rc = self.rc_netlist()
        rc.circuit.create_net('D')
        self.assertEqual(['nets have the same name: D'], self.check(rc, {}))

    def test_capacitances_to_the_substrate_are_on_its_net(self):
        # the summary has them on VSUBS, the netlist on the substrate net B, but the one of B itself, shorted
        rc = self.rc_netlist()
        rc.add_capacitor('D', 'B', 1.0)
        self.assertEqual([], self.check(rc, {('D', 'VSUBS'): 1.0, ('B', 'VSUBS'): 2.0}, substrate_net_name='B'))
