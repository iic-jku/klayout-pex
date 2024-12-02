from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from typing import *

import process_parasitics_pb2


NetName = str
LayerName = str
CellName = str


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

    # NOTE: we norm net names alphabetically
    def normed(self) -> NetCoupleKey:
        if self.net1 < self.net2:
            return self
        else:
            return NetCoupleKey(self.net2, self.net1)


@dataclass
class ExtractionSummary:
    capacitances: Dict[NetCoupleKey, float]

    @classmethod
    def merged(cls, summaries: List[ExtractionSummary]) -> ExtractionSummary:
        merged_capacitances = defaultdict(float)
        for s in summaries:
            for couple_key, cap in s.capacitances.items():
                merged_capacitances[couple_key.normed()] += cap
        return ExtractionSummary(merged_capacitances)


@dataclass
class CellExtractionResults:
    cell_name: CellName

    overlap_coupling: Dict[OverlapKey, OverlapCap] = field(default_factory=dict)
    sidewall_table: Dict[SidewallKey, SidewallCap] = field(default_factory=dict)
    sideoverlap_table: Dict[SideOverlapKey, SideOverlapCap] = field(default_factory=dict)

    def summarize(self) -> ExtractionSummary:
        overlap_summary = ExtractionSummary({
            NetCoupleKey(key.net_top, key.net_bot): cap.cap_value
            for key, cap in self.overlap_coupling.items()
        })

        sidewall_summary = ExtractionSummary({
            NetCoupleKey(key.net1, key.net2): cap.cap_value
            for key, cap in self.sidewall_table.items()
        })

        sideoverlap_summary = ExtractionSummary({
            NetCoupleKey(key.net_inside, key.net_outside): cap.cap_value
            for key, cap in self.sideoverlap_table.items()
        })

        return ExtractionSummary.merged([
            overlap_summary, sidewall_summary, sideoverlap_summary
        ])


@dataclass
class ExtractionResults:
    cell_extraction_results: Dict[CellName, CellExtractionResults] = field(default_factory=dict)

    def summarize(self) -> ExtractionSummary:
        subsummaries = [s.summarize() for s in self.cell_extraction_results.values()]
        return ExtractionSummary.merged(subsummaries)