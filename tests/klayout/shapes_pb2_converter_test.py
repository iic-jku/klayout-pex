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

    def test_klayout_point(self):
        conv = ShapesConverter(self.dbu)

        p_pb = shapes_pb2.Point()
        p_pb.x = 10
        p_pb.y = 20

        p_kly = conv.klayout_point(p_pb)
        self.assertEqual(p_pb.x, p_kly.x)
        self.assertEqual(p_pb.y, p_kly.y)

    def test_klayout_point_to_pb(self):
        conv = ShapesConverter(self.dbu)

        p_kly = kdb.Point(10, 20)
        p_pb = shapes_pb2.Point()
        conv.klayout_point_to_pb(p_kly, p_pb)
        self.assertEqual(p_kly.x, p_pb.x)
        self.assertEqual(p_kly.y, p_pb.y)

    def test_klayout_box(self):
        conv = ShapesConverter(self.dbu)

        sh_pb = shapes_pb2.Shape()
        sh_pb.kind = shapes_pb2.Shape.Kind.SHAPE_KIND_BOX
        sh_pb.box.lower_left.x = 10
        sh_pb.box.lower_left.y = 20
        sh_pb.box.upper_right.x = 750
        sh_pb.box.upper_right.y = 300

        b_kly = conv.klayout_box(sh_pb.box)
        self.assertEqual(sh_pb.box.lower_left.x, b_kly.left)
        self.assertEqual(sh_pb.box.lower_left.y, b_kly.bottom)
        self.assertEqual(sh_pb.box.upper_right.x, b_kly.right)
        self.assertEqual(sh_pb.box.upper_right.y, b_kly.top)

    def test_klayout_box_to_pb(self):
        conv = ShapesConverter(self.dbu)

        b_kly = kdb.Box(10, 20, 750, 300)
        sh_pb = shapes_pb2.Shape()
        conv.klayout_box_to_pb(b_kly, sh_pb)
        self.assertEqual(shapes_pb2.Shape.Kind.SHAPE_KIND_BOX, sh_pb.kind)
        self.assertEqual(b_kly.left, sh_pb.box.lower_left.x)
        self.assertEqual(b_kly.bottom, sh_pb.box.lower_left.y)
        self.assertEqual(b_kly.right, sh_pb.box.upper_right.x)
        self.assertEqual(b_kly.top, sh_pb.box.upper_right.y)

    def test_klayout_box_to_pb__with_properties(self):
        conv = ShapesConverter(self.dbu)

        b_kly = kdb.BoxWithProperties(kdb.Box(10, 20, 750, 300), {'net': 'VDD'})
        sh_pb = shapes_pb2.Shape()
        conv.klayout_box_to_pb(b_kly, sh_pb)
        self.assertEqual(b_kly.property('net'), sh_pb.box.net)

    def test_klayout_polygon(self):
        conv = ShapesConverter(self.dbu)

        sh_pb = shapes_pb2.Shape()
        sh_pb.kind = shapes_pb2.Shape.Kind.SHAPE_KIND_POLYGON
        p0 = sh_pb.polygon.hull_points.add()
        p0.x = 10
        p0.y = 20
        p1 = sh_pb.polygon.hull_points.add()
        p1.x = 10
        p1.y = 30
        p2 = sh_pb.polygon.hull_points.add()
        p2.x = 750
        p2.y = 30
        p3 = sh_pb.polygon.hull_points.add()
        p3.x = 750
        p3.y = 20

        pg_kly = conv.klayout_polygon(sh_pb.polygon)
        pt_kly = list(pg_kly.each_point_hull())

        self.assertEqual(p0.x, pt_kly[0].x)
        self.assertEqual(p0.y, pt_kly[0].y)
        self.assertEqual(p1.x, pt_kly[1].x)
        self.assertEqual(p1.y, pt_kly[1].y)
        self.assertEqual(p2.x, pt_kly[2].x)
        self.assertEqual(p2.y, pt_kly[2].y)
        self.assertEqual(p3.x, pt_kly[3].x)
        self.assertEqual(p3.y, pt_kly[3].y)

    def test_klayout_polygon_to_pb(self):
        conv = ShapesConverter(self.dbu)

        pt_kly = [
            kdb.Point(10, 20),
            kdb.Point(10, 30),
            kdb.Point(750, 30),
            kdb.Point(750, 20),
        ]

        pg_kly = kdb.PolygonWithProperties(
            kdb.Polygon(pt_kly),
            {'net': 'VSS'}
        )

        sh_pb = shapes_pb2.Shape()
        conv.klayout_polygon_to_pb(pg_kly, sh_pb)
        pt_pb = sh_pb.polygon.hull_points
        self.assertEqual(shapes_pb2.Shape.Kind.SHAPE_KIND_POLYGON, sh_pb.kind)
        self.assertEqual('VSS', sh_pb.polygon.net)
        self.assertEqual(pt_kly[0].x, pt_pb[0].x)
        self.assertEqual(pt_kly[0].y, pt_pb[0].y)
        self.assertEqual(pt_kly[1].x, pt_pb[1].x)
        self.assertEqual(pt_kly[1].y, pt_pb[1].y)

    def test_klayout_region(self):
        conv = ShapesConverter(self.dbu)

        r_pb = shapes_pb2.Region()
        sh_pb = r_pb.shapes.add()
        sh_pb.kind = shapes_pb2.Shape.Kind.SHAPE_KIND_POLYGON
        p0 = sh_pb.polygon.hull_points.add()
        p0.x = 10
        p0.y = 20
        p1 = sh_pb.polygon.hull_points.add()
        p1.x = 10
        p1.y = 30
        p2 = sh_pb.polygon.hull_points.add()
        p2.x = 750
        p2.y = 30
        p3 = sh_pb.polygon.hull_points.add()
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
