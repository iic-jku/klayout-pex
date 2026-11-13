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

"""Apply physical line-width bias on the export grid without changing LVS connectivity."""

from fractions import Fraction
import math
from typing import Any, Dict, List, Tuple

import klayout.db as kdb

from klayout_pex.pex25d.protobuf import pex25d_file_pb2


MAX_KLAYOUT_COORDINATE = (1 << 31) - 1
MIN_KLAYOUT_COORDINATE = -(1 << 31)


class PhysicalGeometryError(ValueError):
    """A physical recipe cannot preserve the extracted topology on the chosen grid."""


def width_bias_offsets(tech_info: Any, grid: Fraction) -> Dict[str, int]:
    """Validate signed full-width changes and return exact per-boundary grid offsets."""
    offsets = {}
    for layer in tech_info.process_metal_layers:
        bias = layer.metal_layer.line_width_bias
        if not math.isfinite(bias):
            raise PhysicalGeometryError(f"Physical line-width bias of '{layer.name}' must be finite")
        if not bias:
            continue
        offset = Fraction(str(bias)) / (2*grid)
        if offset.denominator != 1:
            raise PhysicalGeometryError(
                f"Physical line-width bias of '{layer.name}' needs an edge displacement of {bias/2:g} um, "
                f"not representable on the {float(grid):g} um grid. Choose a finer physical grid")
        if abs(offset) > MAX_KLAYOUT_COORDINATE:
            raise PhysicalGeometryError(f"Physical line-width bias of '{layer.name}' exceeds the coordinate range")
        offsets[layer.name] = int(offset)
    return offsets


def shape_region(shape: Any) -> kdb.Region:
    def check(points: Any):
        if any(not MIN_KLAYOUT_COORDINATE <= value <= MAX_KLAYOUT_COORDINATE
               for point in points for value in (point.x, point.y)):
            raise PhysicalGeometryError('Physical geometry exceeds the native KLayout coordinate range')
    kinds = pex25d_file_pb2().ShapeRecord
    match shape.kind:
        case kinds.SHAPE_KIND_BOX:
            box = shape.box
            check((box.lower_left, box.upper_right))
            return kdb.Region(kdb.Box(box.lower_left.x, box.lower_left.y, box.upper_right.x, box.upper_right.y))
        case kinds.SHAPE_KIND_POLYGON:
            check(shape.polygon.outer.points)
            for hole in shape.polygon.holes:
                check(hole.points)
            polygon = kdb.Polygon([kdb.Point(p.x, p.y) for p in shape.polygon.outer.points])
            for hole in shape.polygon.holes:
                polygon.insert_hole([kdb.Point(p.x, p.y) for p in hole.points])
            return kdb.Region(polygon)
        case _:
            raise NotImplementedError(f'Physical bias for shape kind {shape.kind} is not implemented')


def _touches_terminal(region: kdb.Region, terminal: Any) -> bool:
    box = terminal.region
    left, bottom = box.lower_left.x, box.lower_left.y
    right, top = box.upper_right.x, box.upper_right.y
    if min(left, bottom) < MIN_KLAYOUT_COORDINATE or max(right, top) > MAX_KLAYOUT_COORDINATE:
        raise PhysicalGeometryError(f"Terminal '{terminal.name}' exceeds the native KLayout coordinate range")
    if left == right and bottom == top:
        return any(polygon.inside(kdb.Point(left, bottom)) for polygon in region.each_merged())
    if left == right or bottom == top:
        return not region.interacting(kdb.Edges([kdb.Edge(left, bottom, right, top)])).is_empty()
    return not (region & kdb.Region(kdb.Box(left, bottom, right, top))).is_empty()


