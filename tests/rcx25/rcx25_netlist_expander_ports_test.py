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

from klayout_pex.rcx25.extraction_results import CellExtractionResults, ExtractionResults
from klayout_pex.rcx25.netlist_expander import RCX25NetlistExpander
import klayout_pex_protobuf.kpex.r.r_network_pb2 as r_network_pb2


@allure.parent_suite("Unit Tests")
@allure.tag("RCX25", "Netlist Expansion")
class Test(unittest.TestCase):
    def test_a_net_of_several_labels_has_a_port_per_label(self):
        # an nmos with its drain on a wire with the labels D and X at its ends (#211 §11)
        netlist = kdb.Netlist()
        circuit = kdb.Circuit()
        circuit.name = 'chip'
        netlist.add(circuit)
        nmos = kdb.DeviceClassMOS4Transistor()
        nmos.name = 'nmos'
        netlist.add(nmos)
        nets = {name: circuit.create_net(name) for name in ('D,X', 'G', 'S', 'B')}
        m1 = circuit.create_device(nmos, 'M1')
        for terminal, net in (('S', 'S'), ('G', 'G'), ('D', 'D,X'), ('B', 'B')):
            m1.connect_terminal(terminal, nets[net])
        for name in ('D,X', 'G', 'S'):  # like KLayout's make_top_level_pins, a pin per net
            circuit.connect_pin(circuit.create_pin(name), nets[name])

        K = r_network_pb2.RNode.Kind
        results = CellExtractionResults(cell_name='chip')
        network = results.r_extraction_result.networks.add(net_name='D,X')
        for node_id, kind, node_name in ((1, K.KIND_PIN, 'D'),
                                         (2, K.KIND_WIRE_JUNCTION, '$1.Metal1'),
                                         (3, K.KIND_PIN, 'X'),
                                         (4, K.KIND_DEVICE_TERMINAL, 'P0.nSD')):
            node = network.nodes.add(node_id=node_id, node_kind=kind, node_name=node_name)
            if kind != K.KIND_PIN:
                node.net_name = f"D,X.{node_name}"
            if kind == K.KIND_DEVICE_TERMINAL:
                node.device_terminal.device_id = m1.id()
                node.device_terminal.terminal_id = nmos.terminal_id('D')
        for node_a, node_b, resistance in ((1, 2, 0.488), (2, 3, 0.089), (2, 4, 17.0)):
            element = network.elements.add(resistance=resistance)
            element.node_a.node_id = node_a
            element.node_b.node_id = node_b

        expanded = RCX25NetlistExpander.expand(netlist, 'chip', ExtractionResults({'chip': results}),
                                               blackbox_devices=True)
        circuit = expanded.circuit_by_name('chip')

        # NOTE: the pin of D,X is replaced by the ports D and X, in its place
        self.assertEqual([('D', 'D'), ('X', 'X'), ('G', 'G'), ('S', 'S')],
                         [(pin.name(), circuit.net_for_pin(pin.id()).name) for pin in circuit.each_pin()])
        self.assertEqual('D,X', circuit.device_by_name('M1').net_for_terminal('D').name)
        # NOTE: no port touches nothing (a port the labels had lost, which the parent connected, dangled)
        self.assertEqual([], [pin.name() for pin in circuit.each_pin()
                              if circuit.net_for_pin(pin.id()).terminal_count() == 0])
