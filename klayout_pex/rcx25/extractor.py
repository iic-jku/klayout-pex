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

from ..klayout.lvsdb_extractor import KLayoutExtractionContext, GDSPair
from ..log import (
    debug,
    warning,
    error,
    info,
    subproc,
    rule
)
from ..tech_info import TechInfo
from .extraction_results import *
from .extraction_reporter import ExtractionReporter
from .pex_mode import PEXMode
from klayout_pex.rcx25.c.overlap_extractor import OverlapExtractor
from klayout_pex.rcx25.c.sidewall_and_fringe_extractor import SidewallAndFringeExtractor
from klayout_pex.rcx25.r.r_extractor import RExtractor

import klayout_pex_protobuf.kpex.geometry.shapes_pb2 as shapes_pb2
import klayout_pex_protobuf.kpex.layout.location_pb2 as location_pb2
import klayout_pex_protobuf.kpex.request.pex_request_pb2 as pex_request_pb2
import klayout_pex_protobuf.kpex.result.pex_result_pb2 as pex_result_pb2
import klayout_pex_protobuf.kpex.klayout.r_extractor_tech_pb2 as rex_tech_pb2
from klayout_pex_protobuf.kpex.klayout.r_extractor_tech_pb2 import RExtractorTech as pb_RExtractorTech


class RCX25Extractor:
    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 pex_mode: PEXMode,
                 scale_ratio_to_fit_halo: bool,
                 delaunay_amax: float,
                 delaunay_b: float,
                 tech_info: TechInfo,
                 report_path: str):
        self.pex_context = pex_context
        self.pex_mode = pex_mode
        self.scale_ratio_to_fit_halo = scale_ratio_to_fit_halo
        self.delaunay_amax = delaunay_amax
        self.delaunay_b = delaunay_b
        self.tech_info = tech_info
        self.report_path = report_path

        if "PolygonWithProperties" not in kdb.__all__:
            raise Exception("KLayout version does not support properties (needs 0.30 at least)")

    # TODO: remove this function by inlining
    def gds_pair(self, layer_name) -> Optional[GDSPair]:
        return self.tech_info.gds_pair(layer_name)

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

        # Explicitly log the stacktrace here, because otherwise Exceptions 
        # raised in the callbacks of *NeighborhoodVisitors can cause RuntimeErrors
        # that are not traceable beyond the Region.complex_op() calls
        try:
            self.extract_cell(results=cell_extraction_results,
                              report=extraction_report)
        except RuntimeError as e:
            import traceback
            print(f"Caught a RuntimeError: {e}")
            traceback.print_exc()
            raise

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

        layer_regions_by_name[self.tech_info.internal_substrate_layer_name] = substrate_region

        via_name_below_layer_name: Dict[LayerName, Optional[LayerName]] = {}
        via_name_above_layer_name: Dict[LayerName, Optional[LayerName]] = {}
        via_regions_by_via_name: Dict[LayerName, kdb.Region] = defaultdict(kdb.Region)

        previous_via_name: Optional[str] = None

        for metal_layer in self.tech_info.process_metal_layers:
            layer_name = metal_layer.name
            gds_pair = self.gds_pair(layer_name)
            canonical_layer_name = self.tech_info.canonical_layer_name_by_gds_pair[gds_pair]

            all_layer_shapes = self.shapes_of_layer(layer_name)
            if all_layer_shapes is not None:
                all_layer_shapes.enable_properties()

                layer_regions_by_name[canonical_layer_name] += all_layer_shapes
                layer_regions_by_name[canonical_layer_name].enable_properties()
                all_region += all_layer_shapes

            if metal_layer.metal_layer.HasField('contact_above'):
                contact = metal_layer.metal_layer.contact_above

                via_regions = self.shapes_of_layer(contact.name)
                if via_regions is not None:
                    via_regions.enable_properties()
                    via_regions_by_via_name[contact.name] += via_regions
                via_name_above_layer_name[canonical_layer_name] = contact.name
                via_name_below_layer_name[canonical_layer_name] = previous_via_name

                previous_via_name = contact.name
            else:
                previous_via_name = None

        all_layer_names = list(layer_regions_by_name.keys())

        # ------------------------------------------------------------------------
        if self.pex_mode.need_capacitance():
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

        # ------------------------------------------------------------------------
        if self.pex_mode.need_resistance():
            c: kdb.Circuit = netlist.top_circuit()
            info(f"LVSDB: found {c.pin_count()}pins")

            # FIXME:
            #   currenly, tesselation does not work:
            #   https://github.com/KLayout/klayout/issues/2100
            r_extractor = RExtractor(pex_context=self.pex_context,
                                     substrate_algorithm=pb_RExtractorTech.Algorithm.ALGORITHM_SQUARE_COUNTING,
                                     #substrate_algorithm = pb_RExtractorTech.Algorithm.ALGORITHM_TESSELATION,
                                     wire_algorithm = pb_RExtractorTech.Algorithm.ALGORITHM_SQUARE_COUNTING,
                                     delaunay_b = self.delaunay_b,
                                     delaunay_amax = self.delaunay_amax,
                                     via_merge_distance = 0,
                                     skip_simplify = True)
            rex_request = r_extractor.prepare_request()
            report.output_rex_request(request=rex_request)

            rex_result = r_extractor.extract(rex_request)
            report.output_rex_result(result=rex_result)

            #
            # node_by_id: Dict[int, r_network_pb2.RNode] = {}
            # subproc("\tNodes:")
            # for node in rex_result.nodes:
            #     node_by_id[node.node_id] = node
            #
            #     msg = f"\t\tNode #{hex(node.node_id)} '{node.node_name}' " \
            #           f"of net '{node.net_name}' " \
            #           f"on layer '{node.layer_name}' "
            #     match node.location.kind:
            #         case location_pb2.Location.Kind.LOCATION_KIND_POINT:
            #             p = node.location.point
            #             msg += f"at {p.x},{p.y} ({p.x * dbu} µm, {p.y * dbu} µm)"
            #         case location_pb2.Location.Kind.LOCATION_KIND_BOX:
            #             b = node.location.box
            #             msg += f"at {b.lower_left.x},{b.lower_left.y};{b.upper_right.x},{b.upper_right.y} (" \
            #                    f"B/L {round(b.lower_left.x * dbu, 3)},"\
            #                    f"{round(b.lower_left.y * dbu, 3)} µm, " \
            #                    f"T/R {round(b.upper_right.x * dbu, 3)},"\
            #                    f"{round(b.upper_right.y * dbu)} µm)"
            #     subproc(msg)
            #
            # subproc("\tElements:")
            # for element in rex_result.elements:
            #     node_a = node_by_id[element.node_a.node_id]
            #     node_b = node_by_id[element.node_b.node_id]
            #     subproc(f"\t\t{node_a.node_name} (port net '{node_a.net_name}') "
            #             f"↔︎ {node_b.node_name} (port net '{node_b.net_name}') "
            #             f"{round(element.resistance, 3)} Ω")

            results.r_extraction_result = rex_result

        return results
