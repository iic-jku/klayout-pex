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

import math
from collections import defaultdict
from dataclasses import dataclass
from enum import IntEnum
from typing import *

import klayout.db as kdb
import klayout.rdb as rdb

from ..klayout.lvsdb_extractor import KLayoutExtractionContext, GDSPair
from ..log import (
    console,
    debug,
    info,
    warning,
    error
)
from ..tech_info import TechInfo
from .extraction_results import *
from .extraction_reporter import ExtractionReporter
from .geometry_restorer import GeometryRestorer
from .types import EdgeInterval, EdgeNeighborhood, EdgeNeighborhoodChild, EdgeNeighborhoodChildKind, \
                   PolygonNeighborhood
import klayout_pex_protobuf.process_stack_pb2 as process_stack_pb2


class RCExtractor:
    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 tech_info: TechInfo,
                 report_path: str):
        self.pex_context = pex_context
        self.tech_info = tech_info
        self.report_path = report_path

        if "PolygonWithProperties" not in kdb.__all__:
            raise Exception("KLayout version does not support properties (needs 0.30 at least)")

    def gds_pair(self, layer_name) -> Optional[GDSPair]:
        gds_pair = self.tech_info.gds_pair_for_computed_layer_name.get(layer_name, None)
        if not gds_pair:
            gds_pair = self.tech_info.gds_pair_for_layer_name.get(layer_name, None)
        if not gds_pair:
            warning(f"Can't find GDS pair for layer {layer_name}")
            return None
        return gds_pair

    def shapes_of_layer(self, layer_name: str) -> Optional[kdb.Region]:
        gds_pair = self.gds_pair(layer_name=layer_name)
        if not gds_pair:
            return None

        shapes = self.pex_context.shapes_of_layer(gds_pair=gds_pair)
        if not shapes:
            debug(f"Nothing extracted for layer {layer_name}")

        return shapes

    def extract(self) -> ExtractionResults:
        extraction_results = ExtractionResults()

        # TODO: for now, we always flatten and have only 1 cell
        cell_name = self.pex_context.top_cell.name
        extraction_report = ExtractionReporter(cell_name=cell_name,
                                               dbu=self.pex_context.dbu)
        cell_extraction_results = CellExtractionResults(cell_name=cell_name)

        self.extract_cell(results=cell_extraction_results,
                          report=extraction_report)
        extraction_results.cell_extraction_results[cell_name] = cell_extraction_results

        extraction_report.save(self.report_path)

        return extraction_results

    def extract_cell(self,
                     results: CellExtractionResults,
                     report: ExtractionReporter):
        netlist: kdb.Netlist = self.pex_context.lvsdb.netlist()
        dbu = self.pex_context.dbu
        # ------------------------------------------------------------------------

        layer_regions_by_name: Dict[LayerName, kdb.Region] = defaultdict(kdb.Region)

        all_region = kdb.Region()
        all_region.enable_properties()

        substrate_region = kdb.Region()
        substrate_region.enable_properties()
        substrate_region.insert(self.pex_context.top_cell_bbox().enlarged(8.0 / dbu))  # 8 µm halo
        substrate_layer_name = self.tech_info.internal_substrate_layer_name

        layer_regions_by_name[substrate_layer_name] = substrate_region

        for metal_layer in self.tech_info.process_metal_layers:
            layer_name = metal_layer.name
            gds_pair = self.gds_pair(layer_name)
            canonical_layer_name = self.tech_info.canonical_layer_name_by_gds_pair[gds_pair]

            all_layer_shapes = self.shapes_of_layer(layer_name)
            if all_layer_shapes is None:
                continue

            all_layer_shapes.enable_properties()

            layer_regions_by_name[canonical_layer_name] += all_layer_shapes
            layer_regions_by_name[canonical_layer_name].enable_properties()
            all_region += all_layer_shapes

        all_layer_names = list(layer_regions_by_name.keys())
        all_layer_regions = layer_regions_by_name.values()

        # ------------------------------------------------------------------------

        def emit_overlap(bot_layer_name: LayerName,
                         top_layer_name: LayerName,
                         polygon_bot: kdb.PolygonWithProperties,
                         polygon_top: kdb.PolygonWithProperties,
                         shielded_region: kdb.Region):
            top_overlap_specs = self.tech_info.overlap_cap_by_layer_names.get(top_layer_name, None)
            if not top_overlap_specs:
                warning(f"No overlap cap specified for layer top={top_layer_name}")
                return
            overlap_cap_spec = top_overlap_specs.get(bot_layer_name, None)
            if not overlap_cap_spec:
                warning(f"No overlap cap specified for layer bottom={bot_layer_name}")
                return

            net_bot = self.tech_info.internal_substrate_layer_name \
                      if bot_layer_name == self.tech_info.internal_substrate_layer_name \
                      else polygon_bot.property('net')
            net_top = polygon_top.property('net')

            top_region = kdb.Region(polygon_top)
            bottom_region = kdb.Region(polygon_bot)

            overlap_area = top_region.__and__(bottom_region) - shielded_region

            overlap_area_um2 = overlap_area.area() * dbu ** 2
            cap_femto = overlap_area_um2 * overlap_cap_spec.capacitance / 1000.0
            info(f"(Overlap): {top_layer_name}({net_top})-{bot_layer_name}({net_bot}): "
                 f"cap: {round(cap_femto, 2)} fF, "
                 f"area: {overlap_area_um2} µm^2")

            if cap_femto > 0.0:
                ovk = OverlapKey(layer_top=top_layer_name,
                                 net_top=net_top,
                                 layer_bot=bot_layer_name,
                                 net_bot=net_bot)
                cap = OverlapCap(key=ovk,
                                 cap_value=cap_femto,
                                 shielded_area=0.0,  # TODO shielded_area_um2,
                                 unshielded_area=0.0,  # TODO unshielded_area_um2,
                                 tech_spec=overlap_cap_spec)

                results.add_overlap_cap(cap)

                report.output_overlap(overlap_cap=cap,
                                      bottom_polygon=polygon_bot,
                                      top_polygon=polygon_top,
                                      overlap_area=overlap_area)

        def emit_sidewall(layer_name: LayerName,
                          edge: kdb.EdgeWithProperties,
                          edge_interval: EdgeInterval,
                          polygon: kdb.PolygonWithProperties,
                          geometry_restorer: GeometryRestorer):
            net1 = edge.property('net')
            net2 = polygon.property('net')
            sidewall_cap_spec = self.tech_info.sidewall_cap_by_layer_name[layer_name]

            # TODO!

            # NOTE: this method is always called for a single nearest edge (line), so the
            #       polygons have 4 points.
            #       Polygons points are sorted clockwise, so the edge
            #       that goes from right-to-left is the nearest edge
            #nearby_opposing_edge = [e for e in nearest_lateral_shape[1].each_edge() if e.d().x < 0][-1]
            #nearby_opposing_edge_trans = geometry_restorer.restore_edge(edge) * nearby_opposing_edge

            # C = Csidewall * l * t / s
            # C = Csidewall * l / s

            avg_length = edge_interval[1] - edge_interval[0]
            avg_distance = min(polygon.bbox().p1.y, polygon.bbox().p2.y)

            # outside_edge = kdb.Edge(polygon.bbox().p1, polygon.bbox().p2)
            outside_edge = [e for e in polygon.each_edge() if e.d().x < 0][-1]

            length_um = avg_length * dbu
            distance_um = avg_distance * dbu

            # NOTE: dividing by 2 (like MAGIC this not bidirectional),
            #       but we count 2 sidewall contributions (one for each side of the cap)
            cap_femto = ((length_um * sidewall_cap_spec.capacitance)
                         / (distance_um + sidewall_cap_spec.offset)
                         / 2.0       # non-bidirectional (half)
                         / 1000.0)   # aF -> fF

            info(f"(Sidewall) layer {layer_name}: Nets {net1} <-> {net2}: {round(cap_femto, 5)} fF")

            swk = SidewallKey(layer=layer_name, net1=net1, net2=net2)
            sw_cap = SidewallCap(key=swk,
                                 cap_value=cap_femto,
                                 distance=distance_um,
                                 length=length_um,
                                 tech_spec=sidewall_cap_spec)
            results.add_sidewall_cap(sw_cap)

            report.output_sidewall(sidewall_cap=sw_cap,
                                   inside_edge=geometry_restorer.restore_edge_interval(edge_interval),
                                   outside_edge=geometry_restorer.restore_edge(outside_edge))

        def emit_fringe(inside_layer_name: LayerName,
                        outside_layer_name: LayerName,
                        edge: kdb.EdgeWithProperties,
                        edge_interval: EdgeInterval,
                        polygon: kdb.PolygonWithProperties,
                        geometry_restorer: GeometryRestorer):
            pass

        # ------------------------------------------------------------------------

        class PEXPolygonNeighborhoodVisitor(kdb.PolygonNeighborhoodVisitor):
            def __init__(self,
                         layer_names: List[LayerName],
                         inside_layer_index: int):
                super().__init__()
                self.layer_names = layer_names
                self.inside_layer_index = inside_layer_index

            def neighbors(self,
                          layout: kdb.Layout,
                          cell: kdb.Cell,
                          polygon: kdb.PolygonWithProperties,
                          neighborhood: PolygonNeighborhood):
                # We just look "upwards", as we don't want to count areas twice
                for other_layer_index in range(self.inside_layer_index + 1, len(self.layer_names)):
                    neighbor_polygons = neighborhood.get(other_layer_index, None)
                    if neighbor_polygons is None:
                        continue

                    for neighbor_polygon in neighbor_polygons:
                        # TODO: bot_region is loop invariant, cache
                        emit_overlap(bot_layer_name=self.layer_names[self.inside_layer_index],
                                     top_layer_name=self.layer_names[other_layer_index],
                                     polygon_bot=polygon,
                                     polygon_top=neighbor_polygon)

        # ------------------------------------------------------------------------

        class PEXEdgeNeighborhoodVisitor(kdb.EdgeNeighborhoodVisitor):
            def __init__(self,
                         children_description: List[EdgeNeighborhoodChild]):
                super().__init__()

                self.children_description = children_description
                # NOTE: children_description[0] is the inside net (foreign)
                #       children_description[1:] are the outside nets

            def begin_polygon(self,
                              layout: kdb.Layout,
                              cell: kdb.Cell,
                              polygon: kdb.Polygon):
                debug(f"----------------------------------------")
                debug(f"Polygon: {polygon}")

            def end_polygon(self):
                debug(f"End of polygon")

            def on_edge(self,
                        layout: kdb.Layout,
                        cell: kdb.Cell,
                        edge: kdb.EdgeWithProperties,
                        neighborhood: EdgeNeighborhood):
                #
                # NOTE: this complex operation will automatically rotate every edge to be on the x-axis
                #       going from 0 to edge.length
                #       so we only have to consider the y-axis to get the near and far distances
                #

                geometry_restorer = GeometryRestorer(self.to_original_trans(edge))

                for edge_interval, polygons_by_child in neighborhood:
                    if not polygons_by_child:
                        continue

                    for child_index, polygons in polygons_by_child.items():
                        cd = self.children_description[child_index]

                        match cd.kind:
                            case EdgeNeighborhoodChildKind.SIDEWALL:
                                for polygon in polygons:
                                    emit_sidewall(layer_name=cd.layer_name,
                                                  edge=edge,
                                                  edge_interval=edge_interval,
                                                  polygon=polygon,
                                                  geometry_restorer=geometry_restorer)

                            case EdgeNeighborhoodChildKind.OTHER_LAYER:
                                for polygon in polygons:
                                    emit_fringe(inside_layer_name=layer_name,
                                                outside_layer_name=cd.layer_name,
                                                edge=edge,
                                                edge_interval=edge_interval,
                                                polygon=polygon,
                                                geometry_restorer=geometry_restorer)

        for idx, (layer_name, layer_region) in enumerate(layer_regions_by_name.items()):
            other_layer_names = [oln for oln in all_layer_names if oln != layer_name]
            other_layer_regions = [
                r for ln, r in layer_regions_by_name.items()
                if ln != layer_name
            ]

            #
            # OVERLAP
            #

            ovl_visitor = PEXPolygonNeighborhoodVisitor(
                layer_names=all_layer_names,
                inside_layer_index=idx
            )

            # See comment above: as we use the layers in the stack order,
            # the input index is also the metal layer index
            ovl_children = [kdb.CompoundRegionOperationNode.new_secondary(r) for r in all_layer_regions]

            # We don't use a distance - hence only true overlaps will be considered
            ovl_node = kdb.CompoundRegionOperationNode.new_polygon_neighborhood(ovl_children, ovl_visitor)

            layer_region.complex_op(ovl_node)

            #
            # SIDEWALL / FRINGE
            #

            en_visitor = PEXEdgeNeighborhoodVisitor(
                children_description=[EdgeNeighborhoodChild(EdgeNeighborhoodChildKind.SIDEWALL, layer_name)] +
                                     [EdgeNeighborhoodChild(EdgeNeighborhoodChildKind.OTHER_LAYER, name)
                                      for name in other_layer_names],
            )

            en_children = [
                # kdb.CompoundRegionOperationNode.new_primary(),
                kdb.CompoundRegionOperationNode.new_foreign()
            ]
            en_children += [kdb.CompoundRegionOperationNode.new_secondary(other_layer_region)
                            for other_layer_region in other_layer_regions]

            side_halo_um = self.tech_info.tech.process_parasitics.side_halo
            side_halo_dbu = int(side_halo_um / dbu) + 1  # add 1 nm to halo

            en_node = kdb.CompoundRegionOperationNode.new_edge_neighborhood(
                children=en_children,
                visitor=en_visitor,
                bext=0, # bext
                eext=0, # eext,
                din=0, # din
                dout=side_halo_dbu # dout
            )

            layer_region.complex_op(en_node)

        return results
