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
"""Build explicit ground openings without changing vertical or net ownership."""
from __future__ import annotations
from typing import Any
import klayout.db as kdb


from .native_coordinates import (
    NATIVE_COORDINATE_MIN,
    NATIVE_COORDINATE_MAX,
    is_supported_native_coordinate,
)


from ..plugin_api.v1.pex25d_scene_tools import GroundGeometryError


def check_native_ground_coordinates(ground: Any):
    for cutout in ground.cutouts:
        polygon = cutout.polygon
        for ring in (polygon.outer, *polygon.holes):
            for point in ring.points:
                check_native_ground_coordinate(point.x)
                check_native_ground_coordinate(point.y)


def retained_ground_region(ground: Any, field: kdb.Region) -> kdb.Region:
    check_native_ground_coordinates(ground)
    if field.is_empty():
        return field.dup()
    bounds = field.bbox()
    for coordinate in (bounds.left, bounds.bottom, bounds.right, bounds.top):
        check_native_ground_coordinate(coordinate)
    cutouts = kdb.Region()
    for cutout in ground.cutouts:
        polygon = cutout.polygon
        shape = kdb.Polygon([kdb.Point(p.x, p.y) for p in polygon.outer.points])
        for hole in polygon.holes:
            shape.insert_hole([kdb.Point(p.x, p.y) for p in hole.points])
        cutouts.insert(shape)
    return field - cutouts.merged()


def region_of(conductor_region: Any) -> kdb.Region:
    """Build a region from one conductor's shapes on one layer, in grid units."""
    region = kdb.Region()
    for box in conductor_region.boxes:
        for point in (box.lower_left, box.upper_right):
            check_native_ground_coordinate(point.x)
            check_native_ground_coordinate(point.y)
        region.insert(kdb.Box(box.lower_left.x, box.lower_left.y,
                              box.upper_right.x, box.upper_right.y))
    for polygon in conductor_region.polygons:
        for ring in (polygon.outer, *polygon.holes):
            for point in ring.points:
                check_native_ground_coordinate(point.x)
                check_native_ground_coordinate(point.y)
        shape = kdb.Polygon([kdb.Point(p.x, p.y) for p in polygon.outer.points])
        for hole in polygon.holes:
            shape.insert_hole([kdb.Point(p.x, p.y) for p in hole.points])
        region.insert(shape)
    return region


def region_touches_ground(ground: Any, conductor_region: Any) -> bool:
    # A one-grid envelope retains both sides of a possible shared boundary.
    # Cropping at the conductor's own bbox would erase exact edge contacts.
    for box in conductor_region.boxes:
        for point in (box.lower_left, box.upper_right):
            _check_envelope_coordinate(point.x)
            _check_envelope_coordinate(point.y)
    for polygon in conductor_region.polygons:
        for ring in (polygon.outer, *polygon.holes):
            for point in ring.points:
                _check_envelope_coordinate(point.x)
                _check_envelope_coordinate(point.y)
    region = region_of(conductor_region)
    field = kdb.Region(region.bbox().enlarged(1))
    retained = retained_ground_region(ground, field)
    return not region.interacting(retained).is_empty()


def check_native_ground_coordinate(value: int):
    if not NATIVE_COORDINATE_MIN <= value <= NATIVE_COORDINATE_MAX:
        raise GroundGeometryError("Ground geometry exceeds the native signed 32-bit grid")
    # Both endpoints fail native interaction, and MAX can hang subtraction:
    # https://github.com/KLayout/klayout/issues/2552
    if not is_supported_native_coordinate(value):
        raise GroundGeometryError(
            f"Ground geometry reaches unsupported native coordinate endpoint {value}")


def _check_envelope_coordinate(value: int):
    if not (is_supported_native_coordinate(value - 1)
            and is_supported_native_coordinate(value + 1)):
        raise GroundGeometryError(
            "Ground contact geometry needs a one-grid envelope within supported native coordinates")
