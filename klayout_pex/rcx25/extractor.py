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

import klayout.db as kdb

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
from .overlap_extractor import OverlapExtractor
from .sidewall_and_fringe_extractor import SidewallAndFringeExtractor
from .types import EdgeInterval


class RCExtractor:
    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 scale_ratio_to_fit_halo: bool,
                 tech_info: TechInfo,
                 report_path: str):
        self.pex_context = pex_context
        self.scale_ratio_to_fit_halo = scale_ratio_to_fit_halo
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
        cell_name = self.pex_context.annotated_top_cell.name
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

        side_halo_um = self.tech_info.tech.process_parasitics.side_halo
        substrate_region.insert(self.pex_context.top_cell_bbox().enlarged(side_halo_um / dbu))  # e.g. 8 µm halo

        layer_regions_by_name[ self.tech_info.internal_substrate_layer_name] = substrate_region

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

        overlap_extractor = OverlapExtractor(
            all_layer_names=all_layer_names,
            layer_regions_by_name=layer_regions_by_name,
            dbu=dbu,
            tech_info=self.tech_info,
            results=results,
            report=report
        )
        overlap_extractor.extract()

        sidewall_and_fringe_extractor = SidewallAndFringeExtractor(
            all_layer_names=all_layer_names,
            layer_regions_by_name=layer_regions_by_name,
            dbu=dbu,
            scale_ratio_to_fit_halo=self.scale_ratio_to_fit_halo,
            tech_info=self.tech_info,
            results=results,
            report=report
        )
        sidewall_and_fringe_extractor.extract()

        return results
