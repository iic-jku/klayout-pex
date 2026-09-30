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

from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from typing import *

from .types import NetName, LayerName, CellName
from ..klayout.lvsdb_extractor import unique_name
from ..log import debug, error

import klayout_pex_protobuf.kpex.r.r_network_pb2 as r_network_pb2
import klayout_pex_protobuf.kpex.result.pex_result_pb2 as pex_result_pb2
import klayout_pex_protobuf.kpex.tech.process_parasitics_pb2 as process_parasitics_pb2


@dataclass
class NodeRegion:
    layer_name: LayerName
    net_name: NetName
    cap_to_gnd: float
    perimeter: float
    area: float


@dataclass(frozen=True)
class SidewallKey:
    layer: LayerName
    net1: NetName
    net2: NetName


@dataclass
class SidewallCap:  # see Magic EdgeCap, extractInt.c L444
    key: SidewallKey
    cap_value: float   # femto farad
    distance: float    # distance in µm
    length: float      # length in µm
    tech_spec: process_parasitics_pb2.CapacitanceInfo.SidewallCapacitance


@dataclass(frozen=True)
class OverlapKey:
    layer_top: LayerName
    net_top: NetName
    layer_bot: LayerName
    net_bot: NetName


@dataclass
class OverlapCap:
    key: OverlapKey
    cap_value: float  # femto farad
    shielded_area: float  # in µm^2
    unshielded_area: float  # in µm^2
    tech_spec: process_parasitics_pb2.CapacitanceInfo.OverlapCapacitance


@dataclass(frozen=True)
class SideOverlapKey:
    layer_inside: LayerName
    net_inside: NetName
    layer_outside: LayerName
    net_outside: NetName

    def __repr__(self) -> str:
        return f"{self.layer_inside}({self.net_inside})-"\
               f"{self.layer_outside}({self.net_outside})"

    def __post_init__(self):
        if self.layer_inside is None:
            raise ValueError("layer_inside cannot be None")
        if self.net_inside is None:
            raise ValueError("net_inside cannot be None")
        if self.layer_outside is None:
            raise ValueError("layer_outside cannot be None")
        if self.net_outside is None:
            raise ValueError("net_outside cannot be None")


@dataclass
class SideOverlapCap:
    key: SideOverlapKey
    cap_value: float  # femto farad

    def __str__(self) -> str:
        return f"(Side Overlap): {self.key} = {round(self.cap_value, 6)}fF"


@dataclass(frozen=True)
class NetCoupleKey:
    net1: NetName
    net2: NetName

    def __repr__(self) -> str:
        return f"{self.net1}-{self.net2}"

    def __lt__(self, other) -> bool:
        if not isinstance(other, NetCoupleKey):
            raise NotImplemented
        return (self.net1.casefold(), self.net2.casefold()) < (other.net1.casefold(), other.net2.casefold())

    def __post_init__(self):
        if self.net1 is None:
            raise ValueError("net1 cannot be None")
        if self.net2 is None:
            raise ValueError("net2 cannot be None")

    # NOTE: we norm net names alphabetically
    def normed(self) -> NetCoupleKey:
        if self.net1 < self.net2:
            return self
        else:
            return NetCoupleKey(self.net2, self.net1)


def parallel_resistance(r1: float, r2: float) -> float:
    if r1 == 0.0 or r2 == 0.0:
        return 0.0
    return r1 * r2 / (r1 + r2)


def add_resistance(resistance_table: Dict[NetCoupleKey, float],
                   key: NetCoupleKey,
                   resistance: float):
    # NOTE: resistances between the same pair of nodes are in parallel
    #       (unlike capacitances, they must not be summed up)
    if key in resistance_table:
        resistance_table[key] = parallel_resistance(resistance_table[key], resistance)
    else:
        resistance_table[key] = resistance


@dataclass(frozen=True, order=True)
class DeviceTerminalKey:
    device_id: int
    terminal_id: int


