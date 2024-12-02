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
from .fastercap_model_generator import FasterCapModelBuilder
from ..logging import (
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
                 tech_info: TechInfo):
        self.pex_context = pex_context
        self.tech_info = tech_info

    @cached_property
    def dbu(self) -> float:
        return self.pex_context.dbu

    @staticmethod
    def add_comment_section(file: InputFile3D,
                            comment: str,
                            separator_char: str = '-'):
        separator_line = separator_char * 80
        file.lines.add().comment.message = separator_line
        for comment_line in comment.splitlines():
            file.lines.add().comment.message = comment_line
        file.lines.add().comment.message = separator_line
        file.lines.add().comment.message = ""

    def _add_triangle_in_z(self,
                           conductor_file: InputFile3D,
                           net_name: str,
                           triangle: kdb.Polygon,
                           z_list: List[float]):  # e.g. [z_bottom, z_top]
        hull = list(triangle.each_point_hull())
        assert len(hull) == 3

        for z in z_list:
            panel = conductor_file.lines.add().triangular_panel

            for i in range(0, 3):
                panel.conductor_name = net_name
                point = getattr(panel, f'point_{i}')
                point.x = hull[i].x * self.dbu
                point.y = hull[i].y * self.dbu
                point.z = z

    def _add_perimeter_extrusion(self,
                                 conductor_file: InputFile3D,
                                 net_name: str,
                                 edge: kdb.Edge,
                                 z_bottom: float,
                                 z_top: float):
        side_panel = conductor_file.lines.add().quadrilateral_panel
        side_panel.conductor_name = net_name
        side_panel.point_0.x = edge.p1.x * self.dbu
        side_panel.point_0.y = edge.p1.y * self.dbu
        side_panel.point_0.z = z_top
        side_panel.point_1.x = edge.p1.x * self.dbu
        side_panel.point_1.y = edge.p1.y * self.dbu
        side_panel.point_1.z = z_bottom
        side_panel.point_2.x = edge.p2.x * self.dbu
        side_panel.point_2.y = edge.p2.y * self.dbu
        side_panel.point_2.z = z_bottom
        side_panel.point_3.x = edge.p2.x * self.dbu
        side_panel.point_3.y = edge.p2.y * self.dbu
        side_panel.point_3.z = z_top

    def _add_region_extrusion(self,
                              conductor_file: InputFile3D,
                              net_name: str,
                              region: kdb.Region,
                              z_bottom: float,
                              z_top: float):
        triangulated_shapes = region.delaunay(0.0, 1.0)

        # ====================================================================
        #   Phase A)
        #     1) create a top plane
        #     2) create a bottom plane
        # ====================================================================
        for shape in triangulated_shapes:
            #     print(f"Triangle: {shape} (Area: {shape.area()} nm^2)")
            self._add_triangle_in_z(
                conductor_file=conductor_file,
                net_name=net_name,
                triangle=shape,
                z_list=[z_bottom, z_top]
            )

        # ====================================================================
        #   Phase B)
        #     1) for each edges along the perimeter, create the "side walls"
        # ====================================================================
        for edge in region.edges():
            # print(f"Edge: {edge}")
            self._add_perimeter_extrusion(
                conductor_file=conductor_file,
                net_name=net_name,
                edge=edge,
                z_bottom=z_bottom,
                z_top=z_top
            )

        # TODO: perhaps the amount of data can be reduced by decomposing rectangles as much as possible,
        #       and then only use triangles where needed
        #       ...
        #       also, FastHenry2 seems to only support rectangular geometries,
        #       so this decomposition would be useful there also

    def extracted_layer(self, net_name: str, layer_name: str) -> Optional[KLayoutExtractedLayerInfo]:
        if layer_name not in self.tech_info.gds_pair_for_layer_name:
            warning(f"Can't find GDS pair for layer {layer_name} (net {net_name})")
            return None

        gds_pair = self.tech_info.gds_pair_for_layer_name[layer_name]
        if gds_pair not in self.pex_context.extracted_layers:
            debug(f"Nothing extracted for layer {layer_name} (net {net_name})")
            return None

        extracted_layer = self.pex_context.extracted_layers[gds_pair]
        return extracted_layer

    def _add_layer_extrusion(self,
                             conductor_file: InputFile3D,
                             net: kdb.Net,
                             net_name: str,
                             layer_name: str,
                             extracted_layer: KLayoutExtractedLayerInfo,
                             z_bottom: float,
                             z_top: float):
        shapes: kdb.Region = self.pex_context.lvsdb.shapes_of_net(net, extracted_layer.region, True)
        if shapes.count() == 0:
            return

        self.add_comment_section(file=conductor_file,
                                 comment=f"Net {net_name} / Layer {layer_name} {extracted_layer.gds_pair}")

        self._add_region_extrusion(
            conductor_file=conductor_file,
            net_name=net_name,
            region=shapes,
            z_bottom=z_bottom,
            z_top=z_top
        )

        conductor_file.lines.add().comment.message = ""

    def build(self) -> List[Tuple[kdb.Circuit, InputFile3D]]:
        result_files: List[Tuple[kdb.Circuit, InputFile3D]] = []

        lvsdb = self.pex_context.lvsdb
        netlist = lvsdb.netlist()
        substrate_layers = self.tech_info.process_substrate_layers
        metal_layers = self.tech_info.process_metal_layers

        def format_terminal(t: kdb.NetTerminalRef) -> str:
            td = t.terminal_def()
            d = t.device()
            return f"{d.expanded_name()}/{td.name}/{td.description}"

        model_builder = FasterCapModelBuilder(
            dbu=self.dbu,
            k_void=3.5,  # TODO
            delaunay_amax=0.5,
            delaunay_b=0.5
        )

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

        for circuit in netlist.each_circuit():
            # https://www.klayout.de/doc-qt5/code/class_Circuit.html

            for net in circuit.each_net():
                # https://www.klayout.de/doc-qt5/code/class_Net.html
                debug(f"Net name={net.name}, expanded_name={net.expanded_name()}, pin_count={net.pin_count()}, "
                      f"is_floating={net.is_floating()}, is_passive={net.is_passive()}, "
                      f"terminals={list(map(lambda t: format_terminal(t), net.each_terminal()))}")

                net_name = net.expanded_name()

                for metal_layer in metal_layers:
                    metal_layer_name = metal_layer.name
                    metal_layer = metal_layer.metal_layer

                    metal_z_bottom = metal_layer.height
                    metal_z_top = metal_z_bottom + metal_layer.thickness

                    extracted_layer = self.extracted_layer(net_name=net_name, layer_name=metal_layer_name)
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
                        extracted_layer = self.extracted_layer(net_name=net_name, layer_name=contact.name)
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

                #
                # substrate
                #
                for substrate_layer in substrate_layers:
                    substrate_layer_name = substrate_layer.name
                    substrate_layer = substrate_layer.diffusion_layer
                    extracted_layer = self.extracted_layer(net_name=net_name, layer_name=substrate_layer_name)
                    debug(f"Substrate layer {substrate_layer_name}, net {net_name}: "
                          f"Extracted?={extracted_layer is not None}")
                    if extracted_layer:
                        shapes: kdb.Region = self.pex_context.lvsdb.shapes_of_net(net, extracted_layer.region, True)
                        if shapes.count() >= 1:
                            model_builder.add_conductor(net_name=net_name,
                                                        layer=shapes,
                                                        z=-0.1,
                                                        height=0.1)  # TODO: substrate_layer.diffusion_layer.height

                    contact = substrate_layer.contact_above
                    extracted_layer = self.extracted_layer(net_name=net_name, layer_name=contact.name)
                    if extracted_layer and not extracted_layer.region.is_empty():
                        shapes: kdb.Region = self.pex_context.lvsdb.shapes_of_net(net, extracted_layer.region, True)
                        if shapes.count() >= 1:
                            model_builder.add_conductor(net_name=net_name,
                                                        layer=shapes,
                                                        z=0.0,
                                                        height=contact.thickness)

                    diel_above = self.tech_info.process_stack_layer_by_name[substrate_layer.reference]
                    if diel_above:
                        pass

                    # TODO: add stuff

            gen = model_builder.generate()
            gen.check()
            gen.dump_stl()
            gen.write_fastcap("fastercap_")

            print()

        return result_files