def apply_width_bias(file: Any, offsets: Dict[str, int]):
    """Preserve contacts, terminals and net separation before mutating any geometry.

    Each original connected polygon and each original connection across co-height
    profiles must survive. Ambiguous aliases that need union-before-erosion are
    rejected conservatively; this operation does not manufacture an internal seam.
    Non-Manhattan vertices snap to the export grid after normal edge displacement.
    """
    if not offsets:
        return
    original: Dict[Tuple[str, str], kdb.Region] = {}
    for shape in file.shapes:
        key = shape.conductor, shape.layer
        original.setdefault(key, kdb.Region())
        original[key] += shape_region(shape)
    regions = dict(original)
    parts: Dict[Tuple[str, str], List[Tuple[kdb.Region, kdb.Region]]] = {
        key: [(kdb.Region(p), kdb.Region(p)) for p in region.each_merged()] for key, region in original.items()}
    changed = set()
    for key, region in original.items():
        offset = offsets.get(key[1], 0)
        if not offset:
            continue
        biased = kdb.Region()
        adjusted_parts = []
        for source, _ in parts[key]:
            polygon, = list(source.each())
            box = polygon.bbox()
            # KLayout's native Coord is signed32 even though the scene uses
            # int64. Mode2 clips acute corners at 90 degrees; twice the normal
            # offset bounds its corner excursions. Rectangles need one offset.
            padding = abs(offset)*(1 if polygon.is_box() else 2)
            if min(box.left, box.bottom)-padding < MIN_KLAYOUT_COORDINATE or \
                    max(box.right, box.top)+padding > MAX_KLAYOUT_COORDINATE:
                raise PhysicalGeometryError('Physical width bias exceeds the native KLayout coordinate range')
            # Mode 2 offsets edges normally and clips sharp corners at 90 degrees.
            # Each originally connected polygon must remain connected and nonempty.
            part = kdb.Region(polygon).sized(offset, 2).merged()
            if part.count() != 1:
                raise PhysicalGeometryError(
                    f"Physical width bias collapses or disconnects conductor '{key[0]}' on '{key[1]}'")
            biased += part
            adjusted_parts.append((source, part))
        parts[key] = adjusted_parts
        regions[key] = biased.merged()
        changed.add(key)

    # Physical conductor profiles can share a height range (e.g. split MIM masks).
    # Check actual volume contact, including touching boundaries, across those aliases.
    bounds = {metal.name: (metal.zlow, metal.zhigh) for metal in file.metals}
    metal_names = set(bounds)
    for via in file.vias:
        bounds[via.name] = bounds[via.connects_below][1], bounds[via.connects_above][0]
    net = {conductor.name: conductor.net for conductor in file.conductors}
    keys = list(regions)
    for index, first in enumerate(keys):
        for second in keys[index+1:]:
            if first not in changed and second not in changed:
                continue
            first_z, second_z = bounds[first[1]], bounds[second[1]]
            if max(first_z[0], second_z[0]) > min(first_z[1], second_z[1]):
                continue
            if first[0] == second[0] or (net[first[0]] == net[second[0]] and net[first[0]] != 'FLOATING'):
                if first[1] in metal_names and second[1] in metal_names and any(
                        not old_first.interacting(old_second).is_empty() and
                        new_first.interacting(new_second).is_empty()
                        for old_first, new_first in parts[first] for old_second, new_second in parts[second]):
                    raise PhysicalGeometryError(
                        f"Physical width bias disconnects touching profiles '{first[1]}' and '{second[1]}' "
                        f"on conductor '{first[0]}'")
                continue
            if not regions[first].interacting(regions[second]).is_empty():
                raise PhysicalGeometryError(
                    f"Physical width bias joins different conductors '{first[0]}' on '{first[1]}' "
                    f"and '{second[0]}' on '{second[1]}'")

    for via in file.vias:
        for (conductor, layer), cuts in original.items():
            if layer != via.name:
                continue
            for endpoint in (via.connects_below, via.connects_above):
                key = conductor, endpoint
                if key not in changed:
                    continue
                for cut in cuts.each_merged():
                    cut_region = kdb.Region(cut)
                    if any(not (old & cut_region).is_empty() and (new & cut_region).is_empty()
                           for old, new in parts[key]):
                        raise PhysicalGeometryError(
                            f"Physical width bias disconnects contact '{via.name}' from '{endpoint}' "
                            f"on conductor '{conductor}'")
    for terminal in file.terminals:
        key = terminal.conductor, terminal.layer
        if key in changed and not _touches_terminal(regions[key], terminal):
            raise PhysicalGeometryError(f"Physical width bias disconnects terminal '{terminal.name}'")

    # Keep unchanged records and their source references byte-identical. New boundary
    # geometry has no single drawn-shape source when merged polygons were involved.
    retained = [shape for shape in file.shapes if (shape.conductor, shape.layer) not in changed]
    del file.shapes[:]
    file.shapes.extend(retained)
    kinds = pex25d_file_pb2().ShapeRecord
    for conductor, layer in sorted(changed):
        for polygon in regions[conductor, layer].each_merged():
            shape = file.shapes.add(conductor=conductor, layer=layer)
            if polygon.is_box():
                shape.kind = kinds.SHAPE_KIND_BOX
                box = polygon.bbox()
                shape.box.lower_left.x, shape.box.lower_left.y = box.left, box.bottom
                shape.box.upper_right.x, shape.box.upper_right.y = box.right, box.top
            else:
                shape.kind = kinds.SHAPE_KIND_POLYGON
                for point in polygon.each_point_hull():
                    shape.polygon.outer.points.add(x=point.x, y=point.y)
                for index in range(polygon.holes()):
                    hole = shape.polygon.holes.add()
                    for point in polygon.each_point_hole(index):
                        hole.points.add(x=point.x, y=point.y)
    file.metadata.add(key='physical_line_width_bias',
                      value=','.join(f'{layer}:{offset}' for layer, offset in sorted(offsets.items()))+' grid units per edge')