# NOTE: ties the port of a label to the node of another label it's on (#211 §11),
#       not 0 Ω, which a simulator can't solve for
LABEL_TIE_RESISTANCE = 1e-3  # Ω


@dataclass
class ExtractionSummary:
    capacitances: Dict[NetCoupleKey, float]
    resistances: Dict[NetCoupleKey, float]

    # node of the resistor network each device terminal connects to
    device_terminal_nodes: Dict[DeviceTerminalKey, NetName] = field(default_factory=dict)

    # the ports of each net of several labels, a node per label (#211 §11)
    label_ports: Dict[NetName, List[NetName]] = field(default_factory=dict)

    @classmethod
    def merged(cls, summaries: List[ExtractionSummary]) -> ExtractionSummary:
        merged_capacitances = defaultdict(float)
        merged_resistances: Dict[NetCoupleKey, float] = {}
        merged_device_terminal_nodes: Dict[DeviceTerminalKey, NetName] = {}
        merged_label_ports: Dict[NetName, List[NetName]] = {}
        for s in summaries:
            for couple_key, cap in s.capacitances.items():
                merged_capacitances[couple_key.normed()] += cap
            for couple_key, res in s.resistances.items():
                add_resistance(merged_resistances, couple_key.normed(), res)
            merged_device_terminal_nodes.update(s.device_terminal_nodes)
            merged_label_ports.update(s.label_ports)
        return ExtractionSummary(capacitances=merged_capacitances,
                                 resistances=merged_resistances,
                                 device_terminal_nodes=merged_device_terminal_nodes,
                                 label_ports=merged_label_ports)


@dataclass
class NetworkNodeNames:
    """
    The names of the netlist nodes of a resistor network
    """
    by_node_id: Dict[int, NetName]

    # the IDs of the nodes of each device terminal (its ports)
    terminal_node_ids: Dict[DeviceTerminalKey, List[int]]

    @classmethod
    def from_network(cls,
                     network: r_network_pb2.RNetwork,
                     port_names: Optional[Dict[str, NetName]] = None) -> NetworkNodeNames:
        """
        Nodes that are one electrical node get one name: the ports of a device terminal,
        and nodes joined by an element without resistance (which a simulator can't solve for).

        :param port_names: the port name of each label, for a net of several labels
        """
        K = r_network_pb2.RNode.Kind

        pin_labels = {n.node_name for n in network.nodes if n.node_kind == K.KIND_PIN}

        def default_name(node: r_network_pb2.RNode) -> NetName:
            if node.node_kind == K.KIND_PIN:
                # NOTE: the pins of a net with one label are the node of the net,
                #       which is named after the label, unless other nets are too (e.g. vss$1, #211 §10)
                if len(pin_labels) == 1:
                    return network.net_name
                # NOTE: if we have an electrical short between 2 pins A and B
                #       and a parasitic resistance between the two,
                #       KLayout will call the net of both pins "A,B"
                #       but we really want the pin as the node, a port of its own (#211 §11)
                return (port_names or {}).get(node.node_name, node.node_name)
            if not node.net_name or ',' in node.net_name:
                # NOTE: network prefix, as node name is only unique per network
                return f"{network.net_name}.{node.node_name}"
            return node.net_name

        # NOTE: ordered by name, as the node IDs differ from run to run
        nodes = sorted(network.nodes, key=lambda n: n.node_name)

        terminal_node_ids: Dict[DeviceTerminalKey, List[int]] = defaultdict(list)
        for n in nodes:
            if n.node_kind == K.KIND_DEVICE_TERMINAL:
                key = DeviceTerminalKey(n.device_terminal.device_id, n.device_terminal.terminal_id)
                terminal_node_ids[key].append(n.node_id)

        # groups of nodes that are one electrical node (union-find, by node ID)
        parent: Dict[int, int] = {n.node_id: n.node_id for n in nodes}

        def find(node_id: int) -> int:
            while parent[node_id] != node_id:
                parent[node_id] = parent[parent[node_id]]
                node_id = parent[node_id]
            return node_id

        def union(node_id_a: int, node_id_b: int):
            parent[find(node_id_a)] = find(node_id_b)

        for node_ids in terminal_node_ids.values():
            for node_id in node_ids[1:]:
                union(node_id, node_ids[0])
        for element in network.elements:
            if element.resistance == 0.0:
                union(element.node_a.node_id, element.node_b.node_id)

        groups: Dict[int, List[r_network_pb2.RNode]] = defaultdict(list)  # by root node ID
        for n in nodes:
            groups[find(n.node_id)].append(n)

        def has_pin(root: int) -> bool:
            return any(n.node_kind == K.KIND_PIN for n in groups[root])

        def group_name(root: int) -> NetName:
            pin_names = sorted({default_name(n) for n in groups[root] if n.node_kind == K.KIND_PIN})
            if network.net_name in pin_names:
                return network.net_name
            if pin_names:
                return pin_names[0]
            # NOTE: preferably the name of a device terminal's port
            ports = [n for n in groups[root] if n.node_kind == K.KIND_DEVICE_TERMINAL]
            return default_name((ports or groups[root])[0])

        name_by_root: Dict[int, NetName] = {root: group_name(root) for root in groups}

        # NOTE: one node carries the name of the net, so that what stays connected to the net
        #       (its capacitances, device terminals without a port, e.g. a MOS bulk) is on the resistor network:
        #       a pin of that name, otherwise the first device terminal, otherwise the first node (but a pin)
        if network.net_name not in name_by_root.values():
            candidate_roots = [find(terminal_node_ids[key][0]) for key in sorted(terminal_node_ids)] + \
                              [find(n.node_id) for n in nodes]
            root = next((r for r in candidate_roots if not has_pin(r)), None)
            if root is not None:
                name_by_root[root] = network.net_name

        return cls(by_node_id={n.node_id: name_by_root[find(n.node_id)] for n in nodes},
                   terminal_node_ids=terminal_node_ids)


