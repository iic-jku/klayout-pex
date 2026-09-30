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
    def test_device_terminals_are_connected_to_their_nodes(self):
        # 2 nmos with drain on the unlabelled net $2, and gate on the pin G
        netlist = kdb.Netlist()
        circuit = kdb.Circuit()
        circuit.name = 'chip'
        netlist.add(circuit)
        nmos = kdb.DeviceClassMOS4Transistor()
        nmos.name = 'nmos'
        netlist.add(nmos)
        nets = {name: circuit.create_net(name) for name in ('G', '$2', 'S', 'B')}
        m1 = circuit.create_device(nmos, 'M1')
        m2 = circuit.create_device(nmos, 'M2')
        for m in (m1, m2):
            for terminal, net in (('S', 'S'), ('G', 'G'), ('D', '$2'), ('B', 'B')):
                m.connect_terminal(terminal, nets[net])

        K = r_network_pb2.RNode.Kind
        results = CellExtractionResults(cell_name='chip')
        for net_name, nodes, elements in (
                ('$2', [(1, K.KIND_DEVICE_TERMINAL, 'P0.12', m1.id(), 'D'),
                        (2, K.KIND_WIRE_JUNCTION, '$0.12', None, None),
                        (3, K.KIND_DEVICE_TERMINAL, 'P1.12', m2.id(), 'D')],
                       [(1, 2, 10.0), (2, 3, 20.0)]),
                ('G', [(1, K.KIND_PIN, 'G', None, None),
                       (2, K.KIND_DEVICE_TERMINAL, 'P0.16', m1.id(), 'G')],
                      [(1, 2, 100.0)])):
            network = results.r_extraction_result.networks.add(net_name=net_name)
            for node_id, kind, node_name, device_id, terminal in nodes:
                node = network.nodes.add(node_id=node_id, node_kind=kind, node_name=node_name)
                if kind != K.KIND_PIN:
                    node.net_name = f"{net_name}.{node_name}"
                if device_id is not None:
                    node.device_terminal.device_id = device_id
                    node.device_terminal.terminal_id = nmos.terminal_id(terminal)
            for node_a, node_b, resistance in elements:
                element = network.elements.add(resistance=resistance)
                element.node_a.node_id = node_a
                element.node_b.node_id = node_b

        expanded = RCX25NetlistExpander.expand(netlist, 'chip', ExtractionResults({'chip': results}),
                                               blackbox_devices=True)
        circuit = expanded.circuit_by_name('chip')

        def net_of(device_name: str, terminal: str) -> str:
            return circuit.device_by_name(device_name).net_for_terminal(terminal).name

        # NOTE: M1's drain is the first device terminal of $2, so it carries the net's name
        self.assertEqual('$2', net_of('M1', 'D'))
        self.assertEqual('$2.P1.12', net_of('M2', 'D'))
        self.assertEqual('G.P0.16', net_of('M1', 'G'))
        self.assertEqual('G', net_of('M2', 'G'))  # no port, stays on the net
        self.assertEqual('B', net_of('M1', 'B'))  # no resistor network
        resistors = {frozenset((d.net_for_terminal('A').name, d.net_for_terminal('B').name)): d.parameter('R')
                     for d in circuit.each_device() if d.device_class().name == 'PEX_RES'}
        self.assertEqual({frozenset(('$2', '$2.$0.12')): 10.0,
                          frozenset(('$2.$0.12', '$2.P1.12')): 20.0,
                          frozenset(('G', 'G.P0.16')): 100.0}, resistors)
