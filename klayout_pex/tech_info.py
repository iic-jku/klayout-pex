#! /usr/bin/env python3
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

from __future__ import annotations  # allow class type hints within same class
from typing import *
from functools import cached_property
import google.protobuf.json_format

from .util.multiple_choice import MultipleChoicePattern
from .log import (
    warning
)

import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2
import klayout_pex_protobuf.kpex.tech.process_stack_pb2 as process_stack_pb2
import klayout_pex_protobuf.kpex.tech.process_parasitics_pb2 as process_parasitics_pb2

class TechInfo:
    """Helper class for Protocol Buffer tech_pb2.Technology"""

    LVSLayerName = str
    CanonicalLayerName = str
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
    def gds_pair_for_computed_layer_name(self) -> Dict[LVSLayerName, GDSPair]:
        return {lyr.layer_info.name: (lyr.layer_info.drw_gds_pair.layer, lyr.layer_info.drw_gds_pair.datatype)
                for lyr in self.tech.lvs_computed_layers}

    @cached_property
    def computed_layer_info_by_name(self) -> Dict[LVSLayerName, tech_pb2.ComputedLayerInfo]:
        return {lyr.layer_info.name: lyr for lyr in self.tech.lvs_computed_layers}

    @cached_property
    def computed_layer_info_by_gds_pair(self) -> Dict[GDSPair, tech_pb2.ComputedLayerInfo]:
        return {
            (lyr.layer_info.drw_gds_pair.layer, lyr.layer_info.drw_gds_pair.datatype): lyr
            for lyr in self.tech.lvs_computed_layers
        }

    @cached_property
    def canonical_layer_name_by_gds_pair(self) -> Dict[GDSPair, CanonicalLayerName]:
        return {
            (lyr.layer_info.drw_gds_pair.layer, lyr.layer_info.drw_gds_pair.datatype): lyr.original_layer_name
            for lyr in self.tech.lvs_computed_layers
        }

    @cached_property
    def layer_info_by_name(self) -> Dict[CanonicalLayerName, tech_pb2.LayerInfo]:
        return {lyr.name: lyr for lyr in self.tech.layers}

    @cached_property
    def pin_layer_mapping_for_drw_gds_pair(self) -> Dict[GDSPair, tech_pb2.PinLayerMapping]:
        return {
            (m.drw_gds_layer, m.drw_gds_datatype): (m.pin_gds_layer, m.pin_gds_datatype)
            for m in self.tech.pin_layer_mappings
        }

    @cached_property
    def gds_pair_for_layer_name(self) -> Dict[CanonicalLayerName, GDSPair]:
        return {lyr.name: (lyr.drw_gds_pair.layer, lyr.drw_gds_pair.datatype) for lyr in self.tech.layers}

    @cached_property
    def layer_info_by_gds_pair(self) -> Dict[GDSPair, tech_pb2.LayerInfo]:
        return {(lyr.drw_gds_pair.layer, lyr.drw_gds_pair.datatype): lyr for lyr in self.tech.layers}

    @cached_property
    def process_stack_layer_by_name(self) -> Dict[LVSLayerName, process_stack_pb2.ProcessStackInfo.LayerInfo]:
        return {lyr.name: lyr for lyr in self.tech.process_stack.layers}

    @cached_property
    def process_stack_layer_by_gds_pair(self) -> Dict[GDSPair, process_stack_pb2.ProcessStackInfo.LayerInfo]:
        return {
            (lyr.drw_gds_pair.layer, lyr.drw_gds_pair.datatype): self.process_stack_layer_by_name[lyr.name]
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
                    return diel_lyr, lyr.metal_layer.z - found_layer.metal_layer.z
        return diel_lyr, 5.0   # air TODO

    @cached_property
    def contact_above_metal_layer_name(self) -> Dict[str, process_stack_pb2.ProcessStackInfo.Contact]:
        d = {}
        for lyr in self.process_metal_layers:
            contact = lyr.metal_layer.contact_above
            via_gds_pair = self.gds_pair(contact)
            canonical_via_name = self.canonical_layer_name_by_gds_pair[via_gds_pair]
            d[lyr.name] = canonical_via_name
        return d

    @cached_property
    def contact_by_device_lvs_layer_name(self) -> Dict[str, process_stack_pb2.ProcessStackInfo.Contact]:
        d = {}
        LT = process_stack_pb2.ProcessStackInfo.LayerType
        for lyr in self.tech.process_stack.layers:
            match lyr.layer_type:
                case LT.LAYER_TYPE_NWELL:
                    d[lyr.name] = lyr.nwell_layer.contact_above

                case LT.LAYER_TYPE_DIFFUSION:  # nsdm or psdm
                    d[lyr.name] = lyr.diffusion_layer.contact_above
        return d

    @cached_property
    def contact_by_contact_lvs_layer_name(self) -> Dict[str, process_stack_pb2.ProcessStackInfo.Contact]:
        d = {}
        LT = process_stack_pb2.ProcessStackInfo.LayerType
        for lyr in self.tech.process_stack.layers:
            match lyr.layer_type:
                case LT.LAYER_TYPE_NWELL:
                    d[lyr.nwell_layer.contact_above.name] = lyr.nwell_layer.contact_above

                case LT.LAYER_TYPE_DIFFUSION:  # nsdm or psdm
                    d[lyr.diffusion_layer.contact_above.name] = lyr.diffusion_layer.contact_above

                case LT.LAYER_TYPE_METAL:
                    d[lyr.metal_layer.contact_above.name] = lyr.metal_layer.contact_above
        return d

    def gds_pair(self, layer_name) -> Optional[GDSPair]:
        gds_pair = self.gds_pair_for_computed_layer_name.get(layer_name, None)
        if not gds_pair:
            gds_pair = self.gds_pair_for_layer_name.get(layer_name, None)
        if not gds_pair:
            warning(f"Can't find GDS pair for layer {layer_name}")
            return None
        return gds_pair

    @cached_property
    def bottom_and_top_layer_name_by_via_computed_layer_name(self) -> Dict[str, Tuple[str, str]]:
        # NOTE: vias under the same name can be used in multiple situations
        #       e.g. in sky130A, via3 has two (bot, top) cases: {(met3, met4), (met3, cmim)},
        #       therefore the canonical name must not be used,
        #       but really the LVS computed name, that is also used in the process stack
        #
        #       the metal layers however are canonical!

        d = {}
        for metal_layer in self.process_metal_layers:
            layer_name = metal_layer.name
            gds_pair = self.gds_pair(layer_name)

            if metal_layer.metal_layer.HasField('contact_above'):
                contact = metal_layer.metal_layer.contact_above
                d[contact.name] = (contact.layer_below, contact.metal_above)

        return d
    #--------------------------------

    @cached_property
    def layer_resistance_by_layer_name(self) -> Dict[str, process_parasitics_pb2.ResistanceInfo.LayerResistance]:
        return {r.layer_name: r for r in self.tech.process_parasitics.resistance.layers}

    @cached_property
    def contact_resistance_by_device_layer_name(self) -> Dict[str, process_parasitics_pb2.ResistanceInfo.ContactResistance]:
        return {r.device_layer_name: r for r in self.tech.process_parasitics.resistance.contacts}

    @cached_property
    def via_resistance_by_layer_name(self) -> Dict[str, process_parasitics_pb2.ResistanceInfo.ViaResistance]:
        return {r.via_name: r for r in self.tech.process_parasitics.resistance.vias}

    @staticmethod
    def milliohm_to_ohm(milliohm: float) -> float:
        # NOTE: tech_pb2 has mΩ/µm^2
        #       RExtractorTech.Conductor.resistance is in Ω/µm^2
        return milliohm / 1000.0

    @staticmethod
    def milliohm_by_cnt_to_ohm_by_square_for_contact(
            contact: process_stack_pb2.ProcessStackInfo.Contact,
            contact_resistance: process_parasitics_pb2.ResistanceInfo.ContactResistance) -> float:
        # NOTE: ContactResistance ... mΩ/CNT
        #
        ohm_by_square = contact_resistance.resistance / 1000.0 * contact.width ** 2
        return ohm_by_square

    @staticmethod
    def milliohm_by_cnt_to_ohm_by_square_for_via(
            contact: process_stack_pb2.ProcessStackInfo.Contact,
            via_resistance: process_parasitics_pb2.ResistanceInfo.ViaResistance) -> float:
        ohm_by_square = via_resistance.resistance / 1000.0 * contact.width ** 2
        return ohm_by_square

    #--------------------------------

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

    @property
    def internal_substrate_layer_name(self) -> str:
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