@dataclass
class CellExtractionResults:
    cell_name: CellName

    overlap_table: Dict[OverlapKey, List[OverlapCap]] = field(default_factory=lambda: defaultdict(list))
    sidewall_table: Dict[SidewallKey, List[SidewallCap]] = field(default_factory=lambda: defaultdict(list))
    sideoverlap_table: Dict[SideOverlapKey, List[SideOverlapCap]] = field(default_factory=lambda: defaultdict(list))

    r_extraction_result: pex_result_pb2.RExtractionResult = field(default_factory=lambda: pex_result_pb2.RExtractionResult())

    def add_overlap_cap(self, cap: OverlapCap):
        self.overlap_table[cap.key].append(cap)

    def add_sidewall_cap(self, cap: SidewallCap):
        self.sidewall_table[cap.key].append(cap)

    def add_sideoverlap_cap(self, cap: SideOverlapCap):
        self.sideoverlap_table[cap.key].append(cap)

    def label_port_names(self) -> Dict[NetName, Dict[str, NetName]]:
        """
        The port names of the nets of several labels, by label

        NOTE: KLayout names a net of several labels after all of them (e.g. "A,B"),
              but each label is a port of its own (#211 §11), named after the label,
              unless a net or another port is (e.g. A$1, like KLayout's SPICE writer)
        """
        K = r_network_pb2.RNode.Kind
        networks = sorted(self.r_extraction_result.networks, key=lambda n: n.net_name)
        taken_names: Set[NetName] = {network.net_name for network in networks}
        port_names_by_net: Dict[NetName, Dict[str, NetName]] = {}
        for network in networks:
            labels = sorted({n.node_name for n in network.nodes if n.node_kind == K.KIND_PIN})
            if len(labels) < 2:
                continue
            port_names: Dict[str, NetName] = {}
            for label in labels:
                port_names[label] = unique_name(label, taken_names)
                taken_names.add(port_names[label])
            port_names_by_net[network.net_name] = port_names
        return port_names_by_net

    def summarize(self) -> ExtractionSummary:
        normalized_overlap_table: Dict[NetCoupleKey, float] = defaultdict(float)
        for key, entries in self.overlap_table.items():
            normalized_key = NetCoupleKey(key.net_bot, key.net_top).normed()
            normalized_overlap_table[normalized_key] += sum((e.cap_value for e in entries))
        overlap_summary = ExtractionSummary(capacitances=normalized_overlap_table,
                                            resistances={})

        normalized_sidewall_table: Dict[NetCoupleKey, float] = defaultdict(float)
        for key, entries in self.sidewall_table.items():
            normalized_key = NetCoupleKey(key.net1, key.net2).normed()
            normalized_sidewall_table[normalized_key] += sum((e.cap_value for e in entries))
        sidewall_summary = ExtractionSummary(capacitances=normalized_sidewall_table,
                                             resistances={})

        normalized_sideoverlap_table: Dict[NetCoupleKey, float] = defaultdict(float)
        for key, entries in self.sideoverlap_table.items():
            normalized_key = NetCoupleKey(key.net_inside, key.net_outside).normed()
            normalized_sideoverlap_table[normalized_key] += sum((e.cap_value for e in entries))
        sideoverlap_summary = ExtractionSummary(capacitances=normalized_sideoverlap_table,
                                                resistances={})

        normalized_resistance_table: Dict[NetCoupleKey, float] = {}
        device_terminal_nodes: Dict[DeviceTerminalKey, NetName] = {}

        port_names_by_net = self.label_port_names()

        for network in self.r_extraction_result.networks:
            port_names = port_names_by_net.get(network.net_name, {})
            node_names = NetworkNodeNames.from_network(network, port_names)
            for terminal_key, node_ids in node_names.terminal_node_ids.items():
                device_terminal_nodes[terminal_key] = node_names.by_node_id[node_ids[0]]

            # NOTE: the port of a label on the node of another label (e.g. both on one via) is tied to it
            ties = {NetCoupleKey(port_names[n.node_name], node_names.by_node_id[n.node_id]).normed()
                    for n in network.nodes
                    if n.node_kind == r_network_pb2.RNode.Kind.KIND_PIN
                    and n.node_name in port_names
                    and port_names[n.node_name] != node_names.by_node_id[n.node_id]}
            for key in sorted(ties):
                add_resistance(normalized_resistance_table, key, LABEL_TIE_RESISTANCE)

            for element in network.elements:
                resistance = element.resistance
                normalized_key = NetCoupleKey(node_names.by_node_id[element.node_a.node_id],
                                              node_names.by_node_id[element.node_b.node_id]).normed()
                # NOTE: different nodes can have the same name, e.g. pins with the same label,
                #       which are one node in the netlist, so their elements are in parallel,
                #       and an element between two of them is shorted
                if normalized_key.net1 == normalized_key.net2:
                    debug(f"Skipping resistor between nodes of the same name {normalized_key.net1} "
                          f"with value {'%.12g' % resistance}")
                    continue
                add_resistance(normalized_resistance_table, normalized_key, resistance)

        resistance_summary = ExtractionSummary(capacitances={},
                                               resistances=normalized_resistance_table,
                                               device_terminal_nodes=device_terminal_nodes,
                                               label_ports={net_name: [port_names[label] for label in sorted(port_names)]
                                                            for net_name, port_names in port_names_by_net.items()})

        return ExtractionSummary.merged([
            overlap_summary, sidewall_summary, sideoverlap_summary,
            resistance_summary
        ])


@dataclass
class ExtractionResults:
    cell_extraction_results: Dict[CellName, CellExtractionResults] = field(default_factory=dict)

    def summarize(self) -> ExtractionSummary:
        subsummaries = [s.summarize() for s in self.cell_extraction_results.values()]
        return ExtractionSummary.merged(subsummaries)
