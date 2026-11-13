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
"""Shared electrical identity and lazy native geometry for scene exporters."""
from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING, Any

from ...pex25d.electrical import (
    BodyKind, ElectricalBody, conductor_body, ground_body,
    solver_body_names, write_solver_body_map,
)

if TYPE_CHECKING:
    import klayout.db as kdb


class GroundGeometryError(ValueError):
    """Scene geometry cannot be represented without changing its coordinates."""


def _geometry_module() -> ModuleType:
    try:
        from ...klayout import pex25d_ground
    except ImportError as exc:
        raise GroundGeometryError(f"Native scene geometry requires KLayout: {exc}") from exc
    return pex25d_ground


def check_native_ground_coordinate(value: int):
    """Check the native coordinate interval used by ground and conductor geometry."""
    _geometry_module().check_native_ground_coordinate(value)


def retained_ground_region(ground: Any, field: kdb.Region) -> kdb.Region:
    """Return field minus the union of explicit ground openings, in scene grid units.

    Polygon holes retain material of the same reference net. Inputs are unchanged.
    KLayout loads only when this native geometry operation is called.
    """
    return _geometry_module().retained_ground_region(ground, field)


def region_of(conductor_region: Any) -> kdb.Region:
    """Convert a conductor's grid-unit boxes/polygons without changing coordinates.

    Unsupported native endpoints fail before constructing their shapes.
    """
    return _geometry_module().region_of(conductor_region)
