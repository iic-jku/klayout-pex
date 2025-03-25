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

from functools import cached_property

import klayout.rdb as rdb
import klayout.db as kdb

from .extraction_results import *
from klayout_pex.rcx25.c.geometry_restorer import GeometryRestorer
from .types import EdgeNeighborhood, LayerName
from ..klayout.lvsdb_extractor import KLayoutDeviceInfo

VarShapes = kdb.Shapes | kdb.Region | List[kdb.Edge] | List[kdb.Polygon]


class ExtractionReporter:
    def __init__(self,
                 cell_name: str,
                 dbu: float):
        self.report = rdb.ReportDatabase(f"PEX {cell_name}")
        self.cell = self.report.create_cell(cell_name)
        self.dbu_trans = kdb.CplxTrans(mag=dbu)
        self.category_name_counter: Dict[str, int] = defaultdict(int)

    @cached_property
    def cat_common(self) -> rdb.RdbCategory:
        return self.report.create_category('Common')

    @cached_property
    def cat_pins(self) -> rdb.RdbCategory:
        return self.report.create_category("Pins")

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
                       devices_by_name: Dict[str, KLayoutDeviceInfo]):
        for d in devices_by_name.values():
            self.output_device(d)

    def output_device(self,
                      device: KLayoutDeviceInfo):
        cat_device = self.report.create_category(
            self.cat_devices,
            f"{device.name}: {device.class_name}"
        )
        cat_device_params = self.report.create_category(cat_device, 'Params')
        for name, value in device.params.items():
            self.report.create_category(cat_device_params, f"{name}: {value}")

        cat_device_terminals = self.report.create_category(cat_device, 'Terminals')
        for t in device.terminals.terminals:
            if t.regions_by_layer_name:
                for layer_name, regions in t.regions_by_layer_name.items():
                    self.output_shapes(
                        cat_device_terminals,
                        f"{t.name}: net {t.net_name}, layer {layer_name}",
                        regions
                    )
            else:
                self.report.create_category(
                    cat_device_terminals,
                    f"{t.name}: net <NOT CONNECTED> (TODO layer/shapes)",
                )

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
