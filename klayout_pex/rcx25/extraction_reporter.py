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

from functools import cached_property

import klayout.rdb as rdb
import klayout.db as kdb

from .extraction_results import *
from .types import EdgeNeighborhood, LayerName
from klayout_pex.rcx25.c.geometry_restorer import GeometryRestorer
from klayout_pex.klayout.shapes_pb2_converter import ShapesConverter

import klayout_pex_protobuf.kpex.geometry.shapes_pb2 as shapes_pb2
import klayout_pex_protobuf.kpex.layout.device_pb2 as device_pb2
import klayout_pex_protobuf.kpex.layout.pin_pb2 as pin_pb2
import klayout_pex_protobuf.kpex.layout.location_pb2 as location_pb2
import klayout_pex_protobuf.kpex.klayout.r_extractor_tech_pb2 as r_extractor_tech_pb2
import klayout_pex_protobuf.kpex.r.r_network_pb2 as r_network_pb2
import klayout_pex_protobuf.kpex.request.pex_request_pb2 as pex_request_pb2
import klayout_pex_protobuf.kpex.result.pex_result_pb2 as pex_result_pb2

VarShapes = kdb.Shapes | kdb.Region | List[kdb.Edge] | List[kdb.Polygon | kdb.Box]


class ExtractionReporter:
    def __init__(self,
                 cell_name: str,
                 dbu: float):
        self.report = rdb.ReportDatabase(f"PEX {cell_name}")
        self.cell = self.report.create_cell(cell_name)
        self.dbu = dbu
        self.dbu_trans = kdb.CplxTrans(mag=dbu)
        self.category_name_counter: Dict[str, int] = defaultdict(int)
        self.shapes_converter = ShapesConverter(dbu=dbu)

    @cached_property
    def cat_common(self) -> rdb.RdbCategory:
        return self.report.create_category('Common')

    @cached_property
    def cat_pins(self) -> rdb.RdbCategory:
        return self.report.create_category("Pins")

    @cached_property
    def cat_rex_request(self) -> rdb.RdbCategory:
        return self.report.create_category("[R] Extraction Request")

    @cached_property
    def cat_rex_tech(self) -> rdb.RdbCategory:
        return self.report.create_category(self.cat_rex_request, "[R] Extraction Tech")

    @cached_property
    def cat_rex_request_devices(self) -> rdb.RdbCategory:
        return self.report.create_category(self.cat_rex_request, "Devices")

    @cached_property
    def cat_rex_request_pins(self) -> rdb.RdbCategory:
        return self.report.create_category(self.cat_rex_request, "Pins")

    @cached_property
    def cat_rex_request_network_extraction(self) -> rdb.RdbCategory:
            return self.report.create_category(self.cat_rex_request, "Network Extraction Request")

    @cached_property
    def cat_rex_result(self) -> rdb.RdbCategory:
        return self.report.create_category("[R] Extraction Result")

    @cached_property
    def cat_rex_result_networks(self) -> rdb.RdbCategory:
        return self.report.create_category(self.cat_rex_result, "Networks")

    @cached_property
    def cat_rex_nodes(self) -> rdb.RdbCategory:
        return self.report.create_category(self.cat_rex_result, "Nodes")

    @cached_property
    def cat_rex_elements(self) -> rdb.RdbCategory:
        return self.report.create_category(self.cat_rex_result, "Net Elements (Edges)")

    @cached_property
    def cat_devices(self) -> rdb.RdbCategory:
        return self.report.create_category("Devices")

    @cached_property
    def cat_vias(self) -> rdb.RdbCategory:
        return self.report.create_category("Vias")

    @cached_property
    def cat_overlap(self) -> rdb.RdbCategory:
        return self.report.create_category("[C] Overlap")

    @cached_property
    def cat_sidewall(self) -> rdb.RdbCategory:
        return self.report.create_category("[C] Sidewall")

    @cached_property
    def cat_fringe(self) -> rdb.RdbCategory:
        return self.report.create_category("[C] Fringe / Side Overlap")

    @cached_property
    def cat_edge_neighborhood(self) -> rdb.RdbCategory:
        return self.report.create_category("[C] Edge Neighborhood Visitor")

    def save(self, path: str):
        self.report.save(path)

    def output_shapes(self,
                      parent_category: rdb.RdbCategory,
                      category_name: str,
                      shapes: VarShapes) -> rdb.RdbCategory:
        rdb_cat = self.report.create_category(parent_category, category_name)
        self.report.create_items(self.cell.rdb_id(),  ## TODO: if later hierarchical mode is introduced
                                 rdb_cat.rdb_id(),
                                 self.dbu_trans,
                                 shapes)
        return rdb_cat

    def output_overlap(self,
                       overlap_cap: OverlapCap,
                       bottom_polygon: kdb.PolygonWithProperties,
                       top_polygon: kdb.PolygonWithProperties,
                       overlap_area: kdb.Region):
        cat_overlap_top_layer = self.report.create_category(self.cat_overlap,
                                                            f"top_layer={overlap_cap.key.layer_top}")
        cat_overlap_bot_layer = self.report.create_category(cat_overlap_top_layer,
                                                            f'bot_layer={overlap_cap.key.layer_bot}')
        cat_overlap_nets = self.report.create_category(cat_overlap_bot_layer,
                                                       f'{overlap_cap.key.net_top} – {overlap_cap.key.net_bot}')
        self.category_name_counter[cat_overlap_nets.path()] += 1
        cat_overlap_cap = self.report.create_category(
            cat_overlap_nets,
            f"#{self.category_name_counter[cat_overlap_nets.path()]} "
            f"{round(overlap_cap.cap_value, 3)} fF",
        )

        self.output_shapes(cat_overlap_cap, "Top Polygon", [top_polygon])
        self.output_shapes(cat_overlap_cap, "Bottom Polygon", [bottom_polygon])
        self.output_shapes(cat_overlap_cap, "Overlap Area", overlap_area)

    def output_sidewall(self,
                        sidewall_cap: SidewallCap,
                        inside_edge: kdb.Edge,
                        outside_edge: kdb.Edge):
        cat_sidewall_layer = self.report.create_category(self.cat_sidewall,
                                                         f"layer={sidewall_cap.key.layer}")
        cat_sidewall_net_inside = self.report.create_category(cat_sidewall_layer,
                                                              f'inside={sidewall_cap.key.net1}')
        cat_sidewall_net_outside = self.report.create_category(cat_sidewall_net_inside,
                                                               f'outside={sidewall_cap.key.net2}')
        self.category_name_counter[cat_sidewall_net_outside.path()] += 1

        self.output_shapes(
            cat_sidewall_net_outside,
            f"#{self.category_name_counter[cat_sidewall_net_outside.path()]}: "
            f"len {sidewall_cap.length} µm, "
            f"distance {sidewall_cap.distance} µm, "
            f"{round(sidewall_cap.cap_value, 3)} fF",
            [inside_edge, outside_edge]
        )

    def output_sideoverlap(self,
                           sideoverlap_cap: SideOverlapCap,
                           inside_edge: kdb.Edge,
                           outside_polygon: kdb.Polygon,
                           lateral_shield: Optional[kdb.Region]):
        cat_sideoverlap_layer_inside = self.report.create_category(self.cat_fringe,
                                                                   f"inside_layer={sideoverlap_cap.key.layer_inside}")
        cat_sideoverlap_net_inside = self.report.create_category(cat_sideoverlap_layer_inside,
                                                                 f'inside_net={sideoverlap_cap.key.net_inside}')
        cat_sideoverlap_layer_outside = self.report.create_category(cat_sideoverlap_net_inside,
                                                                    f'outside_layer={sideoverlap_cap.key.layer_outside}')
        cat_sideoverlap_net_outside = self.report.create_category(cat_sideoverlap_layer_outside,
                                                                  f'outside_net={sideoverlap_cap.key.net_outside}')
        self.category_name_counter[cat_sideoverlap_net_outside.path()] += 1

        cat_sideoverlap_cap = self.report.create_category(
            cat_sideoverlap_net_outside,
            f"#{self.category_name_counter[cat_sideoverlap_net_outside.path()]}: "
            f"{round(sideoverlap_cap.cap_value, 3)} fF"
        )

        self.output_shapes(cat_sideoverlap_cap, 'Inside Edge', inside_edge)

        shapes = kdb.Shapes()
        shapes.insert(outside_polygon)
        self.output_shapes(cat_sideoverlap_cap, 'Outside Polygon', shapes)

        if lateral_shield is not None:
            self.output_shapes(cat_sideoverlap_cap, 'Lateral Shield',
                               [lateral_shield])

    def output_edge_neighborhood(self,
                                 inside_layer: LayerName,
                                 all_layer_names: List[LayerName],
                                 edge: kdb.EdgeWithProperties,
                                 neighborhood: EdgeNeighborhood,
                                 geometry_restorer: GeometryRestorer):
        cat_en_layer_inside = self.report.create_category(self.cat_edge_neighborhood, f"inside_layer={inside_layer}")
        inside_net = edge.property('net')
        cat_en_net_inside = self.report.create_category(cat_en_layer_inside, f'inside_net={inside_net}')

        for edge_interval, polygons_by_child in neighborhood:
            cat_en_edge_interval = self.report.create_category(cat_en_net_inside, f"Edge Interval: {edge_interval}")
            self.category_name_counter[cat_en_edge_interval.path()] += 1
            cat_en_edge = self.report.create_category(
                cat_en_edge_interval,
                f"#{self.category_name_counter[cat_en_edge_interval.path()]}"
            )
            self.output_shapes(cat_en_edge, "Edge", [edge])  # geometry_restorer.restore_edge(edge))

            for child_index, polygons in polygons_by_child.items():
                self.output_shapes(
                    cat_en_edge,
                    f"Child {child_index}: "
                    f"{child_index < len(all_layer_names) and all_layer_names[child_index] or 'None'}",
                    [geometry_restorer.restore_polygon(p) for p in polygons]
                )

    def output_devices(self,
                       devices: List[device_pb2.Device]):
        for d in devices:
            self.output_device(d)

    def output_device_terminals(self,
                                terminals: List[device_pb2.Device.Terminal],
                                category: rdb.RdbCategory):
        for t in terminals:
            for l2r in t.region_by_layer:
                r = self.shapes_converter.klayout_region(l2r.region)

                self.output_shapes(
                    category,
                    f"{t.name}: net {t.net_name}, layer {l2r.layer.canonical_layer_name}",
                    r
                )

    def output_device(self,
                      device: device_pb2.Device):
        cat_device = self.report.create_category(
            self.cat_rex_request_devices,
            f"{device.device_name}: {device.device_class_name}"
        )
        cat_device_params = self.report.create_category(cat_device, 'Params')
        for p in device.parameters:
            self.report.create_category(cat_device_params, f"{p.name}: {p.value}")

        cat_device_terminals = self.report.create_category(cat_device, 'Terminals')
        self.output_device_terminals(terminals=device.terminals, category=cat_device_terminals)

    def output_pins(self, pins: List[pin_pb2.Pin], category: rdb.RdbCategory):
        for p in pins:
            self.output_pb_pin(p, category)

    def output_pb_pin(self, pin: pin_pb2.Pin, category: rdb.RdbCategory):
        cat_pin = self.report.create_category(
            category,
            f"{pin.label} (net {pin.net_name} on layer {pin.layer.canonical_layer_name})"
        )
        marker_box = self.marker_box_for_pb_point(pin.label_point)
        self.output_shapes(cat_pin, "label point",
                           [self.shapes_converter.klayout_box(marker_box)])

    def output_via(self,
                   via_name: LayerName,
                   bottom_layer: LayerName,
                   top_layer: LayerName,
                   net: str,
                   via_width: float,
                   via_spacing: float,
                   via_border: float,
                   polygon: kdb.Polygon,
                   ohm: float,
                   comment: str):
        cat_via_layers = self.report.create_category(
            self.cat_vias,
            f"{via_name} ({bottom_layer} ↔ {top_layer}) (w={via_width}, sp={via_spacing}, b={via_border})"
        )

        self.category_name_counter[cat_via_layers.path()] += 1

        self.output_shapes(
            cat_via_layers,
            f"#{self.category_name_counter[cat_via_layers.path()]} "
            f"{ohm} Ω  (net {net}) | {comment}",
            [polygon]
        )

    def output_pin(self,
                   layer_name: LayerName,
                   pin_point: kdb.Box,
                   label: kdb.Text):
        cat_pin_layer = self.report.create_category(self.cat_pins, layer_name)
        sh = kdb.Shapes()
        sh.insert(pin_point)
        self.output_shapes(cat_pin_layer, label.string, sh)

    def output_rex_tech(self, tech: r_extractor_tech_pb2.RExtractorTech):
        layer_by_id = {c.layer.id: c.layer for c in tech.conductors}

        self.report.create_category(self.cat_rex_tech, f"Skip simplify: {tech.skip_simplify}")
        cat_conductors = self.report.create_category(self.cat_rex_tech, 'Conductors')
        cat_vias = self.report.create_category(self.cat_rex_tech, 'Vias')
        for c in tech.conductors:
            self.report.create_category(
                cat_conductors,
                f"{c.layer.id}: {c.layer.canonical_layer_name} (LVS {c.layer.lvs_layer_name}), "
                f"{round(c.resistance, 3)} mΩ/µm^2"
            )
        for v in tech.vias:
            bot = layer_by_id[v.bottom_conductor.id].canonical_layer_name
            top = layer_by_id[v.top_conductor.id].canonical_layer_name
            self.report.create_category(
                cat_vias,
                f"{v.layer.id}: {v.layer.canonical_layer_name} (LVS {v.layer.lvs_layer_name}, "
                f"{bot}↔︎{top}), "
                f"{round(v.resistance, 3)} mΩ/µm^2"
            )

    def output_net_extraction_request(self, request: pex_request_pb2.RNetExtractionRequest):
        cat_req = self.report.create_category(self.cat_rex_request_network_extraction, f"Net {request.net_name}")
        cat_pins = self.report.create_category(cat_req, "Pins")
        cat_device_terminals = self.report.create_category(cat_req, "Device Terminals")
        cat_layer_regions = self.report.create_category(cat_req, "Layer Regions")
        self.output_pins(request.pins, cat_pins)
        self.output_device_terminals(terminals=request.device_terminals, category=cat_device_terminals)
        for l2r in request.region_by_layer:
            self.output_shapes(cat_layer_regions, f"Layer {l2r.layer.canonical_layer_name}",
                               self.shapes_converter.klayout_region(l2r.region))

    def output_rex_request(self, request: pex_request_pb2.RExtractionRequest):
        self.output_rex_tech(request.tech)
        self.output_devices(request.devices)
        self.output_pins(request.pins, category=self.cat_rex_request_pins)

        for r in request.net_extraction_requests:
            self.output_net_extraction_request(r)

    def output_rex_result_network(self, network: r_network_pb2.RNetwork):
        cat_network = self.report.create_category(self.cat_rex_result_networks, f"Net {network.net_name}")
        cat_nodes = self.report.create_category(cat_network, f"Nodes")
        cat_elements = self.report.create_category(cat_network, f"Elements")

        node_id_to_node: Dict[int, r_network_pb2.RNode] = {}

        for node in network.nodes:
            self.output_node(node, category=cat_nodes)
            node_id_to_node[node.node_id] = node
        for element in network.elements:
            self.output_element(element, node_id_to_node, category=cat_elements)

    def output_rex_result(self,
                          result: pex_result_pb2.RExtractionResult):
        for network in result.networks:
            self.output_rex_result_network(network)

    def marker_box_for_pb_point(self, point: shapes_pb2.Point) -> shapes_pb2.Box:
        sized_value = 5
        box = shapes_pb2.Box()
        box.lower_left.x = point.x - sized_value
        box.lower_left.y = point.y - sized_value
        box.upper_right.x = point.x + sized_value
        box.upper_right.y = point.y + sized_value
        if point.net:
            box.net = point.net
        return box

    def marker_box_for_node_location(self, node: r_network_pb2.RNode) -> kdb.Box:
        box: shapes_pb2.Box
        match node.location.kind:
            case location_pb2.Location.Kind.LOCATION_KIND_POINT:
                # create marker around point for better visiblity
                box = self.marker_box_for_pb_point(node.location.point)
            case location_pb2.Location.Kind.LOCATION_KIND_BOX:
                box = node.location.box
            case _:
                raise NotImplementedError("unknown location type: {node.location_type}")
        return self.shapes_converter.klayout_box(box)

    def marker_arrow_between_nodes(self,
                                   node_a: r_network_pb2.RNode,
                                   node_b: r_network_pb2.RNode) -> kdb.Polygon:
        a_center = self.marker_box_for_node_location(node_a).center()
        b_center = self.marker_box_for_node_location(node_b).center()
        path = kdb.Path([self.shapes_converter.klayout_point(a_center),
                         self.shapes_converter.klayout_point(b_center)],
                        width=5)
        return path.polygon()

    def output_node(self,
                    node: r_network_pb2.RNode,
                    category: rdb.RdbCategory):
        node_kind: str
        match node.node_kind:
            case r_network_pb2.RNode.Kind.KIND_UNSPECIFIED:
                node_kind = '???'
            case r_network_pb2.RNode.Kind.KIND_PIN:
                node_kind = 'Pin'
            case r_network_pb2.RNode.Kind.KIND_DEVICE_TERMINAL:
                node_kind = 'Device Terminal'
            case r_network_pb2.RNode.Kind.KIND_WIRE_JUNCTION:
                node_kind = 'Wire Junction'
            case r_network_pb2.RNode.Kind.KIND_VIA_JUNCTION:
                node_kind = 'Via Junction'
            case _:
                raise NotImplementedError()

        node_title = f"[{node_kind}] {node.node_name}, port net {node.net_name}, " \
                     f"layer {node.layer_name}"
        sh = kdb.Shapes()
        sh.insert(self.marker_box_for_node_location(node))
        self.output_shapes(category, node_title, sh)

    def output_element(self,
                       element: r_network_pb2.RElement,
                       node_id_to_node: Dict[int, r_network_pb2.RNode],
                       category: rdb.RdbCategory):
        a = node_id_to_node[element.node_a.node_id]
        b = node_id_to_node[element.node_b.node_id]

        if element.resistance >= 0.001:
            ohm = f"{round(element.resistance, 3)} Ω"
        else:
            ohm = f"{round(element.resistance * 1000.0, 6)} mΩ"

        element_title = f"{a.node_name} ({a.layer_name}) ↔︎ " \
                        f"{b.node_name} ({b.layer_name})" \
                        f": {ohm}"
        polygon = self.marker_arrow_between_nodes(a, b)
        self.output_shapes(category, element_title, [polygon])
