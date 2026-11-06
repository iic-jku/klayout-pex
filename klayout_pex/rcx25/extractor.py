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

from ..klayout.lvsdb_extractor import DEVICE_CAPACITOR_PLATE_PROPERTY, KLayoutExtractionContext
from ..log import (
    debug,
    warning,
    error,
    info,
    subproc,
    rule
)
from ..tech_info import TechInfo
from ..types import GDSPair, LVSLayerName
from ..util.peak_memory import log_peak_memory
from .extraction_results import *
from .extraction_reporter import ExtractionReporter
from .exclusion import BlockKind, CutLayers, ExcludedBlock, Exclusions, listed_names
from .netlist_expander import RCX25NetlistExpander
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
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2
from klayout_pex_protobuf.kpex.klayout.r_extractor_tech_pb2 import RExtractorTech as pb_RExtractorTech


class CExtractionTechError(Exception):
    """
    The tech info can't model the capacitances of the layout
    """
    pass


def is_on_tap(lvs_layer_name: LVSLayerName, tech_info: TechInfo) -> bool:
    LP = tech_pb2.LayerInfo.Purpose
    computed_layer_info = tech_info.computed_layer_info_by_name.get(lvs_layer_name, None)
    return computed_layer_info is not None and \
        computed_layer_info.layer_info.purpose in (LP.PURPOSE_NTAP, LP.PURPOSE_PTAP, LP.PURPOSE_NTAP_OR_PTAP)


def is_on_well(lvs_layer_name: LVSLayerName, tech_info: TechInfo) -> bool:
    LP = tech_pb2.LayerInfo.Purpose
    computed_layer_info = tech_info.computed_layer_info_by_name.get(lvs_layer_name, None)
    return computed_layer_info is not None and \
        computed_layer_info.layer_info.purpose in (LP.PURPOSE_NWELL, LP.PURPOSE_PWELL, LP.PURPOSE_DNWELL)


def devices_of_cut_cells(exclusions: Exclusions,
                         pex_context: KLayoutExtractionContext,
                         tech_info: TechInfo) -> Dict[int, int]:
    """
    :return: the devices within the cut cells by their IDs, with the indexes of their blocks: those that a cell draws,
             by the layers that LVS makes them from (see TechInfo.device_gds_pairs), at their terminals, but those
             on the substrate, and on a tap, which goes on beyond the cell, unless the device is a tap
             (see CutCellInstance.draws_device)

    NOTE: by geometry, as the LVS netlist is flat
    """
    cut_block_indexes = {index for index, block in enumerate(exclusions.blocks) if block.kind == BlockKind.CUT}
    if not cut_block_indexes:
        return {}

    lvsdb = pex_context.lvsdb
    substrate_lvs_layer_names = set(tech_info.tech.substrate.lvs_layer_names)
    gds_pairs_by_class: Dict[str, Optional[Set[GDSPair]]] = {}
    blocks: Dict[int, int] = {}
    for device in pex_context.top_circuit.each_device():
        class_name = device.device_class().name
        if class_name not in gds_pairs_by_class:
            gds_pairs_by_class[class_name] = tech_info.device_gds_pairs(class_name)
        gds_pairs = gds_pairs_by_class[class_name]
        if gds_pairs is None:
            continue

        terminals: List[kdb.Region] = []
        on_taps: List[kdb.Region] = []
        is_a_tap = True
        bbox = kdb.Box()
        for terminal_definition in device.device_class().terminal_definitions():
            for reference in pex_context.terminal_refs[(device.id(), terminal_definition.id())]:
                for index, shapes in pex_context.shapes_of_terminal(device, reference).items():
                    lvs_layer_name = lvsdb.layer_name(index)
                    if shapes.is_empty() or lvs_layer_name in substrate_lvs_layer_names:
                        continue
                    if is_on_tap(lvs_layer_name, tech_info):
                        on_taps.append(shapes)
                        continue
                    terminals.append(shapes)
                    bbox += shapes.bbox()
                    is_a_tap &= is_on_well(lvs_layer_name, tech_info)
        if is_a_tap:
            terminals += on_taps
            for shapes in on_taps:
                bbox += shapes.bbox()

        block_index = next((index for index in exclusions.block_indexes_touching(bbox)
                            if index in cut_block_indexes
                            and exclusions.blocks[index].cell_instance.draws_device(gds_pairs, terminals)), None)
        if block_index is not None:
            blocks[device.id()] = block_index

    unknown_classes = sorted(name for name, gds_pairs in gds_pairs_by_class.items() if gds_pairs is None)
    if unknown_classes:
        warning(f"The tech info doesn't tell what LVS makes these device classes from, so the netlist keeps "
                f"their devices, also of the cut cells: {', '.join(unknown_classes)}")
    return blocks


