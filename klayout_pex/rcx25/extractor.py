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
import klayout_pex_protobuf.process_stack_pb2 as process_stack_pb2


EdgeInterval = Tuple[float, float]
ChildIndex = int
EdgeNeighborhood = List[Tuple[EdgeInterval, Dict[ChildIndex, List[kdb.Polygon]]]]


class RCExtractor:
    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 tech_info: TechInfo,
                 report_path: str):
        self.pex_context = pex_context
        self.tech_info = tech_info
        self.report_path = report_path

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
        report = rdb.ReportDatabase(f"PEX {cell_name}")
        cell_extraction_result = self.extract_cell(cell_name=cell_name, report=report)
        extraction_results.cell_extraction_results[cell_name] = cell_extraction_result

        report.save(self.report_path)

        return extraction_results

    def extract_cell(self,
                     cell_name: CellName,
                     report: rdb.ReportDatabase) -> CellExtractionResults:
        netlist: kdb.Netlist = self.pex_context.lvsdb.netlist()
        dbu = self.pex_context.dbu

        extraction_results = CellExtractionResults(cell_name=cell_name)

        rdb_cell = report.create_cell(cell_name)
        rdb_cat_common = report.create_category("Common")
        rdb_cat_sidewall_old = report.create_category("Sidewall (legacy space_check)")
        rdb_cat_sidewall = report.create_category("Sidewall (EdgeNeighborhoodVisitor)")
        rdb_cat_overlap = report.create_category("Overlap")
        rdb_cat_fringe = report.create_category("Fringe / Side Overlap")

        def rdb_output(parent_category: rdb.RdbCategory,
                       category_name: str,
                       shapes: kdb.Shapes | kdb.Region | List[kdb.Edge]):
            rdb_cat = report.create_category(parent_category, category_name)
            report.create_items(rdb_cell.rdb_id(),  ## TODO: if later hierarchical mode is introduced
                                rdb_cat.rdb_id(),
                                kdb.CplxTrans(mag=dbu),
                                shapes)

        # ------------------------------------------------------------------------

        layer_by_name: Dict[LayerName, process_stack_pb2.ProcessStackInfo.LayerInfo] = {}
        layer_regions_by_name: Dict[LayerName, kdb.Region] = defaultdict(kdb.Region)
        all_region = kdb.Region()
        all_region.enable_properties()

        substrate_region = kdb.Region()
        substrate_region.enable_properties()
        substrate_region.insert(self.pex_context.top_cell_bbox().enlarged(8.0 / dbu))  # 8 µm halo
        substrate_layer_name = self.tech_info.internal_substrate_layer_name

        for metal_layer in self.tech_info.process_metal_layers:
            layer_name = metal_layer.name
            gds_pair = self.gds_pair(layer_name)
            canonical_layer_name = self.tech_info.canonical_layer_name_by_gds_pair[gds_pair]

            all_layer_shapes = self.shapes_of_layer(layer_name) or kdb.Region()
            all_layer_shapes.enable_properties()

            layer_regions_by_name[canonical_layer_name] += all_layer_shapes
            layer_regions_by_name[canonical_layer_name].enable_properties()
            all_region += all_layer_shapes


        # ------------------------------------------------------------------------

        class PEXEdgeNeighborhoodVisitor(kdb.EdgeNeighborhoodVisitor):
            def __init__(self,
                         child_names: List[str],
                         tech_info: TechInfo,
                         report_category: rdb.RdbCategory):
                self.child_names = child_names
                # NOTE: child_names[0] is the inside net (foreign)
                #       child_names[1] is the shielded net (between layers)
                #       child_names[2:] are the outside nets
                self.tech_info = tech_info
                self.report_category = report_category

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
                        edge: kdb.Edge,
                        neighborhood: EdgeNeighborhood):
                #
                # NOTE: this complex operation will automatically rotate every edge to be on the x-axis
                #       going from 0 to edge.length
                #       so we only have to consider the y-axis to get the near and far distances
                #

                # TODO: consider z-shielding!

                for (x1, x2), polygons_by_net in neighborhood:
                    if not polygons_by_net:
                        continue

                    edge_interval_length = x2 - x1

        for layer_name, layer_region in layer_regions_by_name.items():
            rdb_cat_layer = report.create_category(rdb_cat_common, f"Layer {layer_name}")

            other_layer_names = [oln for oln in layer_regions_by_name.keys() if oln != layer_name]

            visitor = PEXEdgeNeighborhoodVisitor(
                child_names=[layer_name, other_layer_names],
                tech_info=self.tech_info,
                report_category=rdb_cat_layer
            )

            # children = [kdb.CompoundRegionOperationNode.new_secondary(shapes_inside_net),
            children = [kdb.CompoundRegionOperationNode.new_primary(),
                        kdb.CompoundRegionOperationNode.new_foreign()]
            children += [kdb.CompoundRegionOperationNode.new_secondary(layer_regions_by_name[other_layer_name])
                         for other_layer_name in other_layer_names]

            side_halo_um = self.tech_info.tech.process_parasitics.side_halo
            side_halo_dbu = int(side_halo_um / dbu) + 1  # add 1 nm to halo

            node = kdb.CompoundRegionOperationNode.new_edge_neighborhood(
                children=children,
                visitor=visitor,
                bext=0, # bext
                eext=0, # eext,
                din=0, # din
                dout=side_halo_dbu # dout
            )

            layer_region.complex_op(node)

        return extraction_results
