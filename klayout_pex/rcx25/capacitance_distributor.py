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
Distribution of the capacitances onto the nodes of the resistor networks (#211 §8)

NOTE: each part of the geometry of a capacitance (its area, or its edge) goes to the node
      of the resistor network nearest to it, on each of the two nets (on the layer of the capacitance),
      so that the RC netlist is a distributed RC, e.g. a wire between 2 nodes has half of its
      capacitance on each of them (π model). A net without a resistor network keeps its capacitances.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
import math
from typing import *

import klayout.db as kdb

from .types import LayerName, NetName

import klayout_pex_protobuf.kpex.layout.location_pb2 as location_pb2
import klayout_pex_protobuf.kpex.r.r_network_pb2 as r_network_pb2


Point = Tuple[float, float]  # in DBU
Contour = List[Point]

# the nodes of a capacitance, of its first and second net
NodePair = Tuple[NetName, NetName]


@dataclass(frozen=True)
class NodeSite:
    """
    The location of a node of a resistor network (in DBU), by the name of its node in the netlist
    """
    x: float
    y: float
    node_name: NetName

    @classmethod
    def from_node(cls, node: r_network_pb2.RNode, node_name: NetName) -> Optional[NodeSite]:
        """
        :return: the site of a pin, or the center of the box of another node, None without location
        """
        K = location_pb2.Location.Kind
        match node.location.kind:
            case K.LOCATION_KIND_POINT:
                return cls(node.location.point.x, node.location.point.y, node_name)
            case K.LOCATION_KIND_BOX:
                box = node.location.box
                return cls((box.lower_left.x + box.upper_right.x) / 2.0,
                           (box.lower_left.y + box.upper_right.y) / 2.0,
                           node_name)
            case _:
                return None


class NodeSites:
    """
    The sites of the nodes of a net (on a layer)
    """
    def __init__(self, sites: Iterable[NodeSite]):
        # NOTE: one site per location, as nodes at the same location would share the same part of the geometry
        by_location: Dict[Point, NodeSite] = {}
        for site in sorted(sites, key=lambda s: (s.node_name, s.x, s.y)):
            by_location.setdefault((site.x, site.y), site)
        self.sites: List[NodeSite] = sorted(by_location.values(), key=lambda s: (s.x, s.y, s.node_name))
        self.xs: List[float] = [s.x for s in self.sites]

    def nearest(self, x: float, y: float) -> NodeSite:
        best_site, best_distance = None, math.inf
        idx = bisect_left(self.xs, x)
        # NOTE: outwards from x, as long as the sites can be nearer
        for indices in (range(idx, len(self.sites)), range(idx - 1, -1, -1)):
            for i in indices:
                site = self.sites[i]
                if abs(site.x - x) > best_distance:
                    break
                distance = math.hypot(site.x - x, site.y - y)
                if distance < best_distance:
                    best_site, best_distance = site, distance
        return best_site

    def candidates(self, box: kdb.Box | kdb.DBox) -> List[NodeSite]:
        """
        The sites that can be the nearest to a point of the box
        """
        if len(self.sites) == 1:
            return self.sites

        # NOTE: each point of the box has a site within the distance of the farthest corner
        #       from the site nearest to the center, so a site farther from the box is never the nearest
        center = box.center()
        site = self.nearest(center.x, center.y)
        radius = math.hypot(max(abs(site.x - box.left), abs(site.x - box.right)),
                            max(abs(site.y - box.bottom), abs(site.y - box.top)))
        candidates: List[NodeSite] = []
        for i in range(bisect_left(self.xs, box.left - radius), bisect_right(self.xs, box.right + radius)):
            s = self.sites[i]
            dx = max(box.left - s.x, 0.0, s.x - box.right)
            dy = max(box.bottom - s.y, 0.0, s.y - box.top)
            if math.hypot(dx, dy) <= radius:
                candidates.append(s)
        return candidates


def edge_parts(p: Point, q: Point, sites: Sequence[NodeSite]) -> List[Tuple[float, float, NetName]]:
    """
    The parts of the segment from p to q, by the site nearest to them

    :return: (t0, t1, node name) for the points p + t·(q - p), t0 ≤ t ≤ t1, from t = 0 to t = 1
    """
    dx, dy = q[0] - p[0], q[1] - p[1]

    # NOTE: the squared distance of p + t·(q - p) to a site is |q - p|²·t² + a·t + b,
    #       so the nearest site is the one of the lowest line a·t + b
    lines = sorted(((2.0 * (dx * (p[0] - s.x) + dy * (p[1] - s.y)),
                     (p[0] - s.x) ** 2 + (p[1] - s.y) ** 2,
                     s.node_name) for s in sites),
                   key=lambda line: (line[1], line[0]))

    parts: List[Tuple[float, float, NetName]] = []
    t = 0.0
    a, b, node_name = lines[0]
    while True:
        # NOTE: the next line below the current one has a lower slope, and crosses it first
        next_t, next_line = 1.0, None
        for line in lines:
            if line[0] >= a:
                continue
            crossing = max(t, (line[1] - b) / (a - line[0]))
            if crossing < next_t or (crossing == next_t and next_line is not None and line[0] < next_line[0]):
                next_t, next_line = crossing, line
        if next_t > t:
            if parts and parts[-1][2] == node_name:
                parts[-1] = (parts[-1][0], next_t, node_name)
            else:
                parts.append((t, next_t, node_name))
        if next_line is None:
            return parts
        t = next_t
        a, b, node_name = next_line


def clip(contour: Contour, nx: float, ny: float, c: float) -> Contour:
    """
    The part of the contour where nx·x + ny·y ≤ c (Sutherland–Hodgman)

    NOTE: the clipped contour of a concave polygon may have edges back and forth on the line,
          but its area is the one of the part
    """
    clipped: Contour = []
    for i in range(len(contour)):
        p, q = contour[i - 1], contour[i]
        dp = nx * p[0] + ny * p[1] - c
        dq = nx * q[0] + ny * q[1] - c
        if (dp > 0.0) != (dq > 0.0):
            s = dp / (dp - dq)
            clipped.append((p[0] + s * (q[0] - p[0]), p[1] + s * (q[1] - p[1])))
        if dq <= 0.0:
            clipped.append(q)
    return clipped


def signed_area(contour: Contour) -> float:
    return 0.5 * sum(contour[i - 1][0] * contour[i][1] - contour[i][0] * contour[i - 1][1]
                     for i in range(len(contour)))


@dataclass
class Area:
    """
    An area, as contours with their sign (+1 for a hull, -1 for a hole), relative to an origin
    """
    contours: List[Tuple[Contour, float]]

    @classmethod
    def from_region(cls, region: kdb.Region, origin: kdb.Point) -> Area:
        contours: List[Tuple[Contour, float]] = []
        for polygon in region.each():
            hull = [(p.x - origin.x, p.y - origin.y) for p in polygon.each_point_hull()]
            contours.append((hull, math.copysign(1.0, signed_area(hull))))
            for h in range(polygon.holes()):
                hole = [(p.x - origin.x, p.y - origin.y) for p in polygon.each_point_hole(h)]
                contours.append((hole, -math.copysign(1.0, signed_area(hole))))
        return cls(contours)

    def area(self) -> float:
        return sum(sign * signed_area(contour) for contour, sign in self.contours)

    def bbox(self, origin: kdb.Point) -> kdb.DBox:
        xs = [p[0] for contour, _ in self.contours for p in contour]
        ys = [p[1] for contour, _ in self.contours for p in contour]
        return kdb.DBox(min(xs) + origin.x, min(ys) + origin.y, max(xs) + origin.x, max(ys) + origin.y)

    def parts(self,
              sites: Optional[NodeSites],
              net_name: NetName,
              origin: kdb.Point) -> Iterator[Tuple[NetName, Area]]:
        """
        The parts of the area by the node of the site nearest to them (the whole area for a net without sites)
        """
        if sites is None:
            yield net_name, self
            return
        candidates = sites.candidates(self.bbox(origin))
        if len(candidates) == 1:
            yield candidates[0].node_name, self
            return
        for i, site in enumerate(candidates):
            part = self.clipped_to_cell(candidates, i, origin)
            if part.contours:
                yield site.node_name, part

    def clipped_to_cell(self, sites: Sequence[NodeSite], index: int, origin: kdb.Point) -> Area:
        """
        The part of the area nearer to the site of the index than to the other sites (its Voronoi cell)
        """
        sx, sy = sites[index].x - origin.x, sites[index].y - origin.y
        contours = self.contours
        for j, other in enumerate(sites):
            if j == index:
                continue
            ox, oy = other.x - origin.x, other.y - origin.y
            # NOTE: |x - s|² ≤ |x - o|²  ⇔  (o - s)·x ≤ (|o|² - |s|²) / 2
            nx, ny, c = ox - sx, oy - sy, (ox * ox + oy * oy - sx * sx - sy * sy) / 2.0
            contours = [(clipped, sign) for contour, sign in contours
                        if len(clipped := clip(contour, nx, ny, c)) >= 3]
        return Area(contours)


class CapacitanceDistributor:
    """
    The nodes of the resistor networks, which the capacitances go to, by their geometry
    """
    def __init__(self,
                 sites_by_net_and_layer: Dict[Tuple[NetName, LayerName], NodeSites],
                 sites_by_net: Dict[NetName, NodeSites]):
        self.sites_by_net_and_layer = sites_by_net_and_layer
        self.sites_by_net = sites_by_net

    @classmethod
    def from_networks(cls,
                      networks: Iterable[Tuple[r_network_pb2.RNetwork, Dict[int, NetName]]]) -> CapacitanceDistributor:
        """
        :param networks: each resistor network, with the netlist node names by node ID
        """
        sites_by_net_and_layer: Dict[Tuple[NetName, LayerName], List[NodeSite]] = defaultdict(list)
        sites_by_net: Dict[NetName, List[NodeSite]] = defaultdict(list)
        for network, node_names in networks:
            for node in network.nodes:
                site = NodeSite.from_node(node, node_names[node.node_id])
                if site is None:
                    continue
                sites_by_net_and_layer[(network.net_name, node.layer_name)].append(site)
                sites_by_net[network.net_name].append(site)
        return cls(sites_by_net_and_layer={key: NodeSites(sites) for key, sites in sites_by_net_and_layer.items()},
                   sites_by_net={net_name: NodeSites(sites) for net_name, sites in sites_by_net.items()})

    def has_nodes(self, net_name: NetName) -> bool:
        return net_name in self.sites_by_net

    def sites(self, net_name: NetName, layer_name: LayerName) -> Optional[NodeSites]:
        """
        The sites of the nodes of the net on the layer,
        otherwise on any layer (e.g. a layer the resistance extraction doesn't model)
        """
        return self.sites_by_net_and_layer.get((net_name, layer_name), None) or \
               self.sites_by_net.get(net_name, None)

    def area_fractions(self,
                       net_a: NetName, layer_a: LayerName,
                       net_b: NetName, layer_b: LayerName,
                       area: Optional[kdb.Region]) -> Dict[NodePair, float]:
        """
        The fractions of a capacitance across an area (e.g. an overlap) by the nodes nearest to its parts

        :return: the fraction by node pair, which sum up to 1
        """
        if area is None or area.is_empty():
            return {(net_a, net_b): 1.0}

        # NOTE: relative to the center, to keep the coordinates small
        origin = area.bbox().center()
        sites_a = self.sites(net_a, layer_a)
        sites_b = self.sites(net_b, layer_b)

        fractions: Dict[NodePair, float] = defaultdict(float)
        for node_a, part_a in Area.from_region(area, origin).parts(sites_a, net_a, origin):
            for node_b, part in part_a.parts(sites_b, net_b, origin):
                fractions[(node_a, node_b)] += part.area()
        return self._normalized(fractions, net_a, net_b)

    def edge_fractions(self,
                       net_a: NetName, layer_a: LayerName, edge_a: Optional[kdb.Edge],
                       net_b: NetName, layer_b: LayerName, edge_b: Optional[kdb.Edge]) -> Dict[NodePair, float]:
        """
        The fractions of a capacitance between two edges (e.g. a sidewall) by the nodes nearest to their parts

        :param edge_a: the edge of net A
        :param edge_b: the edge of net B, its points face the ones of edge A (same direction)
        :return: the fraction by node pair, which sum up to 1
        """
        if edge_a is None or edge_b is None:
            return {(net_a, net_b): 1.0}

        parts_a = self._edge_parts(net_a, layer_a, edge_a)
        parts_b = self._edge_parts(net_b, layer_b, edge_b)

        # NOTE: the parts of both edges facing each other
        fractions: Dict[NodePair, float] = defaultdict(float)
        i, j, t = 0, 0, 0.0
        while i < len(parts_a) and j < len(parts_b):
            t1 = min(parts_a[i][1], parts_b[j][1])
            fractions[(parts_a[i][2], parts_b[j][2])] += t1 - t
            t = t1
            if parts_a[i][1] <= t1:
                i += 1
            if parts_b[j][1] <= t1:
                j += 1
        return self._normalized(fractions, net_a, net_b)

    def _edge_parts(self,
                    net_name: NetName,
                    layer_name: LayerName,
                    edge: kdb.Edge) -> List[Tuple[float, float, NetName]]:
        sites = self.sites(net_name, layer_name)
        if sites is None:
            return [(0.0, 1.0, net_name)]
        return edge_parts((edge.p1.x, edge.p1.y), (edge.p2.x, edge.p2.y), sites.candidates(edge.bbox()))

    @staticmethod
    def _normalized(fractions: Dict[NodePair, float], net_a: NetName, net_b: NetName) -> Dict[NodePair, float]:
        total = sum(fractions.values())
        if total <= 0.0:
            return {(net_a, net_b): 1.0}
        # NOTE: in order, so that the sums are the same from run to run
        return {pair: fraction / total for pair, fraction in sorted(fractions.items()) if fraction > 0.0}