def add_filled_diffusion_to_cut_cells(exclusions: Exclusions,
                                      pex_context: KLayoutExtractionContext,
                                      tech_info: TechInfo):
    """
    The cut cells stand for what LVS computes of their devices where the layout draws no diffusion,
    e.g. the drain of an LDMOS, across the gap to its gate
    """
    diffusion_layer_names = set(tech_info.process_diffusion_layer_names)
    diffusion_gds_pairs = CutLayers.of_tech(tech_info).diffusion_gds_pairs
    for device in pex_context.top_circuit.each_device():
        block_index = exclusions.removed_device_blocks.get(device.id(), None)
        if block_index is None:
            continue
        instance = exclusions.blocks[block_index].cell_instance
        for terminal_definition in device.device_class().terminal_definitions():
            for reference in pex_context.terminal_refs[(device.id(), terminal_definition.id())]:
                for index, shapes in pex_context.shapes_of_terminal(device, reference).items():
                    lvs_layer_name = pex_context.lvsdb.layer_name(index)
                    computed_layer_info = tech_info.computed_layer_info_by_name.get(lvs_layer_name, None)
                    layer_name = computed_layer_info.original_layer_name if computed_layer_info is not None else None
                    # NOTE: not the box of a ring (e.g. the collector of a Schottky diode), which is no gap of a device
                    if layer_name in diffusion_layer_names and not is_on_tap(lvs_layer_name, tech_info):
                        filled = shapes - instance.shapes_of_layout(diffusion_gds_pairs, shapes.bbox())
                        if not filled.is_empty():
                            exclusions.add_to_cut_cell(block_index, layer_name, filled)


