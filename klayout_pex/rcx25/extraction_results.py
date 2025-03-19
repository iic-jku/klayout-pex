#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/martinjankoehler/klayout-pex).
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

from .r.resistor_network import MultiLayerResistanceNetwork, ViaJunction, DeviceTerminal
from .types import NetName, LayerName, CellName
import klayout_pex_protobuf.process_parasitics_pb2 as process_parasitics_pb2
from ..log import error


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


@dataclass
class ExtractionSummary:
    capacitances: Dict[NetCoupleKey, float]
    resistances: Dict[NetCoupleKey, float]

    @classmethod
    def merged(cls, summaries: List[ExtractionSummary]) -> ExtractionSummary:
        merged_capacitances = defaultdict(float)
        merged_resistances = defaultdict(float)
        for s in summaries:
            for couple_key, cap in s.capacitances.items():
                merged_capacitances[couple_key.normed()] += cap
            for couple_key, res in s.resistances.items():
                merged_resistances[couple_key.normed()] += res
        return ExtractionSummary(capacitances=merged_capacitances,
                                 resistances=merged_resistances)


@dataclass
class CellExtractionResults:
    cell_name: CellName

    overlap_table: Dict[OverlapKey, List[OverlapCap]] = field(default_factory=lambda: defaultdict(list))
    sidewall_table: Dict[SidewallKey, List[SidewallCap]] = field(default_factory=lambda: defaultdict(list))
    sideoverlap_table: Dict[SideOverlapKey, List[SideOverlapCap]] = field(default_factory=lambda: defaultdict(list))

    resistor_network: MultiLayerResistanceNetwork = \
        field(default_factory=lambda: MultiLayerResistanceNetwork(resistor_networks_by_layer={}, via_resistors=[]))

    def add_overlap_cap(self, cap: OverlapCap):
        self.overlap_table[cap.key].append(cap)

    def add_sidewall_cap(self, cap: SidewallCap):
        self.sidewall_table[cap.key].append(cap)

    def add_sideoverlap_cap(self, cap: SideOverlapCap):
        self.sideoverlap_table[cap.key].append(cap)

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

        normalized_resistance_table: Dict[NetCoupleKey, float] = defaultdict(float)
        for via_resistor in self.resistor_network.via_resistors:
            key1: str = ''
            match via_resistor.bottom:
                case None:
                    key1 = '__UNKNOWN__'
                case ViaJunction():
                    if via_resistor.bottom.network is None: # TODO: happened for ptap cell (VSS)!
                        error(f"Bottom net is None: {via_resistor}")
                        continue
                    key1 = via_resistor.bottom.network.node_names[via_resistor.bottom.node_id]
                case DeviceTerminal():
                    key1 = via_resistor.bottom.device_terminal.net_name
                case _:
                    raise NotImplementedError("unexpected type")
            if via_resistor.top.network is None:
                error(f"Top net is None: {via_resistor}")
                continue
            key2 = via_resistor.top.network.node_names[via_resistor.top.node_id]
            normalized_key = NetCoupleKey(key1, key2).normed()
            normalized_resistance_table[normalized_key] += via_resistor.resistance
        for layer_name, networks in self.resistor_network.resistor_networks_by_layer.items():
            for network in networks.networks:
                visited_resistors: Set[Conductance] = set()
                for node_id, resistors in network.node_to_s.items():
                    node_name = network.node_names[node_id]
                    for conductance, other_node_id in resistors:
                        if conductance in visited_resistors:
                            continue  # we don't want to add it twice, only once per direction!
                        visited_resistors.add(conductance)

                        other_node_name = network.node_names[other_node_id]
                        ohm = networks.layer_sheet_resistance / 1000.0 / conductance.cond
                        normalized_key = NetCoupleKey(node_name, other_node_name).normed()
                        normalized_resistance_table[normalized_key] += ohm

        resistance_summary = ExtractionSummary(capacitances={},
                                                resistances=normalized_resistance_table)

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