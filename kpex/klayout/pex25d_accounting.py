#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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

"""Resolve capacitance masks using the shared native geometry backend.

Only this geometric operation needs KLayout. Reading, writing and validating
policy structure, and consuming an already partitioned scene, do not.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, Tuple
from types import SimpleNamespace
from math import gcd, lcm

import klayout.db as kdb

from .pex25d_ground import region_of


class AccountingGridError(ValueError):
    """Exact mask intersections need a finer rational grid, without moving geometry."""

    def __init__(self, refinement_factor: int):
        self.refinement_factor = refinement_factor
        super().__init__(f'Capacitance accounting intersection is off the declared grid; '
                         f'use a finer GRID (divide current grid by {refinement_factor})')


Edge = Tuple[int, int, int, int]


def _edges(region: kdb.Region) -> List[Edge]:
    return [(edge.p1.x, edge.p1.y, edge.p2.x, edge.p2.y)
            for polygon in region.each() for edge in polygon.each_edge()]


def _angled(edge: Edge) -> bool:
    return edge[0] != edge[2] and edge[1] != edge[3]


def _crossing_refinement(first: Edge, second: Edge) -> int:
    ax, ay, bx, by = first
    cx, cy, dx, dy = second
    if max(ax, bx) < min(cx, dx) or max(cx, dx) < min(ax, bx) or \
            max(ay, by) < min(cy, dy) or max(cy, dy) < min(ay, by):
        return 1
    ux, uy, vx, vy = bx - ax, by - ay, dx - cx, dy - cy
    denominator = ux * vy - uy * vx
    if not denominator:
        return 1  # parallel/collinear edges introduce no nonintegral vertex
    numerator = (cx - ax) * vy - (cy - ay) * vx
    other = (cx - ax) * uy - (cy - ay) * ux
    if denominator < 0:
        denominator, numerator, other = -denominator, -numerator, -other
    if not (0 <= numerator <= denominator and 0 <= other <= denominator):
        return 1
    x_numerator = ax * denominator + numerator * ux
    y_numerator = ay * denominator + numerator * uy
    return lcm(denominator // gcd(x_numerator, denominator),
               denominator // gcd(y_numerator, denominator))


def _check_grid_crossings(first: kdb.Region, second: Optional[kdb.Region] = None):
    """Reject fractional intersections before integer Booleans can round them.

    Manhattan pairs are always integral. Only angled edges need pair checks;
    ordinary rectangular masks and layout geometry therefore take a linear path.
    """
    refinement = 1
    first_edges = _edges(first)
    first_angled = [edge for edge in first_edges if _angled(edge)]
    if second is None:
        if not first_angled:
            return
        for index, edge in enumerate(first_angled):
            for other in first_angled[index + 1:]:
                refinement = lcm(refinement, _crossing_refinement(edge, other))
        first_axis = [edge for edge in first_edges if not _angled(edge)]
        for edge in first_angled:
            for other in first_axis:
                refinement = lcm(refinement, _crossing_refinement(edge, other))
        if refinement != 1:
            raise AccountingGridError(refinement)
        return
    second_edges = _edges(second)
    for edge in first_angled:
        for other in second_edges:
            refinement = lcm(refinement, _crossing_refinement(edge, other))
    second_angled = [edge for edge in second_edges if _angled(edge)]
    if second_angled:
        for edge in first_edges:
            if not _angled(edge):
                for other in second_angled:
                    refinement = lcm(refinement, _crossing_refinement(edge, other))
    if refinement != 1:
        raise AccountingGridError(refinement)


def _merge_exact(region: kdb.Region) -> kdb.Region:
    _check_grid_crossings(region)
    return region.merged()


def fill_region(target: Any, region: kdb.Region):
    """Serialize a region once, preserving polygon holes and the scene grid."""
    for polygon in region.each_merged():
        if polygon.is_box():
            box = polygon.bbox()
            item = target.boxes.add()
            item.lower_left.x, item.lower_left.y = box.left, box.bottom
            item.upper_right.x, item.upper_right.y = box.right, box.top
        else:
            item = target.polygons.add()
            for point in polygon.each_point_hull():
                item.outer.points.add(x=point.x, y=point.y)
            for hole in range(polygon.holes()):
                ring = item.holes.add()
                for point in polygon.each_point_hole(hole):
                    ring.points.add(x=point.x, y=point.y)


def masks_of(scene: Any) -> Dict[str, Dict[str, kdb.Region]]:
    return {region.name: {mask.layer: _merge_exact(region_of(SimpleNamespace(boxes=(), polygons=mask.polygons)))
                          for mask in region.masks}
            for region in scene.capacitance_accounting.regions}


def partition_accounting(scene: Any):
    """Partition geometry without changing NET, floating identity or coordinates.

    Whole via cuts must stay whole. Layout generation classifies their source-grid
    centers before serializing exact via masks; authored masks must cover each
    via completely or miss it completely. A failure leaves the input unchanged.
    """
    masks = masks_of(scene)
    if not masks:
        return
    vias = {layer.name for layer in scene.layers if layer.kind == layer.RESOLVED_LAYER_KIND_VIA}
    pending: List[Tuple[Any, List[Any]]] = []
    for conductor in scene.conductors:
        by_layer: Dict[str, List[Any]] = {}
        for source in conductor.regions:
            by_layer.setdefault(source.layer, []).append(source)
        resolved = []
        for layer, sources in by_layer.items():
            raw = region_of(SimpleNamespace(boxes=[box for source in sources for box in source.boxes],
                                            polygons=[p for source in sources for p in source.polygons]))
            whole = _merge_exact(raw)
            parts: List[Tuple[kdb.Region, FrozenSet[str]]] = [(whole, frozenset())]
            for name, by_mask_layer in masks.items():
                mask = by_mask_layer.get(layer)
                if mask is None:
                    continue
                if layer in vias:
                    for polygon in raw.each():
                        cut = kdb.Region(polygon)
                        _check_grid_crossings(cut, mask)
                        if not (cut & mask).is_empty() and not (cut - mask).is_empty():
                            raise ValueError(f"Accounting region '{name}' clips a via cut on '{layer}'")
                next_parts = []
                for region, memberships in parts:
                    _check_grid_crossings(region, mask)
                    inside, outside = region & mask, region - mask
                    if not inside.is_empty():
                        next_parts.append((inside, memberships | {name}))
                    if not outside.is_empty():
                        next_parts.append((outside, memberships))
                parts = next_parts
            occupied = kdb.Region()
            for index, (geometry, memberships) in enumerate(parts):
                if geometry.is_empty():
                    continue
                if not (occupied & geometry).is_empty():
                    raise ValueError(f"Accounting partition overlaps on conductor '{conductor.name}', layer '{layer}'")
                occupied += geometry
                target = type(sources[0])(layer=layer,
                                          accounting_part_id=f'{len(conductor.name)}:{conductor.name}:{layer}:{index}')
                target.accounting_regions.extend(sorted(memberships))
                fill_region(target, geometry)
                resolved.append(target)
            if not (occupied ^ whole).is_empty():
                raise ValueError(f"Accounting partition changes conductor '{conductor.name}' on '{layer}'")
        pending.append((conductor, resolved))
    for conductor, regions in pending:
        conductor.ClearField('regions')
        conductor.regions.extend(regions)


def validate_accounting_geometry(scene: Any):
    """Check serialized membership and disjointness before native export."""
    masks = masks_of(scene)
    for conductor in scene.conductors:
        occupied: Dict[str, kdb.Region] = {}
        for part in conductor.regions:
            geometry = _merge_exact(region_of(part))
            previous = occupied.setdefault(part.layer, kdb.Region())
            _check_grid_crossings(previous, geometry)
            if not (previous & geometry).is_empty():
                raise ValueError(f"Accounting parts overlap on conductor '{conductor.name}', layer '{part.layer}'")
            occupied[part.layer] += geometry
            for name, by_layer in masks.items():
                mask = by_layer.get(part.layer)
                if mask is None:
                    continue
                _check_grid_crossings(geometry, mask)
                wrong = geometry - mask if name in part.accounting_regions else geometry & mask
                if not wrong.is_empty():
                    raise ValueError(f"Accounting part '{part.accounting_part_id}' disagrees with region '{name}'")
