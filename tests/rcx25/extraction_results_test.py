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
import dataclasses
import pytest
import random
import unittest

import klayout.db as kdb

from klayout_pex.rcx25.extraction_results import *
import klayout_pex_protobuf.kpex.layout.location_pb2 as location_pb2


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
    def test_capacitances_keep_their_geometry_only_if_asked_to(self):
        # NOTE: the geometry places each capacitance on the resistor network (RC mode), and takes memory otherwise
        def add_capacitances(results: CellExtractionResults):
            results.add_overlap_cap(OverlapCap(key=OverlapKey('met1', 'A', 'li1', 'B'), cap_value=1.0,
                                               shielded_area=0.0, unshielded_area=0.0, tech_spec=None,
                                               area=kdb.Region(kdb.Box(0, 0, 100, 100))))
            results.add_sidewall_cap(SidewallCap(key=SidewallKey('li1', 'A', 'B'), cap_value=1.0,
                                                 distance=0.2, length=0.1, tech_spec=None,
                                                 inside_edge=kdb.Edge(0, 0, 100, 0),
                                                 outside_edge=kdb.Edge(0, 200, 100, 200)))
            results.add_sideoverlap_cap(SideOverlapCap(key=SideOverlapKey('li1', 'A', 'met1', 'B'), cap_value=1.0,
                                                       inside_edge=kdb.Edge(0, 0, 100, 0),
                                                       outside_edge=kdb.Edge(0, 300, 100, 300)))

        def geometries(results: CellExtractionResults) -> List[Any]:
            o, = [c for caps in results.overlap_table.values() for c in caps]
            s, = [c for caps in results.sidewall_table.values() for c in caps]
            f, = [c for caps in results.sideoverlap_table.values() for c in caps]
            return [o.area, s.inside_edge, s.outside_edge, f.inside_edge, f.outside_edge]

        kept = CellExtractionResults(cell_name='Cell', keep_capacitance_geometry=True)
        add_capacitances(kept)
        self.assertTrue(all(g is not None for g in geometries(kept)))

        dropped = CellExtractionResults(cell_name='Cell')
        add_capacitances(dropped)
        self.assertEqual([None] * 5, geometries(dropped))

    def test_summarize_distributes_the_capacitances_onto_the_nodes_of_the_resistor_network(self):
        # a wire W of 100 µm x 1 µm (DBU 1 nm) with its pin at the left end and a junction at the right end,
        # 2 µm beside it a wire V without resistor network (#211 §8)
        results = CellExtractionResults(cell_name='Cell', keep_capacitance_geometry=True)
        self.add_wire_network(results, 'W', 'met1', [(0, 500, 'W'), (100000, 500, '$1.met1')])
        results.add_overlap_cap(OverlapCap(key=OverlapKey(layer_top='met1', net_top='W',
                                                          layer_bot='VSUBS', net_bot='VSUBS'),
                                           cap_value=4.0, shielded_area=0.0, unshielded_area=0.0, tech_spec=None,
                                           area=kdb.Region(kdb.Box(0, 0, 100000, 1000))))
        results.add_sidewall_cap(SidewallCap(key=SidewallKey(layer='met1', net1='W', net2='V'),
                                             cap_value=2.0, distance=2.0, length=100.0, tech_spec=None,
                                             inside_edge=kdb.Edge(0, 1000, 100000, 1000),
                                             outside_edge=kdb.Edge(0, 3000, 100000, 3000)))
        results.add_sideoverlap_cap(SideOverlapCap(key=SideOverlapKey(layer_inside='met1', net_inside='W',
                                                                      layer_outside='VSUBS', net_outside='VSUBS'),
                                                   cap_value=1.0,
                                                   inside_edge=kdb.Edge(100000, 0, 0, 0),
                                                   outside_edge=kdb.Edge(100000, -500, 0, -500)))

        summary = results.summarize()

        # NOTE: half of the wire is nearer to each of its nodes (π model)
        expected = {NetCoupleKey('VSUBS', 'W'): 2.5,
                    NetCoupleKey('VSUBS', 'W.$1.met1'): 2.5,
                    NetCoupleKey('V', 'W'): 1.0,
                    NetCoupleKey('V', 'W.$1.met1'): 1.0}
        self.assertEqual(set(expected), set(summary.capacitances))
        for key, capacitance in expected.items():
            self.assertAlmostEqual(capacitance, summary.capacitances[key], places=12)


    def test_summarize_keeps_the_capacitance_between_each_pair_of_nets(self):
        # NOTE: the capacitances are distributed onto the nodes, but their sum per pair of nets is the same
        rng = random.Random(211)

        def box() -> kdb.Box:
            x, y = rng.randrange(0, 50000), rng.randrange(0, 50000)
            return kdb.Box(x, y, x + rng.randrange(100, 20000), y + rng.randrange(100, 20000))

        def edges() -> Tuple[kdb.Edge, kdb.Edge]:
            b = box()
            return kdb.Edge(b.left, b.bottom, b.right, b.bottom), kdb.Edge(b.left, b.top, b.right, b.top)

        layer_by_net = {'A': 'met1', 'B': 'met1', 'C': 'met2', 'D': 'met2'}
        results = CellExtractionResults(cell_name='Cell', keep_capacitance_geometry=True)
        for net_name in ('A', 'B', 'C'):  # NOTE: D has no resistor network
            self.add_wire_network(results, net_name, layer_by_net[net_name],
                                  [(rng.randrange(0, 70000), rng.randrange(0, 70000), f"$n{i}")
                                   for i in range(rng.randrange(1, 8))])
        for _ in range(100):
            net1, net2 = rng.sample(sorted(layer_by_net), 2)
            layer1, layer2 = layer_by_net[net1], layer_by_net[net2]
            area = kdb.Region(box()) + kdb.Region(box())
            results.add_overlap_cap(OverlapCap(key=OverlapKey(layer_top=layer2, net_top=net2,
                                                              layer_bot=layer1, net_bot=net1),
                                               cap_value=rng.uniform(0.001, 10.0),
                                               shielded_area=0.0, unshielded_area=0.0, tech_spec=None,
                                               area=area))
            edge1, edge2 = edges()
            results.add_sidewall_cap(SidewallCap(key=SidewallKey(layer=layer1, net1=net1, net2=net2),
                                                 cap_value=rng.uniform(0.001, 10.0), distance=1.0, length=1.0,
                                                 tech_spec=None, inside_edge=edge1, outside_edge=edge2))
            edge1, edge2 = edges()
            results.add_sideoverlap_cap(SideOverlapCap(key=SideOverlapKey(layer_inside=layer1, net_inside=net1,
                                                                          layer_outside=layer2, net_outside=net2),
                                                       cap_value=rng.uniform(0.001, 10.0),
                                                       inside_edge=edge1, outside_edge=edge2))

        distributed = results.summarize()
        lumped = dataclasses.replace(results, r_extraction_result=pex_result_pb2.RExtractionResult()).summarize()

        def net_of(node_name: str) -> str:
            return node_name.split('.')[0]

        distributed_by_nets: Dict[NetCoupleKey, float] = defaultdict(float)
        for key, capacitance in distributed.capacitances.items():
            distributed_by_nets[NetCoupleKey(net_of(key.net1), net_of(key.net2)).normed()] += capacitance

        self.assertGreater(len(distributed.capacitances), len(lumped.capacitances))
        self.assertEqual(set(lumped.capacitances), set(distributed_by_nets))
        for key, capacitance in lumped.capacitances.items():
            self.assertAlmostEqual(capacitance, distributed_by_nets[key], delta=1e-12 * capacitance)



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
    def add_wire_network(results: CellExtractionResults,
                         net_name: str,
                         layer_name: str,
                         nodes: List[Tuple[int, int, str]]):
        """
        The resistor network of a wire, each node joined to the one before

        :param nodes: (x, y, node name) of a pin (the first node) and wire junctions
        """
        K = r_network_pb2.RNode.Kind
        network = results.r_extraction_result.networks.add(net_name=net_name)
        for node_id, (x, y, node_name) in enumerate(nodes, start=1):
            node = network.nodes.add(node_id=node_id, node_name=node_name, layer_name=layer_name,
                                     node_kind=K.KIND_PIN if node_id == 1 else K.KIND_WIRE_JUNCTION)
            if node_id > 1:
                node.net_name = f"{net_name}.{node_name}"
            node.location.kind = location_pb2.Location.Kind.LOCATION_KIND_POINT
            node.location.point.x, node.location.point.y = x, y
            if node_id > 1:
                element = network.elements.add(resistance=10.0)
                element.node_a.node_id = node_id - 1
                element.node_b.node_id = node_id


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
