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
    error,
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
    DeviceTerminal,
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
            rex = ResistorExtraction(b=self.delaunay_b, amax=self.delaunay_amax)

            c: kdb.Circuit = netlist.top_circuit()
            info(f"LVSDB: found {c.pin_count()}pins")

            result_network = MultiLayerResistanceNetwork(
                resistor_networks_by_layer={},
                via_resistors=[]
            )

            devices_by_name = self.pex_context.devices_by_name
            report.output_devices(devices_by_name)

            node_count_by_net: Dict[str, int] = defaultdict(int)

            for layer_name, region in layer_regions_by_name.items():
                if layer_name == self.tech_info.internal_substrate_layer_name:
                    continue

                layer_sheet_resistance = self.tech_info.layer_resistance_by_layer_name.get(layer_name, None)
                if layer_sheet_resistance is None:
                    continue

                gds_pair = self.gds_pair(layer_name)
                pins = self.pex_context.pins_of_layer(gds_pair)
                labels = self.pex_context.labels_of_layer(gds_pair)

                nodes = kdb.Region()
                nodes.enable_properties()

                pin_labels: kdb.Texts = labels & pins
                for l in pin_labels:
                    l: kdb.Text
                    # NOTE: because we want more like a point as a junction
                    #       and folx create huge pins (covering the whole metal)
                    #       we create our own "mini squares"
                    #    (ResistorExtractor will subtract the pins from the metal polygons,
                    #     so in the extreme case the polygons could become empty)
                    pin_point = l.bbox().enlarge(5)
                    nodes.insert(pin_point)

                    report.output_pin(layer_name=layer_name,
                                      pin_point=pin_point,
                                      label=l)

                def create_nodes_for_region(region: kdb.Region):
                    for p in region:
                        p: kdb.PolygonWithProperties
                        cp: kdb.Point = p.bbox().center()
                        b = kdb.Box(w=6, h=6)
                        b.move(cp.x - b.width() / 2,
                               cp.y - b.height() / 2)
                        bwp = kdb.BoxWithProperties(b, p.properties())

                        net = bwp.property('net')
                        if net is None or net == '':
                            error(f"Could not find net for via at {cp}")
                        else:
                            label_text = f"{net}.n{node_count_by_net[net]}"
                            node_count_by_net[net] += 1
                            label = kdb.Text(label_text, cp.x, cp.y)
                            labels.insert(label)

                        nodes.insert(bwp)

                # create additional nodes for vias
                via_above = via_name_above_layer_name.get(layer_name, None)
                if via_above is not None:
                    create_nodes_for_region(via_regions_by_via_name[via_above])
                via_below = via_name_below_layer_name.get(layer_name, None)
                if via_below is not None:
                    create_nodes_for_region(via_regions_by_via_name[via_below])

                extracted_resistor_networks = rex.extract(polygons=region, pins=nodes, labels=labels)
                resistor_networks = ResistorNetworks(
                    layer_name=layer_name,
                    layer_sheet_resistance=layer_sheet_resistance.resistance,
                    networks=extracted_resistor_networks
                )

                result_network.resistor_networks_by_layer[layer_name] = resistor_networks

                subproc(f"Layer {layer_name}   (R_coeff = {layer_sheet_resistance.resistance}):")
                for rn in resistor_networks.networks:
                    # print(rn.to_string(True))
                    if not rn.node_to_s:
                        continue

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
                if (layer_idx_bottom + 1) == len(all_layer_names):
                    break

                via = self.tech_info.contact_above_metal_layer_name.get(layer_name_bottom, None)
                if via is None:
                    continue

                via_gds_pair = self.gds_pair(via.name)
                canonical_via_name = self.tech_info.canonical_layer_name_by_gds_pair[via_gds_pair]

                via_region = via_regions_by_via_name.get(canonical_via_name)
                if via_region is None:
                    continue

                # NOTE: poly layer stands for poly/nsdm/psdm, this will be in contacts, not in vias
                via_resistance = self.tech_info.via_resistance_by_layer_name.get(canonical_via_name, None)
                r_coeff: Optional[float] = None
                if via_resistance is None:
                    r_coeff = self.tech_info.contact_resistance_by_layer_name[layer_name_bottom].resistance
                else:
                    r_coeff = via_resistance.resistance

                layer_name_top = all_layer_names[layer_idx_bottom + 1]

                networks_bottom = result_network.resistor_networks_by_layer[layer_name_bottom]
                networks_top = result_network.resistor_networks_by_layer[layer_name_top]

                for via_polygon in via_region:
                    net_name = via_polygon.property('net')
                    matches_bottom = networks_bottom.find_network_nodes(location=via_polygon)

                    device_terminal: Optional[Tuple[DeviceTerminal, float]] = None

                    if len(matches_bottom) == 0:
                        ignored_device_layers: Set[str] = set()

                        def find_device_terminal(via_region: kdb.Region) -> Optional[Tuple[DeviceTerminal, float]]:
                            for d in devices_by_name.values():
                                for dt in d.terminals.terminals:
                                    for ln, r in dt.regions_by_layer_name.items():
                                        res = self.tech_info.contact_resistance_by_layer_name.get(ln, None)
                                        if res is None:
                                            ignored_device_layers.add(ln)
                                            continue
                                        elif r.overlapping(via_region):
                                            return (DeviceTerminal(device=d, device_terminal=dt), res)
                            return None

                        if layer_name_bottom in self.tech_info.contact_resistance_by_layer_name.keys():
                            device_terminal = find_device_terminal(via_region=kdb.Region(via_polygon))
                        if device_terminal is None:
                            warning(f"Couldn't find bottom network node (on {layer_name_bottom}) "
                                    f"for location {via_polygon}, "
                                    f"but could not find a device terminal either "
                                    f"(ignored layers: {ignored_device_layers})")
                        else:
                            r_coeff = device_terminal[1].resistance

                    matches_top = networks_top.find_network_nodes(location=via_polygon)
                    if len(matches_top) == 0:
                        error(f"Could not find top network nodes for location {via_polygon}")

                    # given a drawn via area, we calculate the actual via matrix
                    approx_width = math.sqrt(via_polygon.area()) * dbu
                    n_xy = 1 + math.floor((approx_width - (via.width + 2 * via.border)) / (via.width + via.spacing))
                    if n_xy < 1:
                        n_xy = 1
                    r_via_ohm = r_coeff / n_xy**2 / 1000.0   # mΩ -> Ω

                    info(f"via ({canonical_via_name}) found between "
                         f"metals {layer_name_bottom} ↔ {layer_name_top} at {via_polygon}, "
                         f"{n_xy}x{n_xy} (w={via.width}, sp={via.spacing}, border={via.border}), "
                         f"{r_via_ohm} Ω")

                    report.output_via(via_name=canonical_via_name,
                                      bottom_layer=layer_name_bottom,
                                      top_layer=layer_name_top,
                                      net=net_name,
                                      via_width=via.width,
                                      via_spacing=via.spacing,
                                      via_border=via.border,
                                      polygon=via_polygon,
                                      ohm=r_via_ohm,
                                      comment=f"({len(matches_bottom)} bottom, {len(matches_top)} top)")

                    match_top = matches_top[0] if len(matches_top) == 1 else (None, -1)

                    bottom: ViaJunction | DeviceTerminal
                    if device_terminal is None:
                        match_bottom = matches_bottom[0] if len(matches_bottom) == 1 else (None, -1)
                        bottom = ViaJunction(layer_name=layer_name_bottom,
                                             network=match_bottom[0],
                                             node_id=match_bottom[1])
                    else:
                        bottom = device_terminal[0]

                    via_resistor = ViaResistor(
                        bottom=bottom,
                        top=ViaJunction(layer_name=layer_name_top,
                                        network=match_top[0],
                                        node_id=match_top[1]),
                        resistance=r_via_ohm
                    )
                    result_network.via_resistors.append(via_resistor)

            # import rich.pretty
            # rich.pretty.pprint(result_network)
            results.resistor_network = result_network

        return results
