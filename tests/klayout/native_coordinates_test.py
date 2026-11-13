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

"""Supported boundary values preserve native merge and contact results."""
from __future__ import annotations

import klayout.db as kdb
import pytest

from klayout_pex.klayout.native_coordinates import is_supported_native_coordinate


@pytest.mark.parametrize('value,accepted', [
    (-2147483649, False), (-2147483648, False), (-2147483647, True),
    (0, True), (2147483646, True), (2147483647, False), (2147483648, False),
])
def test_supported_coordinate_interval(value: int, accepted: bool):
    # Exact endpoints can lose real interactions even when ordinary intersection
    # succeeds. Keep these rejected cases pure Python so CI never hangs natively.
    assert is_supported_native_coordinate(value) is accepted


@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('edge', [-2147483647, 2147483646])
def test_adjacent_interior_bounds_preserve_native_union_and_contact(axis: str, edge: int):
    low, high = (edge, edge+20) if edge < 0 else (edge-20, edge)
    first = kdb.Box(low, 0, high, 10) if axis == 'x' else kdb.Box(0, low, 10, high)
    second = kdb.Box(low+5, 5, high, 15) if axis == 'x' else kdb.Box(5, low+5, 15, high)
    a, b = kdb.Region(first), kdb.Region(second)
    assert (a & b).area() == 75
    assert a.interacting(b).area() == 200
    assert b.interacting(a).area() == 150
    assert (a+b).merged().area() == 275
