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

from functools import cached_property
import math

import klayout.db as kdb

from klayout_pex.log import (
    info,
    warning,
    get_log_level,
    LogLevel
)
from klayout_pex.tech_info import TechInfo

from klayout_pex.rcx25.c.geometry_restorer import GeometryRestorer
from klayout_pex.rcx25.extraction_results import *
from klayout_pex.rcx25.extraction_reporter import ExtractionReporter
from klayout_pex.rcx25.c.polygon_utils import find_polygon_with_nearest_edge, nearest_edge
from klayout_pex.rcx25.types import EdgeInterval, EdgeNeighborhood
from klayout_pex_protobuf.kpex.tech.process_parasitics_pb2 import CapacitanceInfo


class SidewallAndFringeExtractor:
    def __init__(self,
                 all_layer_names: List[LayerName],
                 layer_regions_by_name: Dict[LayerName, kdb.Region],
                 dbu: float,
                 scale_ratio_to_fit_halo: bool,
                 tech_info: TechInfo,
                 results: CellExtractionResults,
                 report: ExtractionReporter):
        self.all_layer_names = all_layer_names
        self.layer_regions_by_name = layer_regions_by_name
        self.dbu = dbu
        self.scale_ratio_to_fit_halo = scale_ratio_to_fit_halo
        self.tech_info = tech_info
        self.results = results
        self.report = report

        self.all_layer_regions = layer_regions_by_name.values()

    def extract(self):
        for idx, (layer_name, layer_region) in enumerate(self.layer_regions_by_name.items()):
            other_layer_regions = [
                r for ln, r in self.layer_regions_by_name.items()
                if ln != layer_name
            ]

            en_visitor = self.PEXEdgeNeighborhoodVisitor(
                all_layer_names=self.all_layer_names,
                inside_layer_index=idx,
                dbu=self.dbu,
                scale_ratio_to_fit_halo=self.scale_ratio_to_fit_halo,
                tech_info=self.tech_info,
                results=self.results,
                report=self.report
            )

            en_children = [kdb.CompoundRegionOperationNode.new_secondary(r)
                           for r in self.all_layer_regions]
            en_children[idx] = kdb.CompoundRegionOperationNode.new_foreign()  # sidewall of other nets on the same layer
            en_children.append(kdb.CompoundRegionOperationNode.new_primary()) # opposing structures of the same polygon

            side_halo_um = self.tech_info.tech.process_parasitics.side_halo
            side_halo_dbu = int(side_halo_um / self.dbu) + 1  # add 1 nm to halo

            en_node = kdb.CompoundRegionOperationNode.new_edge_neighborhood(
                children=en_children,
                visitor=en_visitor,
                bext=-1, # NOTE: -1 dbu, suppresses quasi-empty contributions (will also suppress 90° edges)
                eext=-1, # NOTE: -1 dbu, suppresses quasi-empty contributions (will also suppress 90° edges)
                din=-1,  # NOTE: -1 dbu, suppresses the edge itself appearing as a pseudo-polygon in new_primary()
                dout=side_halo_dbu # dout
            )

            layer_region.complex_op(en_node)

    # ------------------------------------------------------------------------

    class PEXEdgeNeighborhoodVisitor(kdb.EdgeNeighborhoodVisitor):
        def __init__(self,
                     all_layer_names: List[LayerName],
                     inside_layer_index: int,
                     dbu: float,
                     tech_info: TechInfo,
                     scale_ratio_to_fit_halo: bool,
                     results: CellExtractionResults,
                     report: ExtractionReporter):
            super().__init__()

            self.all_layer_names = all_layer_names
            self.inside_layer_index = inside_layer_index
            self.dbu = dbu
            self.tech_info = tech_info
            self.scale_ratio_to_fit_halo = scale_ratio_to_fit_halo
            self.results = results
            self.report = report

            # NOTE: prepare layers below and layers above the "inside" layer,
            #       each prepared for iteration that allows iterativly growing a shield region
            self.layer_below_indices = reversed(range(0, inside_layer_index))
            self.layer_above_indices = range(inside_layer_index,
                                             len(all_layer_names) - inside_layer_index)

        @cached_property
        def inside_layer_name(self) -> LayerName:
            return self.all_layer_names[self.inside_layer_index]

        def begin_polygon(self,
                          layout: kdb.Layout,
                          cell: kdb.Cell,
                          polygon: kdb.Polygon):
            pass

        def end_polygon(self):
            pass

        @cached_property
        def side_halo(self) -> float:
            return self.tech_info.tech.process_parasitics.side_halo

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

            if get_log_level() == LogLevel.DEBUG:
                self.report.output_edge_neighborhood(inside_layer=self.inside_layer_name,
                                                     all_layer_names=self.all_layer_names,
                                                     edge=edge,
                                                     neighborhood=neighborhood,
                                                     geometry_restorer=geometry_restorer)

            for edge_interval, polygons_by_child in neighborhood:
                if not polygons_by_child:
                    continue

                edge_interval_length = edge_interval[1] - edge_interval[0]
                if edge_interval_length <= 1:
                    warning(f"Short edge interval {edge_interval} "
                            f"(length {edge_interval_length * self.dbu * 1000} nm), "
                            f"expected to be dropped due to bext/eext parameters, skipping…")
                    continue

                layer_fringe_shields = [kdb.Region() for _ in self.all_layer_names]
                for child_index, polygons in polygons_by_child.items():
                    if child_index < len(self.all_layer_names):
                        layer_fringe_shields[child_index].insert(polygons)

                # NOTE: lateral fringe shielding, can be caused by
                #         - sidewall (other net)
                #         - same net "sidewall" (other polygons)
                #         - even opposing edges of the same polygon of the same net!
                #       fringe to shapes on other layers will be limited by this distance
                #       (i.e., fringe is shielded beyond this distance)

                nearest_distance: Optional[float] = None
                nearest_lateral_edge: Optional[kdb.EdgeWithProperties] = None

                for child_index, polygons in polygons_by_child.items():
                    if child_index == len(self.all_layer_names):  # TODO, fix index, same layer, same polygon
                        distance, nearby_polygon = find_polygon_with_nearest_edge(polygons_on_same_layer=polygons)

                        if nearest_distance is None or \
                           distance < nearest_distance:
                            nearest_distance = distance
                            nearest_lateral_edge = nearest_edge(nearby_polygon)
                    elif self.inside_layer_index == child_index:   # SIDEWALL!
                        # NOTE: use only the nearest polygon,
                        #       as the others are laterally shielded by the nearer ones
                        distance, nearby_polygon = find_polygon_with_nearest_edge(polygons_on_same_layer=polygons)

                        if nearest_distance is None or \
                           distance < nearest_distance:
                            nearest_distance = distance
                            nearest_lateral_edge = nearest_edge(nearby_polygon)

                        self.emit_sidewall(
                            layer_name=self.inside_layer_name,
                            edge=edge,
                            edge_interval=edge_interval,
                            polygon=nearby_polygon,
                            geometry_restorer=geometry_restorer
                        )

                lateral_shield: Optional[kdb.Polygon] = None
                if nearest_lateral_edge is not None:
                    lateral_shield = kdb.Polygon([
                        nearest_lateral_edge.p2,
                        nearest_lateral_edge.p1,
                        kdb.Point(nearest_lateral_edge.p1.x, (self.side_halo + 10) / self.dbu),
                        kdb.Point(nearest_lateral_edge.p2.x, (self.side_halo + 10) / self.dbu),
                    ])

                for child_index, polygons in polygons_by_child.items():
                    if self.inside_layer_index == child_index:
                        continue  # already handled above
                    elif child_index < len(self.all_layer_names): # FRINGE!
                        fringe_shield = kdb.Region()
                        if lateral_shield is not None:
                            fringe_shield.insert(lateral_shield)
                        if child_index < self.inside_layer_index:
                            r = range(child_index + 1, self.inside_layer_index)
                            for idx in r:
                                fringe_shield += layer_fringe_shields[idx]
                        elif self.inside_layer_index < child_index:
                            r = range(self.inside_layer_index + 1, child_index)
                            for idx in r:
                                fringe_shield += layer_fringe_shields[idx]

                        # NOTE:
                        #    polygons can have different nets
                        #    polygons can be segmented after shield is applied

                        self.emit_fringe(
                            inside_layer_name=self.inside_layer_name,
                            outside_layer_name=self.all_layer_names[child_index],
                            edge=edge,
                            edge_interval=edge_interval,
                            outside_polygons=polygons,
                            shield=fringe_shield,
                            lateral_shield=lateral_shield,
                            geometry_restorer=geometry_restorer)

        def emit_sidewall(self,
                          layer_name: LayerName,
                          edge: kdb.EdgeWithProperties,
                          edge_interval: EdgeInterval,
                          polygon: kdb.PolygonWithProperties,
                          geometry_restorer: GeometryRestorer):
            net1 = edge.property('net')
            net2 = polygon.property('net')

            if net1 == net2:
                return

            sidewall_cap_spec = self.tech_info.sidewall_cap_by_layer_name[layer_name]

            # TODO!

            # NOTE: this method is always called for a single nearest edge (line), so the
            #       polygons have 4 points.
            #       Polygons points are sorted clockwise, so the edge
            #       that goes from right-to-left is the nearest edge
            # nearby_opposing_edge = [e for e in nearest_lateral_shape[1].each_edge() if e.d().x < 0][-1]
            # nearby_opposing_edge_trans = geometry_restorer.restore_edge(edge) * nearby_opposing_edge

            # C = Csidewall * l * t / s
            # C = Csidewall * l / s

            avg_length = edge_interval[1] - edge_interval[0]
            avg_distance = min(polygon.bbox().p1.y, polygon.bbox().p2.y)

            outside_edge = nearest_edge(polygon)

            length_um = avg_length * self.dbu
            distance_um = avg_distance * self.dbu

            # NOTE: dividing by 2 (like MAGIC this not bidirectional),
            #       but we count 2 sidewall contributions (one for each side of the cap)
            cap_femto = ((length_um * sidewall_cap_spec.capacitance)
                         / (distance_um + sidewall_cap_spec.offset)
                         / 2.0  # non-bidirectional (half)
                         / 1000.0)  # aF -> fF

            # info(f"(Sidewall) layer {layer_name}: Nets {net1} <-> {net2}: {round(cap_femto, 5)} fF")

            swk = SidewallKey(layer=layer_name, net1=net1, net2=net2)
            sw_cap = SidewallCap(key=swk,
                                 cap_value=cap_femto,
                                 distance=distance_um,
                                 length=length_um,
                                 tech_spec=sidewall_cap_spec)
            self.results.add_sidewall_cap(sw_cap)

            self.report.output_sidewall(
                sidewall_cap=sw_cap,
                inside_edge=geometry_restorer.restore_edge_interval(edge_interval),
                outside_edge=geometry_restorer.restore_edge(outside_edge)
            )

        def fringe_cap(self,
                       edge_interval_length: float,
                       distance_near: float,
                       distance_far: float,
                       overlap_cap_spec: CapacitanceInfo.OverlapCapacitance,
                       sideoverlap_cap_spec: CapacitanceInfo.SideOverlapCapacitance) -> float:
            distance_near_um = distance_near * self.dbu
            distance_far_um = distance_far * self.dbu
            edge_interval_length_um = edge_interval_length * self.dbu

            # NOTE: overlap scaling is 1/50  (see MAGIC ExtTech)
            alpha_scale_factor = 0.02 * 0.01 * 0.5 * 200.0
            alpha_c = overlap_cap_spec.capacitance * alpha_scale_factor

            # see Magic ExtCouple.c L1164
            cnear = (2.0 / math.pi) * math.atan(alpha_c * distance_near_um)
            cfar = (2.0 / math.pi) * math.atan(alpha_c * distance_far_um)

            if self.scale_ratio_to_fit_halo:
                full_halo_ratio = (2.0 / math.pi) * math.atan(alpha_c * self.side_halo)
                # NOTE: for a large enough halo, full_halo would be 1,
                #       but it is smaller, so we compensate
                if full_halo_ratio < 1.0:
                    cnear /= full_halo_ratio
                    cfar /= full_halo_ratio

            # "cfrac" is the fractional portion of the fringe cap seen
            # by tile tp along its length.  This is independent of the
            # portion of the boundary length that tile tp occupies.
            cfrac = cfar - cnear

            cap_femto = (cfrac * edge_interval_length_um *
                         sideoverlap_cap_spec.capacitance / 1000.0)

            return cap_femto

        def emit_fringe(self,
                        inside_layer_name: LayerName,
                        outside_layer_name: LayerName,
                        edge: kdb.EdgeWithProperties,
                        edge_interval: EdgeInterval,
                        outside_polygons: List[kdb.PolygonWithProperties],
                        shield: kdb.Region,
                        lateral_shield: kdb.Polygon,
                        geometry_restorer: GeometryRestorer):
            inside_net_name = self.tech_info.internal_substrate_layer_name \
                if inside_layer_name == self.tech_info.internal_substrate_layer_name \
                else edge.property('net')

            # NOTE: each polygon in outside_polygons
            #          - could have a different net
            #          - could be segmented by a shield into multiple polygons
            #            each with different near/far regions

            outside_net_names = [
                self.tech_info.internal_substrate_layer_name \
                if outside_layer_name == self.tech_info.internal_substrate_layer_name \
                else p.property('net')
                for p in outside_polygons
            ]

            same_net_markers = [
                inside_net_name == outside_net_name
                for outside_net_name in outside_net_names
            ]

            # NOTE: overlap_cap_by_layer_names is top/bot (dict is not symmetric)
            overlap_cap_spec = self.tech_info.overlap_cap_by_layer_names[inside_layer_name].get(outside_layer_name,
                                                                                                None)
            if not overlap_cap_spec:
                overlap_cap_spec = self.tech_info.overlap_cap_by_layer_names[outside_layer_name][inside_layer_name]

            substrate_cap_spec = self.tech_info.substrate_cap_by_layer_name[inside_layer_name]
            sideoverlap_cap_spec = self.tech_info.side_overlap_cap_by_layer_names[inside_layer_name][
                outside_layer_name]

            polygons_by_net: Dict[NetName, List[kdb.PolygonWithProperties]] = defaultdict(list)

            for idx, p in enumerate(outside_polygons):
                outside_net = outside_net_names[idx]
                is_same_net = same_net_markers[idx]

                if is_same_net:
                    # TODO: log?
                    continue

                if shield.is_empty():
                    polygons_by_net[outside_net].append(p)
                else:
                    unshielded_region = kdb.Region(p)
                    unshielded_region.enable_properties()
                    unshielded_region -= shield
                    if unshielded_region.is_empty():
                        # TODO: log?
                        continue

                    for up in unshielded_region.each():
                        up = kdb.PolygonWithProperties(up, {'net': outside_net})
                        polygons_by_net[outside_net].append(up)
                        # if p != up:
                        #    print(f"Unshieleded polygon {up}, differs from original polygon {p}")

            for outside_net_name, polygons in polygons_by_net.items():
                for p in polygons:
                    bbox = p.bbox()
                    if not p.is_box():
                        warning(f"Side overlap, polygon {p} is not a box. "
                                f"Currently, only boxes are supported, will be using bounding box {bbox}")

                    distance_near = bbox.p1.y  # + 1
                    if distance_near < 0:
                        distance_near = 0
                    distance_far = bbox.p2.y  # - 2
                    if distance_far < 0:
                        distance_far = 0
                    try:
                        assert distance_near >= 0
                        assert distance_far >= distance_near
                    except AssertionError:
                        print()
                        raise

                    if distance_far == distance_near:
                        return

                    edge_interval_length = edge_interval[1] - edge_interval[0]
                    edge_interval_length_um = edge_interval_length * self.dbu

                    cap_femto = self.fringe_cap(edge_interval_length=edge_interval_length,
                                                distance_near=distance_near,
                                                distance_far=distance_far,
                                                overlap_cap_spec=overlap_cap_spec,
                                                sideoverlap_cap_spec=sideoverlap_cap_spec)

                    if cap_femto > 0.0001:  # TODO: configurable threshold, but keeping accumulation might also be nice
                        # info(f"(Side Overlap) "
                        #      f"{inside_layer_name}({inside_net_name})-{outside_layer_name}({outside_net_name}): "
                        #      f"{round(cap_femto, 5)} fF, "
                        #      f"edge interval length = {round(edge_interval_length_um, 2)} µm")

                        sok = SideOverlapKey(layer_inside=inside_layer_name,
                                             net_inside=inside_net_name,
                                             layer_outside=outside_layer_name,
                                             net_outside=outside_net_name)
                        soc = SideOverlapCap(key=sok, cap_value=cap_femto)
                        self.results.add_sideoverlap_cap(soc)

                        self.report.output_sideoverlap(
                            sideoverlap_cap=soc,
                            inside_edge=geometry_restorer.restore_edge_interval(edge_interval),
                            outside_polygon=geometry_restorer.restore_polygon(p),
                            lateral_shield=geometry_restorer.restore_polygon(lateral_shield) \
                                           if lateral_shield is not None else None
                        )
