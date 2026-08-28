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
The integer geometry the validator's ``--strict`` tier is built on.

Several cases here came out of a differential fuzz against shapely rather than
out of inspection; where that is so, the test says which shape defeated which
attempt. shapely is deliberately not a dependency — the point of this package
is that it needs protobuf and nothing else — so the cases it found are frozen
here as fixed tests.
"""

from __future__ import annotations

import allure
import unittest

from klayout_pex.pex25d.validator import (
    Polygon, polygons_overlap, ring_is_collinear, ring_is_simple,
    ring_strictly_inside, rings_meet,
)

UNIT = [(0, 0), (2, 0), (2, 2), (0, 2)]
L_SHAPE = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)]


def square(x: int, y: int, size: int) -> list:
    return [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]


@allure.parent_suite("Unit Tests")
@allure.tag("PEX25D", "Geometry")
class Pex25DGeometryTest(unittest.TestCase):
    # ------------------------------------------------------------- one ring

    def test_ring_is_simple(self):
        assert ring_is_simple(UNIT)
        assert ring_is_simple(L_SHAPE)
        assert ring_is_simple([(0, 0), (4, 0), (2, 3)])

    def test_a_bowtie_is_not_simple(self):
        assert not ring_is_simple([(0, 0), (2, 2), (2, 0), (0, 2)])
        assert not ring_is_simple([(0, 0), (4, 4), (4, 0), (0, 3)])

    def test_a_fold_back_is_not_simple(self):
        # Consecutive edges may share their endpoint but not run along it.
        assert not ring_is_simple([(0, 0), (4, 0), (2, 0), (2, 3)])

    def test_ring_is_collinear(self):
        assert ring_is_collinear([(0, 0), (1, 0), (3, 0), (2, 0)])
        assert ring_is_collinear([(0, 0), (1, 1), (2, 2)])
        assert not ring_is_collinear(UNIT)

    def test_winding_does_not_matter(self):
        assert ring_is_simple(UNIT[::-1])
        assert ring_strictly_inside(square(1, 1, 2), square(0, 0, 8)[::-1])

    # --------------------------------------------------------- ring against ring

    def test_ring_strictly_inside(self):
        outer = square(0, 0, 8)
        assert ring_strictly_inside(square(2, 2, 4), outer)
        assert not ring_strictly_inside(square(9, 9, 2), outer)      # outside
        assert not ring_strictly_inside(square(0, 1, 2), outer)      # touching
        assert not ring_strictly_inside(square(-1, -1, 10), outer)   # containing

    def test_a_hole_that_leaves_a_concave_outer_and_comes_back(self):
        # Every vertex inside is not enough: this one's vertices are all in the
        # L, but the edge between two of them crosses the notch.
        assert not ring_strictly_inside([(0, 0), (3, 0), (3, 3), (0, 3)], L_SHAPE)

    def test_rings_meet(self):
        assert rings_meet(square(0, 0, 4), square(2, 2, 4))     # crossing
        assert rings_meet(square(0, 0, 4), square(4, 0, 4))     # touching
        assert rings_meet(square(0, 0, 8), square(2, 2, 2))     # nested
        assert not rings_meet(square(0, 0, 4), square(5, 5, 2))

    # ------------------------------------------------------------- overlap

    def test_overlapping_and_disjoint_boxes(self):
        assert polygons_overlap(Polygon(square(0, 0, 4)), Polygon(square(2, 2, 4)))
        assert not polygons_overlap(Polygon(square(0, 0, 4)), Polygon(square(9, 9, 4)))

    def test_touching_is_not_overlapping(self):
        assert not polygons_overlap(Polygon(square(0, 0, 4)), Polygon(square(4, 0, 4)))
        assert not polygons_overlap(Polygon(square(0, 0, 4)), Polygon(square(4, 4, 4)))

    def test_containment_counts(self):
        assert polygons_overlap(Polygon(square(0, 0, 8)), Polygon(square(2, 2, 2)))

    def test_identical_polygons_overlap(self):
        # Every vertex and every edge midpoint of each lies exactly ON the
        # other, so no sampled point is ever strictly inside. This is what the
        # vertical decomposition is for.
        assert polygons_overlap(Polygon(square(0, 0, 4)), Polygon(square(0, 0, 4)))
        assert polygons_overlap(
            Polygon(square(0, 0, 8), [square(2, 2, 4)]),
            Polygon(square(0, 0, 8), [square(2, 2, 4)]))

    def test_a_hole_is_not_part_of_the_polygon(self):
        donut = Polygon(square(0, 0, 8), [square(2, 2, 4)])
        assert not polygons_overlap(donut, Polygon(square(3, 3, 2)))
        assert polygons_overlap(donut, Polygon(square(1, 3, 4)))

    def test_a_shape_filling_a_hole_exactly(self):
        donut = Polygon(square(0, 0, 8), [square(2, 2, 4)])
        assert not polygons_overlap(donut, Polygon(square(2, 2, 4)))

    def test_coincident_boundary_with_material_beyond_it(self):
        # From the shapely fuzz. The right-hand strip of the box is outside the
        # donut's hole and inside its material, but the two outlines share the
        # whole lower edge and both upper corners, so vertex-and-midpoint
        # sampling reported no overlap here.
        donut = Polygon([(2, 0), (10, 0), (10, 8), (2, 8)],
                        [[(6, 2), (9, 2), (9, 5), (6, 5)]])
        assert polygons_overlap(donut, Polygon([(7, 2), (10, 2), (10, 5), (7, 5)]))

    def test_an_l_shape_and_its_notch(self):
        assert not polygons_overlap(Polygon(L_SHAPE), Polygon(square(1, 1, 3)))
        assert polygons_overlap(Polygon(L_SHAPE),
                                Polygon([(0, 0), (3, 0), (3, 1), (0, 1)]))

    def test_a_sliver_of_shared_area(self):
        # One grid unit of overlap is an overlap.
        assert polygons_overlap(Polygon(square(0, 0, 4)),
                                Polygon([(3, 3), (9, 3), (9, 9), (3, 9)]))

    def test_overlap_is_symmetric(self):
        pairs = (
            (Polygon(square(0, 0, 4)), Polygon(square(2, 2, 4))),
            (Polygon(square(0, 0, 4)), Polygon(square(4, 0, 4))),
            (Polygon(square(0, 0, 8), [square(2, 2, 4)]), Polygon(square(3, 3, 2))),
            (Polygon(L_SHAPE), Polygon(square(1, 1, 3))),
        )
        for first, second in pairs:
            with self.subTest(first=first.outer, second=second.outer):
                assert polygons_overlap(first, second) == polygons_overlap(second, first)
