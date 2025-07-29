#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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

from collections import defaultdict
from typing import *

from klayout_pex.log import (
    warning,
    subproc,
)

from klayout_pex.klayout.shapes_pb2_converter import ShapesConverter
from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.klayout.rex_core import klayout_r_extractor_tech

import klayout_pex_protobuf.kpex.layout.location_pb2 as location_pb2
from klayout_pex_protobuf.kpex.klayout.r_extractor_tech_pb2 import RExtractorTech as pb_RExtractorTech
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2
import klayout_pex_protobuf.kpex.request.pex_request_pb2 as pex_request_pb2
import klayout_pex_protobuf.kpex.result.pex_result_pb2 as pex_result_pb2

import klayout.db as kdb
import klayout.pex as klp


class RExtractor:
    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 substrate_algorithm: pb_RExtractorTech.Algorithm,
                 wire_algorithm: pb_RExtractorTech.Algorithm,
                 delaunay_b: float,
                 delaunay_amax: float,
                 via_merge_distance: float,
                 skip_simplify: bool):
        """
        :param pex_context: KLayout PEX extraction context
        :param substrate_algorithm: The KLayout PEXCore Algorithm for decomposing polygons.
                                    Either SquareCounting or Tesselation (recommended)
        :param wire_algorithm: The KLayout PEXCore Algorithm for decomposing polygons.
                               Either SquareCounting (recommended) or Tesselation
        :param delaunay_b: The "b" parameter for the Delaunay triangulation,
                           a ratio of shortest triangle edge to circle radius
        :param delaunay_amax: The "max_area" specifies the maximum area of the triangles
                              produced in square micrometers.
        :param via_merge_distance: Maximum distance where close vias are merged together
        :param skip_simplify: skip simplification of resistor network
        """
        self.pex_context = pex_context
        self.substrate_algorithm = substrate_algorithm
        self.wire_algorithm = wire_algorithm
        self.delaunay_b = delaunay_b
        self.delaunay_amax = delaunay_amax
        self.via_merge_distance = via_merge_distance
        self.skip_simplify = skip_simplify

    def prepare_r_extractor_tech_pb(self,
                                    rex_tech: pb_RExtractorTech):
        """
        Prepare KLayout PEXCore Technology Description based on the KPEX Tech Info data
        :param rex_tech: RExtractorTech protobuffer message
        """

        rex_tech.skip_simplify = self.skip_simplify

        tech = self.pex_context.tech

        for gds_pair, li in self.pex_context.extracted_layers.items():
            computed_layer_info = tech.computed_layer_info_by_gds_pair.get(gds_pair, None)
            if computed_layer_info is None:
                warning(f"ignoring layer {gds_pair}, no computed layer info found in tech info")
                continue

            canonical_layer_name = tech.canonical_layer_name_by_gds_pair[gds_pair]

            LP = tech_pb2.LayerInfo.Purpose

            if computed_layer_info.kind != tech_pb2.ComputedLayerInfo.Kind.KIND_PIN:
                match computed_layer_info.layer_info.purpose:
                    case LP.PURPOSE_NWELL:
                        pass  # TODO!

                    case LP.PURPOSE_N_IMPLANT | LP.PURPOSE_P_IMPLANT:
                        # device terminals
                        #   - source/drain (e.g. sky130A: nsdm, psdm)
                        #   - bulk (e.g. nwell)
                        #
                        # we will consider this only as an pin end-point, there are no wires at all on this layer,
                        # so the resistance does not matter for PEX
                        for source_layer in li.source_layers:
                            cond = rex_tech.conductors.add()

                            cond.layer.id = self.pex_context.annotated_layout.layer(*source_layer.gds_pair)
                            cond.layer.canonical_layer_name = canonical_layer_name
                            cond.layer.lvs_layer_name = source_layer.lvs_layer_name

                            cond.triangulation_min_b = self.delaunay_b
                            cond.triangulation_max_area = self.delaunay_amax

                            cond.algorithm = self.substrate_algorithm
                            cond.resistance = 0  # see comment above

                    case LP.PURPOSE_METAL:
                        if computed_layer_info.kind == tech_pb2.ComputedLayerInfo.Kind.KIND_PIN:
                            continue

                        layer_resistance = tech.layer_resistance_by_layer_name.get(canonical_layer_name, None)
                        for source_layer in li.source_layers:
                            cond = rex_tech.conductors.add()

                            cond.layer.id = self.pex_context.annotated_layout.layer(*source_layer.gds_pair)
                            cond.layer.canonical_layer_name = canonical_layer_name
                            cond.layer.lvs_layer_name = source_layer.lvs_layer_name

                            cond.triangulation_min_b = self.delaunay_b
                            cond.triangulation_max_area = self.delaunay_amax

                            if canonical_layer_name == tech.internal_substrate_layer_name:
                                cond.algorithm = self.substrate_algorithm
                            else:
                                cond.algorithm = self.wire_algorithm
                            cond.resistance = layer_resistance.resistance

                    case LP.PURPOSE_CONTACT:
                        for source_layer in li.source_layers:
                            contact = tech.contact_by_contact_lvs_layer_name.get(source_layer.lvs_layer_name, None)
                            if contact is None:
                                warning(
                                    f"ignoring LVS layer {source_layer.lvs_layer_name} (layer {canonical_layer_name}), "
                                    f"no contact found in tech info")
                                continue

                            contact_resistance = tech.contact_resistance_by_device_layer_name.get(contact.layer_below,
                                                                                                  None)
                            if contact_resistance is None:
                                warning(
                                    f"ignoring layer {canonical_layer_name}, no contact resistance found in tech info")
                                continue

                            via = rex_tech.vias.add()

                            bot_gds_pair = tech.gds_pair(contact.layer_below)
                            top_gds_pair = tech.gds_pair(contact.metal_above)

                            via.layer.id = self.pex_context.annotated_layout.layer(*source_layer.gds_pair)
                            via.layer.canonical_layer_name = source_layer.lvs_layer_name
                            via.layer.lvs_layer_name = source_layer.lvs_layer_name

                            via.bottom_conductor.id = self.pex_context.annotated_layout.layer(*bot_gds_pair)
                            via.top_conductor.id = self.pex_context.annotated_layout.layer(*top_gds_pair)

                            via.resistance = contact_resistance.resistance * contact.width ** 2
                            via.merge_distance = self.via_merge_distance

                    case LP.PURPOSE_VIA:
                        via_resistance = tech.via_resistance_by_layer_name.get(canonical_layer_name, None)
                        if via_resistance is None:
                            warning(f"ignoring layer {canonical_layer_name}, no via resistance found in tech info")
                            continue
                        for source_layer in li.source_layers:
                            via = rex_tech.vias.add()

                            (bot, top) = tech.bottom_and_top_layer_name_by_via_computed_layer_name.get(
                                source_layer.lvs_layer_name, None)
                            bot_gds_pair = tech.gds_pair(bot)
                            top_gds_pair = tech.gds_pair(top)

                            via.layer.id = self.pex_context.annotated_layout.layer(*source_layer.gds_pair)
                            via.layer.canonical_layer_name = source_layer.lvs_layer_name
                            via.layer.lvs_layer_name = source_layer.lvs_layer_name

                            via.bottom_conductor.id = self.pex_context.annotated_layout.layer(*bot_gds_pair)
                            via.top_conductor.id = self.pex_context.annotated_layout.layer(*top_gds_pair)

                            contact = self.pex_context.tech.contact_by_contact_lvs_layer_name[
                                source_layer.lvs_layer_name]

                            via.resistance = via_resistance.resistance * contact.width ** 2
                            via.merge_distance = self.via_merge_distance

                    # case _:
                    #     raise NotImplementedError(f"unknown device purpose {computed_layer_info.layer_info.purpose}")

        return rex_tech

    def prepare_request(self) -> pex_request_pb2.RExtractionRequest:
        rex_request = pex_request_pb2.RExtractionRequest()

        # prepare tech info
        self.prepare_r_extractor_tech_pb(rex_tech=rex_request.tech)

        # prepare devices
        devices_by_name = self.pex_context.devices_by_name
        rex_request.devices.MergeFrom(devices_by_name.values())

        # prepare pins
        for pin_list in self.pex_context.pins_pb2_by_layer.values():
            rex_request.pins.MergeFrom(pin_list)

        # prepare layer regions
        #     currently not part of request PB, but in-memory from GDS

        return rex_request

    def extract(self, rex_request: pex_request_pb2.RExtractionRequest) -> pex_result_pb2.RExtractionResult:
        rex_result = pex_result_pb2.RExtractionResult()

        rex_tech_kly = klayout_r_extractor_tech(rex_request.tech)

        Label = str
        LayerName = str
        NetName = str
        DeviceID = int
        TerminalID = int

        # dicts keyed by id / klayout_index
        layer_names: Dict[int, LayerName] = {}
        vertex_ports: Dict[int, List[kdb.Point]] = defaultdict(list)
        polygon_ports: Dict[int, List[kdb.Polygon]] = defaultdict(list)
        vertex_port_pins: Dict[int, List[Tuple[Label, NetName]]] = defaultdict(list)
        polygon_port_device_terminals: Dict[int, List[Tuple[DeviceID, TerminalID], Label, NetName]] = defaultdict(list)
        regions: Dict[int, kdb.Region] = defaultdict(kdb.Region)

        shapes_converter = ShapesConverter(dbu=self.pex_context.dbu)

        for c in rex_request.tech.conductors:
            layer_names[c.layer.id] = c.layer.canonical_layer_name

        for v in rex_request.tech.vias:
            layer_names[v.layer.id] = v.layer.canonical_layer_name

        for d in rex_request.devices:
            for t in d.terminals:
                for l2r in t.regions_by_layer:
                    for p in l2r.region.polygons:
                        p_kly = shapes_converter.klayout_polygon(p)
                        polygon_ports[l2r.layer.id].append(p_kly)
                        polygon_port_device_terminals[l2r.layer.id].append((d.id, t.id, t.name, t.net_name))

        for pin in rex_request.pins:
            p = shapes_converter.klayout_point(pin.label_point)
            vertex_ports[pin.layer.id].append(p)
            vertex_port_pins[pin.layer.id].append((pin.label, pin.net_name))

        LK = tech_pb2.ComputedLayerInfo.Kind
        for lvs_gds_pair, lyr_info in self.pex_context.extracted_layers.items():
            for lyr in lyr_info.source_layers:
                li = self.pex_context.tech.computed_layer_info_by_gds_pair[lyr.gds_pair]
                match li.kind:
                    case LK.KIND_PIN:
                        continue  # skip
                    case LK.KIND_REGULAR | LK.KIND_DEVICE_CAPACITOR | LK.KIND_DEVICE_RESISTOR:
                        klayout_index = self.pex_context.annotated_layout.layer(*lyr.gds_pair)
                        regions[klayout_index] = lyr.region


        rex = klp.RNetExtractor(self.pex_context.dbu)
        resistor_networks = rex.extract(rex_tech_kly,
                                        regions,
                                        vertex_ports,
                                        polygon_ports)

        node_by_node_id: Dict[int, pex_result_pb2.RNode] = {}

        for rn in resistor_networks.each_node():
            loc = rn.location()
            layer_id = rn.layer()
            canonical_layer_name = layer_names[layer_id]

            r_node = pex_result_pb2.RNode()
            r_node.node_id = rn.object_id()
            r_node.node_name = rn.to_s()
            r_node.node_type = pex_result_pb2.RNode.Kind.KIND_UNSPECIFIED  # TODO!
            r_node.layer_name = canonical_layer_name

            match rn.type():
                case klp.RNodeType.VertexPort:
                    r_node.location.kind = location_pb2.Location.Kind.LOCATION_KIND_POINT
                    p = loc.center().to_itype(self.pex_context.dbu)
                    r_node.location.point.x = p.x
                    r_node.location.point.y = p.y
                case klp.RNodeType.PolygonPort | _:
                    r_node.location.kind = location_pb2.Location.Kind.LOCATION_KIND_BOX
                    p1 = loc.p1.to_itype(self.pex_context.dbu)
                    p2 = loc.p2.to_itype(self.pex_context.dbu)
                    r_node.location.box.lower_left.x = p1.x
                    r_node.location.box.lower_left.y = p1.y
                    r_node.location.box.upper_right.x = p2.x
                    r_node.location.box.upper_right.y = p2.y

            match rn.type():
                case klp.RNodeType.VertexPort:
                    port_idx = rn.port_index()
                    r_node.net_name = vertex_port_pins[rn.layer()][port_idx][1]
                case klp.RNodeType.PolygonPort:
                    port_idx = rn.port_index()
                    r_node.net_name = polygon_port_device_terminals[rn.layer()][port_idx][3]
                case _:
                    r_node.net_name = r_node.node_name

            rex_result.nodes.append(r_node)
            node_by_node_id[r_node.node_id] = r_node

        for el in resistor_networks.each_element():
            r_element = pex_result_pb2.RElement()
            r_element.element_id = el.object_id()
            r_element.node_a.node_id = el.a().object_id()
            r_element.node_b.node_id = el.b().object_id()
            r_element.resistance = el.resistance() / 1000.0  # convert mΩ to Ω

            rex_result.elements.append(r_element)

        return rex_result

