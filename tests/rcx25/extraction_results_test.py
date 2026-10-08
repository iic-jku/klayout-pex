#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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
import unittest

from klayout_pex.rcx25.extraction_results import *


@allure.parent_suite("Unit Tests")
class NetCoupleKeyTest(unittest.TestCase):
    def test_normed_ascending(self):
        k = NetCoupleKey('net_bottom', 'net_top')
        obtained_k = k.normed()
        expected_k = NetCoupleKey('net_bottom', 'net_top')
        self.assertEqual(expected_k, obtained_k)

    def test_normed_descending(self):
        k = NetCoupleKey('net_top', 'net_bottom')
        obtained_k = k.normed()
        expected_k = NetCoupleKey('net_bottom', 'net_top')
        self.assertEqual(expected_k, obtained_k)


@allure.parent_suite("Unit Tests")
class CellExtractionResultsTest(unittest.TestCase):
    def test_summarize_overlap(self):
        results = CellExtractionResults(cell_name='Cell')

        ovk1a = OverlapKey(layer_top='m2',
                           net_top='net_top',
                           layer_bot='m1',
                           net_bot='net_bot')

        ovk1b = OverlapKey(layer_top='m2',
                           net_top='net_top',
                           layer_bot='m1',
                           net_bot='net_bot')

        ovk2 = OverlapKey(layer_top='m3',
                           net_top='net_top',
                           layer_bot='m1',
                           net_bot='net_bot')

        ovc1a = OverlapCap(key=ovk1a,
                           cap_value=10.0,
                           shielded_area=20.0,
                           unshielded_area=30.0,
                           tech_spec=None)

        ovc1b = OverlapCap(key=ovk1b,
                           cap_value=11.0,
                           shielded_area=21.0,
                           unshielded_area=31.0,
                           tech_spec=None)

        ovc2 = OverlapCap(key=ovk2,
                          cap_value=12.0,
                          shielded_area=22.0,
                          unshielded_area=32.0,
                          tech_spec=None)

        results.add_overlap_cap(ovc1a)
        results.add_overlap_cap(ovc2)
        results.add_overlap_cap(ovc1b)

        summary = results.summarize()
        obtained_cap_value = summary.capacitances[NetCoupleKey('net_top', 'net_bot').normed()]
        expected_cap_value = ovc1a.cap_value + ovc1b.cap_value + ovc2.cap_value
        self.assertEqual(expected_cap_value, obtained_cap_value)

    def test_summarize_sidewall(self):
        results = CellExtractionResults(cell_name='Cell')

        k1a = SidewallKey(layer='m2',
                          net1='net1',
                          net2='net2')

        k1b = SidewallKey(layer='m2',
                          net1='net2',
                          net2='net1')

        k2 = SidewallKey(layer='m3',
                         net1='net1',
                         net2='net3')

        c1a = SidewallCap(key=k1a,
                          cap_value=10.0,
                          distance=20.0,
                          length=30.0,
                          tech_spec=None)

        c1b = SidewallCap(key=k1b,
                          cap_value=11.0,
                          distance=21.0,
                          length=31.0,
                          tech_spec=None)

        c2 = SidewallCap(key=k2,
                         cap_value=12.0,
                         distance=22.0,
                         length=32.0,
                         tech_spec=None)

        results.add_sidewall_cap(c1a)
        results.add_sidewall_cap(c1b)
        results.add_sidewall_cap(c2)

        summary = results.summarize()

        obtained_cap_value = summary.capacitances[NetCoupleKey('net1', 'net2').normed()]
        expected_cap_value = c1a.cap_value + c1b.cap_value
        self.assertEqual(expected_cap_value, obtained_cap_value)

        obtained_cap_value = summary.capacitances[NetCoupleKey('net1', 'net3').normed()]
        expected_cap_value = c2.cap_value
        self.assertEqual(expected_cap_value, obtained_cap_value)

    def test_summarize_sideoverlap(self):
        results = CellExtractionResults(cell_name='Cell')

        k1a = SideOverlapKey(layer_inside='m2',
                             net_inside='net2',
                             layer_outside='m1',
                             net_outside='net1')

        k1b = SideOverlapKey(layer_inside='m1',
                             net_inside='net1',
                             layer_outside='m2',
                             net_outside='net2')

        k2 = SideOverlapKey(layer_inside='m3',
                            net_inside='net3',
                            layer_outside='m1',
                            net_outside='net1')

        c1a = SideOverlapCap(key=k1a,
                             cap_value=10.0)

        c1b = SideOverlapCap(key=k1b,
                             cap_value=10.0)

        c2 = SideOverlapCap(key=k2,
                            cap_value=10.0)

        results.add_sideoverlap_cap(c1a)
        results.add_sideoverlap_cap(c1b)
        results.add_sideoverlap_cap(c2)

        summary = results.summarize()

        obtained_cap_value = summary.capacitances[NetCoupleKey('net1', 'net2').normed()]
        expected_cap_value = c1a.cap_value + c1b.cap_value
        self.assertEqual(expected_cap_value, obtained_cap_value)

        obtained_cap_value = summary.capacitances[NetCoupleKey('net1', 'net3').normed()]
        expected_cap_value = c2.cap_value
        self.assertEqual(expected_cap_value, obtained_cap_value)

    def test_summarize_resistances_between_the_same_nodes_are_in_parallel(self):
        # a wire with pin A at both ends, and pin B at a stub in the middle:
        # both pins A are one node in the netlist, so each half of the wire is in parallel to the other
        results = CellExtractionResults(cell_name='Cell')
        network = results.r_extraction_result.networks.add()
        network.net_name = 'A,B'
        for node_id, kind, node_name in ((1, r_network_pb2.RNode.Kind.KIND_PIN, 'A'),
                                         (2, r_network_pb2.RNode.Kind.KIND_PIN, 'A'),
                                         (3, r_network_pb2.RNode.Kind.KIND_WIRE_JUNCTION, '$1.16'),
                                         (4, r_network_pb2.RNode.Kind.KIND_PIN, 'B')):
            node = network.nodes.add(node_id=node_id, node_kind=kind, node_name=node_name)
            if kind == r_network_pb2.RNode.Kind.KIND_WIRE_JUNCTION:
                node.net_name = f"{network.net_name}.{node_name}"
        for node_a, node_b, resistance in ((1, 3, 426.667), (2, 3, 413.867), (3, 4, 72.533)):
            element = network.elements.add(resistance=resistance)
            element.node_a.node_id = node_a
            element.node_b.node_id = node_b

        summary = results.summarize()

        # NOTE: no pin carries the net's name A,B, so the wire junction does
        self.assertEqual({NetCoupleKey('A', 'A,B'), NetCoupleKey('A,B', 'B')},
                         set(summary.resistances.keys()))
        self.assertAlmostEqual(426.667 * 413.867 / (426.667 + 413.867),
                               summary.resistances[NetCoupleKey('A', 'A,B')])
        self.assertAlmostEqual(72.533, summary.resistances[NetCoupleKey('A,B', 'B')])

    def test_summarize_skips_resistances_between_pins_with_the_same_label(self):
        # e.g. output Y of sky130_fd_sc_hd__inv_1, which has two labels:
        # both pins Y are one node in the netlist, so the element between them is shorted
        results = CellExtractionResults(cell_name='Cell')
        network = results.r_extraction_result.networks.add()
        network.net_name = 'Y'
        for node_id, kind, node_name in ((1, r_network_pb2.RNode.Kind.KIND_PIN, 'Y'),
                                         (2, r_network_pb2.RNode.Kind.KIND_PIN, 'Y'),
                                         (3, r_network_pb2.RNode.Kind.KIND_DEVICE_TERMINAL, '$0.3')):
            node = network.nodes.add(node_id=node_id, node_kind=kind, node_name=node_name)
            if kind == r_network_pb2.RNode.Kind.KIND_DEVICE_TERMINAL:
                node.net_name = f"{network.net_name}.{node_name}"
        for node_a, node_b, resistance in ((1, 2, 18.981), (2, 3, 5.0)):
            element = network.elements.add(resistance=resistance)
            element.node_a.node_id = node_a
            element.node_b.node_id = node_b

        summary = results.summarize()

        self.assertEqual({NetCoupleKey('Y', 'Y.$0.3'): 5.0}, summary.resistances)

    @staticmethod
    def add_network(results: CellExtractionResults,
                    net_name: str,
                    nodes: List[Tuple],
                    elements: List[Tuple[int, int, float]]):
        """
        :param nodes: (node ID, kind, node name[, (device ID, terminal ID)])
        """
        network = results.r_extraction_result.networks.add(net_name=net_name)
        for node_id, kind, node_name, *terminal in nodes:
            node = network.nodes.add(node_id=node_id, node_kind=kind, node_name=node_name)
            if kind != r_network_pb2.RNode.Kind.KIND_PIN:
                node.net_name = f"{net_name}.{node_name}"
            if terminal:
                node.device_terminal.device_id, node.device_terminal.terminal_id = terminal[0]
        for node_a, node_b, resistance in elements:
            element = network.elements.add(resistance=resistance)
            element.node_a.node_id = node_a
            element.node_b.node_id = node_b

    def test_summarize_device_terminals_and_the_node_carrying_the_net_name(self):
        # a net without a pin: device 3 and device 5 (with 2 ports for one terminal) on a wire
        K = r_network_pb2.RNode.Kind
        results = CellExtractionResults(cell_name='Cell')
        self.add_network(results, '$2',
                         nodes=[(1, K.KIND_DEVICE_TERMINAL, 'P0.12', (5, 2)),
                                (2, K.KIND_WIRE_JUNCTION, '$0.12'),
                                (3, K.KIND_DEVICE_TERMINAL, 'P0.13', (3, 0)),
                                (4, K.KIND_DEVICE_TERMINAL, 'P1.12', (5, 2))],
                         elements=[(1, 2, 10.0), (2, 3, 20.0), (4, 2, 30.0)])

        summary = results.summarize()

        # NOTE: the first device terminal carries the net's name,
        #       and the ports of one terminal are one node (so their elements are in parallel)
        self.assertEqual({DeviceTerminalKey(3, 0): '$2',
                          DeviceTerminalKey(5, 2): '$2.P0.12'}, summary.device_terminal_nodes)
        self.assertEqual({NetCoupleKey('$2', '$2.$0.12'): 20.0,
                          NetCoupleKey('$2.$0.12', '$2.P0.12'): 7.5}, summary.resistances)

    def test_summarize_a_pin_carries_the_net_name(self):
        K = r_network_pb2.RNode.Kind
        results = CellExtractionResults(cell_name='Cell')
        self.add_network(results, 'G',
                         nodes=[(1, K.KIND_PIN, 'G'),
                                (2, K.KIND_DEVICE_TERMINAL, 'P0.16', (1, 1))],
                         elements=[(1, 2, 100.0)])

        summary = results.summarize()

        self.assertEqual({DeviceTerminalKey(1, 1): 'G.P0.16'}, summary.device_terminal_nodes)
        self.assertEqual({NetCoupleKey('G', 'G.P0.16'): 100.0}, summary.resistances)

    def test_summarize_the_pins_of_a_net_of_one_label_are_its_node(self):
        # NOTE: another net has the label D too, so this one is called D$1 (#211 §10)
        K = r_network_pb2.RNode.Kind
        results = CellExtractionResults(cell_name='Cell')
        self.add_network(results, 'D$1',
                         nodes=[(1, K.KIND_PIN, 'D'),
                                (2, K.KIND_WIRE_JUNCTION, '$1.Metal1'),
                                (3, K.KIND_DEVICE_TERMINAL, 'P0.nSD', (1, 2))],
                         elements=[(1, 2, 0.488), (2, 3, 17.0)])

        summary = results.summarize()

        self.assertEqual({DeviceTerminalKey(1, 2): 'D$1.P0.nSD'}, summary.device_terminal_nodes)
        self.assertEqual({NetCoupleKey('D$1', 'D$1.$1.Metal1'): 0.488,
                          NetCoupleKey('D$1.$1.Metal1', 'D$1.P0.nSD'): 17.0}, summary.resistances)

    def test_summarize_a_net_of_several_labels_has_a_port_per_label(self):
        # a drain wire with the labels D and X at its ends (#211 §11)
        K = r_network_pb2.RNode.Kind
        results = CellExtractionResults(cell_name='Cell')
        self.add_network(results, 'D,X',
                         nodes=[(1, K.KIND_PIN, 'D'),
                                (2, K.KIND_WIRE_JUNCTION, '$1.Metal1'),
                                (3, K.KIND_PIN, 'X'),
                                (4, K.KIND_DEVICE_TERMINAL, 'P0.nSD', (1, 2))],
                         elements=[(1, 2, 0.488), (2, 3, 0.089), (2, 4, 17.0)])

        summary = results.summarize()

        self.assertEqual({'D,X': ['D', 'X']}, summary.label_ports)
        # NOTE: no pin carries the net's name, so the device terminal does
        self.assertEqual({DeviceTerminalKey(1, 2): 'D,X'}, summary.device_terminal_nodes)
        self.assertEqual({NetCoupleKey('D', 'D,X.$1.Metal1'): 0.488,
                          NetCoupleKey('D,X.$1.Metal1', 'X'): 0.089,
                          NetCoupleKey('D,X', 'D,X.$1.Metal1'): 17.0}, summary.resistances)

    def test_summarize_the_port_of_a_label_has_a_unique_name(self):
        # the label D is the name of another net too
        K = r_network_pb2.RNode.Kind
        results = CellExtractionResults(cell_name='Cell')
        self.add_network(results, 'D',
                         nodes=[(1, K.KIND_PIN, 'D'),
                                (2, K.KIND_WIRE_JUNCTION, '$1.Metal1')],
                         elements=[(1, 2, 0.5)])
        self.add_network(results, 'D,X',
                         nodes=[(1, K.KIND_PIN, 'D'),
                                (2, K.KIND_PIN, 'X')],
                         elements=[(1, 2, 0.6)])

        summary = results.summarize()

        self.assertEqual({'D,X': ['D$1', 'X']}, summary.label_ports)
        self.assertEqual({NetCoupleKey('D', 'D.$1.Metal1'): 0.5,
                          NetCoupleKey('D$1', 'X'): 0.6,
                          NetCoupleKey('D$1', 'D,X'): LABEL_TIE_RESISTANCE}, summary.resistances)

    def test_summarize_a_net_of_labels_only_is_tied_to_its_first_label(self):
        # a wire between the labels A and B: no node carries the net's name A,B,
        # so the node of A is tied to it, rather than leaving the net (e.g. its capacitances) off the network
        K = r_network_pb2.RNode.Kind
        results = CellExtractionResults(cell_name='Cell')
        self.add_network(results, 'A,B',
                         nodes=[(1, K.KIND_PIN, 'A'),
                                (2, K.KIND_PIN, 'B')],
                         elements=[(1, 2, 3.823)])

        summary = results.summarize()

        self.assertEqual({'A,B': ['A', 'B']}, summary.label_ports)
        self.assertEqual({NetCoupleKey('A', 'B'): 3.823,
                          NetCoupleKey('A', 'A,B'): LABEL_TIE_RESISTANCE}, summary.resistances)

    def test_summarize_labels_on_one_node_are_tied(self):
        # NOTE: each label is a port, so the port of X is tied to the node of D (#211 §11)
        K = r_network_pb2.RNode.Kind
        results = CellExtractionResults(cell_name='Cell')
        self.add_network(results, 'D,X',
                         nodes=[(1, K.KIND_PIN, 'D'),
                                (2, K.KIND_PIN, 'X'),
                                (3, K.KIND_WIRE_JUNCTION, '$1.Metal1')],
                         elements=[(1, 2, 0.0), (2, 3, 0.488)])

        summary = results.summarize()

        self.assertEqual({'D,X': ['D', 'X']}, summary.label_ports)
        self.assertEqual({NetCoupleKey('D', 'D,X'): 0.488,
                          NetCoupleKey('D', 'X'): LABEL_TIE_RESISTANCE}, summary.resistances)

    def test_summarize_nodes_joined_without_resistance_are_one_node(self):
        # NOTE: a simulator can't solve for a resistor of 0 Ω, so no such resistor must be written
        K = r_network_pb2.RNode.Kind
        results = CellExtractionResults(cell_name='Cell')
        self.add_network(results, '$2',
                         nodes=[(1, K.KIND_DEVICE_TERMINAL, 'P0.12', (1, 2)),
                                (2, K.KIND_WIRE_JUNCTION, '$0.12'),
                                (3, K.KIND_WIRE_JUNCTION, '$1.17'),
                                (4, K.KIND_DEVICE_TERMINAL, 'P1.12', (2, 0)),
                                (5, K.KIND_WIRE_JUNCTION, '$2.12')],
                         elements=[(1, 2, 0.0), (2, 3, 209.667), (3, 5, 100.0), (5, 4, 0.0)])
        self.add_network(results, 'VGND',
                         nodes=[(1, K.KIND_PIN, 'VGND'),
                                (2, K.KIND_WIRE_JUNCTION, '$5.26'),
                                (3, K.KIND_WIRE_JUNCTION, '$4.18')],
                         elements=[(1, 2, 0.0), (2, 3, 9.3)])

        summary = results.summarize()

        # NOTE: a group of nodes is named after its pin, otherwise its device terminal's port,
        #       but the first device terminal carries the net's name
        self.assertEqual({DeviceTerminalKey(1, 2): '$2',
                          DeviceTerminalKey(2, 0): '$2.P1.12'}, summary.device_terminal_nodes)
        self.assertEqual({NetCoupleKey('$2', '$2.$1.17'): 209.667,
                          NetCoupleKey('$2.$1.17', '$2.P1.12'): 100.0,
                          NetCoupleKey('VGND', 'VGND.$4.18'): 9.3}, summary.resistances)


@allure.parent_suite("Unit Tests")
class ExtractionSummaryTest(unittest.TestCase):
    def test_parallel_resistance(self):
        self.assertAlmostEqual(50.0, parallel_resistance(100.0, 100.0))
        self.assertAlmostEqual(75.0, parallel_resistance(100.0, 300.0))
        self.assertEqual(0.0, parallel_resistance(0.0, 100.0))
        self.assertEqual(0.0, parallel_resistance(100.0, 0.0))

    def test_merged_resistances_between_the_same_nodes_are_in_parallel(self):
        summary = ExtractionSummary.merged([
            ExtractionSummary(capacitances={NetCoupleKey('A', 'B'): 1.0},
                              resistances={NetCoupleKey('A', 'B'): 100.0}),
            ExtractionSummary(capacitances={NetCoupleKey('B', 'A'): 2.0},
                              resistances={NetCoupleKey('B', 'A'): 300.0,
                                           NetCoupleKey('B', 'C'): 10.0}),
        ])
        self.assertEqual({NetCoupleKey('A', 'B'): 3.0}, dict(summary.capacitances))
        self.assertEqual({NetCoupleKey('A', 'B'): 75.0,
                          NetCoupleKey('B', 'C'): 10.0}, summary.resistances)
