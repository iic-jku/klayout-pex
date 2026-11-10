#! /usr/bin/env python3
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

from dataclasses import dataclass
from typing import *
import math

import klayout.db as kdb
from klayout.dbcore import EdgeWithProperties

from klayout_pex.rcx25.types import EdgeDistance


# NOTE: first lateral nearby shape blocks everything beyond (like sidewall situation) up to halo
def nearest_edge_distance(polygon: kdb.Polygon) -> float:
    if polygon.is_box():
        return max(0, polygon.bbox().bottom)
    # Neighborhood trapezoids span the same interval. Their facing boundaries
    # cannot cross without the polygons touching, so compare them at its middle.
    edge = _facing_edge(polygon)
    return max(0.0, (edge.p1.y + edge.p2.y) / 2.0)


def find_polygon_with_nearest_edge(polygons_on_same_layer: List[kdb.PolygonWithProperties]) -> Tuple[EdgeDistance, kdb.PolygonWithProperties]:
    nearest_lateral_shape = (math.inf, polygons_on_same_layer[0])

    for p in polygons_on_same_layer:
        dnear = nearest_edge_distance(p)
        if dnear < nearest_lateral_shape[0]:
            nearest_lateral_shape = (dnear, p)

    return nearest_lateral_shape


def nearest_edge(polygon: kdb.PolygonWithProperties) -> EdgeWithProperties:
    edge = _facing_edge(polygon)
    return kdb.EdgeWithProperties(edge, properties={'net': polygon.property('net')})


def _facing_edge(polygon: kdb.Polygon) -> kdb.Edge:
    return next(edge for edge in polygon.each_edge() if edge.d().x < 0)


@dataclass(frozen=True)
class Trapezoid:
    left: float
    right: float
    near_left: float
    near_right: float
    far_left: float
    far_right: float

    def polygon(self) -> kdb.Polygon:
        # Only report geometry is rounded back to the layout grid. Capacitance
        # uses the floating-point intersections below without added grid error.
        return kdb.Polygon([kdb.Point(self.left, self.near_left),
                            kdb.Point(self.left, self.far_left),
                            kdb.Point(self.right, self.far_right),
                            kdb.Point(self.right, self.near_right)])


def vertical_trapezoids(polygon: kdb.Polygon) -> Iterator[Trapezoid]:
    """Partition a polygon, including holes, without rounding new intersections."""
    edges = [edge for edge in polygon.each_edge() if edge.p1.x != edge.p2.x]
    xs = sorted({point.x for edge in edges for point in (edge.p1, edge.p2)})
    for left, right in zip(xs, xs[1:]):
        middle = (left + right) / 2.0
        boundaries = []
        for edge in edges:
            if min(edge.p1.x, edge.p2.x) < middle < max(edge.p1.x, edge.p2.x):
                slope = (edge.p2.y - edge.p1.y) / (edge.p2.x - edge.p1.x)
                first = edge.p1.y + (left - edge.p1.x) * slope
                last = edge.p1.y + (right - edge.p1.x) * slope
                boundaries.append((first, last))
        boundaries.sort(key=lambda pair: pair[0] + pair[1])
        # Even/odd fill pairs both the hull and holes at this vertical slice.
        for near, far in zip(boundaries[::2], boundaries[1::2]):
            yield Trapezoid(left, right, near[0], near[1], far[0], far[1])
