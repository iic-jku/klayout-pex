#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
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

"""
What the 2.5D extraction leaves to a model of the layout it stands for (e.g. an EM model of an inductor),
by exclusion markers (#401)

NOTE: the conductors within a marker stay in the layout the capacitances are extracted from, as they shield
      the rest of the layout, whose capacitances neither the netlist nor the model would have without them.
      So only the extracted parasitics are filtered, each by the plates it is between:
        - both within one marker, or one within a marker and the other the substrate: left out, the model has them
        - both outside: unchanged
        - one within a marker, the other outside: kept (on the net of the plate within the marker, or on the
          substrate if nothing connects that net to the netlist), as the model doesn't know the conductor outside
      The resistance network has no resistance within a marker (see RExtractor.split_at_exclusions)

NOTE: with ports at the cuts, the parts of a net that only a model joins are apart in the netlist,
      so their capacitances to each other count, unlike the ones within a net otherwise (see NetPiece)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
import re
from typing import *

import klayout.db as kdb

from ..types import GDSPair, LayerName, NetName


Interval = Tuple[float, float]  # a part of an edge, by the parameter t ∈ [0, 1] along it


class ExclusionError(Exception):
    """
    What is to be left out can't be honored
    """
    pass


class ExclusionMarkerMode(StrEnum):
    """
    What the 2.5D engine does with the exclusion markers of the tech info (--exclusion-markers)
    """
    IGNORE = 'ignore'
    """extract what is within them, like the rest of the layout"""
    TIE = 'tie'
    """leave out the parasitics within them, each net stays connected across them, without resistance"""
    PORTS = 'ports'
    """leave out the parasitics within them, where a net enters them is a port, for the model"""
    DEFAULT = 'ignore'


def merged_intervals(intervals: Iterable[Interval]) -> List[Interval]:
    merged: List[Interval] = []
    for t0, t1 in sorted(intervals):
        if merged and t0 <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], t1))
        else:
            merged.append((t0, t1))
    return merged


def intersected_intervals(intervals_a: List[Interval], intervals_b: List[Interval]) -> List[Interval]:
    """
    :param intervals_a: merged intervals
    :param intervals_b: merged intervals
    """
    intersected: List[Interval] = []
    i, j = 0, 0
    while i < len(intervals_a) and j < len(intervals_b):
        t0, t1 = max(intervals_a[i][0], intervals_b[j][0]), min(intervals_a[i][1], intervals_b[j][1])
        if t0 < t1:
            intersected.append((t0, t1))
        if intervals_a[i][1] <= intervals_b[j][1]:
            i += 1
        else:
            j += 1
    return intersected


def complemented_intervals(intervals: List[Interval]) -> List[Interval]:
    """
    :param intervals: merged intervals
    :return: the rest of [0, 1]
    """
    complemented: List[Interval] = []
    t = 0.0
    for t0, t1 in intervals:
        if t0 > t:
            complemented.append((t, t0))
        t = t1
    if t < 1.0:
        complemented.append((t, 1.0))
    return complemented


def intervals_within(edge: kdb.Edge, region: kdb.Region) -> List[Interval]:
    """
    :return: the merged parts of the edge within the region (also on its boundary)
    """
    dx, dy = edge.dx(), edge.dy()
    squared_length = dx * dx + dy * dy
    if squared_length == 0:
        return []

    def parameter(x: int, y: int) -> float:
        return ((x - edge.x1) * dx + (y - edge.y1) * dy) / squared_length

    return merged_intervals(sorted((parameter(part.x1, part.y1), parameter(part.x2, part.y2)))
                            for part in (kdb.Edges([edge]) & region).each())


def edge_part(edge: kdb.Edge, interval: Interval) -> kdb.Edge:
    """
    :return: the part of the edge of the interval, rounded to the grid
    """
    def point(t: float) -> kdb.Point:
        return kdb.Point(round(edge.x1 + t * edge.dx()), round(edge.y1 + t * edge.dy()))
    return kdb.Edge(point(interval[0]), point(interval[1]))


def listed_names(names: Sequence[str], listed_count: int = 20) -> str:
    """
    :return: the names for a message, of many only the first ones
    """
    more = f", and {len(names) - listed_count} more" if len(names) > listed_count else ''
    return ', '.join(names[:listed_count]) + more


class RegionIndex:
    """
    The polygons of regions by location: a boolean operation goes through all polygons of its operands,
    while a capacitance or a net only needs those near it, also of a hard block of many shapes
    """

    def __init__(self):
        # NOTE: with the region, as its ID would go to another one otherwise
        self._shapes_by_id: Dict[int, Tuple[kdb.Region, kdb.Shapes]] = {}

    def near(self, region: kdb.Region, box: kdb.Box) -> kdb.Region:
        """
        :param region: which must not change anymore
        :return: the merged polygons of the region that touch the box
        """
        entry = self._shapes_by_id.get(id(region), None)
        if entry is None:
            shapes = kdb.Shapes()
            shapes.insert(region.merged())
            entry = (region, shapes)
            self._shapes_by_id[id(region)] = entry
        polygons = kdb.Region()
        for shape in entry[1].each_touching(kdb.Shapes.SRegions, box):
            polygons.insert(shape.polygon)
        return polygons


@dataclass
class NetPiece:
    """
    A part of a net with ports at exclusion markers, which its other parts are only joined to through a model:
    the metal outside the markers that resistors join, or the metal within one marker.

    NOTE: by location, as a polygon can have several of them, e.g. a coil with its leads
    """
    name: str  # NOTE: stands for the net in the capacitance tables, until they go to the nodes of the piece
    region_by_layer: Dict[LayerName, kdb.Region]


@dataclass(frozen=True)
class MarkerLayer:
    """
    A layer of the layout that marks what the extraction leaves out
    """
    name: str  # NOTE: for messages
    gds_pair: GDSPair
    layer_names: FrozenSet[LayerName] = frozenset()  # the layers of the stack it applies to, all if empty
    is_capacitance_pair: bool = False  # it only leaves out the capacitances between its two layers

    @classmethod
    def parse(cls,
              specification: str,
              tech_markers: Mapping[str, MarkerLayer],
              stack_layer_names: Collection[LayerName]) -> MarkerLayer:
        """
        :param specification: the name of a marker of the tech info, or a GDS pair with the optional layers
                              of the stack it applies to, e.g. 235/5 or 235/5:met2,met3
        :param tech_markers: the markers of the tech info by name
        :param stack_layer_names: the layers of the stack
        """
        if specification in tech_markers:
            return tech_markers[specification]
        match = re.fullmatch(r'(\d+)/(\d+)(?::(.+))?', specification)
        if match is None:
            raise ExclusionError(f"The exclusion marker layer {specification} is neither L/D or L/D:layer,layer "
                                 f"nor a marker of the tech info: {', '.join(tech_markers) or 'it has none'}")
        layer_names = frozenset(match.group(3).split(',')) if match.group(3) else frozenset()
        unknown_layer_names = sorted(layer_names - set(stack_layer_names))
        if unknown_layer_names:
            raise ExclusionError(f"The exclusion marker layer {specification} names layers the stack doesn't have: "
                                 f"{', '.join(unknown_layer_names)}, it has: {', '.join(sorted(stack_layer_names))}")
        return cls(name=specification, gds_pair=(int(match.group(1)), int(match.group(2))), layer_names=layer_names)


def selected_marker_layers(tech_markers: Iterable[Any],
                           stack_layer_names: Collection[LayerName],
                           specifications: Optional[Sequence[str]]) -> List[MarkerLayer]:
    """
    :param tech_markers: the markers of the tech info (ExclusionMarker)
    :param stack_layer_names: the layers of the stack
    :param specifications: of the marker layers (see MarkerLayer.parse), by default the markers on by default
    :raises ExclusionError: if one is invalid
    """
    markers = list(tech_markers)
    marker_layers = {m.name: MarkerLayer(name=m.name,
                                         gds_pair=(m.gds_pair.layer, m.gds_pair.datatype),
                                         layer_names=frozenset(m.layer_names),
                                         is_capacitance_pair=m.is_capacitance_pair)
                     for m in markers}
    if not specifications:
        return [marker_layers[m.name] for m in markers if not m.on_request]
    return [MarkerLayer.parse(specification, marker_layers, stack_layer_names) for specification in specifications]


@dataclass
class ExcludedBlock:
    """
    What one model stands for: a capacitance between plates within different blocks stays, as neither model has it
    """
    name: str  # NOTE: for the names of ports
    region: kdb.Region  # NOTE: all of its shapes, or the same on each layer if it has no layer_regions
    layer_regions: Optional[Dict[LayerName, kdb.Region]] = None  # its shapes by layer, it isn't on other layers
    capacitance_pair: Optional[FrozenSet[LayerName]] = None  # it only leaves out the capacitances between these layers
    ports: bool = False  # where a net enters it is a port, otherwise it stays connected across it

    def region_of(self, layer_name: LayerName) -> Optional[kdb.Region]:
        return self.region if self.layer_regions is None else self.layer_regions.get(layer_name, None)

    def applies_between(self, layer_name_a: LayerName, layer_name_b: LayerName) -> bool:
        return self.capacitance_pair is None or self.capacitance_pair == {layer_name_a, layer_name_b}


def polygons_by_center_inside(shapes: kdb.Region, mask: kdb.Region) -> kdb.Region:
    """
    :return: the merged polygons of the shapes with the center of their bounding boxes strictly inside the mask
    """
    polygons_by_center_box: Dict[kdb.Box, List[kdb.Polygon]] = defaultdict(list)
    center_boxes = kdb.Region()
    center_boxes.merged_semantics = False  # NOTE: each box on its own
    for polygon in shapes.merged().each():
        center = polygon.bbox().center()
        box = kdb.Box(center, center).enlarged(1, 1)
        polygons_by_center_box[box].append(polygon.downcast())
        center_boxes.insert(box)
    within = kdb.Region()
    for box in center_boxes.inside(mask).each():
        for polygon in polygons_by_center_box[box.bbox()]:
            within.insert(polygon)
    return within


class Exclusions:
    """
    What the extraction leaves out of a layout, as blocks that models stand for
    """

    def __init__(self, blocks: List[ExcludedBlock], substrate_layer_name: LayerName = 'VSUBS'):
        """
        :param blocks: in the coordinates of the top cell, in DBU of the extraction
        :param substrate_layer_name: of the capacitances, the model of a block has the substrate below all its plates
        """
        self.blocks = blocks
        self.substrate_layer_name = substrate_layer_name
        self.bbox = kdb.Box()
        for block in blocks:
            self.bbox += block.region.bbox()

        # NOTE: found by their boxes, as each capacitance looks them up
        self.block_boxes = kdb.Shapes()
        for index, block in enumerate(blocks):
            self.block_boxes.insert(kdb.BoxWithProperties(block.region.bbox(), {'block': index}))

        self._masks: Dict[Tuple[LayerName, Optional[bool]], kdb.Region] = {}
        self.regions = RegionIndex()

        # the nets within the blocks that nothing connects to the netlist (see net_of_capacitance)
        self.floating_net_names: Set[NetName] = set()

        # the pieces of the nets with ports at the blocks, by the resistance extraction
        self.pieces_by_net: Dict[NetName, List[NetPiece]] = {}

    @classmethod
    def from_region(cls,
                    region: kdb.Region,
                    ports: bool = False,
                    substrate_layer_name: LayerName = 'VSUBS') -> Exclusions:
        """
        :param region: shapes that mark all layers of the stack, each merged polygon a block
        """
        return cls(cls.blocks_of_marker_region(region, MarkerLayer('', (0, 0)), ports, first_index=0),
                   substrate_layer_name)

    @staticmethod
    def blocks_of_marker_region(region: kdb.Region,
                                marker_layer: MarkerLayer,
                                ports: bool,
                                first_index: int) -> List[ExcludedBlock]:
        """
        :param region: the shapes of the marker layer
        :param first_index: of the first block, as the names of the blocks number them
        :return: a block of each merged polygon
        """
        blocks: List[ExcludedBlock] = []
        for index, polygon in enumerate(region.merged().each(), start=first_index):
            block_region = kdb.Region(polygon.downcast())
            layer_regions = {layer_name: block_region for layer_name in marker_layer.layer_names} \
                            if marker_layer.layer_names else None
            blocks.append(ExcludedBlock(name=f"m{index}",
                                        region=block_region,
                                        layer_regions=layer_regions,
                                        capacitance_pair=marker_layer.layer_names
                                                         if marker_layer.is_capacitance_pair else None,
                                        ports=ports and not marker_layer.is_capacitance_pair))
        return blocks

    @classmethod
    def from_layout(cls,
                    layout: kdb.Layout,
                    cell_name: str,
                    marker_layers: Iterable[MarkerLayer],
                    dbu: float,
                    ports: bool = False,
                    substrate_layer_name: LayerName = 'VSUBS') -> Exclusions:
        """
        :param layout: the layout the LVS database is of
        :param cell_name: the top cell of the extraction
        :param marker_layers: the marker layers
        :param dbu: the database unit of the extraction
        :param ports: where a net enters a marker is a port, otherwise it stays connected across the marker
        :param substrate_layer_name: see __init__
        """
        cell = layout.cell(cell_name)
        scale = kdb.ICplxTrans(layout.dbu / dbu)
        blocks: List[ExcludedBlock] = []
        for marker_layer in marker_layers:
            layer_index = layout.find_layer(*marker_layer.gds_pair)
            if layer_index is not None:
                region = kdb.Region(cell.begin_shapes_rec(layer_index)).transformed(scale)
                blocks.extend(cls.blocks_of_marker_region(region, marker_layer, ports, first_index=len(blocks)))
        return cls(blocks, substrate_layer_name)

    def mask(self,
             layer_name: LayerName,
             ports: Optional[bool] = None) -> kdb.Region:
        """
        :param layer_name: a layer of the stack
        :param ports: only of the blocks with ports at their cuts, or without
        :return: the shapes of the blocks on the layer, but of those that only leave out some capacitances
        """
        key = (layer_name, ports)
        mask = self._masks.get(key, None)
        if mask is None:
            mask = kdb.Region()
            for block in self.blocks:
                region = block.region_of(layer_name)
                if region is not None and block.capacitance_pair is None and ports in (None, block.ports):
                    mask += region
            mask = mask.merged()
            self._masks[key] = mask
        return mask

    def mask_near(self,
                  box: kdb.Box,
                  layer_name: LayerName,
                  ports: Optional[bool] = None) -> kdb.Region:
        """
        :return: the polygons of the mask (see mask) that touch the box
        """
        return self.regions.near(self.mask(layer_name, ports), box)

    def block_indexes_touching(self, box: kdb.Box) -> List[int]:
        """
        :return: the indexes of the blocks whose boxes touch the box, in their order
        """
        return sorted(shape.property('block') for shape in self.block_boxes.each_touching(kdb.Shapes.SAll, box))

    def block_index_with_ports_at(self, box: kdb.Box, layer_name: LayerName) -> int:
        """
        :param box: of something at a block (e.g. a strip of metal beside it)
        :param layer_name: of a layer the block is on
        :return: the index of the first block with ports it touches (not only by the box of the block)
        """
        box = box.enlarged(1, 1)
        box_region = kdb.Region(box)

        def touches(block: ExcludedBlock) -> bool:
            region = block.region_of(layer_name)
            return block.ports and region is not None and \
                not self.regions.near(region, box).interacting(box_region).is_empty()

        return next(index for index in self.block_indexes_touching(box) if touches(self.blocks[index]))

    def block_indexes_with_ports_within(self, polygon: kdb.Region, layer_name: LayerName) -> List[int]:
        """
        :param polygon: of something within blocks
        :param layer_name: its layer
        :return: the indexes of the blocks with ports it is within, also only partly
        """
        box = polygon.bbox()

        def overlaps(block: ExcludedBlock) -> bool:
            region = block.region_of(layer_name)
            return block.ports and region is not None and not (polygon & self.regions.near(region, box)).is_empty()

        return [index for index in self.block_indexes_touching(box) if overlaps(self.blocks[index])]

    def net_of_capacitance(self, net_name: NetName, substrate_net_name: NetName) -> NetName:
        """
        :return: the net a capacitance of a plate of the net goes to:
                 the substrate for the conductors within a block that nothing connects to the netlist,
                 like metal with a floating node, but which a model of the block doesn't know either
        """
        return substrate_net_name if net_name in self.floating_net_names else net_name

    def has_pieces(self, net_name: NetName) -> bool:
        return net_name in self.pieces_by_net

    def area_parts(self,
                   area: kdb.Region,
                   net_name: NetName,
                   layer_name: LayerName) -> List[Tuple[kdb.Region, NetName]]:
        """
        :param area: of a plate of the net on the layer
        :return: its parts by the piece of the net they are on, or by the net itself, off its pieces
                 (e.g. the substrate, or metal the resistance extraction has no nodes on)
        """
        pieces = self.pieces_by_net.get(net_name, None)
        if pieces is None:
            return [(area, net_name)]
        parts: List[Tuple[kdb.Region, NetName]] = []
        rest = area
        for piece in pieces:
            region = piece.region_by_layer.get(layer_name, None)
            if region is None:
                continue
            part = rest & self.regions.near(region, rest.bbox())
            if not part.is_empty():
                parts.append((part, piece.name))
                rest = rest - part
        if not rest.is_empty():
            parts.append((rest, net_name))
        return parts

    def edge_parts(self,
                   edge: kdb.Edge,
                   metal_side: int,
                   net_name: NetName,
                   layer_name: LayerName) -> List[Tuple[Interval, NetName]]:
        """
        :param edge: of a plate of the net on the layer
        :param metal_side: where the metal is beside the edge, -1 on its right, 1 on its left
        :return: its parts by the piece of the net they are on, or by the net itself, off its pieces
        """
        pieces = self.pieces_by_net.get(net_name, None)
        if pieces is None:
            return [((0.0, 1.0), net_name)]
        metal_edge = edge.shifted(metal_side)
        parts: List[Tuple[Interval, NetName]] = []
        rest: List[Interval] = [(0.0, 1.0)]
        for piece in pieces:
            region = piece.region_by_layer.get(layer_name, None)
            if region is not None:
                # NOTE: each part of the edge on one piece only, as a node of a piece can touch a polygon of another
                within = intervals_within(metal_edge, self.regions.near(region, metal_edge.bbox()))
                parts.extend((interval, piece.name) for interval in intersected_intervals(within, rest))
                rest = intersected_intervals(rest, complemented_intervals(within))
        parts.extend((interval, net_name) for interval in rest)
        return sorted(parts)

    def blocks_touching(self, box: kdb.Box) -> Iterator[ExcludedBlock]:
        for shape in self.block_boxes.each_touching(kdb.Shapes.SAll, box):
            yield self.blocks[shape.property('block')]

    def excluded_area(self, area: kdb.Region, layer_name_a: LayerName, layer_name_b: LayerName) -> kdb.Region:
        """
        :param area: an overlap of two plates, of these layers, the second may be the substrate
        :return: the part of it that a model has: both plates (or a plate and the substrate) within one block
        """
        excluded = kdb.Region()
        for block in self.blocks_touching(area.bbox()):
            if not block.applies_between(layer_name_a, layer_name_b):
                continue
            part = area
            for layer_name in (layer_name_a, layer_name_b):
                if layer_name != self.substrate_layer_name:
                    region = block.region_of(layer_name)
                    part = kdb.Region() if region is None else part & self.regions.near(region, area.bbox())
            excluded += part
        return excluded.merged()

    def kept_edge_parts(self,
                        edge_a: kdb.Edge,
                        layer_name_a: LayerName,
                        edge_b: kdb.Edge,
                        layer_name_b: LayerName) -> List[Interval]:
        """
        The capacitance between a plate and what its edge faces (e.g. a sidewall, a fringe)

        :param edge_a: the edge of the plate (on its right), in a direction of its polygon
        :param layer_name_a: the layer of the plate
        :param edge_b: the edge of what it faces (same direction, on its left)
        :param layer_name_b: the layer of what it faces, the substrate is below all plates of a model
        :return: the parts of the edges (their parameters) that the model doesn't have
        """
        if not edge_a.bbox().enlarged(1, 1).touches(self.bbox):
            return [(0.0, 1.0)]

        # NOTE: by the metal beside the edges rather than the edges, as they may be on the boundary of a marker,
        #       e.g. a plate within it up to there, or a wire outside that ends there
        metal_edge_a = edge_a.shifted(-1)
        metal_edge_b = edge_b.shifted(1)

        excluded: List[Interval] = []
        for block in self.blocks_touching(metal_edge_a.bbox()):
            if not block.applies_between(layer_name_a, layer_name_b):
                continue
            region_a = block.region_of(layer_name_a)
            if region_a is None:
                continue
            parts = intervals_within(metal_edge_a, self.regions.near(region_a, metal_edge_a.bbox()))
            if parts and layer_name_b != self.substrate_layer_name:
                region_b = block.region_of(layer_name_b)
                parts = [] if region_b is None else intersected_intervals(
                    parts, intervals_within(metal_edge_b, self.regions.near(region_b, metal_edge_b.bbox())))
            excluded.extend(parts)
        return complemented_intervals(merged_intervals(excluded))
