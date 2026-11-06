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

NOTE: a field solver only tells the capacitances between its conductors, not where they end on them,
      so each net is a conductor per set of blocks it is within (see ConductorPart), and the matrix filtered by these
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase
import re
from typing import *

import klayout.db as kdb

from ..common.capacitance_matrix import CapacitanceMatrix
from ..types import GDSPair, LayerName, NetName

import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2


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
class ConductorPart:
    """
    A part of a net that a field solver has as a conductor of its own
    """
    net_name: NetName
    block_indexes: FrozenSet[int] = frozenset()  # of the blocks it is within, as these can overlap
    layer_name: Optional[LayerName] = None  # its layer, within a block that only leaves out some capacitances
    is_substrate: bool = False  # the substrate below everything, as the net of the substrate can have metal as well


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


@dataclass(frozen=True)
class CutRequest:
    """
    The instances of the cells to leave out of the extraction, for models of them (kpex --cut)
    """
    cell_pattern: str  # a name of a cell, or a glob pattern of names
    prefix: Optional[str] = None  # of the names of the ports, by default the name of the cell and a number

    @property
    def specification(self) -> str:
        return self.cell_pattern if self.prefix is None else f"{self.cell_pattern}={self.prefix}"

    @classmethod
    def parse(cls, specification: str) -> CutRequest:
        """
        :param specification: CELL or CELL=PREFIX
        """
        cell_pattern, separator, prefix = specification.partition('=')
        if not cell_pattern or (separator and not prefix):
            raise ExclusionError(f"--cut {specification}: expected CELL or CELL=PREFIX")
        if prefix and re.fullmatch(r'[A-Za-z0-9_]+', prefix) is None:
            raise ExclusionError(f"--cut {specification}: the prefix names ports of the netlist, "
                                 f"so it may only have letters, digits and _")
        return cls(cell_pattern, prefix or None)


def parsed_cut_requests(specifications: Iterable[str]) -> List[CutRequest]:
    """
    :raises ExclusionError: if one is invalid, or two have the same prefix, whose ports would be one node
    """
    requests = [CutRequest.parse(specification) for specification in specifications]
    prefixes = Counter(request.prefix for request in requests if request.prefix is not None)
    duplicates = sorted(prefix for prefix, count in prefixes.items() if count > 1)
    if duplicates:
        raise ExclusionError(f"--cut: each one needs a prefix of its own, given several times: {', '.join(duplicates)}")
    return requests


@dataclass(frozen=True)
class CutLayers:
    """
    Which shapes of a cell are on which layers of the stack
    """
    # the drawn layers of the conductors with their fill, by layer of the stack: the own one (metal, wells),
    # or the diffusion for what LVS computes from it (e.g. the source/drain), as its implants overhang
    gds_pairs_by_layer: Mapping[LayerName, Collection[GDSPair]]
    # the labels of the metal, by layer of the stack
    label_gds_pairs: Mapping[LayerName, GDSPair]
    diffusion_gds_pairs: Collection[GDSPair]

    @classmethod
    def of_tech(cls, tech_info: Any) -> CutLayers:
        """
        :param tech_info: the TechInfo
        """
        def pair(gds_pair: Any) -> GDSPair:
            return gds_pair.layer, gds_pair.datatype

        def drawn_gds_pairs(layer: Any) -> Tuple[GDSPair, ...]:
            return (pair(layer.drw_gds_pair), pair(layer.fill_gds_pair)) if layer.HasField('fill_gds_pair') \
                else (pair(layer.drw_gds_pair),)

        LP = tech_pb2.LayerInfo.Purpose
        layers = list(tech_info.tech.layers)
        diffusion_gds_pairs = {gds_pair for layer in layers
                               if layer.purpose in (LP.PURPOSE_DIFF, LP.PURPOSE_NTAP_OR_PTAP)
                               for gds_pair in drawn_gds_pairs(layer)}
        gds_pairs_by_layer: Dict[LayerName, Collection[GDSPair]] = {
            layer_name: diffusion_gds_pairs for layer_name in tech_info.process_diffusion_layer_names
        }
        gds_pairs_by_layer.update({layer.name: drawn_gds_pairs(layer) for layer in layers
                                   if layer.purpose in (LP.PURPOSE_METAL, LP.PURPOSE_MIM_CAP, LP.PURPOSE_NWELL,
                                                        LP.PURPOSE_PWELL, LP.PURPOSE_DNWELL)})
        return cls(gds_pairs_by_layer=gds_pairs_by_layer,
                   label_gds_pairs={layer.name: pair(layer.label_gds_pair) for layer in layers
                                    if layer.purpose in (LP.PURPOSE_METAL, LP.PURPOSE_MIM_CAP)
                                    and layer.HasField('label_gds_pair')},
                   diffusion_gds_pairs=diffusion_gds_pairs)


