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

from __future__ import annotations
from dataclasses import dataclass
from typing import *

import klayout.db as kdb

from klayout_pex.log import (
    debug,
    error,
    warning,
)
from .conductance import Conductance
from ..types import LayerName

NodeID = int


class ResistorNetwork:
    """
    A general container for a resistor network

    The container manages the networks through node IDs. Those are integers
    describing one network node. A node has a location (a kdb.Point) and
    one to many resistors connecting two of them each.

    Attributes are:
    * nodes -> dict[kdb.Point, NodeID]: The node IDs per kdb.Point
    * locations -> dict[NodeID, kdb.Point]: the kdb.Point of a node (given by ID)
    * s -> dict[(NodeID, NodeID), Conductance]: the registors
    * node_to_s -> dict[NodeID, list[(Conductance, NodeID)]]: the resistors connected to a node with the
      node connected by the resistor
    * precious -> set[NodeID]: a set of node IDs for the precious nodes
    * node_names -> dict[NodeID, str]: the names of nodes
    """

    def __init__(self):
        self.nodes = {}
        self.locations = {}
        self.s = {}
        self.node_to_s = {}
        self.next_id = 0
        self.precious = set()
        self.node_names = {}

    @staticmethod
    def is_skinny_tri(pts: list[kdb.Point]) -> Optional[bool]:
        for i in range(0, 3):
            pm1 = pts[i]
            p0 = pts[(i + 1) % 3]
            p1 = pts[(i + 2) % 3]

            lm1 = (p0 - pm1).sq_length()
            l0 = (p1 - p0).sq_length()
            l1 = (pm1 - p1).sq_length()

            if l0 + l1 < lm1 * (1.0 - 1e-10):
                return i != 0

        return None

    @staticmethod
    def expand_skinny_tris(p: kdb.Polygon) -> List[kdb.Polygon]:
        pts = [pt for pt in p.each_point_hull()]

        i = ResistorNetwork.is_skinny_tri(pts)
        if i is None:
            return [p]

        pm1 = pts[i]
        p0 = pts[(i + 1) % 3]
        p1 = pts[(i + 2) % 3]

        lm1 = (p0 - pm1).sq_length()
        px = p0 + (pm1 - p0) * ((pm1 - p0).sprod(p1 - p0) / lm1)

        return [kdb.Polygon([p0, p1, px]), kdb.Polygon([px, p1, pm1])]

    def __str__(self) -> str:
        return self.to_string(False)

    def to_string(self, resistance: bool = False) -> str:
        """ A more elaborate string generator

        :param resistance: if true, prints resistance values instead of conductance values
        """

        res: List[str] = []
        res.append("Nodes:")
        for nid in sorted(self.locations.keys()):
            nn = self.node_names[nid] if nid in self.node_names else str(nid)
            res.append(f"  {nn}: {self.locations[nid]}")

        if not resistance:
            res.append("Conductors:")
            for ab in sorted(self.s.keys()):
                if ab[0] < ab[1]:
                    nna = self.node_names[ab[0]] if ab[0] in self.node_names else str(ab[0])
                    nnb = self.node_names[ab[1]] if ab[1] in self.node_names else str(ab[1])
                    res.append(f"  {nna},{nnb}: {self.s[ab]}")
            return "\n".join(res)

        res.append("Resistors:")
        for ab in sorted(self.s.keys()):
            if ab[0] < ab[1]:
                nna = self.node_names[ab[0]] if ab[0] in self.node_names else str(ab[0])
                nnb = self.node_names[ab[1]] if ab[1] in self.node_names else str(ab[1])
                res.append(f"  {nna},{nnb}: {self.s[ab].res()}")
        return "\n".join(res)

    def check(self) -> int:
        """
        A self-check.

        :return: the number of errors found
        """
        errors = 0
        for nid in sorted(self.locations.keys()):
            loc = self.locations[nid]
            if loc not in self.nodes:
                error(f"location {loc} with id {nid} not found in nodes list")
                errors += 1
        for loc in sorted(self.nodes.keys()):
            nid = self.nodes[loc]
            if nid not in self.locations:
                error(f"node id {nid} with location {loc} not found in locations list")
                errors += 1
        for ab in sorted(self.s.keys()):
            if (ab[1], ab[0]) not in self.s:
                error(f"reverse of key pair {ab} not found in conductor list")
                errors += 1
            if ab[0] not in self.node_to_s:
                error(f"No entry for node {ab[0]} in star list")
                errors += 1
            elif ab[1] not in self.node_to_s:
                error(f"No entry for node {ab[1]} in star list")
                errors += 1
            else:
                cond = self.s[ab]
                if (cond, ab[1]) not in self.node_to_s[ab[0]]:
                    error(f"Missing entry {cond}@{ab[1]} in star list")
                    errors += 1
                if (cond, ab[0]) not in self.node_to_s[ab[1]]:
                    error(f"Missing entry {cond}@{ab[0]} in star list")
                    errors += 1
        for nid in sorted(self.node_to_s.keys()):
            star = self.node_to_s[nid]
            for s in star:
                if (nid, s[1]) not in self.s:
                    error(f"Missing star entry {nid},{s[1]} in conductor list")
                    errors += 1
        return errors

    # TODO: this is slow!
    def node_ids(self, edge: kdb.Edge) -> List[NodeID]:
        """
        Gets the node IDs that are on a given Edge
        """
        return [nid for (p, nid) in self.nodes.items() if edge.contains(p)]

    def node_id(self, point: kdb.Point) -> NodeID:
        """
        Gets the node ID for a given point
        """
        if point in self.nodes:
            return self.nodes[point]

        nid = self.next_id
        self.nodes[point] = nid
        self.locations[nid] = point
        self.next_id += 1
        return nid

    def has_node(self, point: kdb.Point) -> bool:
        """
        Returns a value indicating that there is a node with the given kdb.Point
        """
        return point in self.nodes

    def name(self, nid: int, name: str):
        """
        Provides a name for a node
        """
        self.node_names[nid] = name

    def mark_precious(self, nid: NodeID):
        """
        Marks a node a precious

        Precious nodes are not eliminated
        """
        self.precious.add(nid)

    def location(self, nid: NodeID) -> Optional[kdb.Point]:
        """
        Gets the location for a given node ID
        """
        if nid in self.locations:
            return self.locations[nid]

        return None

    def add_cond(self, a: NodeID, b: NodeID, cond: Conductance):
        """
        Adds a resistor connecting two nodes

        If a resistor already exists connecting these nodes, the new one is added in parallel to it.
        """
        if (a, b) in self.s:
            self.s[(a, b)].add_parallel(cond)
        else:
            self.s[(a, b)] = self.s[(b, a)] = cond
            if a not in self.node_to_s:
                self.node_to_s[a] = []
            self.node_to_s[a].append((cond, b))
            if b not in self.node_to_s:
                self.node_to_s[b] = []
            self.node_to_s[b].append((cond, a))

    def eliminate_node(self, nid: NodeID):
        """
        Eliminates a node

        This uses start to n-mesh transformation to eliminate
        the node.
        """
        if nid not in self.node_to_s:
            return

        star = self.node_to_s[nid]
        s_sum = 0.0
        for s in star:
            s_sum += s[0].cond
        if abs(s_sum) > 1e-10:
            for i in range(0, len(star) - 1):
                for j in range(i + 1, len(star)):
                    s1 = star[i]
                    s2 = star[j]
                    c = s1[0].cond * s2[0].cond / s_sum
                    self.add_cond(s1[1], s2[1], Conductance(c))
        self.remove_node(nid)

    def remove_node(self, nid: NodeID):
        """
        Deletes a node and the corresponding resistors
        """
        if nid not in self.node_to_s:
            return
        star = self.node_to_s[nid]
        for (cond, other) in star:
            if other in self.node_to_s:
                self.node_to_s[other].remove((cond, nid))
            del self.s[(nid, other)]
            del self.s[(other, nid)]
        del self.node_to_s[nid]
        del self.nodes[self.locations[nid]]
        del self.locations[nid]

    def connect_nodes(self, a: NodeID, b: NodeID):
        """
        Contracts a and b into a.
        NOTE: b will be removed and is no longer valid afterwards
        """
        if b not in self.node_to_s:
            return
        star_b = self.node_to_s[b]
        for (cond, other) in star_b:
            if other != a:
                self.add_cond(a, other, cond)
            if other in self.node_to_s:
                self.node_to_s[other].remove((cond, b))
            del self.s[(b, other)]
            del self.s[(other, b)]
        del self.node_to_s[b]
        del self.nodes[self.locations[b]]
        del self.locations[b]

    def eliminate_all(self):
        """
        Runs the elimination loop

        The loop finishes when only precious nodes are left.
        """

        debug(f"Starting with {len(self.node_to_s)} nodes with {len(self.s)} edges.")

        niter = 0
        nmax = 3
        while nmax is not None:
            another_loop = True

            while another_loop:
                nmax_next = None
                to_eliminate = []
                for nid in sorted(self.node_to_s.keys()):
                    if nid not in self.precious:
                        n = len(self.node_to_s[nid])
                        if n <= nmax:
                            to_eliminate.append(nid)
                        elif nmax_next is None or n < nmax_next:
                            nmax_next = n

                if len(to_eliminate) == 0:
                    another_loop = False
                    nmax = nmax_next
                    debug(f"Nothing left to eliminate with nmax={nmax}.")
                else:
                    for nid in to_eliminate:
                        self.eliminate_node(nid)
                    niter += 1
                    debug(f"Nodes left after iteration {niter} with nmax={nmax}: "
                          f"{len(self.node_to_s)} with {len(self.s)} edges.")


@dataclass
class ResistorNetworks:
    layer_name: str
    layer_sheet_resistance: float  # mΩ/µm^2
    networks: List[ResistorNetwork]

    def find_network_nodes(self, location: kdb.Polygon) -> List[Tuple[ResistorNetwork, NodeID]]:
        matches = []

        for nw in self.networks:
            for point, nid in nw.nodes.items():
                if location.inside(point):
                    print(f"node {nid} is located ({point}) within search area {location}")
                    matches.append((nw, nid))

        return matches


@dataclass
class ViaJunction:
    layer_name: LayerName
    network: ResistorNetwork
    node_id: NodeID


@dataclass
class DeviceTerminal:
    device: KLayoutDeviceInfo
    device_terminal: KLayoutDeviceTerminal


@dataclass
class ViaResistor:
    bottom: ViaJunction | DeviceTerminal
    top: ViaJunction
    resistance: float  # mΩ


@dataclass
class MultiLayerResistanceNetwork:
    resistor_networks_by_layer: Dict[LayerName, ResistorNetworks]
    via_resistors: List[ViaResistor]
