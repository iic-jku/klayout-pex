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

import klayout.db as kdb
import klayout_pex_protobuf.kpex.geometry.shapes_pb2 as shapes_pb2


class ShapesConverter:
    def __init__(self, dbu: float):
        self.dbu = dbu

    def klayout_point(self, point: shapes_pb2.Point) -> kdb.Point:
        # FIXME: there is no PointWithProperties yet
        return kdb.Point(point.x, point.y)

    def klayout_polygon(self, polygon: shapes_pb2.Polygon) -> kdb.Polygon:
        points_kly = [self.klayout_point(pt) for pt in polygon.hull_points]
        polygon_kly = kdb.Polygon(points_kly)
        if len(polygon.net) >= 1:
            polygon_kly = kdb.PolygonWithProperties(polygon_kly, {'net': polygon.net})
        return polygon_kly

    def klayout_region(self, region: shapes_pb2.Region) -> kdb.Region:
        region_kly = kdb.Region()
        for polygon in region.polygons:
            region_kly.insert(self.klayout_polygon(polygon))
        return region_kly

    def klayout_box(self, box: shapes_pb2.Box) -> kdb.Box:
        box_kly = kdb.Box(box.lower_left.x,
                          box.lower_left.y,
                          box.upper_right.x,
                          box.upper_right.y)
        if box.net:
            box_kly = kdb.BoxWithProperties(box_kly, {'net': box.net})
        return box_kly

    def klayout_point_to_pb(self,
                            point_kly: kdb.Point,
                            point_pb: shapes_pb2.Point):
        point_pb.x = point_kly.x
        point_pb.y = point_kly.y

    def klayout_polygon_to_pb(self,
                              polygon_kly: kdb.Polygon,
                              polygon_pb: shapes_pb2.Polygon):
        net_name = polygon_kly.property('net')
        if net_name:
            polygon_pb.net = net_name
        for p_kly in polygon_kly.each_point_hull():
            self.klayout_point_to_pb(p_kly, polygon_pb.hull_points.add())

    def klayout_region_to_pb(self,
                             region_kly: kdb.Region,
                             region_pb: shapes_pb2.Region):
        for pgn_kly in region_kly:
            self.klayout_polygon_to_pb(pgn_kly, region_pb.polygons.add())