@dataclass(frozen=True)
class BlockLabel:
    text: str
    position: kdb.Point
    layer_name: LayerName


class BlockKind(StrEnum):
    MARKER = 'marker'
    CUT = 'cut'


@dataclass(frozen=True)
class CutCellInstance:
    """
    An instance of a cut cell in the layout, which tells who draws what is at a place of it
    """
    layout: kdb.Layout
    top_cell: kdb.Cell
    cell: kdb.Cell
    top_trans: kdb.ICplxTrans  # of the top cell, into the coordinates of the blocks
    cell_trans: kdb.ICplxTrans  # of the instance, into the coordinates of the blocks

    @staticmethod
    def _shapes_of(cell: kdb.Cell, trans: kdb.ICplxTrans, layer_index: int, box: kdb.Box) -> kdb.Region:
        return kdb.Region(cell.begin_shapes_rec_touching(layer_index, trans.inverted() * box)).transformed(trans)

    def shapes_of_layout(self, gds_pairs: Iterable[GDSPair], box: kdb.Box) -> kdb.Region:
        """
        :param box: in the coordinates of the blocks
        :return: all shapes of the layout on the layers that touch the box
        """
        shapes = kdb.Region()
        for gds_pair in gds_pairs:
            layer_index = self.layout.find_layer(*gds_pair)
            if layer_index is not None:
                shapes += self._shapes_of(self.top_cell, self.top_trans, layer_index, box)
        return shapes

    def draws_device(self, gds_pairs: Iterable[GDSPair], terminals: Sequence[kdb.Region]) -> bool:
        """
        :param gds_pairs: the layers that LVS makes the device from (see TechInfo.device_gds_pairs)
        :param terminals: the shapes of its terminals, in the coordinates of the blocks
        :return: whether the cell draws the device, on each of these layers that is at its terminals: a polygon at all
                 of them, unless only the rest of the layout has one, or it has one over more of them (e.g. a tap
                 that overlaps the one of a neighbor), as a terminal can be on a wire that goes on to another device
                 (a diffusion can also go on beyond the cell), or else at each of them, if nothing is at all of them
                 (e.g. the diffusions of a BJT)

        NOTE: a polygon of the cell is apart from one of the rest of the layout that it abuts (e.g. the taps at a cell,
              the fingers of a transistor). At a terminal are the polygons that overlap it, or else those that touch it,
              as the terminals of a resistor abut its marker
        """
        box = kdb.Box()
        for shapes in terminals:
            box += shapes.bbox()

        def polygons_at(shapes: kdb.Region) -> Tuple[kdb.Region, kdb.Region]:
            cell_at, rest_at = cell_polygons.overlapping(shapes), rest_polygons.overlapping(shapes)
            if cell_at.is_empty() and rest_at.is_empty():
                return cell_polygons.interacting(shapes), rest_polygons.interacting(shapes)
            return cell_at, rest_at

        draws_any = False
        for gds_pair in gds_pairs:
            layer_index = self.layout.find_layer(*gds_pair)
            if layer_index is None:
                continue
            cell_polygons = self._shapes_of(self.cell, self.cell_trans, layer_index, box).merged()
            rest_polygons = (self._shapes_of(self.top_cell, self.top_trans, layer_index, box) - cell_polygons).merged()
            at_terminals = [(shapes, *polygons_at(shapes)) for shapes in terminals]
            at_terminals = [at for at in at_terminals if not (at[1].is_empty() and at[2].is_empty())]
            if not at_terminals:
                continue
            draws_any = True
            cell_at_all, rest_at_all = at_terminals[0][1:]
            for _, cell_at, rest_at in at_terminals[1:]:
                cell_at_all, rest_at_all = cell_at_all & cell_at, rest_at_all & rest_at
            if cell_at_all.is_empty():
                if not rest_at_all.is_empty() or any(cell_at.is_empty() for _, cell_at, _ in at_terminals):
                    return False
            elif sum((rest_at_all & shapes).area() for shapes, _, _ in at_terminals) > \
                    sum((cell_at_all & shapes).area() for shapes, _, _ in at_terminals):
                return False
        return draws_any


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
    kind: BlockKind = BlockKind.MARKER
    labels: List[BlockLabel] = field(default_factory=list)  # of a cut cell, which name the ports
    cell_instance: Optional[CutCellInstance] = None  # of a cut cell, which tells its devices

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


