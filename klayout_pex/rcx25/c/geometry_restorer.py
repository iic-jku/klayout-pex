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

import klayout.db as kdb

from klayout_pex.rcx25.types import EdgeInterval


class GeometryRestorer:
    def __init__(self, transformation: kdb.IMatrix3d):
        self.transformation = transformation

    def restore_edge_interval(self, edge_interval: EdgeInterval) -> kdb.Edge:
        return self.transformation * kdb.Edge(kdb.Point(edge_interval[0], 0),
                                              kdb.Point(edge_interval[1], 0))

    def restore_edge(self, edge: kdb.Edge) -> kdb.Edge:
        return self.transformation * edge

    def restore_polygon(self, polygon: kdb.Polygon) -> kdb.Polygon:
        return self.transformation * polygon

    def restore_region(self, region: kdb.Region) -> kdb.Region:
        return region.transformed(self.transformation)
