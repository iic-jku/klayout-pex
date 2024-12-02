#! /usr/bin/env python3

#
# Protocol Buffer Schema for FasterCap Input Files
# https://www.fastfieldsolvers.com/software.htm#fastercap
#

from typing import *
from functools import cached_property
import klayout.db as kdb

from klayout.lvsdb_extractor import KLayoutExtractionContext, KLayoutExtractedLayerInfo
from tech_info import TechInfo
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
            print(f"WARN: Can't find GDS pair for layer {layer_name} (net {net_name})")
            return None

        gds_pair = self.tech_info.gds_pair_for_layer_name[layer_name]
        if gds_pair not in self.pex_context.extracted_layers:
            print(f"INFO: Nothing extracted for layer {layer_name} (net {net_name})")
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

    def build(self) -> InputFile3D:
        lvsdb = self.pex_context.lvsdb
        netlist = lvsdb.netlist()

        substrate_layers = self.tech_info.process_substrate_layers
        metal_layers = self.tech_info.process_metal_layers

        def format_terminal(t: kdb.NetTerminalRef) -> str:
            td = t.terminal_def()
            d = t.device()
            return f"{d.expanded_name()}/{td.name}/{td.description}"

        for circuit in netlist.each_circuit():
            # https://www.klayout.de/doc-qt5/code/class_Circuit.html

            faster_cap_file = InputFile3D()
            faster_cap_file.file_name = f"circuit_{circuit.name}.lst"
            self.add_comment_section(file=faster_cap_file,
                                     comment=f"FasterCap LST file\n\tCircuit: {circuit.name}",
                                     separator_char='=')

            for net in circuit.each_net():
                # https://www.klayout.de/doc-qt5/code/class_Net.html
                print(f"Net name={net.name}, expanded_name={net.expanded_name()}, pin_count={net.pin_count()}, "
                      f"is_floating={net.is_floating()}, is_passive={net.is_passive()}, "
                      f"terminals={list(map(lambda t: format_terminal(t), net.each_terminal()))}")

                net_name = net.expanded_name()

                conductor = faster_cap_file.lines.add().conductor
                conductor.file_name = f"circuit_{circuit.name}__conductor_{net_name}.txt"
                conductor.relative_permittivity = 4.2   # TODO!!!!
                conductor.offset_in_space.x = 0.0
                conductor.offset_in_space.y = 0.0
                conductor.offset_in_space.z = 0.0

                conductor_file = faster_cap_file.sub_input_files.add()
                conductor_file.file_name = conductor.file_name
                self.add_comment_section(file=conductor_file,
                                         comment=f"FasterCap Conductor File\n"
                                                 f"\tCircuit: {circuit.name}\n"
                                                 f"\tNet: {net_name}")

                for metal_layer in metal_layers:
                    metal_z_bottom = metal_layer.metal_layer.height
                    metal_z_top = metal_z_bottom + metal_layer.metal_layer.thickness

                    extracted_layer = self.extracted_layer(net_name=net_name, layer_name=metal_layer.name)
                    if not extracted_layer:
                        continue

                    self._add_layer_extrusion(conductor_file=conductor_file,
                                              net=net,
                                              net_name=net_name,
                                              layer_name=metal_layer.name,
                                              extracted_layer=extracted_layer,
                                              z_bottom=metal_z_bottom,
                                              z_top=metal_z_top)

                    contact = metal_layer.metal_layer.contact_above
                    extracted_layer = self.extracted_layer(net_name=net_name, layer_name=contact.name)
                    if not extracted_layer:
                        # there's nothing extracted on top the metal layer, skip
                        continue

                    contact_z_bottom = metal_z_top
                    contact_z_top = contact_z_bottom + contact.thickness
                    self._add_layer_extrusion(conductor_file=conductor_file,
                                              net=net,
                                              net_name=net_name,
                                              layer_name=contact.name,
                                              extracted_layer=extracted_layer,
                                              z_bottom=contact_z_bottom,
                                              z_top=contact_z_top)

                #
                # substrate
                #
                for substrate_layer in substrate_layers:
                    extracted_layer = self.extracted_layer(net_name=net_name, layer_name=substrate_layer.name)
                    print(f"Substrate layer {substrate_layer.name}, net {net_name}: "
                          f"Extracted?={extracted_layer is not None}")
                    if not extracted_layer:
                        continue

                    region = extracted_layer.region
                    if region.count() == 0:
                        continue

                    self.add_comment_section(file=conductor_file,
                                             comment=f"Net {net_name} / "
                                                     f"Layer {substrate_layer.name} {extracted_layer.gds_pair}")

                    triangulated_shapes = region.delaunay(0.0, 1.0)
                    for shape in triangulated_shapes:
                        #     print(f"Triangle: {shape} (Area: {shape.area()} nm^2)")
                        self._add_triangle_in_z(
                            conductor_file=conductor_file,
                            net_name=net_name,
                            triangle=shape,
                            z_list=[0.0]
                        )

                print()
                # print(f"Shapes of net {net_name}: ")
                # for shape in shapes:
                    #     print(f"Type: {type(shape)}: {shape} (Area: {shape.area()} nm^2)")
                    #
                    # # ARE there overlaps?
                    # for shape1 in shapes:
                    #     for shape2 in shapes:
                    #         if shape1 == shape2:
                    #             continue
                    #         r1 = pya.Region(shape1)
                    #         r2 = pya.Region(shape2)
                    #         ov = r1.overlapping(r2)
                    #         if ov:
                    #             ins = r1 & r2
                    #             print(f"Shape1 {shape1} overlaps shape2 {shape2}: {ins}")
                    #             l = pya.Layout()
                    #             c = l.create_cell("TOP")
                    #             lyr = l.layer(pya.LayerInfo(layer_info.gds_layer, layer_info.gds_datatype))
                    #             c.shapes(lyr).insert(shape1)
                    #             c.shapes(lyr).insert(shape2)
                    #             lyr = l.layer(pya.LayerInfo(1000, 0, "intersection.dbg"))
                    #             c.shapes(lyr).insert(ins)
                    #             timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
                    #
                    #             #
                    #             # l.write(f"overlap__net_{net.name}__layer_{layer_info.name}__{timestamp}.gds")
                    #             #
                    #
                    #             # VARIANTEN zum Angucken:
                    #
                    #             # 1) Browser mit:
                    #             # https://github.com/gdsfactory/kweb
                    #             # 2) prozess mit klayout anstarten mit dem gds
                    #
                    #             # display.show(l)
                    #             # print("...")

        return faster_cap_file