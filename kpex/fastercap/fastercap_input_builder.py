#! /usr/bin/env python3

#
# Protocol Buffer Schema for FasterCap Input Files
# https://www.fastfieldsolvers.com/software.htm#fastercap
#

from typing import *
from functools import cached_property
import math

import klayout.db as kdb

from ..klayout.lvsdb_extractor import KLayoutExtractionContext, KLayoutExtractedLayerInfo
from .fastercap_model_generator import FasterCapModelBuilder, FasterCapModelGenerator
from ..log import (
    console,
    debug,
    info,
    warning,
    error
)
from ..tech_info import TechInfo

import process_stack_pb2
from fastercap_file_format_pb2 import *


class FasterCapInputBuilder:
    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 tech_info: TechInfo,
                 k_void: float = 3.5,
                 delaunay_amax: float = 0.0,
                 delaunay_b: float = 1.0):
        self.pex_context = pex_context
        self.tech_info = tech_info
        self.k_void = k_void
        self.delaunay_amax = delaunay_amax
        self.delaunay_b = delaunay_b

    @cached_property
    def dbu(self) -> float:
        return self.pex_context.dbu

    def extracted_layer(self, layer_name: str) -> Optional[KLayoutExtractedLayerInfo]:
        if layer_name not in self.tech_info.gds_pair_for_layer_name:
            warning(f"Can't find GDS pair for layer {layer_name}")
            return None

        gds_pair = self.tech_info.gds_pair_for_layer_name[layer_name]
        if gds_pair not in self.pex_context.extracted_layers:
            debug(f"Nothing extracted for layer {layer_name}")
            return None

        extracted_layer = self.pex_context.extracted_layers[gds_pair]
        return extracted_layer

    def build(self) -> FasterCapModelGenerator:
        lvsdb = self.pex_context.lvsdb
        netlist: kdb.Netlist = lvsdb.netlist()

        def format_terminal(t: kdb.NetTerminalRef) -> str:
            td = t.terminal_def()
            d = t.device()
            return f"{d.expanded_name()}/{td.name}/{td.description}"

        model_builder = FasterCapModelBuilder(
            dbu=self.dbu,
            k_void=self.k_void,
            delaunay_amax=self.delaunay_amax,   # test/compare with smaller, e.g. 0.05 => more triangles
            delaunay_b=self.delaunay_b          # test/compare with 1.0 => more triangles at edges
        )

        # zellen vergleichen:
        #    caps VPP ... vergleichen mit modellierten capacities / referenzwert
        #    flipflops (auswirkung auf setup/hold zeiten)

        for pl in self.tech_info.tech.process_stack.layers:
            match pl.layer_type:
                case process_stack_pb2.ProcessStackInfo.LAYER_TYPE_SIMPLE_DIELECTRIC:
                    diel = pl.simple_dielectric_layer
                    model_builder.add_material(pl.name, diel.dielectric_k)
                case process_stack_pb2.ProcessStackInfo.LAYER_TYPE_CONFORMAL_DIELECTRIC:
                    diel = pl.conformal_dielectric_layer
                    model_builder.add_material(pl.name, diel.dielectric_k)
                case process_stack_pb2.ProcessStackInfo.LAYER_TYPE_SIDEWALL_DIELECTRIC:
                    diel = pl.sidewall_dielectric_layer
                    model_builder.add_material(pl.name, diel.dielectric_k)

        circuit = netlist.circuit_by_name(self.pex_context.top_cell.name)
        # https://www.klayout.de/doc-qt5/code/class_Circuit.html
        if not circuit:
            circuits = [c.name for c in netlist.each_circuit()]
            raise Exception(f"Expected circuit called {self.pex_context.top_cell.name} in extracted netlist, "
                            f"only available circuits are: {circuits}")

        diffusion_regions: List[kdb.Region] = []

        for net in circuit.each_net():
            # https://www.klayout.de/doc-qt5/code/class_Net.html
            debug(f"Net name={net.name}, expanded_name={net.expanded_name()}, pin_count={net.pin_count()}, "
                  f"is_floating={net.is_floating()}, is_passive={net.is_passive()}, "
                  f"terminals={list(map(lambda t: format_terminal(t), net.each_terminal()))}")

            net_name = net.expanded_name()

            for metal_layer in self.tech_info.process_metal_layers:
                metal_layer_name = metal_layer.name
                metal_layer = metal_layer.metal_layer

                metal_z_bottom = metal_layer.height
                metal_z_top = metal_z_bottom + metal_layer.thickness

                extracted_layer = self.extracted_layer(layer_name=metal_layer_name)
                if extracted_layer:
                    shapes: kdb.Region = self.pex_context.lvsdb.shapes_of_net(net, extracted_layer.region, True)
                    if shapes.count() >= 1:
                        model_builder.add_conductor(net_name=net_name,
                                                    layer=shapes,
                                                    z=metal_layer.height,
                                                    height=metal_layer.thickness)

                        sidewall_height = 0
                        sidewall_region = extracted_layer.region
                        sidewallee = metal_layer_name
                        while True:
                            sidewall = self.tech_info.sidewall_dielectric_layer(sidewallee)
                            if not sidewall:
                                break
                            match sidewall.layer_type:
                                case process_stack_pb2.ProcessStackInfo.LAYER_TYPE_SIDEWALL_DIELECTRIC:
                                    d = math.floor(sidewall.sidewall_dielectric_layer.width_outside_sidewall / self.dbu)
                                    sidewall_region = sidewall_region.sized(d)
                                    h_delta = sidewall.sidewall_dielectric_layer.height_above_metal or metal_layer.thickness
                                    # if h_delta == 0:
                                    #     h_delta = metal_layer.thickness
                                    sidewall_height += h_delta
                                    model_builder.add_dielectric(material_name=sidewall.name,
                                                                 layer=sidewall_region,
                                                                 z=metal_layer.height,
                                                                 height=sidewall_height)
                                case process_stack_pb2.ProcessStackInfo.LAYER_TYPE_CONFORMAL_DIELECTRIC:
                                    d = math.floor(sidewall.conformal_dielectric_layer.thickness_sidewall / self.dbu)
                                    sidewall_region = sidewall_region.sized(d)
                                    sidewall_height = metal_layer.thickness + sidewall.conformal_dielectric_layer.thickness_over_metal
                                    model_builder.add_dielectric(material_name=sidewall.name,
                                                                 layer=sidewall_region,
                                                                 z=metal_layer.height,
                                                                 height=sidewall_height)
                            sidewallee = sidewall.name

                    contact = metal_layer.contact_above
                    extracted_layer = self.extracted_layer(layer_name=contact.name)
                    if extracted_layer and not extracted_layer.region.is_empty():
                        shapes: kdb.Region = self.pex_context.lvsdb.shapes_of_net(net, extracted_layer.region, True)
                        model_builder.add_conductor(net_name=net_name,
                                                    layer=shapes,
                                                    z=metal_z_top,
                                                    height=contact.thickness)

                diel_above = self.tech_info.process_stack_layer_by_name.get(metal_layer.reference_above, None)
                if diel_above:
                    #model_builder.add_dielectric(material_name=metal_layer.reference_above,
                    #                             layer=kdb.Region().)
                    pass
                # TODO: add stuff

            # DIFF / TAP
            for diffusion_layer in self.tech_info.process_diffusion_layers:
                diffusion_layer_name = diffusion_layer.name
                diffusion_layer = diffusion_layer.diffusion_layer
                extracted_layer = self.extracted_layer(layer_name=diffusion_layer_name)
                if extracted_layer:
                    shapes: kdb.Region = self.pex_context.lvsdb.shapes_of_net(net, extracted_layer.region, True)
                    if shapes.count() >= 1:
                        diffusion_regions.append(shapes)
                        model_builder.add_conductor(net_name=net_name,
                                                    layer=shapes,
                                                    z=0,  # TODO
                                                    height=0.1)  # TODO: diffusion_layer.height

                contact = diffusion_layer.contact_above
                extracted_layer = self.extracted_layer(layer_name=contact.name)
                if extracted_layer and not extracted_layer.region.is_empty():
                    shapes: kdb.Region = self.pex_context.lvsdb.shapes_of_net(net, extracted_layer.region, True)
                    if shapes.count() >= 1:
                        model_builder.add_conductor(net_name=net_name,
                                                    layer=shapes,
                                                    z=0.0,
                                                    height=contact.thickness)

                diel_above = self.tech_info.process_stack_layer_by_name[diffusion_layer.reference]
                if diel_above:
                    pass

                # TODO: add stuff

        # substrate block blow everything. independent of nets!

        substrate_layer = self.tech_info.process_substrate_layer.substrate_layer
        substrate_region = kdb.Region()

        top_cell_bbox: kdb.Box = self.pex_context.target_layout.top_cell().bbox()
        substrate_block = top_cell_bbox.enlarged(math.floor(1 / self.dbu))  # 1µm
        substrate_region.insert(substrate_block)

        diffusion_margin = math.floor(1 / self.dbu)  # 1 µm
        for d in diffusion_regions:
            substrate_region -= d.sized(diffusion_margin)
        model_builder.add_conductor(net_name="0",
                                    layer=substrate_region,
                                    z=0 - substrate_layer.height - substrate_layer.thickness,
                                    height=substrate_layer.thickness)

        gen = model_builder.generate()
        return gen
