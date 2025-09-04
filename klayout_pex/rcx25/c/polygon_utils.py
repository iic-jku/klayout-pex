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

from typing import *
import math

import klayout.db as kdb
from klayout.dbcore import EdgeWithProperties

from klayout_pex.rcx25.types import EdgeDistance
from klayout_pex.log import warning


# NOTE: first lateral nearby shape blocks everything beyond (like sidewall situation) up to halo
def nearest_edge_distance(polygon: kdb.Polygon) -> float:
    bbox: kdb.Box = polygon.bbox()

    if not polygon.is_box():
        warning(f"Side overlap, outside polygon {polygon} is not a box. "
                f"Currently, only boxes are supported, will be using bounding box {bbox}")
    ## distance_near = (bbox.p1.y + bbox.p2.y) / 2.0
    distance_near = min(bbox.p1.y, bbox.p2.y)
    if distance_near < 0:
        distance_near = 0
    return distance_near


def find_polygon_with_nearest_edge(polygons_on_same_layer: List[kdb.PolygonWithProperties]) -> Tuple[EdgeDistance, kdb.PolygonWithProperties]:
    nearest_lateral_shape = (math.inf, polygons_on_same_layer[0])

    for p in polygons_on_same_layer:
        dnear = nearest_edge_distance(p)
        if dnear < nearest_lateral_shape[0]:
            nearest_lateral_shape = (dnear, p)

    return nearest_lateral_shape


def nearest_edge(polygon: kdb.PolygonWithProperties) -> EdgeWithProperties:
    edge = [e for e in polygon.each_edge() if e.d().x < 0][-1]
    return kdb.EdgeWithProperties(edge, properties={'net': polygon.property('net')})
