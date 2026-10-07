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
from klayout_pex.rcx25.c.device_capacitor_plates import DeviceCapacitorPlates
from klayout_pex.rcx25.c.overlap_extractor import OverlapExtractor
from klayout_pex.rcx25.c.sidewall_and_fringe_extractor import SidewallAndFringeExtractor
from klayout_pex.rcx25.r.r_extractor import RExtractor

import klayout_pex_protobuf.kpex.geometry.shapes_pb2 as shapes_pb2
import klayout_pex_protobuf.kpex.layout.location_pb2 as location_pb2
import klayout_pex_protobuf.kpex.request.pex_request_pb2 as pex_request_pb2
import klayout_pex_protobuf.kpex.result.pex_result_pb2 as pex_result_pb2
import klayout_pex_protobuf.kpex.klayout.r_extractor_tech_pb2 as rex_tech_pb2
from klayout_pex_protobuf.kpex.klayout.r_extractor_tech_pb2 import RExtractorTech as pb_RExtractorTech


class CExtractionTechError(Exception):
    """
    The tech info can't model the capacitances of the layout
    """
    pass


class RCX25Extractor:
    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 pex_mode: PEXMode,
                 scale_ratio_to_fit_halo: bool,
                 delaunay_amax: float,
                 delaunay_b: float,
                 tech_info: TechInfo,
                 report_path: str,
                 report_caps: bool):
        """
        :param report_caps: the report has each capacitance contribution with its shapes (see ExtractionReporter)
        """
        self.pex_context = pex_context
        self.pex_mode = pex_mode
        self.scale_ratio_to_fit_halo = scale_ratio_to_fit_halo
        self.delaunay_amax = delaunay_amax
        self.delaunay_b = delaunay_b
        self.tech_info = tech_info
        self.report_path = report_path
        self.report_caps = report_caps

        if "PolygonWithProperties" not in kdb.__all__:
            raise Exception("KLayout version does not support properties (needs 0.30 at least)")

    # TODO: remove this function by inlining
    def gds_pair(self, layer_name) -> Optional[GDSPair]:
        return self.tech_info.gds_pair(layer_name)

    def shapes_of_layer(self, layer_name: str, mark_device_capacitor_plates: bool = False) -> Optional[kdb.Region]:
        gds_pair = self.gds_pair(layer_name=layer_name)
        if not gds_pair:
            return None

        shapes = self.pex_context.shapes_of_layer(gds_pair=gds_pair,
                                                  mark_device_capacitor_plates=mark_device_capacitor_plates)
        if not shapes:
            debug(f"Nothing extracted for layer {layer_name}")

        return shapes

    def substrate_region(self) -> kdb.Region:
        """
        The substrate below the layout (and its halo), the bottom plate of the capacitances to the substrate,
        split into its wells, of the nets of the wells (e.g. VDD), and the rest, of the substrate (VSUBS)
        """
        dbu = self.pex_context.dbu
        side_halo_um = self.tech_info.tech.process_parasitics.side_halo
        rest = kdb.Region(self.pex_context.top_cell_bbox().enlarged(side_halo_um / dbu))  # e.g. 8 µm halo

        substrate_region = kdb.Region()
        substrate_region.enable_properties()

        def insert(region: kdb.Region, net_name: NetName):
            for polygon in region.each():
                substrate_region.insert(kdb.PolygonWithProperties(polygon.downcast(), {'net': net_name}))

        # NOTE: where wells overlap (e.g. an nwell within a deep nwell), the first one is at the surface
        for well_layer_name in self.tech_info.tech.substrate.well_lvs_layer_names:
            wells = self.shapes_of_layer(well_layer_name)
            if wells is None:
                continue
            for well in wells.merged().each():  # NOTE: merged per net
                well_region = kdb.Region(well.downcast()) & rest
                rest -= well_region
                insert(well_region, well.property('net'))

        insert(rest, self.tech_info.internal_substrate_layer_name)
        return substrate_region

    def extract(self) -> ExtractionResults:
        extraction_results = ExtractionResults()

        # TODO: for now, we always flatten and have only 1 cell
        cell_name = self.pex_context.annotated_top_cell.name
        extraction_report = ExtractionReporter(cell_name=cell_name,
                                               dbu=self.pex_context.dbu,
                                               report_caps=self.report_caps)
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

        layer_regions_by_name[self.tech_info.internal_substrate_layer_name] = self.substrate_region()

        # NOTE: the diffusion (the source/drain of the transistors) is above the substrate, which it shields,
        #       and below the metal layers, of whose capacitances it's the bottom plate
        for diffusion_layer in self.tech_info.process_diffusion_layers:
            diffusion_shapes = self.shapes_of_layer(diffusion_layer.name)
            if diffusion_shapes is not None:
                diffusion_shapes.enable_properties()
                gds_pair = self.gds_pair(diffusion_layer.name)
                canonical_layer_name = self.tech_info.canonical_layer_name_by_gds_pair[gds_pair]
                layer_regions_by_name[canonical_layer_name] += diffusion_shapes
                layer_regions_by_name[canonical_layer_name].enable_properties()

        via_name_below_layer_name: Dict[LayerName, Optional[LayerName]] = {}
        via_name_above_layer_name: Dict[LayerName, Optional[LayerName]] = {}
        via_regions_by_via_name: Dict[LayerName, kdb.Region] = defaultdict(kdb.Region)

        previous_via_name: Optional[str] = None

        for metal_layer in self.tech_info.process_metal_layers:
            layer_name = metal_layer.name
            gds_pair = self.gds_pair(layer_name)
            canonical_layer_name = self.tech_info.canonical_layer_name_by_gds_pair[gds_pair]

            # NOTE: with --blackbox, the plates of the capacitor devices are marked (see DeviceCapacitorPlates)
            all_layer_shapes = self.shapes_of_layer(layer_name,
                                                    mark_device_capacitor_plates=self.pex_context.blackbox_devices)
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
            # NOTE: a layer pair without an overlap capacitance would miss its capacitances,
            #       which is never intended (#217), e.g. the plates of a MIM cap in white-box mode,
            #       but for the capacitances of the devices (e.g. of the diffusion to the substrate)
            missing_overlap_caps = [f"{top_layer_name} over {bottom_layer_name}"
                                    for idx, bottom_layer_name in enumerate(all_layer_names)
                                    for top_layer_name in all_layer_names[idx + 1:]
                                    if not self.tech_info.overlap_cap_by_layer_names
                                                         .get(top_layer_name, {}).get(bottom_layer_name, None)
                                    and not self.tech_info.is_device_capacitance(top_layer_name, bottom_layer_name)]
            if missing_overlap_caps:
                raise CExtractionTechError(
                    "The tech info has no overlap capacitance for these layer pairs of the layout, "
                    "so their capacitances would be missing (e.g. the plates of a MIM cap, "
                    "which --blackbox leaves to the device model):\n" +
                    '\n'.join(f"  - {pair}" for pair in missing_overlap_caps)
                )

            # NOTE: with --blackbox, the capacitances between the plates of a capacitor device
            #       (e.g. the fingers of a MOM cap) are left to its model
            device_capacitor_plates = DeviceCapacitorPlates.from_circuit(
                circuit=self.pex_context.top_circuit,
                device_class_names=self.tech_info.device_models.metal_capacitor_class_names
            ) if self.pex_context.blackbox_devices else DeviceCapacitorPlates()

            overlap_extractor = OverlapExtractor(
                all_layer_names=all_layer_names,
                layer_regions_by_name=layer_regions_by_name,
                dbu=dbu,
                tech_info=self.tech_info,
                device_capacitor_plates=device_capacitor_plates,
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
                device_capacitor_plates=device_capacitor_plates,
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