def cells_called_by(layout: kdb.Layout, cell: kdb.Cell) -> List[str]:
    """
    :return: the names of the cells below the cell, sorted
    """
    return sorted(layout.cell(index).name for index in cell.called_cells())


def matches_name(name: str, pattern: str) -> bool:
    """
    :return: whether the name is the pattern (e.g. data[1], whose brackets a pattern takes as a set), or matches it
    """
    return name == pattern or fnmatchcase(name, pattern)


def instances_of_cut_cells(layout: kdb.Layout,
                           top_cell: kdb.Cell,
                           cut_requests: Sequence[CutRequest],
                           label_gds_pairs: Iterable[GDSPair],
                           scale: kdb.ICplxTrans) -> Tuple[Dict[CutRequest, List[Tuple[kdb.Cell, kdb.ICplxTrans]]],
                                                           Set[Tuple[str, kdb.Point]]]:
    """
    :param label_gds_pairs: of the labels of the metal
    :param scale: to the coordinates of the blocks
    :return: the instances of the cells of each request, sorted, but those within another one of them,
             and the labels of the rest of the layout on the metal, by their texts and positions
    :raises ExclusionError: if one isn't at a multiple of 90°, or something below it
    """
    instances_by_request: Dict[CutRequest, List[Tuple[kdb.Cell, kdb.ICplxTrans]]] = {r: [] for r in cut_requests}
    label_layer_indexes = [layer_index for layer_index in (layout.find_layer(*gds_pair) for gds_pair in label_gds_pairs)
                           if layer_index is not None]
    own_labels_by_cell: Dict[int, List[Tuple[str, kdb.Point]]] = {}
    labels_of_rest: Set[Tuple[str, kdb.Point]] = set()
    orientations_checked: Set[Tuple[int, float]] = set()

    def any_angle_instance_at(cell: kdb.Cell, trans: kdb.ICplxTrans) -> Optional[Tuple[kdb.Cell, float]]:
        """
        :return: the cell of an instance at or below this one that isn't at a multiple of 90°, with its angle
        """
        if not trans.is_ortho():
            return cell, trans.angle
        if (cell.cell_index(), trans.angle) not in orientations_checked:
            orientations_checked.add((cell.cell_index(), trans.angle))
            for instance in cell.each_inst():
                found = any_angle_instance_at(layout.cell(instance.cell_index), trans * instance.cplx_trans)
                if found is not None:
                    return found
        return None

    def own_labels(cell: kdb.Cell) -> List[Tuple[str, kdb.Point]]:
        labels = own_labels_by_cell.get(cell.cell_index(), None)
        if labels is None:
            labels = [(shape.text.string, kdb.Point(shape.text.x, shape.text.y))
                      for layer_index in label_layer_indexes
                      for shape in cell.shapes(layer_index).each(kdb.Shapes.STexts)]
            own_labels_by_cell[cell.cell_index()] = labels
        return labels

    def visit(cell: kdb.Cell, trans: kdb.ICplxTrans):
        labels_of_rest.update((text, trans * position) for text, position in own_labels(cell))
        for instance in cell.each_inst():
            child = layout.cell(instance.cell_index)
            request = next((r for r in cut_requests if matches_name(child.name, r.cell_pattern)), None)
            for instance_trans in instance.cell_inst.each_cplx_trans():
                child_trans = trans * instance_trans
                if request is not None:
                    # NOTE: of such an instance, LVS only has the bounding boxes of the shapes
                    any_angle_instance = any_angle_instance_at(child, child_trans)
                    if any_angle_instance is not None:
                        raise ExclusionError(f"--cut {request.cell_pattern}: an instance of the cell "
                                             f"{any_angle_instance[0].name} has an angle of "
                                             f"{any_angle_instance[1]:.6g}°, not a multiple of 90°")
                    instances_by_request[request].append((child, child_trans))
                else:
                    visit(child, child_trans)

    visit(top_cell, scale)
    for instances in instances_by_request.values():
        instances.sort(key=lambda i: (i[0].name, (i[1] * i[0].bbox()).bottom, (i[1] * i[0].bbox()).left))
    return instances_by_request, labels_of_rest