def prepare_exclusions(exclusions: Exclusions,
                       pex_context: KLayoutExtractionContext,
                       tech_info: TechInfo):
    """
    Finds the nets within the exclusion blocks that nothing connects to the netlist,
    and warns of what the extraction leaves out with the markers beyond what they stand for
    """
    if not exclusions.blocks:
        return

    exclusions.labels_by_net_name = pex_context.labels_by_net_name
    exclusions.removed_device_blocks = devices_of_cut_cells(exclusions, pex_context, tech_info)
    if exclusions.removed_device_blocks:
        info(f"The netlist leaves out the {len(exclusions.removed_device_blocks)} devices of the cut cells")
        add_filled_diffusion_to_cut_cells(exclusions, pex_context, tech_info)

    K = tech_pb2.ComputedLayerInfo.Kind
    layers_within: Dict[NetName, Set[LayerName]] = defaultdict(set)
    layers_within_markers: Dict[NetName, Set[LayerName]] = defaultdict(set)
    nets_outside: Set[NetName] = set()
    nets_outside_markers: Set[NetName] = set()
    # NOTE: not the wells and the substrate below the markers, which are in the models of what they stand for
    for gds_pair in tech_info.process_conductor_gds_pairs:
        extracted_layer = pex_context.extracted_layers.get(gds_pair, None)
        if extracted_layer is None:
            continue
        layer_name = tech_info.canonical_layer_name_by_gds_pair[gds_pair]
        mask = exclusions.mask(layer_name)
        marker_mask = exclusions.mask(layer_name, kind=BlockKind.MARKER)
        for source_layer in extracted_layer.source_layers:
            kind = tech_info.computed_layer_info_by_name[source_layer.lvs_layer_name].kind
            if kind in (K.KIND_PIN, K.KIND_LABEL):
                continue
            shapes_by_net = pex_context.shapes_by_net_name_by_lvs_layer[source_layer.lvs_layer_name]
            for net_name, shapes in shapes_by_net.items():
                for region, within, outside in ((mask, layers_within, nets_outside),
                                                (marker_mask, layers_within_markers, nets_outside_markers)):
                    box = shapes.bbox()
                    if not box.touches(region.bbox()):
                        outside.add(net_name)
                        continue
                    near = exclusions.regions.near(region, box)
                    if not (shapes & near).is_empty():
                        within[net_name].add(layer_name)
                    if not (shapes - near).is_empty():
                        outside.add(net_name)

    circuit = pex_context.top_circuit
    blackbox_devices = pex_context.blackbox_devices
    device_models = tech_info.device_models

    def is_whiteboxed(device: kdb.Device) -> bool:
        return not blackbox_devices and RCX25NetlistExpander.is_whiteboxed(device.device_class(), device_models)

    def is_removed(device: kdb.Device) -> bool:
        return device.id() in exclusions.removed_device_blocks or is_whiteboxed(device)

    def is_connected(net_name: NetName) -> bool:
        net = circuit.net_by_name(net_name)
        return net is None or net.pin_count() + net.subcircuit_pin_count() > 0 or \
            any(not is_removed(terminal.device()) for terminal in net.each_terminal())

    exclusions.floating_net_names = {net_name for net_name in layers_within
                                     if net_name not in nets_outside and not is_connected(net_name)}

    nets_across = sorted(net_name for net_name in layers_within_markers if net_name in nets_outside_markers)
    if nets_across:
        listed_count = 20
        warning("These nets are partly within exclusion markers, so the extraction leaves out their parasitics "
                "there, for the model of what the markers stand for (a wire across a marker loses them too):\n" +
                '\n'.join(f"  - {net_name}: {', '.join(sorted(layers_within_markers[net_name]))}"
                           for net_name in nets_across[:listed_count]) +
                (f"\n  - and {len(nets_across) - listed_count} more" if len(nets_across) > listed_count else ''))
    if exclusions.floating_net_names:
        info(f"Nothing connects these nets within exclusion markers to the netlist, "
             f"so their capacitances to the rest of the layout go to the substrate: "
             f"{listed_names(sorted(exclusions.floating_net_names))}")

    substrate_lvs_layer_names = set(tech_info.tech.substrate.lvs_layer_names)

    def is_plate_within(block: ExcludedBlock, lvs_layer_name: LVSLayerName, shapes: kdb.Region) -> bool:
        computed_layer_info = tech_info.computed_layer_info_by_name.get(lvs_layer_name, None)
        region = block.region if computed_layer_info is None \
            else block.region_of(computed_layer_info.original_layer_name)
        return region is not None and not (shapes & exclusions.regions.near(region, shapes.bbox())).is_empty()

    def has_plates_within_a_block(device: kdb.Device) -> bool:
        """
        NOTE: all of them, as what a capacitance is left out by has both of its plates within one block
        """
        plates: List[List[Tuple[LVSLayerName, kdb.Region]]] = []
        box = kdb.Box()
        for terminal in device.device_class().terminal_definitions():
            plate: List[Tuple[LVSLayerName, kdb.Region]] = []
            for reference in pex_context.terminal_refs[(device.id(), terminal.id())]:
                for index, shapes in pex_context.shapes_of_terminal(device, reference).items():
                    lvs_layer_name = pex_context.lvsdb.layer_name(index)
                    if not shapes.is_empty() and lvs_layer_name not in substrate_lvs_layer_names:
                        plate.append((lvs_layer_name, shapes))
                        box += shapes.bbox()
            if plate:
                plates.append(plate)
        return any(block.capacitance_pair is None and
                   all(any(is_plate_within(block, *part) for part in plate) for plate in plates)
                   for block in exclusions.blocks_touching(box))

    lost_devices = [d.expanded_name() for d in circuit.each_device()
                    if is_whiteboxed(d) and d.id() not in exclusions.removed_device_blocks
                    and has_plates_within_a_block(d)]
    if lost_devices:
        warning(f"The netlist loses these devices within exclusion markers, as white-box mode (--blackbox n) "
                f"removes them, and the capacitances of their plates are left out, use --blackbox y to keep them: "
                f"{listed_names(sorted(lost_devices))}")


def warn_of_ports_without_nodes(exclusions: Exclusions, netlist_description: str):
    """
    :param netlist_description: of a netlist with one node per net
    """
    if any(block.ports for block in exclusions.blocks):
        warning(f"{netlist_description} has one node per net, so the netlist has no ports where nets enter "
                f"what is left out, use --mode R or RC of the 2.5D engine to connect a model")


