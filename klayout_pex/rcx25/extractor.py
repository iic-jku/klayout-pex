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

import klayout.db as kdb

from .r.conductance import Conductance
from ..klayout.lvsdb_extractor import KLayoutExtractionContext, GDSPair
from ..log import (
    debug,
    warning,
    info,
    subproc
)
from ..tech_info import TechInfo
from .extraction_results import *
from .extraction_reporter import ExtractionReporter
from .pex_mode import PEXMode
from klayout_pex.rcx25.c.overlap_extractor import OverlapExtractor
from klayout_pex.rcx25.c.sidewall_and_fringe_extractor import SidewallAndFringeExtractor
from .r.resistor_extraction import ResistorExtraction
from .r.resistor_network import (
    ResistorNetworks,
    ViaResistor,
    ViaJunction,
    MultiLayerResistanceNetwork
)


class RCExtractor:
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
            if all_layer_shapes is None:
                continue

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
            rex = ResistorExtraction(b=self.delaunay_b, amax=self.delaunay_amax)

            c: kdb.Circuit = netlist.top_circuit()
            info(f"LVSDB: found {c.pin_count()}pins")

            result_network = MultiLayerResistanceNetwork(
                resistor_networks_by_layer={},
                via_resistors=[]
            )

            devices: List[kdb.Device] = list(c.each_device())
            for d in devices:
                # https://www.klayout.de/doc-qt5/code/class_Device.html
                param_defs = d.device_class().parameter_definitions()
                params = {p.name: d.parameter(p.id()) for p in param_defs}

                dc: kdb.DeviceClass = d.device_class()
                da: kdb.DeviceAbstract = d.device_abstract

                terminal_definitions = [td.name for td in dc.terminal_definitions()]

                # https://www.klayout.de/0.26/doc/code/class_DeviceAbstract.html
                # NOTE: the Device Abstract has the goemetrical model for the device!
                #      each device is represented by a cell

                info(f"Device id={d.id()}, name={d.name}, expanded_name={d.expanded_name()}, "
                     f"device_class={dc}, device_class.name={dc.name}, "
                     f"device_terminal_definitions={terminal_definitions}, "
                     f"trans={d.trans}, "
                     f"parameter_definitions={list(map(lambda p: p.description, param_defs))}, "
                     f"params={params}")

                # terminal_cluster_ids = [da.cluster_id_for_terminal(td.id())
                #                         for td in d.device_class().terminal_definitions()]

                info(f"Device id={d.id()}, name={d.name}, expanded_name={d.expanded_name()}, "
                     f"Device abstract cell index={da.cell_index()}")

                device_cell_name = self.pex_context.annotated_layout.cell_name(da.cell_index())
                device_cell: kdb.Cell = self.pex_context.annotated_layout.cell(device_cell_name)
                info(f"annotated layout cell for cell index {da.cell_index()}: {device_cell_name}")  # TODO: internal_layout() for annotated?!
                # cl = self.pex_context.lvsdb.internal_layout().cell_name(da.cell_index())
                # info(f"annotated layout cell for cell index {da.cell_index()}: {cl}")

                for td in dc.terminal_definitions():
                    n = d.net_for_terminal(td.id())

                    for lyr_idx in device_cell.layout().layer_indexes():
                        terminal_shapes = device_cell.shapes(lyr_idx)
                        if len(terminal_shapes) >= 1:
                            info(f"Device {d.expanded_name()}, Terminal {td.name} (net {n.name}): {terminal_shapes}")

                    #
                    # for metal_layer in self.tech_info.process_metal_layers:
                    #     layer_name = metal_layer.name
                    #     gds_pair = self.gds_pair(layer_name)
                    #     # canonical_layer_name = self.tech_info.canonical_layer_name_by_gds_pair[gds_pair]
                    #     lyr_idx = self.pex_context.annotated_layout.find_layer(*gds_pair)
                    #     if lyr_idx is None:
                    #         continue
                    #     sh_iter: kdb.RecursiveShapeIterator = self.pex_context.annotated_layout.begin_shapes(device_cell, lyr_idx)
                    #     if not sh_iter.at_end():
                    #         terminal_shapes = kdb.Region(sh_iter)
                    #         info(f"Device {d.expanded_name()}, Terminal {td.name} (net {n.name}): {terminal_shapes}")



            for layer_name, region in layer_regions_by_name.items():
                if layer_name == self.tech_info.internal_substrate_layer_name:
                    continue

                gds_pair = self.gds_pair(layer_name)
                pins = self.pex_context.pins_of_layer(gds_pair)
                labels = self.pex_context.labels_of_layer(gds_pair)

                layer_sheet_resistance = self.tech_info.layer_resistance_by_layer_name[layer_name]

                # TODO: include device terminals


                nodes = kdb.Region()
                nodes.enable_properties()

                nodes.insert(pins)

                # create additional nodes for vias
                via_above = via_name_above_layer_name.get(layer_name, None)
                if via_above is not None:
                    # labels.insert(kdb.Text())
                    nodes.insert(via_regions_by_via_name[via_above])
                via_below = via_name_below_layer_name.get(layer_name, None)
                if via_below is not None:
                    nodes.insert(via_regions_by_via_name[via_below])

                nodes = nodes.sized(-1)  # TODO: with the subtraction done in ResistorExtraction
                                         #       we have the problem that
                                         #       if metal_layer_region == via_region, the Region is empty

                resistor_networks = rex.extract(polygons=region, pins=nodes, labels=labels)

                result_network.resistor_networks_by_layer[layer_name] = resistor_networks

                subproc(f"Layer {layer_name}   (R_coeff = {layer_sheet_resistance.resistance}):")
                for rn in resistor_networks.networks:
                    # print(rn.to_string(True))
                    subproc("\tNodes:")
                    for node_id in rn.node_to_s.keys():
                        loc = rn.locations[node_id]
                        node_name = rn.node_names[node_id]
                        subproc(f"\t\tNode #{node_id} {node_name} at {loc} ({loc.x * dbu} µm, {loc.y * dbu} µm)")

                    subproc("\tResistors:")
                    visited_resistors: Set[Conductance] = set()
                    for node_id, resistors in rn.node_to_s.items():
                        node_name = rn.node_names[node_id]
                        for conductance, other_node_id in resistors:
                            if conductance in visited_resistors:
                                continue # we don't want to add it twice, only once per direction!
                            visited_resistors.add(conductance)

                            other_node_name = rn.node_names[other_node_id]
                            ohm = layer_sheet_resistance.resistance / 1000.0 / conductance.cond
                            # TODO: layer_sheet_resistance.corner_adjustment_fraction not yet used !!!
                            subproc(f"\t\t{node_name} ↔︎ {other_node_name}: {round(ohm, 3)} Ω    (internally: {conductance.cond})")

            # "Stitch" in the VIAs into the graph
            for layer_idx_bottom, layer_name_bottom in enumerate(all_layer_names):
                if layer_name_bottom == self.tech_info.internal_substrate_layer_name:
                    continue

                via = self.tech_info.contact_above_metal_layer_name.get(layer_name_bottom, None)
                if via is None:
                    continue

                via_gds_pair = self.gds_pair(via.name)
                canonical_via_name = self.tech_info.canonical_layer_name_by_gds_pair[via_gds_pair]

                via_region = via_regions_by_via_name.get(canonical_via_name)
                if via_region is None:
                    continue

                r_coeff = self.tech_info.via_resistance_by_layer_name[canonical_via_name].resistance

                layer_name_top = all_layer_names[layer_idx_bottom + 1]

                networks_bottom = result_network.resistor_networks_by_layer[layer_name_bottom]
                networks_top = result_network.resistor_networks_by_layer[layer_name_top]

                for via_polygon in via_region:
                    matches_bottom = networks_bottom.find_network_nodes(location=via_polygon)
                    # info(matches_bottom)
                    matches_top = networks_top.find_network_nodes(location=via_polygon)
                    # info(matches_top)

                    # given a drawn via area, we calculate the actual via matrix
                    approx_width = math.sqrt(via_polygon.area()) * dbu
                    n_xy = 1 + math.floor((approx_width - (via.width + 2 * via.border)) / (via.width + via.spacing))
                    r_via_ohm = r_coeff / n_xy**2 / 1000.0   # mΩ -> Ω

                    info(f"via ({canonical_via_name}) found between "
                         f"metals {layer_name_bottom} ↔ {layer_name_top} at {via_polygon}, "
                         f"{n_xy}x{n_xy} (w={via.width}, sp={via.spacing}, border={via.border}), "
                         f"{r_via_ohm} Ω")

                    match_bottom = matches_bottom[0] if len(matches_bottom) == 1 else (None, -1)
                    match_top = matches_top[0] if len(matches_top) == 1 else (None, -1)

                    via_resistor = ViaResistor(
                        bottom=ViaJunction(layer_name=layer_name_bottom,
                                           network=match_bottom[0],
                                           node_id=match_bottom[1]),
                        top=ViaJunction(layer_name=layer_name_top,
                                        network=match_top[0],
                                        node_id=match_top[1]),
                        resistance=r_via_ohm
                    )
                    result_network.via_resistors.append(via_resistor)

            info(result_network)

        return results
