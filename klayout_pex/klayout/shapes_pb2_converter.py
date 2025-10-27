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

import klayout.db as kdb
import klayout_pex_protobuf.kpex.geometry.shapes_pb2 as shapes_pb2


class ShapesConverter:
    def __init__(self, dbu: float):
        self.dbu = dbu

    def klayout_point(self, point: shapes_pb2.Point) -> kdb.Point:
        # FIXME: there is no PointWithProperties yet
        return kdb.Point(point.x, point.y)

    def klayout_point_to_pb(self,
                            point_kly: kdb.Point,
                            point_pb: shapes_pb2.Point):
        point_pb.x = point_kly.x
        point_pb.y = point_kly.y

    def klayout_box(self, box: shapes_pb2.Box) -> kdb.Box:
        box_kly = kdb.Box(box.lower_left.x,
                          box.lower_left.y,
                          box.upper_right.x,
                          box.upper_right.y)
        if box.net:
            box_kly = kdb.BoxWithProperties(box_kly, {'net': box.net})
        return box_kly

    def klayout_box_to_pb(self,
                          box_kly: kdb.Box,
                          shape_pb: shapes_pb2.Shape):
        shape_pb.kind = shapes_pb2.Shape.Kind.SHAPE_KIND_BOX
        box_pb = shape_pb.box
        if isinstance(box_kly, kdb.BoxWithProperties):
            net_name = box_kly.property('net')
            if net_name:
                box_pb.net = net_name
        box_pb.lower_left.x = box_kly.left
        box_pb.lower_left.y = box_kly.bottom
        box_pb.upper_right.x = box_kly.right
        box_pb.upper_right.y = box_kly.top

    def klayout_polygon(self, polygon: shapes_pb2.Polygon) -> kdb.Polygon:
        points_kly = [self.klayout_point(pt) for pt in polygon.hull_points]
        polygon_kly = kdb.Polygon(points_kly)
        if len(polygon.net) >= 1:
            polygon_kly = kdb.PolygonWithProperties(polygon_kly, {'net': polygon.net})
        return polygon_kly

    def klayout_polygon_to_pb(self,
                              polygon_kly: kdb.Polygon,
                              shape_pb: shapes_pb2.Shape):
        shape_pb.kind = shapes_pb2.Shape.Kind.SHAPE_KIND_POLYGON
        net_name = polygon_kly.property('net')
        if net_name:
            shape_pb.polygon.net = net_name
        for p_kly in polygon_kly.each_point_hull():
            self.klayout_point_to_pb(p_kly, shape_pb.polygon.hull_points.add())

    def klayout_shape(self, shape: shapes_pb2.Shape) -> kdb.Shape:
        match shape.kind:
            case shapes_pb2.Shape.Kind.SHAPE_KIND_BOX:
                return self.klayout_box(shape.box)
            case shapes_pb2.Shape.Kind.SHAPE_KIND_POLYGON:
                return self.klayout_polygon(shape.polygon)
            case _:
                raise NotImplementedError()

    def klayout_shape_to_pb(self,
                            shape_kly: kdb.Shape,
                            shape_pb: shapes_pb2.Shape):
        if shape_kly.is_box():
            self.klayout_box_to_pb(shape_kly.bbox(), shape_pb)
        elif shape_kly.is_polygon():
            self.klayout_polygon_to_pb(shape_kly.polygon(), shape_pb)
        else:
            raise NotImplementedError()

    def klayout_region(self, region: shapes_pb2.Region) -> kdb.Region:
        region_kly = kdb.Region()
        for shape in region.shapes:
            match shape.kind:
                case shapes_pb2.Shape.Kind.SHAPE_KIND_POLYGON:
                    region_kly.insert(self.klayout_polygon(shape.polygon))
                case shapes_pb2.Shape.Kind.SHAPE_KIND_BOX:
                    region_kly.insert(self.klayout_box(shape.box))
                case _:
                    raise NotImplementedError()
        return region_kly

    def klayout_region_to_pb(self,
                             region_kly: kdb.Region,
                             region_pb: shapes_pb2.Region):
        for sh_kly in region_kly:
            self.klayout_polygon_to_pb(sh_kly, region_pb.shapes.add())