class RCX25Extractor:
    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 pex_mode: PEXMode,
                 scale_ratio_to_fit_halo: bool,
                 delaunay_amax: float,
                 delaunay_b: float,
                 tech_info: TechInfo,
                 report_path: str,
                 report_caps: bool,
                 exclusions: Optional[Exclusions] = None):
        """
        :param report_caps: the report has each capacitance contribution with its shapes (see ExtractionReporter)
        :param exclusions: what a model has the parasitics of (see exclusion.py), after prepare_exclusions
        """
        self.pex_context = pex_context
        self.pex_mode = pex_mode
        self.scale_ratio_to_fit_halo = scale_ratio_to_fit_halo
        self.delaunay_amax = delaunay_amax
        self.delaunay_b = delaunay_b
        self.tech_info = tech_info
        self.report_path = report_path
        self.report_caps = report_caps
        self.exclusions = exclusions

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

        NOTE: with --blackbox, its shapes are plates of the capacitor devices with a terminal on the substrate
              (e.g. a VPP cap), see DeviceCapacitorPlates
        """
        dbu = self.pex_context.dbu
        side_halo_um = self.tech_info.tech.process_parasitics.side_halo
        rest = kdb.Region(self.pex_context.top_cell_bbox().enlarged(side_halo_um / dbu))  # e.g. 8 µm halo

        # NOTE: the channels of the transistors aren't substrate the gate poly couples to,
        #       their capacitances are the transistor models' (#290)
        rest -= self.pex_context.mos_channels

        substrate_region = kdb.Region()
        substrate_region.enable_properties()

        plate_properties = {DEVICE_CAPACITOR_PLATE_PROPERTY: True} if self.pex_context.blackbox_devices else {}

        def insert(region: kdb.Region, net_name: NetName):
            for polygon in region.each():
                substrate_region.insert(kdb.PolygonWithProperties(polygon.downcast(),
                                                                  {'net': net_name, **plate_properties}))

        # NOTE: where wells overlap (e.g. an nwell within a deep nwell), the first one is at the surface
        for well_layer_name in self.tech_info.tech.substrate.well_lvs_layer_names:
            gds_pair = self.gds_pair(layer_name=well_layer_name)
            if gds_pair is None:
                continue
            # NOTE: the well's LVS layer only, not the others of its GDS pair (e.g. the pwell around an isolated pwell)
            wells = self.pex_context.shapes_of_layer(gds_pair=gds_pair, lvs_layer_names=[well_layer_name])
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
        # NOTE: in RC mode, the capacitances go onto the resistor network, by their geometry
        cell_extraction_results = CellExtractionResults(
            cell_name=cell_name,
            keep_capacitance_geometry=self.pex_mode == PEXMode.RC,
            substrate_layer_name=self.tech_info.internal_substrate_layer_name,
            substrate_well_layer_names=self.tech_info.substrate_well_layer_names,
            exclusions=self.exclusions
        )

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

        if self.exclusions is not None and not self.pex_mode.need_resistance():
            warn_of_ports_without_nodes(self.exclusions, f"--mode {self.pex_mode}")
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
        # NOTE: before the capacitances, which go by the pieces of the nets with ports at exclusion markers (NetPiece)
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
                                     skip_simplify = True,
                                     exclusions = self.exclusions)
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

            nets_joined_by_substrate = results.nets_joined_by_substrate()
            if nets_joined_by_substrate:
                warning("Only the substrate, a well or a tap joins pieces of the metal of these nets, which the "
                        "resistance network has no resistance for, so the pieces are ideally on their nets: " +
                        ', '.join(nets_joined_by_substrate))
            log_peak_memory('the resistance extraction')

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
            #       (e.g. the fingers of a MOM cap) are left to its model,
            #       and those to the substrate, if the substrate is a terminal of the device (e.g. of a VPP cap)
            device_capacitor_plates = DeviceCapacitorPlates.from_circuit(
                circuit=self.pex_context.top_circuit,
                device_class_names=self.tech_info.device_models.metal_capacitor_class_names,
                substrate_net_name=self.pex_context.substrate_net_name,
                substrate_shapes_net_name=self.tech_info.internal_substrate_layer_name
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
                mos_channels=self.pex_context.mos_channels,
                results=results,
                report=report
            )
            sidewall_and_fringe_extractor.extract()
            log_peak_memory('the capacitance extraction')

        return results
