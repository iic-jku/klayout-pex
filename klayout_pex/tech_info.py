#! /usr/bin/env python3
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

from __future__ import annotations  # allow class type hints within same class
from typing import *
from functools import cached_property
import google.protobuf.json_format

from .util.multiple_choice import MultipleChoicePattern
import klayout_pex_protobuf.tech_pb2 as tech_pb2
import klayout_pex_protobuf.process_stack_pb2 as process_stack_pb2
import klayout_pex_protobuf.process_parasitics_pb2 as process_parasitics_pb2

class TechInfo:
    """Helper class for Protocol Buffer tech_pb2.Technology"""

    GDSPair = Tuple[int, int]

    @staticmethod
    def parse_tech_def(jsonpb_path: str) -> tech_pb2.Technology:
        with open(jsonpb_path, 'r') as f:
            contents = f.read()
            tech = google.protobuf.json_format.Parse(contents, tech_pb2.Technology())
            return tech

    @classmethod
    def from_json(cls,
                  jsonpb_path: str,
                  dielectric_filter: Optional[MultipleChoicePattern]) -> TechInfo:
        tech = cls.parse_tech_def(jsonpb_path=jsonpb_path)
        return TechInfo(tech=tech,
                        dielectric_filter=dielectric_filter)

    def __init__(self,
                 tech: tech_pb2.Technology,
                 dielectric_filter: Optional[MultipleChoicePattern]):
        self.tech = tech
        self.dielectric_filter = dielectric_filter or MultipleChoicePattern(pattern='all')

    @cached_property
    def gds_pair_for_computed_layer_name(self) -> Dict[str, GDSPair]:
        return {lyr.layer_info.name: (lyr.layer_info.gds_layer, lyr.layer_info.gds_datatype)
                for lyr in self.tech.lvs_computed_layers}

    @cached_property
    def computed_layer_info_by_name(self) -> Dict[str, tech_pb2.ComputedLayerInfo]:
        return {lyr.layer_info.name: lyr for lyr in self.tech.lvs_computed_layers}

    @cached_property
    def computed_layer_info_by_gds_pair(self) -> Dict[GDSPair, tech_pb2.ComputedLayerInfo]:
        return {
            (lyr.layer_info.gds_layer, lyr.layer_info.gds_datatype): lyr
            for lyr in self.tech.lvs_computed_layers
        }

    @cached_property
    def canonical_layer_name_by_gds_pair(self) -> Dict[GDSPair, str]:
        return {
            (lyr.layer_info.gds_layer, lyr.layer_info.gds_datatype): lyr.original_layer_name
            for lyr in self.tech.lvs_computed_layers
        }

    @cached_property
    def layer_info_by_name(self) -> Dict[str, tech_pb2.LayerInfo]:
        return {lyr.name: lyr for lyr in self.tech.layers}

    @cached_property
    def gds_pair_for_layer_name(self) -> Dict[str, GDSPair]:
        return {lyr.name: (lyr.gds_layer, lyr.gds_datatype) for lyr in self.tech.layers}

    @cached_property
    def layer_info_by_gds_pair(self) -> Dict[GDSPair, tech_pb2.LayerInfo]:
        return {(lyr.gds_layer, lyr.gds_datatype): lyr for lyr in self.tech.layers}

    @cached_property
    def process_stack_layer_by_name(self) -> Dict[str, process_stack_pb2.ProcessStackInfo.LayerInfo]:
        return {lyr.name: lyr for lyr in self.tech.process_stack.layers}

    @cached_property
    def process_stack_layer_by_gds_pair(self) -> Dict[GDSPair, process_stack_pb2.ProcessStackInfo.LayerInfo]:
        return {
            (lyr.gds_layer, lyr.gds_datatype): self.process_stack_layer_by_name[lyr.name]
            for lyr in self.tech.process_stack.layers
        }

    @cached_property
    def process_substrate_layer(self) -> process_stack_pb2.ProcessStackInfo.LayerInfo:
        return list(
            filter(lambda lyr: lyr.layer_type is process_stack_pb2.ProcessStackInfo.LAYER_TYPE_SUBSTRATE,
                   self.tech.process_stack.layers)
        )[0]

    @cached_property
    def process_diffusion_layers(self) -> List[process_stack_pb2.ProcessStackInfo.LayerInfo]:
        return list(
            filter(lambda lyr: lyr.layer_type is process_stack_pb2.ProcessStackInfo.LAYER_TYPE_DIFFUSION,
                   self.tech.process_stack.layers)
        )

    @cached_property
    def gate_poly_layer(self) -> process_stack_pb2.ProcessStackInfo.LayerInfo:
        return self.process_metal_layers[0]

    @cached_property
    def field_oxide_layer(self) -> process_stack_pb2.ProcessStackInfo.LayerInfo:
        return list(
            filter(lambda lyr: lyr.layer_type is process_stack_pb2.ProcessStackInfo.LAYER_TYPE_FIELD_OXIDE,
                   self.tech.process_stack.layers)
        )[0]

    @cached_property
    def process_metal_layers(self) -> List[process_stack_pb2.ProcessStackInfo.LayerInfo]:
        return list(
            filter(lambda lyr: lyr.layer_type == process_stack_pb2.ProcessStackInfo.LAYER_TYPE_METAL,
                   self.tech.process_stack.layers)
        )

    @cached_property
    def filtered_dielectric_layers(self) -> List[process_stack_pb2.ProcessStackInfo.LayerInfo]:
        layers = []
        for pl in self.tech.process_stack.layers:
            match pl.layer_type:
                case process_stack_pb2.ProcessStackInfo.LAYER_TYPE_SIMPLE_DIELECTRIC | \
                     process_stack_pb2.ProcessStackInfo.LAYER_TYPE_CONFORMAL_DIELECTRIC | \
                     process_stack_pb2.ProcessStackInfo.LAYER_TYPE_SIDEWALL_DIELECTRIC:
                    if self.dielectric_filter.is_included(pl.name):
                        layers.append(pl)
        return layers

    @cached_property
    def dielectric_by_name(self) -> Dict[str, float]:
        diel_by_name = {}
        for pl in self.filtered_dielectric_layers:
            match pl.layer_type:
                case process_stack_pb2.ProcessStackInfo.LAYER_TYPE_SIMPLE_DIELECTRIC:
                    diel_by_name[pl.name] = pl.simple_dielectric_layer.dielectric_k
                case process_stack_pb2.ProcessStackInfo.LAYER_TYPE_CONFORMAL_DIELECTRIC:
                    diel_by_name[pl.name] = pl.conformal_dielectric_layer.dielectric_k
                case process_stack_pb2.ProcessStackInfo.LAYER_TYPE_SIDEWALL_DIELECTRIC:
                    diel_by_name[pl.name] = pl.sidewall_dielectric_layer.dielectric_k
        return diel_by_name

    def sidewall_dielectric_layer(self, layer_name: str) -> Optional[process_stack_pb2.ProcessStackInfo.LayerInfo]:
        found_layers: List[process_stack_pb2.ProcessStackInfo.LayerInfo] = []
        for lyr in self.filtered_dielectric_layers:
            match lyr.layer_type:
                case process_stack_pb2.ProcessStackInfo.LAYER_TYPE_SIDEWALL_DIELECTRIC:
                    if lyr.sidewall_dielectric_layer.reference == layer_name:
                        found_layers.append(lyr)
                case process_stack_pb2.ProcessStackInfo.LAYER_TYPE_CONFORMAL_DIELECTRIC:
                    if lyr.conformal_dielectric_layer.reference == layer_name:
                        found_layers.append(lyr)
                case _:
                    continue

        if len(found_layers) == 0:
            return None
        if len(found_layers) >= 2:
            raise Exception(f"found multiple sidewall dielectric layers for {layer_name}")
        return found_layers[0]

    def simple_dielectric_above_metal(self, layer_name: str) -> Tuple[Optional[process_stack_pb2.ProcessStackInfo.LayerInfo], float]:
        """
        Returns a tuple of the dielectric layer and it's (maximum) height.
        Maximum would be the case where no metal and other dielectrics are present.
        """
        found_layer: Optional[process_stack_pb2.ProcessStackInfo.LayerInfo] = None
        diel_lyr: Optional[process_stack_pb2.ProcessStackInfo.LayerInfo] = None
        for lyr in self.tech.process_stack.layers:
            if lyr.name == layer_name:
                found_layer = lyr
            elif found_layer:
                if not diel_lyr and lyr.layer_type == process_stack_pb2.ProcessStackInfo.LAYER_TYPE_SIMPLE_DIELECTRIC:
                    if not self.dielectric_filter.is_included(lyr.name):
                        return None, 0.0
                    diel_lyr = lyr
                # search for next metal or end of stack
                if lyr.layer_type == process_stack_pb2.ProcessStackInfo.LAYER_TYPE_METAL:
                    return diel_lyr, lyr.metal_layer.height - found_layer.metal_layer.height
        return diel_lyr, 5.0   # air TODO

    @cached_property
    def substrate_cap_by_layer_name(self) -> Dict[str, process_parasitics_pb2.CapacitanceInfo.SubstrateCapacitance]:
        return {sc.layer_name: sc for sc in self.tech.process_parasitics.capacitance.substrates}

    @cached_property
    def overlap_cap_by_layer_names(self) -> Dict[str, Dict[str, process_parasitics_pb2.CapacitanceInfo.OverlapCapacitance]]:
        """
        usage: dict[top_layer_name][bottom_layer_name]
        """

        def convert_substrate_to_overlap_cap(sc: process_parasitics_pb2.CapacitanceInfo.SubstrateCapacitance) \
            -> process_parasitics_pb2.CapacitanceInfo.OverlapCapacitance:
            oc = process_parasitics_pb2.CapacitanceInfo.OverlapCapacitance()
            oc.top_layer_name = sc.layer_name
            oc.bottom_layer_name = self.internal_substrate_layer_name
            oc.capacitance = sc.area_capacitance
            return oc

        d = {
            ln: {
                self.internal_substrate_layer_name: convert_substrate_to_overlap_cap(sc)
            } for ln, sc in self.substrate_cap_by_layer_name.items()
        }

        d2 = {
            oc.top_layer_name: {
                oc_bot.bottom_layer_name: oc_bot
                for oc_bot in self.tech.process_parasitics.capacitance.overlaps if oc_bot.top_layer_name == oc.top_layer_name
            }
            for oc in self.tech.process_parasitics.capacitance.overlaps
        }

        for k1, ve in d2.items():
            for k2, v in ve.items():
                if k1 not in d:
                    d[k1] = {k2: v}
                else:
                    d[k1][k2] = v
        return d

    @cached_property
    def sidewall_cap_by_layer_name(self) -> Dict[str, process_parasitics_pb2.CapacitanceInfo.SidewallCapacitance]:
        return {sc.layer_name: sc for sc in self.tech.process_parasitics.capacitance.sidewalls}

    @classmethod
    @property
    def internal_substrate_layer_name(cls) -> str:
        return 'VSUBS'

    @cached_property
    def side_overlap_cap_by_layer_names(self) -> Dict[str, Dict[str, process_parasitics_pb2.CapacitanceInfo.SideOverlapCapacitance]]:
        """
        usage: dict[in_layer_name][out_layer_name]
        """

        def convert_substrate_to_side_overlap_cap(sc: process_parasitics_pb2.CapacitanceInfo.SubstrateCapacitance) \
            -> process_parasitics_pb2.CapacitanceInfo.SideOverlapCapacitance:
            soc = process_parasitics_pb2.CapacitanceInfo.SideOverlapCapacitance()
            soc.in_layer_name = sc.layer_name
            soc.out_layer_name = self.internal_substrate_layer_name
            soc.capacitance = sc.perimeter_capacitance
            return soc

        d = {
            ln: {
                self.internal_substrate_layer_name: convert_substrate_to_side_overlap_cap(sc)
            } for ln, sc in self.substrate_cap_by_layer_name.items()
        }

        d2 = {
            oc.in_layer_name: {
                oc_bot.out_layer_name: oc_bot
                for oc_bot in self.tech.process_parasitics.capacitance.sideoverlaps if oc_bot.in_layer_name == oc.in_layer_name
            }
            for oc in self.tech.process_parasitics.capacitance.sideoverlaps
        }

        for k1, ve in d2.items():
            for k2, v in ve.items():
                d[k1][k2] = v

        return d
