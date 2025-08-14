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

import klayout.db as kdb

from klayout_pex.log import (
    info,
    warning,
)
from klayout_pex.tech_info import TechInfo

from klayout_pex.rcx25.types import PolygonNeighborhood
from klayout_pex.rcx25.extraction_results import *
from klayout_pex.rcx25.extraction_reporter import ExtractionReporter


class OverlapExtractor:
    def __init__(self,
                 all_layer_names: List[LayerName],
                 layer_regions_by_name: Dict[LayerName, kdb.Region],
                 dbu: float,
                 tech_info: TechInfo,
                 results: CellExtractionResults,
                 report: ExtractionReporter):
        self.all_layer_names = all_layer_names
        self.layer_regions_by_name = layer_regions_by_name
        self.dbu = dbu
        self.tech_info = tech_info
        self.results = results
        self.report = report

    def extract(self):
        for idx, (layer_name, layer_region) in enumerate(self.layer_regions_by_name.items()):
            ovl_visitor = self.PEXPolygonNeighborhoodVisitor(
                layer_names=self.all_layer_names,
                inside_layer_index=idx,
                dbu=self.dbu,
                tech_info=self.tech_info,
                results=self.results,
                report=self.report
            )

            # See comment above: as we use the layers in the stack order,
            # the input index is also the metal layer index
            ovl_children = [kdb.CompoundRegionOperationNode.new_secondary(r)
                            for r in self.layer_regions_by_name.values()]

            # We don't use a distance - hence only true overlaps will be considered
            ovl_node = kdb.CompoundRegionOperationNode.new_polygon_neighborhood(ovl_children, ovl_visitor)

            layer_region.complex_op(ovl_node)

    class PEXPolygonNeighborhoodVisitor(kdb.PolygonNeighborhoodVisitor):
        def __init__(self,
                     layer_names: List[LayerName],
                     inside_layer_index: int,
                     dbu: float,
                     tech_info: TechInfo,
                     results: CellExtractionResults,
                     report: ExtractionReporter):
            super().__init__()
            self.layer_names = layer_names
            self.inside_layer_index = inside_layer_index
            self.dbu = dbu
            self.tech_info = tech_info
            self.results = results
            self.report = report

        def neighbors(self,
                      layout: kdb.Layout,
                      cell: kdb.Cell,
                      polygon: kdb.PolygonWithProperties,
                      neighborhood: PolygonNeighborhood):
            # We just look "upwards", as we don't want to count areas twice

            shielded_region = kdb.Region()
            bottom_region = kdb.Region(polygon)
            bot_layer_name = self.layer_names[self.inside_layer_index]
            net_bot = self.tech_info.internal_substrate_layer_name \
                if bot_layer_name == self.tech_info.internal_substrate_layer_name \
                else polygon.property('net')

            for other_layer_index in range(self.inside_layer_index + 1, len(self.layer_names)):
                polygons_above = neighborhood.get(other_layer_index, None)
                if polygons_above is None:
                    continue

                for polygon_above in polygons_above:
                    net_top = polygon_above.property('net')

                    if net_top == net_bot:
                        continue

                    top_layer_name = self.layer_names[other_layer_index]

                    top_overlap_specs = self.tech_info.overlap_cap_by_layer_names.get(top_layer_name, None)
                    if not top_overlap_specs:
                        warning(f"No overlap cap specified for layer top={top_layer_name}")
                        return
                    overlap_cap_spec = top_overlap_specs.get(bot_layer_name, None)
                    if not overlap_cap_spec:
                        warning(f"No overlap cap specified for layer bottom={bot_layer_name}")
                        return

                    top_region = kdb.Region(polygon_above)

                    overlap_area = top_region.__and__(bottom_region) - shielded_region

                    overlap_area_um2 = overlap_area.area() * self.dbu ** 2
                    cap_femto = overlap_area_um2 * overlap_cap_spec.capacitance / 1000.0
                    # info(f"(Overlap): {top_layer_name}({net_top})-{bot_layer_name}({net_bot}): "
                    #     f"cap: {round(cap_femto, 2)} fF, "
                    #     f"area: {overlap_area_um2} µm^2")

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

                        self.results.add_overlap_cap(cap)

                        self.report.output_overlap(overlap_cap=cap,
                                                   bottom_polygon=polygon,
                                                   top_polygon=polygon_above,
                                                   overlap_area=overlap_area)

                    shielded_region.insert(polygon_above)
