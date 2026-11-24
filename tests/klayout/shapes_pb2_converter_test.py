#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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

import allure
import unittest
from pathlib import Path
from typing import Callable, Optional

import pytest
import klayout.pex as klp

import klayout.db as kdb
import klayout_pex_protobuf.kpex.geometry.shapes_pb2 as shapes_pb2
from klayout_pex.klayout.shapes_pb2_converter import ShapesConverter
from klayout_pex.netlist.rc_network import RCNetwork
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.xyce import xyce_port_admittance, requires_xyce
from tests.common.vacask import vacask_port_admittance, requires_vacask
from tests.common.rc_networks import build_network, port_admittance, spice_subcircuit

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


@pytest.mark.parametrize('holes', [0, 1, 2])
@pytest.mark.parametrize('net', [None, 'VSS'])
@pytest.mark.parametrize('wall', [1, 10])
def test_polygon_round_trip_preserves_holes_and_net(holes: int, net: Optional[str], wall: int):
    # A one-dbu wall and negative coordinates catch rounding or filled bridges.
    # Multiple holes need independent cutlines; a solid polygon must stay solid.
    polygon = kdb.Polygon(kdb.Box(-100, -100, 100, 100))
    if holes:
        polygon.insert_hole(kdb.Box(-100 + wall, -100 + wall, -wall, 100 - wall))
    if holes == 2:
        polygon.insert_hole(kdb.Box(wall, -100 + wall, 100 - wall, 100 - wall))
    original = polygon.dup()
    if net is not None:
        polygon = kdb.PolygonWithProperties(polygon, {'net': net})
    converter = ShapesConverter(0.001)
    shape = shapes_pb2.Shape()
    converter.klayout_polygon_to_pb(polygon, shape)
    restored = converter.klayout_polygon(shapes_pb2.Shape.FromString(shape.SerializeToString()).polygon)
    assert (kdb.Region(restored) ^ kdb.Region(original)).is_empty()
    assert restored.area() == original.area()
    assert polygon == original  # serialization does not resolve the input's holes in place
    assert shape.polygon.net == (net or '')
    if net is not None:
        assert restored.property('net') == net


def test_empty_polygon_and_region_round_trip():
    converter = ShapesConverter(0.001)
    shape = shapes_pb2.Shape()
    converter.klayout_polygon_to_pb(kdb.Polygon(), shape)
    assert converter.klayout_polygon(shape.polygon).is_empty()
    region = shapes_pb2.Region()
    converter.klayout_region_to_pb(kdb.Region(), region)
    assert converter.klayout_region(region).is_empty()


def test_nonrectangular_holes_and_region_net_properties():
    # Concave hulls and sloped hole edges must survive cutline insertion too.
    polygon = kdb.Polygon([kdb.Point(-100, -100), kdb.Point(-100, 100),
                           kdb.Point(100, 100), kdb.Point(100, 40),
                           kdb.Point(20, 40), kdb.Point(20, -100)])
    polygon.insert_hole([kdb.Point(-80, -80), kdb.Point(-80, 40), kdb.Point(0, -10)])
    polygon.insert_hole(kdb.Box(30, 60, 80, 90))
    original = kdb.Region()
    original.insert(kdb.PolygonWithProperties(polygon, {'net': 'ring'}))
    original.insert(kdb.PolygonWithProperties(kdb.Polygon(kdb.Box(200, 200, 300, 300)), {'net': 'island'}))
    converter = ShapesConverter(0.001)
    stored = shapes_pb2.Region()
    converter.klayout_region_to_pb(original, stored)
    restored = converter.klayout_region(stored)
    assert (restored ^ original).is_empty()
    assert {shape.property('net') for shape in restored} == {'ring', 'island'}


def ring_resistance_network(algorithm: klp.Algorithm, serialized: bool) -> RCNetwork:
    """Extract the same ring before/after the production protobuf boundary."""
    polygon = kdb.Polygon(kdb.Box(0, 0, 10000, 6000))
    polygon.insert_hole(kdb.Box(1000, 1000, 9000, 5000))
    region = kdb.Region(polygon)
    if serialized:
        converter = ShapesConverter(0.001)
        stored = shapes_pb2.Region()
        converter.klayout_region_to_pb(region, stored)
        region = converter.klayout_region(shapes_pb2.Region.FromString(stored.SerializeToString()))
    tech = klp.RExtractorTech()
    tech.skip_simplify = True
    conductor = klp.RExtractorTechConductor()
    conductor.layer = 0
    conductor.algorithm = algorithm
    conductor.resistance = 1.0
    tech.add_conductor(conductor)
    ports = {0: [kdb.Polygon(kdb.Box(0, 0, 1000, 6000)),
                 kdb.Polygon(kdb.Box(9000, 0, 10000, 6000))]}
    extracted = klp.RNetExtractor(0.001).extract(tech, {0: region}, {}, ports)
    names = {node.object_id(): f'P{node.port_index()}' if node.port_index() >= 0 else f'N{index}'
             for index, node in enumerate(extracted.each_node())}
    return build_network([(names[element.a().object_id()], names[element.b().object_id()],
                           1 / element.resistance(), 0.0)
                          for element in extracted.each_element()])


@pytest.mark.parametrize('algorithm', [klp.Algorithm.SquareCounting, klp.Algorithm.Tesselation])
def test_region_round_trip_preserves_extracted_resistance(algorithm: klp.Algorithm):
    # The direct KLayout extraction is independent of the converter. Filling the
    # hole changed the square-counting resistance from 4.693147 ohm to 1.5 ohm.
    original = ring_resistance_network(algorithm, serialized=False)
    restored = ring_resistance_network(algorithm, serialized=True)
    assert port_admittance(restored, ['P0', 'P1'], 0.0) == pytest.approx(
        port_admittance(original, ['P0', 'P1'], 0.0), rel=1e-12, abs=0.0)


@pytest.mark.parametrize('simulator', [
    pytest.param(ngspice_port_admittance, marks=requires_ngspice, id='ngspice'),
    pytest.param(xyce_port_admittance, marks=requires_xyce, id='Xyce'),
    pytest.param(vacask_port_admittance, marks=requires_vacask, id='VACASK'),
])
@pytest.mark.parametrize('algorithm', [klp.Algorithm.SquareCounting, klp.Algorithm.Tesselation])
def test_serialized_ring_simulates_like_original_geometry(
        algorithm: klp.Algorithm, simulator: Callable, tmp_path: Path):
    original = ring_resistance_network(algorithm, serialized=False)
    restored = ring_resistance_network(algorithm, serialized=True)
    netlist_path = tmp_path / 'ring.spice'
    netlist_path.write_text(spice_subcircuit(restored, 'ring', ['P0', 'P1']), encoding='utf-8')
    _, measured = simulator(str(netlist_path), 'ring', ['P0', 'P1'], (0, 1), str(tmp_path))
    expected = port_admittance(original, ['P0', 'P1'], 0.0)
    # The converter is absent from the reference. Ngspice writes eight-digit
    # decimal values, while the two geometry paths themselves agree to 1e-12.
    for admittance in measured:
        assert admittance == pytest.approx(expected, rel=1e-7, abs=0.0)
