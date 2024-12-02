#! /usr/bin/env python3

from __future__ import annotations  # allow class type hints within same class
from typing import *
from functools import cached_property
import google.protobuf.json_format

from .util.multiple_choice import MultipleChoicePattern
import tech_pb2
import process_stack_pb2


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
                  dielectric_filter: MultipleChoicePattern) -> TechInfo:
        tech = cls.parse_tech_def(jsonpb_path=jsonpb_path)
        return TechInfo(tech=tech,
                        dielectric_filter=dielectric_filter)

    def __init__(self,
                 tech: tech_pb2.Technology,
                 dielectric_filter: MultipleChoicePattern):
        self.tech = tech
        self.dielectric_filter = dielectric_filter

    @cached_property
    def gds_pair_for_computed_layer_name(self) -> Dict[str, GDSPair]:
        return {lyr.layer_info.name: (lyr.layer_info.gds_layer, lyr.layer_info.gds_datatype)
                for lyr in self.tech.lvs_computed_layers}

    @cached_property
    def computed_layer_info_by_name(self) -> Dict[str, tech_pb2.ComputedLayerInfo]:
        return {lyr.layer_info.name: lyr for lyr in self.tech.lvs_computed_layers}

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
