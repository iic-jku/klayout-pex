#! /usr/bin/env python3

from __future__ import annotations  # allow class type hints within same class
from typing import *
from functools import cached_property
import google.protobuf.json_format

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
    def from_json(cls, jsonpb_path: str) -> TechInfo:
        tech = cls.parse_tech_def(jsonpb_path=jsonpb_path)
        return TechInfo(tech=tech)

    def __init__(self, tech: tech_pb2.Technology):
        self.tech = tech

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

    def sidewall_dielectric_layer(self, layer_name: str) -> Optional[process_stack_pb2.ProcessStackInfo.LayerInfo]:
        found_layers: List[process_stack_pb2.ProcessStackInfo.LayerInfo] = []
        for lyr in self.tech.process_stack.layers:
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