def names_of_blocks_of_cut_cells(instances_by_request: Mapping[CutRequest, Sequence[Tuple[kdb.Cell, kdb.ICplxTrans]]]) \
        -> Dict[CutRequest, List[str]]:
    """
    :param instances_by_request: see instances_of_cut_cells
    :return: the names of the blocks of the instances, in their order
    :raises ExclusionError: if several instances would have one name
    """
    names_by_request: Dict[CutRequest, List[str]] = {}
    instance_counts: Counter[str] = Counter()
    for request, instances in instances_by_request.items():
        names_by_request[request] = []
        for index, (cell, _) in enumerate(instances):
            if request.prefix is None:
                # NOTE: per cell, so that another cell of a pattern doesn't rename its ports
                safe_cell_name = re.sub(r'[^A-Za-z0-9_]', '_', cell.name)
                name = f"{safe_cell_name}_{instance_counts[safe_cell_name]}"
                instance_counts[safe_cell_name] += 1
            else:
                name = request.prefix if len(instances) == 1 else f"{request.prefix}_{index}"
            names_by_request[request].append(name)

    names = Counter(name for request_names in names_by_request.values() for name in request_names)
    duplicates = sorted(name for name, count in names.items() if count > 1)
    if duplicates:
        raise ExclusionError(f"--cut: several instances would have these names, whose ports would be one node, "
                             f"as the numbers of the instances of a cell follow its prefix: {', '.join(duplicates)}")
    return names_by_request


def check_instances_of_cut_cells(layout: kdb.Layout, top_cell: kdb.Cell, cut_requests: Sequence[CutRequest]):
    """
    :raises ExclusionError: see instances_of_cut_cells, names_of_blocks_of_cut_cells,
                            or if a request has no instances, as those of its cells are of another request,
                            or within another cut cell
    """
    instances_by_request, _ = instances_of_cut_cells(layout, top_cell, cut_requests, (), kdb.ICplxTrans())
    names_of_blocks_of_cut_cells(instances_by_request)
    for request, instances in instances_by_request.items():
        if not instances:
            raise ExclusionError(f"--cut {request.specification}: all instances of its cells are of another --cut "
                                 f"before it, or within a cell of one")


