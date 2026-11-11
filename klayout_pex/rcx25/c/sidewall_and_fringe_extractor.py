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

from functools import cached_property, partial
import math

import klayout.db as kdb

from klayout_pex.log import (
    debug,
    info,
    get_log_level,
    LogLevel
)
from klayout_pex.tech_info import TechInfo

from klayout_pex.rcx25.c.device_capacitor_plates import DeviceCapacitorPlates
from klayout_pex.rcx25.c.device_capacitance_checks import CHECK_DEVICE_PROPERTY
from klayout_pex.rcx25.c.capacitance_integrals import (
    EdgeCapacitanceProfile, fringe_alpha, fringe_capacitance, fringe_normalization,
    sidewall_capacitance, sidewall_separation
)
from klayout_pex.rcx25.c.geometry_restorer import GeometryRestorer
from klayout_pex.rcx25.extraction_results import *
from klayout_pex.rcx25.extraction_reporter import ExtractionReporter
from klayout_pex.rcx25.c.polygon_utils import find_polygon_with_nearest_edge, nearest_edge, vertical_trapezoids
from klayout_pex.rcx25.types import EdgeInterval, EdgeNeighborhood
from klayout_pex_protobuf.kpex.tech.process_parasitics_pb2 import CapacitanceInfo


class SidewallAndFringeExtractor:
    def __init__(self,
                 all_layer_names: List[LayerName],
                 layer_regions_by_name: Dict[LayerName, kdb.Region],
                 dbu: float,
                 scale_ratio_to_fit_halo: bool,
                 tech_info: TechInfo,
                 device_capacitor_plates: DeviceCapacitorPlates,
                 mos_channels: kdb.Region,
                 results: CellExtractionResults,
                 report: ExtractionReporter):
        """
        :param mos_channels: the channels of the transistors, whose gate edges along them have no fringe
                             to the substrate and wells (see emit_fringe)
        """
        self.all_layer_names = all_layer_names
        self.layer_regions_by_name = layer_regions_by_name
        self.dbu = dbu
        self.scale_ratio_to_fit_halo = scale_ratio_to_fit_halo
        self.tech_info = tech_info
        self.device_capacitor_plates = device_capacitor_plates
        self.results = results
        self.report = report

        # NOTE: found by their boxes, as each gate edge looks them up
        self.mos_channels = kdb.Shapes()
        for channel in mos_channels.each():
            self.mos_channels.insert(channel)

        self.all_layer_regions = layer_regions_by_name.values()

    @staticmethod
    def has_fringe(tech_info: TechInfo, layer_name: LayerName) -> bool:
        """
        Whether the edges of the layer have a fringe to the other layers

        NOTE: the substrate (with its wells) and the diffusion are the bottom plates of the capacitances
              of the layers above, whose fringe ends at them, while their own edges have none
              (like in the magic techs): those between them are the devices' (e.g. the junctions)
        """
        return layer_name != tech_info.internal_substrate_layer_name and \
            layer_name not in tech_info.process_diffusion_layer_names

    def extract(self):
        bounded_neighbors = [self.bounded_neighbors(region) for region in self.all_layer_regions]
        for idx, (layer_name, layer_region) in enumerate(self.layer_regions_by_name.items()):
            if not self.has_fringe(self.tech_info, layer_name):
                continue

            # NOTE: rotating split polygons for a slanted source edge can round the new vertices differently.
            #       For rectilinear source edges, splitting rectilinear neighbors preserves their geometry exactly.
            neighbors = bounded_neighbors if layer_region.non_rectilinear().is_empty() else self.all_layer_regions

            en_visitor = self.PEXEdgeNeighborhoodVisitor(
                all_layer_names=self.all_layer_names,
                inside_layer_index=idx,
                dbu=self.dbu,
                scale_ratio_to_fit_halo=self.scale_ratio_to_fit_halo,
                tech_info=self.tech_info,
                device_capacitor_plates=self.device_capacitor_plates,
                mos_channels=self.mos_channels,
                results=self.results,
                report=self.report
            )

            en_children = [kdb.CompoundRegionOperationNode.new_secondary(r)
                           for r in neighbors]
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

    @staticmethod
    def bounded_neighbors(region: kdb.Region) -> kdb.Region:
        """
        Splits large rectilinear neighbor polygons so that an edge visits only their nearby parts.
        KLayout merges the parts by their properties when clipping the edge neighborhood, so no artificial
        edges reach the visitor. The source polygons stay whole, including their opposing edges.
        """
        bounded = kdb.Region()
        bounded.enable_properties()
        changed = False
        for polygon in region.each_merged():
            if polygon.num_points() > 64 and polygon.is_rectilinear():
                for part in polygon.break_(64, 0):
                    bounded.insert(kdb.PolygonWithProperties(part, polygon.properties()))
                changed = True
            else:
                bounded.insert(polygon)
        if not changed:
            return region
        # NOTE: otherwise complex_op merges these parts back before looking up an edge's neighbors
        bounded.merged_semantics = False
        return bounded

    # ------------------------------------------------------------------------

    class PEXEdgeNeighborhoodVisitor(kdb.EdgeNeighborhoodVisitor):
        def __init__(self,
                     all_layer_names: List[LayerName],
                     inside_layer_index: int,
                     dbu: float,
                     tech_info: TechInfo,
                     scale_ratio_to_fit_halo: bool,
                     device_capacitor_plates: DeviceCapacitorPlates,
                     mos_channels: kdb.Shapes,
                     results: CellExtractionResults,
                     report: ExtractionReporter):
            super().__init__()

            self.all_layer_names = all_layer_names
            self.inside_layer_index = inside_layer_index
            self.dbu = dbu
            self.tech_info = tech_info
            self.scale_ratio_to_fit_halo = scale_ratio_to_fit_halo
            self.device_capacitor_plates = device_capacitor_plates
            self.mos_channels = mos_channels
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
                    # NOTE: expected, so no warning, which would train to ignore warnings
                    debug(f"Short edge interval {edge_interval} "
                          f"(length {edge_interval_length * self.dbu * 1000} nm), "
                          f"expected to be dropped due to bext/eext parameters, skipping…")
                    continue

                # NOTE: lateral fringe shielding, can be caused by
                #         - sidewall (other net)
                #         - same net "sidewall" (other polygons)
                #         - even opposing edges of the same polygon of the same net!
                #       fringe to shapes on other layers will be limited by this distance
                #       (i.e., fringe is shielded beyond this distance)

                nearest_distance: Optional[float] = None
                nearest_lateral_edge: Optional[kdb.EdgeWithProperties] = None
                nearest_of_same_polygon: Optional[Tuple[float, kdb.PolygonWithProperties]] = None
                nearest_of_other_polygons: Optional[float] = None

                for child_index, polygons in polygons_by_child.items():
                    if child_index == len(self.all_layer_names):  # TODO, fix index, same layer, same polygon
                        distance, nearby_polygon = find_polygon_with_nearest_edge(polygons_on_same_layer=polygons)

                        if nearest_distance is None or \
                           distance < nearest_distance:
                            nearest_distance = distance
                            nearest_lateral_edge = nearest_edge(nearby_polygon)

                        nearest_of_same_polygon = distance, nearby_polygon
                    elif self.inside_layer_index == child_index:   # SIDEWALL!
                        # NOTE: use only the nearest polygon,
                        #       as the others are laterally shielded by the nearer ones
                        distance, nearby_polygon = find_polygon_with_nearest_edge(polygons_on_same_layer=polygons)

                        if nearest_distance is None or \
                           distance < nearest_distance:
                            nearest_distance = distance
                            nearest_lateral_edge = nearest_edge(nearby_polygon)
                        nearest_of_other_polygons = distance

                        self.emit_sidewall(
                            layer_name=self.inside_layer_name,
                            edge=edge,
                            edge_interval=edge_interval,
                            polygon=nearby_polygon,
                            geometry_restorer=geometry_restorer
                        )

                # NOTE: parts of a polygon can be apart in the netlist, e.g. the leads of a coil,
                #       as far as no nearer polygon shields them from each other
                if nearest_of_same_polygon is not None and self.results.has_net_pieces(edge.property('net')) and \
                        (nearest_of_other_polygons is None or nearest_of_same_polygon[0] < nearest_of_other_polygons):
                    self.emit_sidewall(
                        layer_name=self.inside_layer_name,
                        edge=edge,
                        edge_interval=edge_interval,
                        polygon=nearest_of_same_polygon[1],
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

                # Accumulate the intervening layers once in each direction. The
                # current outside layer becomes a shield only for layers beyond it.
                fringe_shields: Dict[int, kdb.Region] = {}
                for indices in (range(self.inside_layer_index - 1, -1, -1),
                                range(self.inside_layer_index + 1, len(self.all_layer_names))):
                    shield = kdb.Region()
                    if lateral_shield is not None:
                        shield.insert(lateral_shield)
                    for idx in indices:
                        if idx in polygons_by_child:
                            fringe_shields[idx] = shield.dup()
                            shield.insert(polygons_by_child[idx])

                for child_index, polygons in polygons_by_child.items():
                    if self.inside_layer_index == child_index:
                        continue  # already handled above
                    elif child_index < len(self.all_layer_names): # FRINGE!
                        # NOTE:
                        #    polygons can have different nets
                        #    polygons can be segmented after shield is applied

                        self.emit_fringe(
                            inside_layer_name=self.inside_layer_name,
                            outside_layer_name=self.all_layer_names[child_index],
                            edge=edge,
                            edge_interval=edge_interval,
                            outside_polygons=polygons,
                            shield=fringe_shields[child_index],
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

            # NOTE: but for the parts of a net that are apart in the netlist
            if net1 == net2 and not self.results.has_net_pieces(net1):
                return

            # NOTE: the model of a device has the capacitance between its plates
            modeled = self.device_capacitor_plates.are_plates_of_a_device(edge, net1, polygon, net2)
            checks = self.device_capacitor_plates.checks
            if modeled and (checks is None or not checks.indexes_for(edge, net1, polygon, net2)):
                return

            sidewall_cap_spec = self.tech_info.sidewall_cap_by_layer_name[layer_name]

            outside_edge = nearest_edge(polygon)
            first_um = outside_edge.p2.y * self.dbu
            last_um = outside_edge.p1.y * self.dbu
            length_um = (edge_interval[1] - edge_interval[0]) * self.dbu
            distance_um = (first_um + last_um) / 2.0

            cap_femto = sidewall_capacitance(length_um, first_um, last_um,
                                             sidewall_cap_spec.capacitance, sidewall_cap_spec.offset)
            profile = None
            if first_um != last_um and (self.results.keep_capacitance_geometry or self.results.exclusions is not None):
                profile = EdgeCapacitanceProfile(partial(sidewall_capacitance, length_um, first_um, last_um,
                                                         sidewall_cap_spec.capacitance, sidewall_cap_spec.offset))

            if modeled:
                checks.record(edge, net1, polygon, net2, 'sidewall', cap_femto)
                return

            # info(f"(Sidewall) layer {layer_name}: Nets {net1} <-> {net2}: {round(cap_femto, 5)} fF")

            inside_edge = geometry_restorer.restore_edge_interval(edge_interval)

            swk = SidewallKey(layer=layer_name, net1=net1, net2=net2)
            sw_cap = SidewallCap(key=swk,
                                 cap_value=cap_femto,
                                 distance=distance_um,
                                 length=length_um,
                                 tech_spec=sidewall_cap_spec,
                                 inside_edge=inside_edge,
                                 # NOTE: the part of the other net facing the edge interval
                                 outside_edge=geometry_restorer.restore_edge(kdb.Edge(outside_edge.p2, outside_edge.p1)),
                                 profile=profile)
            self.results.add_sidewall_cap(sw_cap)

            self.report.output_sidewall(
                sidewall_cap=sw_cap,
                inside_edge=inside_edge,
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

            alpha_c = fringe_alpha(overlap_cap_spec.capacitance)
            if alpha_c == 0.0:
                # NOTE: without an overlap capacitance, none of the fringe is within any distance
                #       (cnear and cfar are 0, like in MAGIC for an overlap multiplier of 0),
                #       so there is none to scale to the halo either
                return 0.0

            # see Magic ExtCouple.c L1164
            cnear = (2.0 / math.pi) * math.atan(alpha_c * distance_near_um)
            cfar = (2.0 / math.pi) * math.atan(alpha_c * distance_far_um)

            if self.scale_ratio_to_fit_halo:
                full_halo_ratio = fringe_normalization(alpha_c, self.side_halo, True)
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

        def is_gate_edge(self, edge: kdb.Edge) -> bool:
            """
            Whether the edge runs along the channel of a transistor (its middle is on the channel's boundary)
            """
            middle = edge.bbox().center()
            return any(shape.polygon.inside(middle)
                       for shape in self.mos_channels.each_touching(kdb.Shapes.SAll, kdb.Box(middle, middle)))

        def emit_fringe(self,
                        inside_layer_name: LayerName,
                        outside_layer_name: LayerName,
                        edge: kdb.EdgeWithProperties,
                        edge_interval: EdgeInterval,
                        outside_polygons: List[kdb.PolygonWithProperties],
                        shield: kdb.Region,
                        lateral_shield: kdb.Polygon,
                        geometry_restorer: GeometryRestorer):
            # NOTE: e.g. the fringe of the gate poly to the source/drain, which the transistor model has
            if self.tech_info.is_device_capacitance(inside_layer_name, outside_layer_name):
                return

            # NOTE: and the fringe of a gate edge along the channel, over the source/drain,
            #       to the substrate or well beyond (#290)
            if outside_layer_name == self.tech_info.internal_substrate_layer_name and \
                    self.is_gate_edge(geometry_restorer.restore_edge_interval(edge_interval)):
                return

            inside_net_name = edge.property('net')

            # NOTE: each polygon in outside_polygons
            #          - could have a different net (e.g. the wells of the substrate and the rest, VSUBS)
            #          - could be segmented by a shield into multiple polygons
            #            each with different near/far regions

            # NOTE: the model of a device has the capacitance between its plates, so they are like one net,
            #       with the fringe from the edge of a plate to the other plate beyond it
            # NOTE: and the parts of a net that are apart in the netlist are like nets of their own
            candidates: List[Tuple[NetName, kdb.PolygonWithProperties]] = []
            checks = self.device_capacitor_plates.checks
            for polygon in outside_polygons:
                outside_net = polygon.property('net')
                if inside_net_name == outside_net and not self.results.has_net_pieces(inside_net_name):
                    continue
                if self.device_capacitor_plates.is_plate_edge_of_a_device(edge, inside_net_name, outside_net) and \
                        (checks is None or not checks.indexes_for(edge, inside_net_name, polygon, outside_net)):
                    continue
                candidates.append((outside_net, polygon))
            if not candidates:
                return

            # NOTE: overlap_cap_by_layer_names is top/bot (dict is not symmetric)
            overlap_cap_spec = self.tech_info.overlap_cap_by_layer_names[inside_layer_name].get(outside_layer_name,
                                                                                                None)
            if not overlap_cap_spec:
                overlap_cap_spec = self.tech_info.overlap_cap_by_layer_names[outside_layer_name][inside_layer_name]

            sideoverlap_cap_spec = self.tech_info.side_overlap_cap_by_layer_names[inside_layer_name][
                outside_layer_name]

            polygons_by_net: Dict[NetName, List[kdb.PolygonWithProperties]] = defaultdict(list)
            shield_is_empty = shield.is_empty()
            shield_intervals = self._full_width_shield_intervals(shield, edge_interval) if not shield_is_empty else None

            for outside_net, p in candidates:
                if shield_is_empty:
                    polygons_by_net[outside_net].append(p)
                else:
                    box = p.bbox() if shield_intervals is not None and p.is_box() else None
                    if box is not None and edge_interval[0] <= box.left and box.right <= edge_interval[1]:
                        unshielded_polygons = self._unshielded_boxes(box, shield_intervals)
                    else:
                        unshielded_region = kdb.Region(p)
                        unshielded_region.enable_properties()
                        unshielded_region -= shield
                        unshielded_polygons = unshielded_region.each()

                    for up in unshielded_polygons:
                        properties = {'net': outside_net}
                        if checks is not None and p.property(CHECK_DEVICE_PROPERTY) is not None:
                            properties[CHECK_DEVICE_PROPERTY] = p.property(CHECK_DEVICE_PROPERTY)
                        up = kdb.PolygonWithProperties(up, properties)
                        polygons_by_net[outside_net].append(up)
                        # if p != up:
                        #    print(f"Unshieleded polygon {up}, differs from original polygon {p}")

            alpha = fringe_alpha(overlap_cap_spec.capacitance)
            normalization = fringe_normalization(alpha, self.side_halo, self.scale_ratio_to_fit_halo)
            for outside_net_name, polygons in polygons_by_net.items():
                key = SideOverlapKey(inside_layer_name, inside_net_name, outside_layer_name, outside_net_name)
                for p in polygons:
                    if p.is_box():
                        bbox = p.bbox()
                        near, far = max(0, bbox.bottom), max(0, bbox.top)
                        cap_femto = self.fringe_cap(bbox.width(), near, far, overlap_cap_spec, sideoverlap_cap_spec)
                        if cap_femto > 0.0001:
                            middle = (near + far) // 2
                            self._record_fringe(key, edge, cap_femto, p, (bbox.left, bbox.right),
                                                kdb.Edge(bbox.left, near, bbox.right, near),
                                                kdb.Edge(bbox.left, middle, bbox.right, middle),
                                                None, lateral_shield, geometry_restorer)
                        continue

                    # Shield subtraction can leave concave polygons and holes.
                    # Keep the cutoff on each original polygon, not on its pieces.
                    parts = []
                    for trapezoid in vertical_trapezoids(p):
                        integral = partial(fringe_capacitance,
                                           (trapezoid.right - trapezoid.left) * self.dbu,
                                           trapezoid.near_left * self.dbu, trapezoid.near_right * self.dbu,
                                           trapezoid.far_left * self.dbu, trapezoid.far_right * self.dbu,
                                           alpha, sideoverlap_cap_spec.capacitance, normalization)
                        parts.append((trapezoid, integral, integral(0.0, 1.0)))
                    if math.fsum(cap for _, _, cap in parts) <= 0.0001:
                        continue
                    for trapezoid, integral, cap_femto in parts:
                        if cap_femto <= 0.0:
                            continue
                        profile = None
                        if self.results.keep_capacitance_geometry or self.results.exclusions is not None:
                            profile = EdgeCapacitanceProfile(integral)
                        self._record_fringe(
                            key, edge, cap_femto, kdb.PolygonWithProperties(trapezoid.polygon(), p.properties()),
                            (trapezoid.left, trapezoid.right),
                            kdb.Edge(trapezoid.left, trapezoid.near_left,
                                      trapezoid.right, trapezoid.near_right),
                            kdb.Edge(trapezoid.left, (trapezoid.near_left + trapezoid.far_left) / 2,
                                      trapezoid.right, (trapezoid.near_right + trapezoid.far_right) / 2),
                            profile, lateral_shield, geometry_restorer)

        @staticmethod
        def _full_width_shield_intervals(shield: kdb.Region,
                                         edge_interval: EdgeInterval) -> Optional[List[Tuple[int, int]]]:
            # Rectilinear edge neighborhoods contain boxes spanning the whole
            # interval. Their union only cuts the vertical extent of a box, so
            # subtraction needs no general polygon operation per candidate.
            intervals = []
            for polygon in shield.each():
                if not polygon.is_box():
                    return None
                box = polygon.bbox()
                if box.left > edge_interval[0] or box.right < edge_interval[1]:
                    return None
                intervals.append((box.bottom, box.top))
            return sorted(intervals)

        @staticmethod
        def _unshielded_boxes(box: kdb.Box, shield_intervals: List[Tuple[int, int]]) -> Iterator[kdb.Box]:
            near = box.bottom
            for bottom, top in shield_intervals:
                if top <= near:
                    continue
                if bottom >= box.top:
                    break
                if bottom > near:
                    yield kdb.Box(box.left, near, box.right, bottom)
                near = max(near, top)
                if near >= box.top:
                    return
            if near < box.top:
                yield kdb.Box(box.left, near, box.right, box.top)

        def _record_fringe(self, key: SideOverlapKey, edge: kdb.EdgeWithProperties,
                           cap_femto: float, polygon: kdb.PolygonWithProperties,
                           interval: EdgeInterval, near_edge: kdb.Edge, outside_edge: kdb.Edge,
                           profile: Optional[EdgeCapacitanceProfile], lateral_shield: Optional[kdb.Polygon],
                           geometry_restorer: GeometryRestorer):
            if self.device_capacitor_plates.is_plate_edge_of_a_device(edge, key.net_inside, key.net_outside):
                checks = self.device_capacitor_plates.checks
                if checks is not None:
                    checks.record(edge, key.net_inside, polygon, key.net_outside, 'fringe', cap_femto)
                return
            inside_edge = geometry_restorer.restore_edge_interval(interval)
            cap = SideOverlapCap(key=key, cap_value=cap_femto, inside_edge=inside_edge,
                                 outside_edge=geometry_restorer.restore_edge(outside_edge),
                                 near_edge=geometry_restorer.restore_edge(near_edge), profile=profile)
            self.results.add_sideoverlap_cap(cap)
            self.report.output_sideoverlap(
                sideoverlap_cap=cap, inside_edge=inside_edge,
                outside_polygon=geometry_restorer.restore_polygon(polygon),
                lateral_shield=geometry_restorer.restore_polygon(lateral_shield)
                if lateral_shield is not None else None)
