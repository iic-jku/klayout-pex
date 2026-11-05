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

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import itertools
import math
import re
from typing import *

from klayout_pex.log import (
    info,
    subproc,
    warning,
)

from klayout_pex.types import DeviceID, GDSPair, Label, LayerName, NetName, TerminalID

from klayout_pex.klayout.shapes_pb2_converter import ShapesConverter
from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.klayout.rex_core import klayout_r_extractor_tech
from klayout_pex.rcx25.exclusion import (
    BlockKind,
    BlockLabel,
    Exclusions,
    NetPiece,
    RegionIndex,
    listed_names,
    polygons_by_center_inside,
)
from klayout_pex.util.disjoint_sets import DisjointSets

import klayout_pex_protobuf.kpex.layout.device_pb2 as device_pb2
import klayout_pex_protobuf.kpex.layout.location_pb2 as location_pb2
from klayout_pex_protobuf.kpex.klayout.r_extractor_tech_pb2 import RExtractorTech as pb_RExtractorTech
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2
import klayout_pex_protobuf.kpex.r.r_network_pb2 as r_network_pb2
import klayout_pex_protobuf.kpex.request.pex_request_pb2 as pex_request_pb2
import klayout_pex_protobuf.kpex.result.pex_result_pb2 as pex_result_pb2

import klayout.db as kdb
import klayout.pex as klp


class RExtractionTechError(Exception):
    """
    The tech info can't model layers of the layout for the resistance extraction
    """
    pass


# NOTE: the layer of what is within an exclusion marker is the one of the layout plus this (see ideal_layer_id),
#       only known to the resistance extraction, which identifies its layers by these IDs
IDEAL_LAYER_ID_OFFSET = 1 << 24


def ideal_layer_id(layer_id: int) -> int:
    return layer_id + IDEAL_LAYER_ID_OFFSET


# the widths of the polygon ports at a cut, in DBU
CUT_STRIP_WIDTH = 1
ANY_ANGLE_CUT_STRIP_WIDTH = 5
# the length of the polygon port at a cut along a conductor, in µm, see port_of_cut
PORT_LENGTH_ALONG_CONDUCTOR = 1.0


PolygonPortKey = Tuple[int, int]  # (layer ID, port index)

# what the polygon ports of each layer ID are of, None for the ones at a cut (see split_at_exclusions)
PolygonPortTerminals = Dict[int, List[Optional[device_pb2.Device.Terminal]]]


@dataclass
class PinWithinMarker:
    position: kdb.Point
    layer_id: int
    label: Label
    net_name: NetName


@dataclass
class TerminalWithinMarker:
    terminal: device_pb2.Device.Terminal
    layer_id: int
    box: kdb.Box


class ConnectedShapesWithin:
    """
    Which shapes of a net within the blocks are joined there, by metal or vias, regardless of the rest of the net,
    so that a label on them can name the ports of a cut of only these shapes
    """
    def __init__(self,
                 regions_within: Mapping[int, Mapping[LayerName, kdb.Region]],
                 vias_within: Iterable[Tuple[LayerName, LayerName, kdb.Region]],
                 kept_for_vias: Mapping[LayerName, kdb.Region]):
        self.kept_for_vias = kept_for_vias
        self.shapes_by_layer: Dict[LayerName, kdb.Shapes] = defaultdict(kdb.Shapes)
        polygon_count = 0
        for region_by_layer in regions_within.values():
            for layer_name, region in region_by_layer.items():
                for polygon in region.merged().each():
                    self.shapes_by_layer[layer_name].insert(kdb.PolygonWithProperties(polygon.downcast(),
                                                                                      {'id': polygon_count}))
                    polygon_count += 1

        self.polygon_sets = DisjointSets(range(polygon_count))
        for bottom_layer_name, top_layer_name, vias in vias_within:
            for via in vias.each():
                box = via.bbox()
                bottom, top = self.polygon_at(bottom_layer_name, box), self.polygon_at(top_layer_name, box)
                if bottom is not None and top is not None:
                    self.polygon_sets.union(bottom, top)

    def polygon_at(self, layer_name: LayerName, box: kdb.Box) -> Optional[int]:
        """
        :return: the ID of the polygon on the layer with the largest overlap with the box
        """
        area_by_id: Dict[int, int] = {}
        box_region = kdb.Region(box)
        for shape in self.shapes_by_layer[layer_name].each_touching(kdb.Shapes.SRegions, box):
            area = (kdb.Region(shape.polygon) & box_region).area()
            if area > 0:
                area_by_id[shape.property('id')] = area
        return max(sorted(area_by_id), key=area_by_id.get, default=None)

    def set_at(self, layer_name: LayerName, box: kdb.Box) -> Optional[int]:
        """
        :return: the ID of what is joined to the shapes at the box on the layer, None if there are no shapes
        """
        polygon = self.polygon_at(layer_name, box)
        return None if polygon is None else self.polygon_sets.find(polygon)

    def set_at_position(self, layer_name: LayerName, position: kdb.Point) -> Optional[int]:
        """
        :return: the ID of what is joined to the shapes at the position (e.g. of a pin) on the layer,
                 None if there are no shapes
        """
        box = kdb.Box(position, position).enlarged(1, 1)
        # NOTE: where the metal stays for a via from above, what is around it has the position
        kept = self.kept_for_vias.get(layer_name, None)
        if kept is not None:
            for via in kept.interacting(kdb.Region(box)).each():
                box = via.bbox().enlarged(1, 1)
        return self.set_at(layer_name, box)


@dataclass
class NetSplit:
    """
    What split_at_exclusions tells about the network of a net
    """
    # the polygon ports to join without resistance, of the conductors on both sides of a cut
    polygon_port_ties: List[Tuple[PolygonPortKey, PolygonPortKey]] = field(default_factory=list)
    # with ports at the cuts: their polygon ports (by the box of the strip), and what is within the markers
    cut_port_boxes: Dict[PolygonPortKey, kdb.Box] = field(default_factory=dict)
    # the index of the block of each of them
    cut_port_blocks: Dict[PolygonPortKey, int] = field(default_factory=dict)
    # the terminal of a removed device that each of them stands for, if any,
    # and that a cut is on, which it is one node with then, unless a label names the cut
    cut_port_terminals: Dict[PolygonPortKey, device_pb2.Device.Terminal] = field(default_factory=dict)
    terminals_of_cuts: Dict[PolygonPortKey, device_pb2.Device.Terminal] = field(default_factory=dict)
    pins_within: List[PinWithinMarker] = field(default_factory=list)
    terminals_within: List[TerminalWithinMarker] = field(default_factory=list)
    # the shapes within each marker, by its index, by layer
    regions_within: Dict[int, Dict[LayerName, kdb.Region]] = field(default_factory=lambda: defaultdict(dict))
    # the vias between them: the layers below and above them, and the vias
    vias_within: List[Tuple[LayerName, LayerName, kdb.Region]] = field(default_factory=list)
    # the index of the block of each node of the network at a cut, by the ID of the node
    block_of_node_id: Dict[int, int] = field(default_factory=dict)
    # the blocks with ports that a conductor goes on from one to another, without a cut between them
    abutting_block_indexes: Set[int] = field(default_factory=set)
    # the vias across a cut by the layer of the conductor below or above them, whose metal stays outside the block
    kept_for_vias: Dict[LayerName, kdb.Region] = field(default_factory=dict)
    # whether a conductor goes on beside a block along a cut, see port_of_cut
    has_cut_along_conductor: bool = False


def label_names_net(label: Label, net_name: NetName) -> bool:
    """
    :return: whether KLayout named the net after the label, regardless of case, as SPICE reads names:
             A of A,B (a net of several labels), vss of vss$1 (islands of one name),
             VDD of $1.VDD (a net within a subcircuit)
    """
    label = label.casefold()
    for name in net_name.casefold().split(','):
        for candidate in (name, re.sub(r'\$\d+$', '', name)):
            if candidate == label or candidate.endswith(f".{label}"):
                return True
    return False


def keep_pins_of_top_circuit(net_name: NetName,
                             vertex_ports: Dict[int, List[kdb.Point]],
                             vertex_port_pins: Dict[int, List[Tuple[Label, NetName]]]):
    """
    Keeps the labels of the hierarchy that are pins of the top circuit, like the ports of its LVS netlist:
    a label in a subcell is none on a net that KLayout named after the labels of its own circuit (#403),
    and the first one of a net that no label names (e.g. with labels in subcells only) is the node of its port

    NOTE: after the split at the exclusions, as a label within a marker names the port of the model there,
          also in a subcell (e.g. of an inductor)
    """
    labels = {pin[0] for pins in vertex_port_pins.values() for pin in pins}
    if not labels:
        return
    pin_labels = {label for label in labels if label_names_net(label, net_name)} or {min(labels)}
    for layer_id in list(vertex_port_pins):
        kept = [(point, pin)
                for point, pin in zip(vertex_ports[layer_id], vertex_port_pins[layer_id])
                if pin[0] in pin_labels]
        if kept:
            vertex_ports[layer_id] = [point for point, _ in kept]
            vertex_port_pins[layer_id] = [pin for _, pin in kept]
        else:
            del vertex_ports[layer_id]
            del vertex_port_pins[layer_id]