def blocks_of_cut_cells(layout: kdb.Layout,
                        top_cell: kdb.Cell,
                        cut_requests: Sequence[CutRequest],
                        cut_layers: CutLayers,
                        scale: kdb.ICplxTrans) -> Tuple[List[ExcludedBlock], Set[Tuple[str, kdb.Point]]]:
    """
    :return: a block of each instance of the cells, but those within another one of them,
             and the labels of the rest of the layout on the metal, by their texts and positions
    """
    instances_by_request, labels_of_rest = instances_of_cut_cells(layout, top_cell, cut_requests,
                                                                  cut_layers.label_gds_pairs.values(), scale)
    names_by_request = names_of_blocks_of_cut_cells(instances_by_request)

    def shapes_of(cell: kdb.Cell, gds_pairs: Iterable[GDSPair]) -> kdb.Region:
        shapes = kdb.Region()
        for gds_pair in gds_pairs:
            layer_index = layout.find_layer(*gds_pair)
            if layer_index is not None:
                shapes += kdb.Region(cell.begin_shapes_rec(layer_index))
        return shapes.merged()

    def labels_of(cell: kdb.Cell) -> List[BlockLabel]:
        labels: List[BlockLabel] = []
        for layer_name, gds_pair in cut_layers.label_gds_pairs.items():
            layer_index = layout.find_layer(*gds_pair)
            if layer_index is None:
                continue
            shape_iterator = cell.begin_shapes_rec(layer_index)
            while not shape_iterator.at_end():
                shape = shape_iterator.shape()
                if shape.is_text():
                    text = shape.text.transformed(shape_iterator.trans())
                    labels.append(BlockLabel(text.string, kdb.Point(text.x, text.y), layer_name))
                shape_iterator.next()
        return labels

    blocks: List[ExcludedBlock] = []
    for request, instances in instances_by_request.items():
        for name, (cell, trans) in zip(names_by_request[request], instances):
            # NOTE: one region for the layers of the same shapes, as a region of a layer goes by its identity
            regions_by_gds_pairs: Dict[FrozenSet[GDSPair], kdb.Region] = {}
            layer_regions: Dict[LayerName, kdb.Region] = {}
            for layer_name, gds_pairs in cut_layers.gds_pairs_by_layer.items():
                key = frozenset(gds_pairs)
                if key not in regions_by_gds_pairs:
                    regions_by_gds_pairs[key] = shapes_of(cell, gds_pairs).transformed(trans)
                layer_regions[layer_name] = regions_by_gds_pairs[key]
            region = kdb.Region()
            for layer_region in regions_by_gds_pairs.values():
                region += layer_region

            labels = [BlockLabel(label.text, trans * label.position, label.layer_name) for label in labels_of(cell)]
            blocks.append(ExcludedBlock(name=name, region=region.merged(), layer_regions=layer_regions, ports=True,
                                        kind=BlockKind.CUT, labels=labels,
                                        cell_instance=CutCellInstance(layout, top_cell, cell, scale, trans)))
    return blocks, labels_of_rest


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

        self._masks: Dict[Tuple[LayerName, Optional[bool], Optional[BlockKind]], kdb.Region] = {}
        self._kept_shapes: Dict[LayerName, kdb.Region] = defaultdict(kdb.Region)  # see without_shapes
        self._label_positions: Dict[Tuple[int, LayerName], kdb.Shapes] = {}  # see labels_at
        self.regions = RegionIndex()

        # the nets within the blocks that nothing connects to the netlist (see net_of_capacitance)
        self.floating_net_names: Set[NetName] = set()

        # the pieces of the nets with ports at the blocks, by the resistance extraction
        self.pieces_by_net: Dict[NetName, List[NetPiece]] = {}

        # the devices the netlist leaves out by their IDs, with the indexes of their blocks (of cut cells)
        self.removed_device_blocks: Dict[int, int] = {}

        # the nets without resistance, and without capacitance to the substrate (kpex --exclude-net)
        # NOTE: no blocks, as all capacitances between nets stay, and a block of a power grid would cost each of them
        self.excluded_net_names: Set[NetName] = set()

        # the labels of the layout on the metal, of the cut cells and outside them, by their texts and positions
        self.labels_of_cut_cells: Set[Tuple[str, kdb.Point]] = {(label.text, label.position)
                                                                for block in blocks for label in block.labels}
        self.labels_of_rest: Set[Tuple[str, kdb.Point]] = set()
        # the labels on each net, of the whole hierarchy, by its name (see KLayoutExtractionContext.labels_of_nets)
        self.labels_by_net_name: Mapping[NetName, Collection[str]] = {}

        # the parts of the nets the field solvers have as conductors, by the names of the conductors
        self.conductor_parts: Dict[str, ConductorPart] = {}
        self.conductor_names: Dict[ConductorPart, str] = {}

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
                    substrate_layer_name: LayerName = 'VSUBS',
                    cut_requests: Sequence[CutRequest] = (),
                    cut_layers: Optional[CutLayers] = None) -> Exclusions:
        """
        :param layout: the layout the LVS database is of
        :param cell_name: the top cell of the extraction
        :param marker_layers: the marker layers
        :param dbu: the database unit of the extraction
        :param ports: where a net enters a marker is a port, otherwise it stays connected across the marker
        :param substrate_layer_name: see __init__
        :param cut_requests: the cells to leave out, with ports where a net enters them
        :param cut_layers: which shapes of a cell are on which layers, for the cut requests
        """
        cell = layout.cell(cell_name)
        scale = kdb.ICplxTrans(layout.dbu / dbu)
        blocks: List[ExcludedBlock] = []
        for marker_layer in marker_layers:
            layer_index = layout.find_layer(*marker_layer.gds_pair)
            if layer_index is not None:
                region = kdb.Region(cell.begin_shapes_rec(layer_index)).transformed(scale)
                blocks.extend(cls.blocks_of_marker_region(region, marker_layer, ports, first_index=len(blocks)))
        labels_of_rest: Set[Tuple[str, kdb.Point]] = set()
        if cut_requests:
            blocks_of_cells, labels_of_rest = blocks_of_cut_cells(layout, cell, cut_requests, cut_layers, scale)
            blocks.extend(blocks_of_cells)
        exclusions = cls(blocks, substrate_layer_name)
        exclusions.labels_of_rest = labels_of_rest
        return exclusions

    def without_shapes(self, shapes_by_layer: Mapping[LayerName, kdb.Region]):
        """
        Takes shapes out of the cut cells (kpex --cut-keep-net), so that they are extracted like the rest of the layout

        :param shapes_by_layer: the shapes by layer of the stack
        """
        for layer_name, shapes in shapes_by_layer.items():
            self._kept_shapes[layer_name] += shapes
        for block in self.blocks:
            if block.kind == BlockKind.CUT:
                for layer_name, shapes in shapes_by_layer.items():
                    region = block.region_of(layer_name)
                    if region is not None:
                        block.layer_regions[layer_name] = (region - shapes).merged()
        self._masks.clear()

    def add_to_cut_cell(self, block_index: int, layer_name: LayerName, shapes: kdb.Region):
        """
        :param shapes: what the cell of the block stands for beyond what it draws on the layer of the stack
        """
        shapes = shapes - self._kept_shapes[layer_name]
        if shapes.is_empty():
            return
        block = self.blocks[block_index]
        block.layer_regions[layer_name] = (block.layer_regions[layer_name] + shapes).merged()
        block.region = (block.region + shapes).merged()
        self.bbox += shapes.bbox()
        self.block_boxes.insert(kdb.BoxWithProperties(shapes.bbox(), {'block': block_index}))
        self._masks.clear()

    def conductor_name(self, part: ConductorPart) -> str:
        """
        :return: the name of the conductor of the part, the name of the net for its part outside of the blocks,
                 unless that is the name of another conductor, as a label can have any text
        """
        name = self.conductor_names.get(part, None)
        if name is not None:
            return name
        if part.is_substrate:
            name = f"{part.net_name}#substrate"
        elif not part.block_indexes:
            name = part.net_name
        else:
            block_indexes = '_'.join(str(index) for index in sorted(part.block_indexes))
            name = f"{part.net_name}#x{block_indexes}"
            if part.layer_name is not None:
                name = f"{name}_{part.layer_name}"
        while name in self.conductor_parts:
            name = f"{name}#"
        self.conductor_parts[name] = part
        self.conductor_names[part] = name
        return name

    def conductor_parts_of_shapes(self,
                                  shapes: kdb.Region,
                                  net_name: NetName,
                                  layer_name: LayerName) -> List[Tuple[kdb.Region, str]]:
        """
        :param shapes: of the net on the conductor layer of the stack
        :return: the parts of the shapes with the names of their conductors
        """
        def part_within(rest: kdb.Region, index: int) -> Optional[Tuple[kdb.Region, kdb.Region, Optional[LayerName]]]:
            block = self.blocks[index]
            region = block.region_of(layer_name)
            if region is None:
                return None
            near = self.regions.near(region, rest.bbox())
            return rest & near, near, None if block.capacitance_pair is None else layer_name

        return self.parts_within_blocks(shapes, net_name, part_within)

    def conductor_parts_of_vias(self,
                                shapes: kdb.Region,
                                net_name: NetName,
                                bottom_layer_name: LayerName,
                                top_layer_name: LayerName) -> List[Tuple[kdb.Region, str]]:
        """
        :param shapes: of the net on the via layer of the stack
        :return: the parts of the shapes with the names of their conductors: within a block by their centers,
                 as for the resistances (see RExtractor.split_at_exclusions)
        """
        def part_within(rest: kdb.Region, index: int) -> Optional[Tuple[kdb.Region, kdb.Region, Optional[LayerName]]]:
            block = self.blocks[index]
            bottom_region, top_region = block.region_of(bottom_layer_name), block.region_of(top_layer_name)
            if bottom_region is None or top_region is None or block.capacitance_pair is not None:
                return None
            box = rest.bbox()
            mask = self.regions.near(bottom_region, box) & self.regions.near(top_region, box)
            part = polygons_by_center_inside(rest, mask)
            return part, part, None

        return self.parts_within_blocks(shapes, net_name, part_within)

    def parts_within_blocks(self,
                            shapes: kdb.Region,
                            net_name: NetName,
                            part_within: Callable[[kdb.Region, int],
                                                  Optional[Tuple[kdb.Region, kdb.Region, Optional[LayerName]]]]) \
            -> List[Tuple[kdb.Region, str]]:
        """
        :param shapes: of the net
        :param part_within: what of some shapes is within the block of the index, what to take out of the shapes
                            for what isn't, and the layer that the block needs a part to have its name
        :return: the parts of the shapes, each within other blocks, with the names of their conductors

        NOTE: the rest goes without the mask rather than the part, as any-angle edges round differently, which leaves
              slivers along the cut otherwise, that join what is on both sides of a block
        """
        parts: List[Tuple[kdb.Region, FrozenSet[int], Optional[LayerName]]] = [(shapes, frozenset(), None)]
        for index in self.block_indexes_touching(shapes.bbox()):
            split_parts: List[Tuple[kdb.Region, FrozenSet[int], Optional[LayerName]]] = []
            for region, block_indexes, part_layer_name in parts:
                within = part_within(region, index)
                if within is None or within[0].is_empty():
                    split_parts.append((region, block_indexes, part_layer_name))
                    continue
                split_parts.append((within[0], block_indexes | {index}, part_layer_name or within[2]))
                rest = region - within[1]
                if not rest.is_empty():
                    split_parts.append((rest, block_indexes, part_layer_name))
            parts = split_parts
        return [(region, self.conductor_name(ConductorPart(net_name, block_indexes, part_layer_name)))
                for region, block_indexes, part_layer_name in parts]

    def leaves_out_to_substrate(self, part: ConductorPart) -> bool:
        """
        :return: whether the capacitance of the part to the substrate is left out
        """
        if part.net_name in self.excluded_net_names:
            return True
        return any(self.blocks[index].applies_between(part.layer_name, self.substrate_layer_name)
                   for index in part.block_indexes)

    def leaves_out_between(self, part_a: ConductorPart, part_b: ConductorPart) -> bool:
        """
        :return: whether the capacitance between the parts is left out
        """
        if part_a.is_substrate or part_b.is_substrate:
            return self.leaves_out_to_substrate(part_b if part_a.is_substrate else part_a)
        return any(self.blocks[index].applies_between(part_a.layer_name, part_b.layer_name)
                   for index in part_a.block_indexes & part_b.block_indexes)

    def capacitance_matrix_of_nets(self,
                                   matrix: CapacitanceMatrix,
                                   conductor_names: List[str],
                                   substrate_net_name: NetName) -> CapacitanceMatrix:
        """
        :param matrix: the Maxwell capacitance matrix of the conductors, whose capacitances to infinity
                       go to the substrate, as in the netlist
        :param conductor_names: of the axes of the matrix, as in conductor_name
        :param substrate_net_name: the net of the capacitances to the substrate
        :return: the Maxwell capacitance matrix of the nets, by their names, without what is left out,
                 the capacitances of the parts of a net summed up: with all at the same potential,
                 the charge they induce adds up to the one of the net as one conductor
        """
        parts = [self.conductor_parts[name] for name in conductor_names]
        nets_of_parts = [self.net_of_capacitance(part.net_name, substrate_net_name) for part in parts]
        net_names = list(dict.fromkeys(nets_of_parts))
        index_of_net = {net_name: index for index, net_name in enumerate(net_names)}
        rows = [[0.0] * len(net_names) for _ in net_names]

        for i, part in enumerate(parts):
            row, net_i = matrix[i], index_of_net[nets_of_parts[i]]
            if part.is_substrate or not self.leaves_out_to_substrate(part):
                rows[net_i][net_i] += sum(row)  # NOTE: the capacitance to infinity, the rest of the row
            for j in range(i + 1, len(parts)):
                net_j = index_of_net[nets_of_parts[j]]
                if net_i != net_j and not self.leaves_out_between(part, parts[j]):
                    rows[net_i][net_j] += row[j]
                    rows[net_j][net_i] += row[j]
                    rows[net_i][net_i] -= row[j]
                    rows[net_j][net_j] -= row[j]
        return CapacitanceMatrix(conductor_names=net_names, rows=rows)

    def leaves_out_capacitance_of_net(self, net_name: NetName, other_net_name: NetName) -> bool:
        """
        :param net_name: the net of a plate
        :param other_net_name: the net of what the plate couples to
        :return: whether it's a capacitance of an excluded net to the substrate

        NOTE: by the net, as a well of another net is on the layer of the substrate, which stays like any other net
        """
        return net_name in self.excluded_net_names and other_net_name == self.substrate_layer_name

    def mask(self,
             layer_name: LayerName,
             ports: Optional[bool] = None,
             kind: Optional[BlockKind] = None) -> kdb.Region:
        """
        :param layer_name: a layer of the stack
        :param ports: only of the blocks with ports at their cuts, or without
        :param kind: only of the blocks of this kind
        :return: the shapes of the blocks on the layer, but of those that only leave out some capacitances
        """
        key = (layer_name, ports, kind)
        mask = self._masks.get(key, None)
        if mask is None:
            mask = kdb.Region()
            for block in self.blocks:
                region = block.region_of(layer_name)
                if region is not None and block.capacitance_pair is None and ports in (None, block.ports) \
                        and kind in (None, block.kind):
                    mask += region
            mask = mask.merged()
            self._masks[key] = mask
        return mask

    def mask_near(self,
                  box: kdb.Box,
                  layer_name: LayerName,
                  ports: Optional[bool] = None,
                  kind: Optional[BlockKind] = None) -> kdb.Region:
        """
        :return: the polygons of the mask (see mask) that touch the box
        """
        return self.regions.near(self.mask(layer_name, ports, kind), box)

    def block_indexes_touching(self, box: kdb.Box) -> List[int]:
        """
        :return: the indexes of the blocks whose boxes touch the box, in their order
        """
        return sorted({shape.property('block') for shape in self.block_boxes.each_touching(kdb.Shapes.SAll, box)})

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

    def is_only_label_of_cut_cell(self, text: str, position: kdb.Point) -> bool:
        """
        :return: whether a cut cell has the label, and the rest of the layout not
        """
        return (text, position) in self.labels_of_cut_cells and (text, position) not in self.labels_of_rest

    def is_only_named_by_cut_cells(self, net_name: NetName) -> bool:
        """
        :return: whether the net has labels, and all of them are labels of the cut cells only,
                 by the labels on the net, rather than by its name, which keeps no label where it isn't unique
                 (e.g. $2, the net of the label A of one of two instances of a cut cell, #417)
        """
        labels = self.labels_by_net_name.get(net_name, ())
        texts_of_cut_cells = {text for text, _ in self.labels_of_cut_cells}
        texts_of_rest = {text for text, _ in self.labels_of_rest}
        return bool(labels) and all(text in texts_of_cut_cells and text not in texts_of_rest for text in labels)

    def labels_at(self, block_index: int, layer_name: LayerName, box: kdb.Box) -> Dict[int, BlockLabel]:
        """
        :return: the labels of the cell of the block at the box, on the layer, by their indexes in its list
        """
        block = self.blocks[block_index]
        positions = self._label_positions.get((block_index, layer_name), None)
        if positions is None:
            positions = kdb.Shapes()
            for index, label in enumerate(block.labels):
                if label.layer_name == layer_name:
                    positions.insert(kdb.BoxWithProperties(kdb.Box(label.position, label.position), {'label': index}))
            self._label_positions[(block_index, layer_name)] = positions
        indexes = (shape.property('label') for shape in positions.each_touching(kdb.Shapes.SAll, box))
        return {index: block.labels[index] for index in indexes}

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
