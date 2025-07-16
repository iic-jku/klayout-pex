#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/martinjankoehler/klayout-pex).
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

import allure
import unittest

import klayout.db as kdb
import klayout_pex_protobuf.kpex.geometry.shapes_pb2 as shapes_pb2
from klayout_pex.klayout.shapes_pb2_converter import ShapesConverter

from klayout_pex.log import (
    LogLevel,
    set_log_level,
)


@allure.parent_suite("Unit Tests")
@allure.tag("Geometry", "Shapes", "KLayout")
class ShapesConverterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        set_log_level(LogLevel.DEBUG)

    def setUp(self):
        self.dbu = 0.001

    def test_klayout_region(self):
        conv = ShapesConverter(self.dbu)

        r_pb = shapes_pb2.Region()
        pg_pb = r_pb.polygons.add()
        p0 = pg_pb.hull_points.add()
        p0.x = 10
        p0.y = 20
        p1 = pg_pb.hull_points.add()
        p1.x = 10
        p1.y = 30
        p2 = pg_pb.hull_points.add()
        p2.x = 750
        p2.y = 30
        p3 = pg_pb.hull_points.add()
        p3.x = 750
        p3.y = 20

        r_kly = conv.klayout_region(r_pb)
        self.assertEqual(1, r_kly.count())
        pg_kly = list(r_kly.each())[0]
        pt_kly = list(pg_kly.each_point_hull())
        self.assertEqual(p0.x, pt_kly[0].x)
        self.assertEqual(p0.y, pt_kly[0].y)
        self.assertEqual(p1.x, pt_kly[1].x)
        self.assertEqual(p1.y, pt_kly[1].y)
        self.assertEqual(p2.x, pt_kly[2].x)
        self.assertEqual(p2.y, pt_kly[2].y)
        self.assertEqual(p3.x, pt_kly[3].x)
        self.assertEqual(p3.y, pt_kly[3].y)