def port_of_cut(strip: kdb.PolygonWithProperties,
                conductor_near: Callable[[kdb.Box], kdb.Region],
                strip_width: int,
                port_length: int) -> kdb.PolygonWithProperties:
    """
    A polygon port is one node. So it's the whole strip where a conductor enters a block, across the current,
    also of a wide wire. But where the conductor goes on beyond the ends of the strip, the strip is along the current,
    beside metal that it would short (a port can't stand for a model in parallel to that metal),
    so then it's a short piece in the middle of the longest edge of the strip

    :param strip: of a conductor along the cut
    :param conductor_near: the polygons of the conductor at a box
    :param strip_width: of the strip
    :param port_length: of the short piece, in DBU
    """
    box = strip.bbox()
    if box.width() >= box.height():
        ends = (kdb.Box(box.left - 1, box.bottom, box.left, box.top),
                kdb.Box(box.right, box.bottom, box.right + 1, box.top))
    else:
        ends = (kdb.Box(box.left, box.bottom - 1, box.right, box.bottom),
                kdb.Box(box.left, box.top, box.right, box.top + 1))
    if not strip.is_rectilinear() or all((conductor_near(end) & kdb.Region(end)).is_empty() for end in ends):
        return strip

    edge = max(strip.each_edge(), key=lambda e: e.length())
    if edge.length() <= port_length:
        return strip
    middle = kdb.Point((edge.x1 + edge.x2) // 2, (edge.y1 + edge.y2) // 2)
    half_length = port_length // 2
    window = kdb.Box(middle.x - half_length, middle.y - strip_width, middle.x + half_length, middle.y + strip_width) \
        if edge.dy() == 0 else \
        kdb.Box(middle.x - strip_width, middle.y - half_length, middle.x + strip_width, middle.y + half_length)
    return next((kdb.Region(strip.downcast()) & kdb.Region(window)).each())


class RExtractor:
    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 substrate_algorithm: pb_RExtractorTech.Algorithm,
                 wire_algorithm: pb_RExtractorTech.Algorithm,
                 delaunay_b: float,
                 delaunay_amax: float,
                 via_merge_distance: float,
                 skip_simplify: bool,
                 exclusions: Optional[Exclusions] = None):
        """
        :param pex_context: KLayout PEX extraction context
        :param substrate_algorithm: The KLayout PEXCore Algorithm for decomposing polygons.
                                    Either SquareCounting or Tesselation (recommended)
        :param wire_algorithm: The KLayout PEXCore Algorithm for decomposing polygons.
                               Either SquareCounting (recommended) or Tesselation
        :param delaunay_b: The "b" parameter for the Delaunay triangulation,
                           a ratio of shortest triangle edge to circle radius
        :param delaunay_amax: The "max_area" specifies the maximum area of the triangles
                              produced in square micrometers.
        :param via_merge_distance: Maximum distance where close vias are merged together
        :param skip_simplify: skip simplification of resistor network
        :param exclusions: within these, the network has no resistances (see split_at_exclusions)
        """
        self.pex_context = pex_context
        self.substrate_algorithm = substrate_algorithm
        self.wire_algorithm = wire_algorithm
        self.delaunay_b = delaunay_b
        self.delaunay_amax = delaunay_amax
        self.via_merge_distance = via_merge_distance
        self.skip_simplify = skip_simplify
        self.exclusions = exclusions

        self.shapes_converter = ShapesConverter(dbu=self.pex_context.dbu)

    def prepare_r_extractor_tech_pb(self,
                                    rex_tech: pb_RExtractorTech):
        """
        Prepare KLayout PEXCore Technology Description based on the KPEX Tech Info data
        :param rex_tech: RExtractorTech protobuffer message
        """

        rex_tech.skip_simplify = self.skip_simplify

        tech = self.pex_context.tech

        # NOTE: a layer that can't be modeled is not part of the resistance network,
        #       e.g. a via that joins nothing, which splits the networks of its nets.
        #       This is never intended, so it's an error rather than a warning (#217).
        #       It includes the LVS layers the tech info has no layer for (e.g. a via with another name)
        unmodeled_layers: List[str] = list(self.pex_context.unmodeled_layers)

        # NOTE: the resistance extraction works on the layer of a GDS pair, with the shapes of all its LVS layers,
        #       so one model covers them all (e.g. sky130A mcon_con and mcon_vpp, the vias within MOM caps)
        unmodeled_layers_by_gds_pair: Dict[GDSPair, List[str]] = defaultdict(list)
        modeled_gds_pairs: Set[GDSPair] = set()

        substrate_gds_pairs = {tech.gds_pair_for_computed_layer_name[name]
                               for name in tech.tech.substrate.lvs_layer_names
                               if name in tech.gds_pair_for_computed_layer_name}
        wells_without_resistance: Set[str] = set()

        for gds_pair, li in self.pex_context.extracted_layers.items():
            for source_layer in li.source_layers:
                computed_layer_info = tech.computed_layer_info_by_name.get(source_layer.lvs_layer_name, None)
                if computed_layer_info is None:
                    unmodeled_layers_by_gds_pair[gds_pair].append(f"LVS {source_layer.lvs_layer_name} {gds_pair}: "
                                                                  f"no computed layer info")
                    continue

                canonical_layer_name = tech.canonical_layer_name_by_gds_pair[gds_pair]
                layer_description = f"{canonical_layer_name} (LVS {source_layer.lvs_layer_name})"

                LP = tech_pb2.LayerInfo.Purpose

                match computed_layer_info.kind:
                    case tech_pb2.ComputedLayerInfo.Kind.KIND_PIN:
                        continue

                    case tech_pb2.ComputedLayerInfo.Kind.KIND_LABEL:
                        continue

                    case _:
                        pass

                match computed_layer_info.layer_info.purpose:
                    case LP.PURPOSE_NWELL | LP.PURPOSE_PWELL:
                        # NOTE: a well is a conductor between the contacts over its taps, which land on the well
                        #       (e.g. sky130A licon_ntap_con), and the device terminals on it (e.g. the PMOS bulks),
                        #       but the substrate (e.g. IHP pwell_sub, on the GDS pair of pwell), which is ideal,
                        #       as it is 3D bulk rather than a sheet, so the device terminals on it stay on
                        #       the node of their net
                        if gds_pair in substrate_gds_pairs:
                            continue

                        layer_resistance = tech.layer_resistance_by_layer_name.get(canonical_layer_name, None)
                        if layer_resistance is None:
                            wells_without_resistance.add(layer_description)
                            continue

                        cond = rex_tech.conductors.add()

                        cond.layer.id = self.pex_context.annotated_layout.layer(*source_layer.gds_pair)
                        cond.layer.canonical_layer_name = canonical_layer_name
                        cond.layer.lvs_layer_name = source_layer.lvs_layer_name

                        cond.triangulation_min_b = self.delaunay_b
                        cond.triangulation_max_area = self.delaunay_amax

                        cond.algorithm = self.substrate_algorithm
                        cond.resistance = self.pex_context.tech.milliohm_to_ohm(layer_resistance.resistance)
                        modeled_gds_pairs.add(gds_pair)

                    case LP.PURPOSE_DNWELL:
                        # NOTE: no conductor: no via joins the deep nwell to the nwell over it,
                        #       so it would be a piece that joins nothing (see isolated_well_node_ids),
                        #       and gf180mcuD has no sheet resistance for it. Like the substrate,
                        #       the device terminals on it stay on the node of their net (#292)
                        continue

                    case LP.PURPOSE_NTAP | LP.PURPOSE_PTAP:
                        # NOTE: no conductor, the contacts over a tap land on the well below it
                        #       (e.g. sky130A licon_ntap_con on the nwell), neglecting the resistance
                        #       of the tap itself, like the one of the diffusion (e.g. SkyWater rule SR.diff.1)
                        continue

                    case LP.PURPOSE_N_IMPLANT | LP.PURPOSE_P_IMPLANT:
                        # device terminals
                        #   - source/drain (e.g. sky130A: nsdm, psdm)
                        #   - bulk (e.g. nwell)
                        #
                        # we will consider this only as a pin end-point, there are no wires at all on this layer,
                        # so the resistance does not matter for PEX
                        cond = rex_tech.conductors.add()

                        cond.layer.id = self.pex_context.annotated_layout.layer(*source_layer.gds_pair)
                        cond.layer.canonical_layer_name = canonical_layer_name
                        cond.layer.lvs_layer_name = source_layer.lvs_layer_name

                        cond.triangulation_min_b = self.delaunay_b
                        cond.triangulation_max_area = self.delaunay_amax

                        cond.algorithm = self.substrate_algorithm
                        cond.resistance = 0  # see comment above
                        modeled_gds_pairs.add(gds_pair)

                    case LP.PURPOSE_METAL | LP.PURPOSE_MIM_CAP:
                        # NOTE: the top plate of a MIM cap is a thin metal, which the white-box extraction keeps
                        #       (the MIM cap layers are no part of the extraction in the black-box mode)
                        layer_resistance = tech.layer_resistance_by_layer_name.get(canonical_layer_name, None)
                        if layer_resistance is None:
                            unmodeled_layers_by_gds_pair[gds_pair].append(f"{layer_description}: no sheet resistance")
                            continue

                        cond = rex_tech.conductors.add()

                        cond.layer.id = self.pex_context.annotated_layout.layer(*source_layer.gds_pair)
                        cond.layer.canonical_layer_name = canonical_layer_name
                        cond.layer.lvs_layer_name = source_layer.lvs_layer_name

                        cond.triangulation_min_b = self.delaunay_b
                        cond.triangulation_max_area = self.delaunay_amax

                        if canonical_layer_name == tech.internal_substrate_layer_name:
                            cond.algorithm = self.substrate_algorithm
                        else:
                            cond.algorithm = self.wire_algorithm
                        cond.resistance = self.pex_context.tech.milliohm_to_ohm(layer_resistance.resistance)
                        modeled_gds_pairs.add(gds_pair)

                    case LP.PURPOSE_CONTACT:
                        contact = tech.contact_by_contact_lvs_layer_name.get(source_layer.lvs_layer_name, None)
                        if contact is None:
                            unmodeled_layers_by_gds_pair[gds_pair].append(f"{layer_description}: no contact")
                            continue

                        contact_resistance = tech.contact_resistance_by_device_layer_name.get(contact.layer_below,
                                                                                              None)
                        if contact_resistance is None:
                            unmodeled_layers_by_gds_pair[gds_pair].append(
                                f"{layer_description}: no contact resistance for {contact.layer_below}")
                            continue

                        via = rex_tech.vias.add()

                        bot_gds_pair = tech.gds_pair(contact.layer_below)
                        top_gds_pair = tech.gds_pair(contact.metal_above)

                        via.layer.id = self.pex_context.annotated_layout.layer(*source_layer.gds_pair)
                        via.layer.canonical_layer_name = canonical_layer_name
                        via.layer.lvs_layer_name = source_layer.lvs_layer_name

                        via.bottom_conductor.id = self.pex_context.annotated_layout.layer(*bot_gds_pair)
                        via.top_conductor.id = self.pex_context.annotated_layout.layer(*top_gds_pair)

                        via.resistance = self.pex_context.tech.milliohm_by_cnt_to_ohm_by_square_for_contact(
                            contact=contact,
                            contact_resistance=contact_resistance
                        )
                        via.merge_distance = self.via_merge_distance
                        modeled_gds_pairs.add(gds_pair)

                    case LP.PURPOSE_VIA:
                        via_resistance = tech.via_resistance_by_layer_name.get(canonical_layer_name, None)
                        if via_resistance is None:
                            unmodeled_layers_by_gds_pair[gds_pair].append(f"{layer_description}: no via resistance")
                            continue
                        # NOTE: the via of the process stack on the GDS pair, if it has none named after the LVS layer
                        #       (e.g. the vias of a device, which the LVS deck has apart from the others)
                        via_name = tech.process_layer_name_by_lvs_layer_name.get(source_layer.lvs_layer_name,
                                                                                 source_layer.lvs_layer_name)
                        bot_top = tech.bottom_and_top_layer_name_by_via_computed_layer_name.get(via_name, None)
                        if bot_top is None:
                            unmodeled_layers_by_gds_pair[gds_pair].append(f"{layer_description}: no bottom/top layers")
                            continue
                        via = rex_tech.vias.add()

                        (bot, top) = bot_top
                        bot_gds_pair = tech.gds_pair(bot)
                        top_gds_pair = tech.gds_pair(top)

                        via.layer.id = self.pex_context.annotated_layout.layer(*source_layer.gds_pair)
                        via.layer.canonical_layer_name = canonical_layer_name
                        via.layer.lvs_layer_name = source_layer.lvs_layer_name

                        via.bottom_conductor.id = self.pex_context.annotated_layout.layer(*bot_gds_pair)
                        via.top_conductor.id = self.pex_context.annotated_layout.layer(*top_gds_pair)

                        contact = self.pex_context.tech.contact_by_contact_lvs_layer_name[via_name]

                        via.resistance = self.pex_context.tech.milliohm_by_cnt_to_ohm_by_square_for_via(
                            contact=contact,
                            via_resistance=via_resistance
                        )

                        via.merge_distance = self.via_merge_distance
                        modeled_gds_pairs.add(gds_pair)

                    case _:
                        unmodeled_layers_by_gds_pair[gds_pair].append(
                            f"{layer_description}: unhandled layer purpose {LP.Name(computed_layer_info.layer_info.purpose)}")

        for gds_pair, descriptions in unmodeled_layers_by_gds_pair.items():
            if gds_pair not in modeled_gds_pairs:
                unmodeled_layers.extend(descriptions)

        if wells_without_resistance:
            warning("The resistance network leaves out these wells, as the tech info has no sheet resistance "
                    "for them, so the device terminals on them (e.g. the PMOS bulks) are ideally on their nets:\n" +
                    '\n'.join(f"  - {well}" for well in sorted(wells_without_resistance)))

        if unmodeled_layers:
            raise RExtractionTechError(
                "The tech info can't model these layers of the layout for the resistance extraction, "
                "so their connections would be missing from the resistance network:\n" +
                '\n'.join(f"  - {layer}" for layer in unmodeled_layers)
            )

        # NOTE: a via joins the conductors below and above it, but the layout may have none on one side,
        #       e.g. a via without metal below, or a tech info that puts the layer below on another GDS pair
        #       (gf180mcuD before #229), so the resistance network would miss the connection there
        conductor_layer_ids = {c.layer.id for c in rex_tech.conductors}
        vias_without_conductor: Set[str] = set()
        for via in rex_tech.vias:
            for side, conductor in (('below', via.bottom_conductor), ('above', via.top_conductor)):
                if conductor.id in conductor_layer_ids:
                    continue
                layer_info = self.pex_context.annotated_layout.get_info(conductor.id)
                gds_pair = (layer_info.layer, layer_info.datatype)
                layer_name = self.pex_context.tech.canonical_layer_name_by_gds_pair.get(gds_pair, '?')
                problem = 'has no shapes' if gds_pair not in self.pex_context.extracted_layers else 'is no conductor'
                vias_without_conductor.add(f"{via.layer.canonical_layer_name} (LVS {via.layer.lvs_layer_name}): "
                                           f"the layer {side} it, {layer_name} {gds_pair}, {problem}")

        if vias_without_conductor:
            raise RExtractionTechError(
                "These vias have no conductor to join on one side, "
                "so their connections would be missing from the resistance network:\n" +
                '\n'.join(f"  - {via}" for via in sorted(vias_without_conductor))
            )

        if self.exclusions is not None:
            self.add_ideal_layers(rex_tech)

        return rex_tech

    @staticmethod
    def add_ideal_layers(rex_tech: pb_RExtractorTech):
        """
        Adds a copy without resistance of each conductor and via, for what is within an exclusion marker
        (see split_at_exclusions)
        """
        for conductor in list(rex_tech.conductors):
            ideal = rex_tech.conductors.add()
            ideal.CopyFrom(conductor)
            ideal.layer.id = ideal_layer_id(conductor.layer.id)
            ideal.resistance = 0
        for via in list(rex_tech.vias):
            ideal = rex_tech.vias.add()
            ideal.CopyFrom(via)
            ideal.layer.id = ideal_layer_id(via.layer.id)
            ideal.bottom_conductor.id = ideal_layer_id(via.bottom_conductor.id)
            ideal.top_conductor.id = ideal_layer_id(via.top_conductor.id)
            ideal.resistance = 0

    def prepare_request(self) -> pex_request_pb2.RExtractionRequest:
        rex_request = pex_request_pb2.RExtractionRequest()

        # prepare tech info
        self.prepare_r_extractor_tech_pb(rex_tech=rex_request.tech)

        # prepare devices
        devices_by_name = self.pex_context.devices_by_name
        rex_request.devices.MergeFrom(devices_by_name.values())

        # prepare pins
        for pin_list in self.pex_context.pins_pb2_by_layer.values():
            rex_request.pins.MergeFrom(pin_list)

        # NOTE: a label without a pin shape makes no port of its net (e.g. of a wire without devices),
        #       but where the net has a port anyway (e.g. as it has devices), a label that names the net
        #       is the node of that port, rather than a device terminal (#405)
        top_circuit = self.pex_context.top_circuit
        for pin_list in self.pex_context.text_label_pins_pb2_by_layer.values():
            for pin in pin_list:
                net = top_circuit.net_by_name(pin.net_name) if pin.net_name else None
                if net is not None and net.pin_count() > 0 and label_names_net(pin.label, pin.net_name):
                    rex_request.pins.add().CopyFrom(pin)

        net_request_by_name: Dict[NetName, pex_request_pb2.RNetExtractionRequest] = {}
        def get_or_create_net_request(net_name: str):
            v = net_request_by_name.get(net_name, None)
            if not v:
                v = rex_request.net_extraction_requests.add()
                v.net_name = net_name
                net_request_by_name[net_name] = v
            return v

        for pin in rex_request.pins:
            get_or_create_net_request(pin.net_name).pins.add().CopyFrom(pin)

        for device in rex_request.devices:
            for terminal in device.terminals:
                get_or_create_net_request(terminal.net_name).device_terminals.add().CopyFrom(terminal)

        netlist = self.pex_context.lvsdb.netlist()
        circuit = netlist.circuit_by_name(self.pex_context.annotated_top_cell.name)
        # https://www.klayout.de/doc-qt5/code/class_Circuit.html
        if not circuit:
            circuits = [c.name for c in netlist.each_circuit()]
            raise Exception(f"Expected circuit called {self.pex_context.annotated_top_cell.name} in extracted netlist, "
                            f"only available circuits are: {circuits}")
        LK = tech_pb2.ComputedLayerInfo.Kind
        for net in circuit.each_net():
            net_name = net.name or f"${net.cluster_id}"
            for lvs_gds_pair, lyr_info in self.pex_context.extracted_layers.items():
                for lyr in lyr_info.source_layers:
                    li = self.pex_context.tech.computed_layer_info_by_gds_pair[lyr.gds_pair]
                    match li.kind:
                        case LK.KIND_PIN:
                            continue  # skip
                        case LK.KIND_REGULAR | LK.KIND_DEVICE_CAPACITOR | LK.KIND_DEVICE_CAPACITOR_PLATE | \
                             LK.KIND_DEVICE_RESISTOR:
                            r = self.pex_context.shapes_of_net(lyr.gds_pair, net)
                            if not r:
                                continue
                            l2r = get_or_create_net_request(net_name).region_by_layer.add()
                            l2r.layer.id = self.pex_context.annotated_layout.layer(*lvs_gds_pair)
                            l2r.layer.canonical_layer_name = self.pex_context.tech.canonical_layer_name_by_gds_pair[lvs_gds_pair]
                            l2r.layer.lvs_layer_name = lyr.lvs_layer_name
                            self.shapes_converter.klayout_region_to_pb(r, l2r.region)
                        case _:
                            raise NotImplementedError()

        return rex_request

    @staticmethod
    def node_name(rn: klp.RNode, layer_name: LayerName, index: int) -> str:
        """
        The name of a node of the resistor network, unique within the network (but pins),
        e.g. $1.li1 (internal node), P0.poly (polygon port), V0.met1 (vertex port)

        NOTE: KLayout names a node after its layer index (e.g. $1.17), but the layer indexes depend on
              the order KLayout creates the LVS layers in, which differs from run to run

        :param index: the port index of a port, the index of an internal node (see internal_node_indexes)
        """
        match rn.type():
            case klp.RNodeType.Internal:
                prefix = '$'
            case klp.RNodeType.VertexPort:
                prefix = 'V'
            case klp.RNodeType.PolygonPort:
                prefix = 'P'
            case _:
                raise NotImplementedError()
        return f"{prefix}{index}.{layer_name}"

    def split_at_exclusions(self,
                            tech: pb_RExtractorTech,
                            regions: Dict[int, kdb.Region],
                            vertex_ports: Dict[int, List[kdb.Point]],
                            vertex_port_pins: Dict[int, List[Tuple[Label, NetName]]],
                            polygon_ports: Dict[int, List[kdb.Polygon]],
                            polygon_port_device_terminals: PolygonPortTerminals,
                            layer_names: Dict[int, LayerName]) -> NetSplit:
        """
        Takes the shapes of a net within the exclusion markers out of its network.
        A polygon port on the conductor beside each cut is its node, as a whole cut is one node, also of a wide wire.

        Either these become ports of the netlist, for the model of what the markers stand for,
        like the device terminals within the markers, which the model connects then.

        Or the shapes go to layers without resistance (ideal_layer_id), so that the extraction still tells what they
        connect, with their pins and device terminals, and a polygon port on them joins each cut to them.

        NOTE: a via is within a block by its center, which is the location of its nodes, on both of its conductors,
              otherwise it keeps its resistance and the metal it lands on, as a via port needs its center on the metal,
              and the resistance of a part of it would be made up

        :param tech: the conductors and vias, with their ideal copies
        :param regions: the shapes of the net by layer ID
        :param vertex_ports: the pins by layer ID
        :param vertex_port_pins: what the pins are of, by layer ID
        :param polygon_ports: the device terminals by layer ID
        :param polygon_port_device_terminals: what the polygon ports are of
        :param layer_names: the canonical names of the conductors and vias, by layer ID
        """
        split = NetSplit()
        exclusions = self.exclusions

        def is_ideal(layer_id: int) -> bool:
            return layer_id >= IDEAL_LAYER_ID_OFFSET

        # NOTE: the device terminals of the removed devices are no ports of devices anymore
        removed_terminals: List[Tuple[int, kdb.Polygon, device_pb2.Device.Terminal]] = []
        removed_terminal_shapes: Dict[int, kdb.Shapes] = defaultdict(kdb.Shapes)
        for layer_id in list(polygon_ports):
            ports_and_terminals = list(zip(polygon_ports.pop(layer_id), polygon_port_device_terminals.pop(layer_id)))
            for port, terminal in ports_and_terminals:
                if terminal.device_id in exclusions.removed_device_blocks:
                    removed_terminal_shapes[layer_id].insert(kdb.PolygonWithProperties(
                        port, {'terminal': len(removed_terminals)}))
                    removed_terminals.append((layer_id, port, terminal))
                else:
                    polygon_ports[layer_id].append(port)
                    polygon_port_device_terminals[layer_id].append(terminal)

        kept_for_vias: Dict[int, kdb.Region] = defaultdict(kdb.Region)
        for via in {v.layer.id: v for v in tech.vias if not is_ideal(v.layer.id)}.values():
            shapes = regions.get(via.layer.id, None)
            # NOTE: most nets are far from the blocks
            if shapes is None or not shapes.bbox().touches(exclusions.bbox):
                continue
            bottom_layer_name = layer_names[via.bottom_conductor.id]
            top_layer_name = layer_names[via.top_conductor.id]
            # NOTE: within a block on both of its conductors
            box = shapes.bbox()
            within_tie = polygons_by_center_inside(shapes, exclusions.mask_near(box, bottom_layer_name, ports=False) &
                                                   exclusions.mask_near(box, top_layer_name, ports=False))
            within_ports = polygons_by_center_inside(shapes, exclusions.mask_near(box, bottom_layer_name, ports=True) &
                                                     exclusions.mask_near(box, top_layer_name, ports=True))
            if not within_tie.is_empty():
                regions[ideal_layer_id(via.layer.id)] = within_tie
            if not within_ports.is_empty():
                split.vias_within.append((bottom_layer_name, top_layer_name, within_ports))
            rest = shapes - within_tie - within_ports
            regions[via.layer.id] = rest
            across = rest.interacting(exclusions.mask_near(box, bottom_layer_name) +
                                      exclusions.mask_near(box, top_layer_name))
            kept_for_vias[via.bottom_conductor.id] += across
            kept_for_vias[via.top_conductor.id] += across

        for layer_id in sorted({c.layer.id for c in tech.conductors if not is_ideal(c.layer.id)}):
            shapes = regions.get(layer_id, None)
            if shapes is None or not shapes.bbox().touches(exclusions.bbox):
                continue
            layer_name = layer_names[layer_id]
            box = shapes.bbox()
            mask_ports = exclusions.mask_near(box, layer_name, ports=True) - kept_for_vias[layer_id]
            mask_tie = exclusions.mask_near(box, layer_name, ports=False) - kept_for_vias[layer_id] - mask_ports
            within_ports = shapes & mask_ports
            within_tie = shapes & mask_tie
            if within_tie.is_empty() and within_ports.is_empty():
                continue
            # NOTE: without the masks rather than what is within them, as any-angle edges round differently,
            #       which leaves slivers along the cuts otherwise, that join what is on both sides of a block
            outside = shapes - mask_ports - mask_tie
            ideal_id = ideal_layer_id(layer_id)
            regions[layer_id] = outside
            split.kept_for_vias[layer_name] = kept_for_vias[layer_id]
            if not within_tie.is_empty():
                regions[ideal_id] = within_tie
            for polygon in within_ports.merged().each():
                block_indexes = exclusions.block_indexes_with_ports_within(kdb.Region(polygon.downcast()), layer_name)
                if len(block_indexes) > 1:
                    split.abutting_block_indexes.update(block_indexes)
                region_by_layer = split.regions_within[block_indexes[0]]
                region_by_layer.setdefault(layer_name, kdb.Region()).insert(polygon.downcast())

            # NOTE: the pins and device terminals go with the conductor they are on, those on both to both of them,
            #       which are one node, as the ports of a device terminal are
            for point, pin in zip(vertex_ports.pop(layer_id, []), vertex_port_pins.pop(layer_id, [])):
                label_box = kdb.Region(kdb.Box(point, point).enlarged(1, 1))
                # NOTE: a pin of a cut cell is none of the top cell, but it names the port of the model,
                #       also where its metal stays for a via from above, which can land on it
                if exclusions.is_only_label_of_cut_cell(pin[0], point) and \
                        not (label_box & exclusions.mask_near(label_box.bbox(), layer_name, ports=True)).is_empty():
                    continue
                if not (label_box & outside).is_empty():
                    vertex_ports[layer_id].append(point)
                    vertex_port_pins[layer_id].append(pin)
                elif not (label_box & within_ports).is_empty():
                    split.pins_within.append(PinWithinMarker(point, layer_id, *pin))
                else:
                    vertex_ports[ideal_id].append(point)
                    vertex_port_pins[ideal_id].append(pin)

            def add_port(port_layer_id: int,
                         polygon: kdb.Polygon,
                         device_terminal: Optional[device_pb2.Device.Terminal] = None) -> PolygonPortKey:
                polygon_ports[port_layer_id].append(polygon.downcast())
                polygon_port_device_terminals[port_layer_id].append(device_terminal)
                return port_layer_id, len(polygon_ports[port_layer_id]) - 1

            for port, terminal in zip(polygon_ports.pop(layer_id, []), polygon_port_device_terminals.pop(layer_id, [])):
                port_region = kdb.Region(port)
                part_tie = port_region & within_tie
                part_ports = port_region & within_ports
                for polygon in (port_region - part_tie - part_ports).each():
                    add_port(layer_id, polygon, terminal)
                for polygon in part_tie.each():
                    add_port(ideal_id, polygon, terminal)
                for polygon in part_ports.each():
                    split.terminals_within.append(TerminalWithinMarker(terminal, layer_id, polygon.bbox()))

            # NOTE: strips of 1 dbu, like the device terminals that abut a conductor
            #       (see KLayoutExtractionContext.terminal_region_on_net),
            #       wider at any angle, where the extractor can't split such a narrow polygon into triangles
            strip_width = CUT_STRIP_WIDTH if (outside + within_ports + within_tie).non_rectilinear().is_empty() \
                else ANY_ANGLE_CUT_STRIP_WIDTH
            around_ports = within_ports.sized(strip_width)

            # NOTE: also where what is within a marker without ports goes on into a block with ports
            conductors_near = RegionIndex()
            for strip_layer_id, conductor in ((layer_id, outside), (ideal_id, within_tie)):
                for strip in (conductor & around_ports).merged().each():
                    port = port_of_cut(strip, lambda box: conductors_near.near(conductor, box), strip_width,
                                       round(PORT_LENGTH_ALONG_CONDUCTOR / self.pex_context.dbu))
                    split.has_cut_along_conductor |= port.bbox() != strip.bbox()
                    key = add_port(strip_layer_id, port)
                    split.cut_port_boxes[key] = port.bbox()
                    split.cut_port_blocks[key] = exclusions.block_index_with_ports_at(port.bbox(), layer_name)
                    for shape in removed_terminal_shapes[layer_id].each_touching(kdb.Shapes.SRegions, port.bbox()):
                        terminal = removed_terminals[shape.property('terminal')][2]
                        if exclusions.removed_device_blocks[terminal.device_id] == split.cut_port_blocks[key] and \
                                not (kdb.Region(shape.polygon) & kdb.Region(port.downcast())).is_empty():
                            split.terminals_of_cuts[key] = terminal
                            break
            for outside_strip in (outside & within_tie.sized(strip_width) - around_ports).merged().each():
                outside_key = add_port(layer_id, outside_strip)
                for within_strip in (within_tie & kdb.Region(outside_strip).sized(strip_width)).merged().each():
                    split.polygon_port_ties.append((outside_key, add_port(ideal_id, within_strip)))

        # NOTE: a removed device stands for what its model has, and where it meets the rest of its net is a port,
        #       e.g. the terminal of a coil on its lead outside its marker
        conductor_layer_ids = {c.layer.id for c in tech.conductors}
        for layer_id, port, terminal in removed_terminals:
            shapes = regions.get(layer_id, None)
            if layer_id not in conductor_layer_ids or shapes is None or shapes.is_empty():
                continue  # NOTE: e.g. the bulk of a transistor on the substrate
            for polygon in (kdb.Region(port) & shapes).merged().each():
                polygon_ports[layer_id].append(polygon.downcast())
                polygon_port_device_terminals[layer_id].append(None)
                key = (layer_id, len(polygon_ports[layer_id]) - 1)
                split.cut_port_boxes[key] = polygon.bbox()
                split.cut_port_blocks[key] = exclusions.removed_device_blocks[terminal.device_id]
                split.cut_port_terminals[key] = terminal
        return split

    @staticmethod
    def sets_of_cuts(split: NetSplit,
                     connected_shapes: ConnectedShapesWithin,
                     layer_names: Dict[int, LayerName]) -> Dict[PolygonPortKey, int]:
        """
        :return: what is joined to the shapes within the blocks at each cut, by its polygon port,
                 a cut without such shapes has none (e.g. of a terminal of a removed device, on a wire to its block)
        """
        sets_of_cuts: Dict[PolygonPortKey, int] = {}
        for key, cut_box in split.cut_port_boxes.items():
            cut_set = connected_shapes.set_at(layer_names[key[0]], cut_box.enlarged(1, 1))
            if cut_set is not None:
                sets_of_cuts[key] = cut_set
        return sets_of_cuts

    def exclusion_port_names(self,
                             net_name: NetName,
                             split: NetSplit,
                             connected_shapes: ConnectedShapesWithin,
                             sets_of_cuts: Mapping[PolygonPortKey, int],
                             layer_names: Dict[int, LayerName],
                             labels_outside: Collection[Label]) -> Tuple[Dict[PolygonPortKey, str], Dict[int, str]]:
        """
        The names of the ports of a net at the exclusion blocks: a cut has the name of the pin of the net
        within the block that is nearest to it (e.g. of a lead of a coil), otherwise <net>__<block>_<number>,
        like the device terminals within the markers.

        At a cut cell, it can also be a label of the cell on the net, <block>__<label>, also for several cuts,
        as these are one pin of its model, or the terminal of a device of it that the cut is on,
        <block>__<terminal>, numbered if devices have several such nodes, otherwise <block>__<net>_<number>

        A pin or a label only names a cut of the shapes it is joined to within the block, as a port is one node.
        So does a pin of a label the net also has outside the block only when that isn't the same name,
        which would be one node with that pin

        :param connected_shapes: of the shapes within the blocks
        :param sets_of_cuts: see sets_of_cuts
        :param labels_outside: the labels of the pins of the net outside the blocks
        :return: the names of the cuts by their polygon ports,
                 and the names of the device terminals within the markers by their indexes in split.terminals_within
        """
        blocks = self.exclusions.blocks
        safe_net_name = re.sub(r'[^A-Za-z0-9_]', '_', net_name)  # NOTE: e.g. A,B of several labels, $2 of none

        def block_index_of_pin(pin: PinWithinMarker) -> int:
            return self.exclusions.block_index_with_ports_at(kdb.Box(pin.position, pin.position),
                                                             layer_names[pin.layer_id])

        cut_keys = sorted(split.cut_port_boxes,
                          key=lambda key: (split.cut_port_blocks[key],
                                           split.cut_port_boxes[key].bottom, split.cut_port_boxes[key].left,
                                           layer_names[key[0]]))

        def distance(position: kdb.Point, box: kdb.Box) -> float:
            center = box.center()
            return math.hypot(position.x - center.x, position.y - center.y)

        # the candidates of the names of each cut: whether on another layer, the distance, the name
        candidates_by_cut: Dict[PolygonPortKey, List[Tuple[bool, float, str]]] = defaultdict(list)
        pin_sets = [connected_shapes.set_at_position(layer_names[pin.layer_id], pin.position)
                    for pin in split.pins_within]
        labels_with_sets = {block_index: [(label, connected_shapes.set_at_position(label.layer_name, label.position))
                                          for label in self.labels_at_shapes(block_index, split)]
                            for block_index in set(split.cut_port_blocks.values())}
        for key in cut_keys:
            # NOTE: a port at the terminal of a removed device is named after that terminal
            if key in split.cut_port_terminals:
                continue
            block_index = split.cut_port_blocks[key]
            cut_box = split.cut_port_boxes[key]
            cut_set = sets_of_cuts.get(key, None)
            if cut_set is None:
                continue
            for pin, pin_set in zip(split.pins_within, pin_sets):
                if pin_set == cut_set and pin.label not in labels_outside and block_index_of_pin(pin) == block_index:
                    candidates_by_cut[key].append((pin.layer_id != key[0],
                                                   distance(pin.position, cut_box),
                                                   pin.label))
            for label, label_set in labels_with_sets[block_index]:
                if label_set == cut_set:
                    candidates_by_cut[key].append((label.layer_name != layer_names[key[0]],
                                                   distance(label.position, cut_box),
                                                   f"{blocks[block_index].name}__{label.text}"))

        # NOTE: the nearest pairs first, on the layer of the pin before others, each pin names one cut
        names_by_cut: Dict[PolygonPortKey, str] = {}
        names_left = {candidate[2] for candidates in candidates_by_cut.values() for candidate in candidates}
        for _, _, name, _, key in sorted((*candidate, index, key)
                                         for index, key in enumerate(cut_keys)
                                         for candidate in candidates_by_cut[key]):
            if name in names_left and key not in names_by_cut:
                names_by_cut[key] = name
                names_left.discard(name)

        numbers: Counter[int] = Counter()
        taken_names: Set[str] = {candidate[2] for candidates in candidates_by_cut.values() for candidate in candidates}
        taken_names.update(labels_outside)
        taken_names.update(pin.label for pin in split.pins_within)

        def numbered_name(block_index: int) -> str:
            while True:
                number = numbers[block_index]
                numbers[block_index] += 1
                name = f"{blocks[block_index].name}__{safe_net_name}_{number}" \
                    if blocks[block_index].kind == BlockKind.CUT else \
                    f"{safe_net_name}__{blocks[block_index].name}_{number}"
                if name not in taken_names:
                    taken_names.add(name)
                    return name

        for key in cut_keys:
            if key in names_by_cut:
                continue
            block_index = split.cut_port_blocks[key]
            cut_candidates = [c for c in candidates_by_cut[key] if c[2].startswith(f"{blocks[block_index].name}__")]
            if blocks[block_index].kind == BlockKind.CUT and cut_candidates:
                names_by_cut[key] = min(cut_candidates)[2]
            elif key not in split.cut_port_terminals and key not in split.terminals_of_cuts:
                names_by_cut[key] = numbered_name(block_index)

        names_by_cut.update(self.terminal_port_names(split, [key for key in cut_keys if key not in names_by_cut],
                                                     taken_names))

        def name_at_terminal_of_removed_device(within: TerminalWithinMarker) -> Optional[str]:
            # NOTE: a diffusion on which a terminal of a removed device also is, which needs no second port
            for key, terminal_box in split.cut_port_boxes.items():
                if key in split.cut_port_terminals and key[0] == within.layer_id and terminal_box.touches(within.box):
                    return names_by_cut[key]
            return None

        # NOTE: the polygons of a device terminal are one port
        names_by_terminal: Dict[Tuple[int, int], str] = {}
        names_by_terminal_index: Dict[int, str] = {}
        for index, within in enumerate(split.terminals_within):
            key = (within.terminal.device_id, within.terminal.terminal_id)
            if key not in names_by_terminal:
                names_by_terminal[key] = name_at_terminal_of_removed_device(within) or \
                    numbered_name(self.exclusions.block_index_with_ports_at(within.box, layer_names[within.layer_id]))
            names_by_terminal_index[index] = names_by_terminal[key]
        return names_by_cut, names_by_terminal_index

    def labels_at_shapes(self, block_index: int, split: NetSplit) -> List[BlockLabel]:
        """
        :return: the labels of the block at the shapes of the net within it,
                 also at its metal kept for vias, which can be in a hole of them or beside them
        """
        labels: Dict[int, BlockLabel] = {}
        for layer_name, region in split.regions_within.get(block_index, {}).items():
            for shapes in (region, split.kept_for_vias.get(layer_name, None)):
                if shapes is not None:
                    for polygon in shapes.merged().each():
                        labels.update(self.exclusions.labels_at(block_index, layer_name, polygon.bbox()))
        return [labels[index] for index in sorted(labels)]

    def terminal_port_names(self,
                            split: NetSplit,
                            keys: Sequence[PolygonPortKey],
                            taken_names: Set[str]) -> Dict[PolygonPortKey, str]:
        """
        A port is one node: of a terminal of a device, also of several polygons,
        and of the terminals of that name of the other devices of the block on the same polygon

        :param keys: the polygon ports at the terminals of removed devices
        :param taken_names: the names of the other ports of the net, to which these go too
        :return: their names, <block>__<terminal>, numbered if the block has several such nodes on the net
        """
        blocks = self.exclusions.blocks
        terminals = {**split.terminals_of_cuts, **split.cut_port_terminals}
        ports = DisjointSets(keys)
        first_key_by_node: Dict[Hashable, PolygonPortKey] = {}
        for key in keys:
            terminal = terminals[key]
            for node in ((terminal.device_id, terminal.terminal_id),
                         (split.cut_port_blocks[key], terminal.name, key[0], split.cut_port_boxes[key])):
                ports.union(key, first_key_by_node.setdefault(node, key))

        roots_by_name: Dict[str, List[PolygonPortKey]] = defaultdict(list)
        for key in keys:
            name = f"{blocks[split.cut_port_blocks[key]].name}__{terminals[key].name}"
            root = ports.find(key)
            if root not in roots_by_name[name]:
                roots_by_name[name].append(root)

        name_by_root: Dict[PolygonPortKey, str] = {}
        for name, roots in roots_by_name.items():
            if len(roots) == 1 and name not in taken_names:
                name_by_root[roots[0]] = name
                taken_names.add(name)
                continue
            numbers = (f"{name}_{number}" for number in itertools.count())
            for root in roots:
                name_by_root[root] = next(number for number in numbers if number not in taken_names)
                taken_names.add(name_by_root[root])
        return {key: name_by_root[ports.find(key)] for key in keys}

    def internal_node_indexes(self,
                              resistor_network: klp.RNetwork,
                              layer_names: Dict[int, LayerName],
                              excluded_node_ids: Set[int]) -> Dict[int, int]:
        """
        The index of each internal node of a resistor network, by its object ID:
        in the order of their layers and locations, nodes of the same location by their elements

        NOTE: KLayout numbers the internal nodes in the order it creates them, which can differ from run to run
              (e.g. KLayout 0.30.12), and their names decide ties in the distribution of the capacitances (#286)
        """
        dbu = self.pex_context.dbu

        def location(rn: klp.RNode) -> Tuple[LayerName, str, int, int, int, int, int]:
            if rn.type() != klp.RNodeType.Internal:
                # NOTE: a port by its index, as KLayout's location of a vertex port can differ from run to run
                return layer_names[rn.layer()], str(rn.type()), rn.port_index(), 0, 0, 0, 0
            box = rn.location()
            p1 = box.p1.to_itype(dbu)
            p2 = box.p2.to_itype(dbu)
            return layer_names[rn.layer()], str(rn.type()), -1, p1.x, p1.y, p2.x, p2.y

        neighbors: Dict[int, List[Tuple[float, Tuple]]] = defaultdict(list)
        for el in resistor_network.each_element():
            neighbors[el.a().object_id()].append((el.resistance(), location(el.b())))
            neighbors[el.b().object_id()].append((el.resistance(), location(el.a())))

        keys = {rn.object_id(): (location(rn), sorted(neighbors[rn.object_id()]))
                for rn in resistor_network.each_node()
                if rn.type() == klp.RNodeType.Internal and rn.object_id() not in excluded_node_ids}
        return {node_id: index for index, node_id in enumerate(sorted(keys, key=keys.get))}

    def extract(self, rex_request: pex_request_pb2.RExtractionRequest) -> pex_result_pb2.RExtractionResult:
        rex_result = pex_result_pb2.RExtractionResult()

        rex_tech_kly = klayout_r_extractor_tech(rex_request.tech)

        # dicts keyed by id / klayout_index
        layer_names: Dict[int, LayerName] = {}

        wire_layer_ids: Set[int] = set()
        via_layer_ids: Set[int] = set()

        for c in rex_request.tech.conductors:
            layer_names[c.layer.id] = c.layer.canonical_layer_name
            wire_layer_ids.add(c.layer.id)

        for v in rex_request.tech.vias:
            layer_names[v.layer.id] = v.layer.canonical_layer_name
            via_layer_ids.add(v.layer.id)

        # NOTE: the nodes of a layer are named after it, and those of an ideal layer have to differ from them
        node_layer_names: Dict[int, str] = {layer_id: f"{name}.excluded" if layer_id >= IDEAL_LAYER_ID_OFFSET else name
                                            for layer_id, name in layer_names.items()}

        LP = tech_pb2.LayerInfo.Purpose
        well_layer_ids: Set[int] = set()
        for c in rex_request.tech.conductors:
            computed_layer_info = self.pex_context.tech.computed_layer_info_by_name.get(c.layer.lvs_layer_name, None)
            if computed_layer_info and computed_layer_info.layer_info.purpose in (LP.PURPOSE_NWELL, LP.PURPOSE_PWELL):
                well_layer_ids.add(c.layer.id)

        nets_with_isolated_wells: List[NetName] = []
        nets_with_cuts_along_conductors: List[NetName] = []

        for net_extraction_request in rex_request.net_extraction_requests:
            if self.exclusions is not None and net_extraction_request.net_name in self.exclusions.excluded_net_names:
                continue

            vertex_ports: Dict[int, List[kdb.Point]] = defaultdict(list)
            polygon_ports: Dict[int, List[kdb.Polygon]] = defaultdict(list)
            vertex_port_pins: Dict[int, List[Tuple[Label, NetName]]] = defaultdict(list)
            polygon_port_device_terminals: PolygonPortTerminals = defaultdict(list)
            regions: Dict[int, kdb.Region] = defaultdict(kdb.Region)

            for t in net_extraction_request.device_terminals:
                for l2r in t.region_by_layer:
                    for sh in l2r.region.shapes:
                        sh_kly = self.shapes_converter.klayout_shape(sh)
                        polygon_ports[l2r.layer.id].append(sh_kly)
                        polygon_port_device_terminals[l2r.layer.id].append(t)

            for pin in net_extraction_request.pins:
                p = self.shapes_converter.klayout_point(pin.label_point)
                vertex_ports[pin.layer.id].append(p)
                vertex_port_pins[pin.layer.id].append((pin.label, pin.net_name))

            for l2r in net_extraction_request.region_by_layer:
                regions[l2r.layer.id] = self.shapes_converter.klayout_region(l2r.region)

            split = NetSplit()
            if self.exclusions is not None:
                split = self.split_at_exclusions(rex_request.tech, regions,
                                                 vertex_ports, vertex_port_pins,
                                                 polygon_ports, polygon_port_device_terminals,
                                                 layer_names)
                if split.has_cut_along_conductor:
                    nets_with_cuts_along_conductors.append(net_extraction_request.net_name)
                if split.abutting_block_indexes:
                    block_names = sorted(self.exclusions.blocks[index].name for index in split.abutting_block_indexes)
                    warning(f"The net {net_extraction_request.net_name} goes on from one to another of "
                            f"{listed_names(block_names)}, where they abut, so the netlist has no ports for their "
                            f"models there")

            keep_pins_of_top_circuit(net_extraction_request.net_name, vertex_ports, vertex_port_pins)

            rex = klp.RNetExtractor(self.pex_context.dbu)
            try:
                resistor_network = rex.extract(rex_tech_kly,
                                               regions,
                                               vertex_ports,
                                               polygon_ports)
            except RuntimeError as exc:
                raise RExtractionTechError(f"KLayout's resistance extraction fails for net "
                                           f"{net_extraction_request.net_name}: {exc}") from exc

            result_network = rex_result.networks.add()
            result_network.net_name = net_extraction_request.net_name

            polygon_port_node_ids = {(rn.layer(), rn.port_index()): rn.object_id()
                                     for rn in resistor_network.each_node()
                                     if rn.type() == klp.RNodeType.PolygonPort}
            node_id_ties = [(polygon_port_node_ids[a], polygon_port_node_ids[b]) for a, b in split.polygon_port_ties]

            cut_port_names: Dict[PolygonPortKey, str] = {}
            terminal_port_names: Dict[int, str] = {}
            sets_of_cuts: Dict[PolygonPortKey, int] = {}
            connected_shapes: Optional[ConnectedShapesWithin] = None
            if split.cut_port_boxes or split.terminals_within or split.pins_within:
                connected_shapes = ConnectedShapesWithin(split.regions_within, split.vias_within, split.kept_for_vias)
                sets_of_cuts = self.sets_of_cuts(split, connected_shapes, layer_names)
                labels_outside = {pin[0] for pins in vertex_port_pins.values() for pin in pins}
                cut_port_names, terminal_port_names = self.exclusion_port_names(result_network.net_name, split,
                                                                                connected_shapes, sets_of_cuts,
                                                                                layer_names, labels_outside)

            pieces = self.network_pieces(resistor_network, node_id_ties)

            # NOTE: LVS may join a well to its net other than by the contacts over its taps,
            #       e.g. by a label of the net on the well, so it's a piece of the network that joins nothing else.
            #       It's left out, so that the device terminals on it stay on the node of their net, ideally
            isolated_well_node_ids = self.isolated_well_node_ids(pieces, well_layer_ids, split.cut_port_boxes)
            if isolated_well_node_ids:
                nets_with_isolated_wells.append(result_network.net_name)

            internal_node_indexes = self.internal_node_indexes(resistor_network, node_layer_names,
                                                               isolated_well_node_ids)

            for rn in resistor_network.each_node():
                if rn.object_id() in isolated_well_node_ids:
                    continue

                node_by_node_id: Dict[int, r_network_pb2.RNode] = {}

                loc = rn.location()
                layer_id = rn.layer()
                canonical_layer_name = layer_names[layer_id]

                r_node = result_network.nodes.add()
                r_node.node_id = rn.object_id()
                r_node.node_name = self.node_name(rn, node_layer_names[layer_id],
                                                  internal_node_indexes.get(rn.object_id(), rn.port_index()))
                r_node.node_kind = r_network_pb2.RNode.Kind.KIND_UNSPECIFIED  # TODO!
                r_node.layer_name = canonical_layer_name

                match rn.type():
                    case klp.RNodeType.VertexPort:   # pins!
                        r_node.location.kind = location_pb2.Location.Kind.LOCATION_KIND_POINT
                        # NOTE: at its label, the vertex port, rather than where KLayout locates the node,
                        #       which can differ from run to run (e.g. KLayout 0.30.12), and so would
                        #       the nodes the capacitances near it go to (#286)
                        p = vertex_ports[rn.layer()][rn.port_index()]
                        r_node.location.point.x = p.x
                        r_node.location.point.y = p.y
                    case klp.RNodeType.PolygonPort | klp.RNodeType.Internal:
                        r_node.location.kind = location_pb2.Location.Kind.LOCATION_KIND_BOX
                        p1 = loc.p1.to_itype(self.pex_context.dbu)
                        p2 = loc.p2.to_itype(self.pex_context.dbu)
                        r_node.location.box.lower_left.x = p1.x
                        r_node.location.box.lower_left.y = p1.y
                        r_node.location.box.upper_right.x = p2.x
                        r_node.location.box.upper_right.y = p2.y
                    case _:
                        raise NotImplementedError()

                match rn.type():
                    case klp.RNodeType.VertexPort:
                        r_node.node_kind = r_network_pb2.RNode.Kind.KIND_PIN
                        port_idx = rn.port_index()
                        r_node.node_name, r_node.net_name = vertex_port_pins[rn.layer()][port_idx][0:2]
                        r_node.location.point.net = r_node.net_name

                    case klp.RNodeType.PolygonPort:
                        port_idx = rn.port_index()
                        device_terminal = polygon_port_device_terminals[rn.layer()][port_idx]
                        cut_port_name = cut_port_names.get((rn.layer(), port_idx), None)
                        if cut_port_name is not None:
                            r_node.node_kind = r_network_pb2.RNode.Kind.KIND_EXCLUSION_PORT
                            r_node.node_name = cut_port_name
                            split.block_of_node_id[r_node.node_id] = split.cut_port_blocks[(rn.layer(), port_idx)]
                        elif device_terminal is None:  # NOTE: at a cut, see split_at_exclusions
                            r_node.node_kind = r_network_pb2.RNode.Kind.KIND_WIRE_JUNCTION
                        else:
                            r_node.node_kind = r_network_pb2.RNode.Kind.KIND_DEVICE_TERMINAL
                            # NOTE: the device terminal behind the port, to connect the device to this node
                            r_node.device_terminal.CopyFrom(device_terminal)
                            r_node.device_terminal.ClearField('region_by_layer')
                        r_node.net_name = f"{result_network.net_name}.{r_node.node_name}"
                        r_node.location.box.net = r_node.net_name
                    case klp.RNodeType.Internal:
                        if rn.layer() in via_layer_ids:
                            r_node.node_kind = r_network_pb2.RNode.Kind.KIND_VIA_JUNCTION
                        elif rn.layer() in wire_layer_ids:
                            r_node.node_kind = r_network_pb2.RNode.Kind.KIND_WIRE_JUNCTION
                        else:
                            raise NotImplementedError()

                        # NOTE: network prefix, as node name is only unique per network
                        r_node.net_name = f"{result_network.net_name}.{r_node.node_name}"
                        r_node.location.box.net = r_node.net_name
                    case _:
                        raise NotImplementedError()

                node_by_node_id[r_node.node_id] = r_node

            # NOTE: nodes of the same name are one node in the netlist, like the pins of the same label,
            #       so the names of the other nodes must be unique
            #       (the internal nodes are numbered per network, the ports per layer, so no 2 layers
            #        of the same name must have ports, e.g. a conductor split into several GDS pairs)
            # NOTE: and so are the ports of the cuts of one pin of a cut cell
            name_counts = Counter(n.node_name for n in result_network.nodes
                                  if n.node_kind not in (r_network_pb2.RNode.Kind.KIND_PIN,
                                                         r_network_pb2.RNode.Kind.KIND_EXCLUSION_PORT))
            duplicate_names = sorted(name for name, count in name_counts.items() if count > 1)
            if duplicate_names:
                raise RExtractionTechError(f"Nodes of net {result_network.net_name} have the same name, "
                                           f"as layers of the same name have ports: {', '.join(duplicate_names)}")

            for el in resistor_network.each_element():
                if el.a().object_id() in isolated_well_node_ids:
                    continue  # NOTE: and so is b, of the same piece
                r_element = result_network.elements.add()
                r_element.element_id = el.object_id()
                r_element.node_a.node_id = el.a().object_id()
                r_element.node_b.node_id = el.b().object_id()
                r_element.resistance = el.resistance()

            for node_id_a, node_id_b in node_id_ties:
                if node_id_a in isolated_well_node_ids:
                    continue  # NOTE: and so is b, of the same piece
                self.add_tie(result_network, node_id_a, node_id_b)

            node_ids_by_set: Dict[int, List[int]] = defaultdict(list)
            for key, cut_set in sets_of_cuts.items():
                node_ids_by_set[cut_set].append(polygon_port_node_ids[key])

            nodes_within = self.add_nodes_within_markers(result_network, split, terminal_port_names, cut_port_names,
                                                         layer_names, vertex_port_pins, connected_shapes,
                                                         node_ids_by_set)
            if self.exclusions is not None:
                self.find_net_pieces(result_network, pieces, nodes_within, split, regions, layer_names, wire_layer_ids,
                                     well_layer_ids)

            if len(pieces) > 1 + sum(p[0].object_id() in isolated_well_node_ids for p in pieces):
                node_ids = self.substrate_joined_node_ids(result_network, regions, layer_names, well_layer_ids)
                result_network.substrate_joined_node_ids.extend(sorted(node_ids))

            for _, node_ids in sorted(node_ids_by_set.items()):
                if len(node_ids) > 1:
                    result_network.model_joins.add().node_ids.extend(sorted(node_ids))

        if nets_with_cuts_along_conductors:
            info("The metal of these nets goes on beside exclusion blocks, along their cuts, so it carries the current "
                 "alone, with a short port for each model, as a port can't connect a model in parallel to it: " +
                 listed_names(sorted(nets_with_cuts_along_conductors)))

        if nets_with_isolated_wells:
            warning("The resistance network leaves out the wells of these nets, as no contact joins them "
                    "to the rest of their net (e.g. a label of the net on the well does), "
                    "so the device terminals on them (e.g. the PMOS bulks) are ideally on their nets: " +
                    ', '.join(sorted(nets_with_isolated_wells)))

        return rex_result

    @staticmethod
    def add_tie(network: r_network_pb2.RNetwork, node_id_a: int, node_id_b: int):
        """
        Adds an element without resistance, which makes the nodes one (see NetworkNodeNames.from_network)
        """
        element = network.elements.add()
        element.element_id = node_id_a
        element.node_a.node_id = node_id_a
        element.node_b.node_id = node_id_b
        element.resistance = 0.0

    @classmethod
    def add_nodes_within_markers(cls,
                                 network: r_network_pb2.RNetwork,
                                 split: NetSplit,
                                 terminal_port_names: Dict[int, str],
                                 cut_port_names: Dict[PolygonPortKey, str],
                                 layer_names: Dict[int, LayerName],
                                 vertex_port_pins: Mapping[int, List[Tuple[Label, NetName]]],
                                 connected_shapes: Optional[ConnectedShapesWithin],
                                 node_ids_by_set: Dict[int, List[int]]) -> List[r_network_pb2.RNode]:
        """
        Adds the nodes of what is within the exclusion markers, for ports at the cuts, as no conductors are there:
        the device terminals with their ports, and the pins that name no cut, which are ports for the model too,
        but those that are pins of the net outside the markers as well

        NOTE: the extractor's node IDs are addresses, so these small ones are unique

        :param connected_shapes: of the shapes within the blocks, if there are such nodes
        :param node_ids_by_set: the ports by what is joined to them within the blocks (see ConnectedShapesWithin),
                                to which these go too
        :return: the nodes
        """
        K = r_network_pb2.RNode.Kind
        next_node_id = 1
        nodes: List[r_network_pb2.RNode] = []

        def add_node(kind: r_network_pb2.RNode.Kind, name: str, layer_id: int, box: kdb.Box) -> r_network_pb2.RNode:
            nonlocal next_node_id
            node = network.nodes.add()
            nodes.append(node)
            node.node_id = next_node_id
            next_node_id += 1
            node.node_name = name
            node.node_kind = kind
            node.layer_name = layer_names[layer_id]
            node.net_name = f"{network.net_name}.{name}"
            node.location.kind = location_pb2.Location.Kind.LOCATION_KIND_BOX
            node.location.box.lower_left.x, node.location.box.lower_left.y = box.left, box.bottom
            node.location.box.upper_right.x, node.location.box.upper_right.y = box.right, box.top
            node.location.box.net = node.net_name
            return node

        def add_to_set(node_set: Optional[int], node_id: int):
            if node_set is not None:
                node_ids_by_set[node_set].append(node_id)

        port_node_id_by_name: Dict[str, int] = {}
        for index, within in enumerate(split.terminals_within):
            port_name = terminal_port_names[index]
            if port_name not in port_node_id_by_name:
                port_node_id_by_name[port_name] = add_node(K.KIND_EXCLUSION_PORT, port_name,
                                                           within.layer_id, within.box).node_id
                add_to_set(connected_shapes.set_at(layer_names[within.layer_id], within.box),
                           port_node_id_by_name[port_name])
            terminal_node = add_node(K.KIND_DEVICE_TERMINAL, f"T{index}.{layer_names[within.layer_id]}.excluded",
                                     within.layer_id, within.box)
            terminal_node.device_terminal.CopyFrom(within.terminal)
            terminal_node.device_terminal.ClearField('region_by_layer')
            cls.add_tie(network, port_node_id_by_name[port_name], terminal_node.node_id)

        taken_names = set(cut_port_names.values()) | {pin[0] for pins in vertex_port_pins.values() for pin in pins}
        for within in split.pins_within:
            if within.label not in taken_names:
                add_to_set(connected_shapes.set_at_position(layer_names[within.layer_id], within.position),
                           add_node(K.KIND_EXCLUSION_PORT, within.label, within.layer_id,
                                    kdb.Box(within.position, within.position)).node_id)
        return nodes

    def find_net_pieces(self,
                        network: r_network_pb2.RNetwork,
                        pieces: List[List[klp.RNode]],
                        nodes_within: List[r_network_pb2.RNode],
                        split: NetSplit,
                        regions: Dict[int, kdb.Region],
                        layer_names: Dict[int, LayerName],
                        wire_layer_ids: Set[int],
                        well_layer_ids: Set[int]):
        """
        Finds the pieces of a net with ports at exclusion markers (see NetPiece), by the nodes of its network:
        what resistors join outside the markers, and what is within each marker, with the ports at its cuts
        """
        if not split.regions_within:
            return

        K = r_network_pb2.RNode.Kind
        well_layer_names = {layer_names[layer_id] for layer_id in well_layer_ids}

        def with_substrate(region_by_layer: Dict[LayerName, kdb.Region]) -> Dict[LayerName, kdb.Region]:
            # NOTE: the capacitances to a well are on the layer of the substrate, which the wells are split from
            wells = [region for layer_name, region in region_by_layer.items() if layer_name in well_layer_names]
            if not wells:
                return region_by_layer
            substrate = kdb.Region()
            for region in wells:
                substrate += region
            return {**region_by_layer, self.exclusions.substrate_layer_name: substrate}

        node_by_id = {node.node_id: node for node in network.nodes}
        names_by_node_id: Dict[int, List[str]] = defaultdict(list)
        net_pieces: List[NetPiece] = []

        def piece_name(name: str) -> str:
            # NOTE: not the name of another net, as a label can have any text
            while self.pex_context.top_circuit.net_by_name(name) is not None:
                name = f"{name}#"
            return name

        for index, piece in enumerate(pieces):
            piece_nodes = [node_by_id[rn.object_id()] for rn in piece if rn.object_id() in node_by_id]
            name = piece_name(f"{network.net_name}#piece{index}")
            region_by_layer: Dict[LayerName, kdb.Region] = {}
            for layer_id in sorted(wire_layer_ids & set(regions)):
                nodes_on_layer = [node for node in piece_nodes if node.layer_name == layer_names[layer_id]]
                if nodes_on_layer:
                    # NOTE: with what is on the ideal copy of the layer, which has the same name
                    region = regions[layer_id].interacting(self.node_boxes(nodes_on_layer))
                    layer_name = layer_names[layer_id]
                    region_by_layer[layer_name] = region_by_layer[layer_name] + region \
                        if layer_name in region_by_layer else region
            if piece_nodes:
                net_pieces.append(NetPiece(name, with_substrate(region_by_layer)))
            for node in piece_nodes:
                names_by_node_id[node.node_id].append(name)

        def block_index_of(node: r_network_pb2.RNode) -> int:
            # NOTE: a port at a terminal of a removed device can be on a net taken out of the block
            block_index = split.block_of_node_id.get(node.node_id, None)
            if block_index is None:
                block_index = self.exclusions.block_index_with_ports_at(self.node_box(node), node.layer_name)
            return block_index

        nodes_of_blocks: Dict[int, List[r_network_pb2.RNode]] = defaultdict(list)
        for node in network.nodes:
            if node.node_kind == K.KIND_EXCLUSION_PORT:
                nodes_of_blocks[block_index_of(node)].append(node)
        for node in nodes_within:
            nodes_of_blocks[block_index_of(node)].append(node)
        for block_index, region_by_layer in split.regions_within.items():
            name = piece_name(f"{network.net_name}#marker{block_index}")
            nodes_of_block = nodes_of_blocks.get(block_index, [])
            if nodes_of_block:
                net_pieces.append(NetPiece(name, with_substrate(region_by_layer)))
            for node in nodes_of_block:
                names_by_node_id[node.node_id].append(name)

        if len(net_pieces) > 1:
            self.exclusions.pieces_by_net[network.net_name] = net_pieces
            for node in network.nodes:
                node.piece_names.extend(names_by_node_id.get(node.node_id, []))

    @staticmethod
    def network_pieces(resistor_network: klp.RNetwork,
                       node_id_ties: Sequence[Tuple[int, int]] = ()) -> List[List[klp.RNode]]:
        """
        :param node_id_ties: the nodes joined besides by the resistors
        :return: the nodes of each piece of the network, which no resistor joins to the others
        """
        nodes = list(resistor_network.each_node())
        node_sets = DisjointSets(n.object_id() for n in nodes)
        for el in resistor_network.each_element():
            node_sets.union(el.a().object_id(), el.b().object_id())
        for node_id_a, node_id_b in node_id_ties:
            node_sets.union(node_id_a, node_id_b)

        pieces: Dict[int, List[klp.RNode]] = defaultdict(list)
        for n in nodes:
            pieces[node_sets.find(n.object_id())].append(n)
        return list(pieces.values())

    @staticmethod
    def isolated_well_node_ids(pieces: List[List[klp.RNode]],
                               well_layer_ids: Set[int],
                               cut_ports: Collection[PolygonPortKey] = ()) -> Set[int]:
        """
        :param cut_ports: the polygon ports at the cuts of exclusion blocks, where a model joins a piece to the rest
        :return: the nodes of the pieces of the network that are wells only, without a pin or a port at a cut,
                 i.e. the wells no contact joins to the rest of their net
                 (none if the network is one piece, e.g. a well with the bulks of transistors only)
        """
        if len(pieces) < 2:
            return set()

        def is_port(n: klp.RNode) -> bool:
            return n.type() == klp.RNodeType.VertexPort or \
                (n.type() == klp.RNodeType.PolygonPort and (n.layer(), n.port_index()) in cut_ports)

        return {n.object_id()
                for piece in pieces
                if all(n.layer() in well_layer_ids and not is_port(n) for n in piece)
                for n in piece}

    def substrate_joined_node_ids(self,
                                  network: r_network_pb2.RNetwork,
                                  regions: Dict[int, kdb.Region],
                                  layer_names: Dict[int, LayerName],
                                  well_layer_ids: Set[int]) -> Set[int]:
        """
        :param regions: the shapes of the net, by layer ID
        :param layer_names: the canonical names of the conductors and vias, by layer ID
        :return: the nodes that the substrate or a well joins to the net of the network, as LVS does:
                 the nodes on a well, and on the conductors joined to a tap (see SubstrateInfo.tap_connections)
        """
        well_layer_names = {layer_names[layer_id] for layer_id in well_layer_ids}
        node_ids = {n.node_id for n in network.nodes if n.layer_name in well_layer_names}

        tech = self.pex_context.tech
        layout = self.pex_context.annotated_layout
        for connection in tech.tech.substrate.tap_connections:
            conductor_layer_id = layout.layer(*tech.gds_pair(connection.conductor_layer_name))
            tap_layer_id = layout.layer(*tech.gds_pair(connection.tap_lvs_layer_name))
            if conductor_layer_id not in layer_names or conductor_layer_id not in regions or tap_layer_id not in regions:
                continue
            conductor = regions[conductor_layer_id]
            if ideal_layer_id(conductor_layer_id) in regions:
                conductor = conductor + regions[ideal_layer_id(conductor_layer_id)]
            node_ids |= self.node_ids_at(nodes=[n for n in network.nodes if n.layer_name == layer_names[conductor_layer_id]],
                                         polygons=conductor.interacting(regions[tap_layer_id]))
        return node_ids

    @staticmethod
    def node_box(node: r_network_pb2.RNode) -> kdb.Box:
        """
        :return: the location of the node, enlarged, as a region drops a box without area
                 (the location of a pin, or a junction across a wire)
        """
        match node.location.kind:
            case location_pb2.Location.Kind.LOCATION_KIND_POINT:
                point = kdb.Point(node.location.point.x, node.location.point.y)
                box = kdb.Box(point, point)
            case _:
                box = kdb.Box(node.location.box.lower_left.x, node.location.box.lower_left.y,
                              node.location.box.upper_right.x, node.location.box.upper_right.y)
        return box.enlarged(1)

    @classmethod
    def node_boxes(cls, nodes: List[r_network_pb2.RNode]) -> kdb.Region:
        boxes = kdb.Region()
        boxes.merged_semantics = False  # NOTE: each box on its own, rather than the polygon of those overlapping
        for node in nodes:
            boxes.insert(cls.node_box(node))
        return boxes

    @classmethod
    def node_ids_at(cls, nodes: List[r_network_pb2.RNode], polygons: kdb.Region) -> Set[int]:
        """
        :return: the nodes at the polygons, by their location
        """
        node_ids_by_box: Dict[kdb.Box, List[int]] = defaultdict(list)
        for node in nodes:
            node_ids_by_box[cls.node_box(node)].append(node.node_id)

        boxes = kdb.Region()
        boxes.merged_semantics = False  # NOTE: each box on its own, rather than the polygon of those overlapping
        for box in node_ids_by_box:
            boxes.insert(box)
        return {node_id for polygon in boxes.interacting(polygons).each() for node_id in node_ids_by_box[polygon.bbox()]}
