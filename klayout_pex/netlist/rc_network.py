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
RC networks for netlist reduction.

An :class:`RCNetwork` is an undirected graph: its nodes are connected by branches,
each a conductance and a capacitance in parallel (either may be zero).
Parallel resistors and capacitors between the same pair of nodes add up into one branch.

Node names are case-insensitive, as in SPICE: 'A' and 'a' are the same node,
which keeps the spelling it was first created with.

A node can be tied to ground (by a large resistor, when written), which is a mark of the node, not a branch:
the reductions don't see it as a resistor.
"""

from __future__ import annotations

import math
from typing import *


class Branch:
    """
    A conductance [S] and a capacitance [F] in parallel, shared by the two nodes it connects
    """

    __slots__ = ('conductance', 'capacitance')

    def __init__(self, conductance: float = 0.0, capacitance: float = 0.0):
        self.conductance = conductance
        self.capacitance = capacitance

    def __repr__(self) -> str:
        return f"Branch(conductance={self.conductance!r}, capacitance={self.capacitance!r})"


class RCNetwork:
    """
    Nodes connected by branches (see :class:`Branch`).

    Nodes are integers, numbered in the order they were created; removed nodes keep their number.
    A protected node is never removed or merged by the reductions.
    """

    def __init__(self):
        self._names: List[str] = []
        self._node_by_key: Dict[str, int] = {}
        self._branches: List[Optional[Dict[int, Branch]]] = []
        self._protected: List[bool] = []
        self._tied: List[bool] = []

    # ----------------------------------------------------------------------- nodes

    @staticmethod
    def name_key(name: str) -> str:
        """The identity of a node name (case-insensitive, as in SPICE)"""
        return name.casefold()

    def node(self, name: str) -> int:
        """The node of this name, created if there is none"""
        node = self.find_node(name)
        if node is not None:
            return node
        node = len(self._names)
        self._names.append(name)
        self._node_by_key[self.name_key(name)] = node
        self._branches.append({})
        self._protected.append(False)
        self._tied.append(False)
        return node

    def find_node(self, name: str) -> Optional[int]:
        """The node of this name, None if there is none (or if it was removed)"""
        node = self._node_by_key.get(self.name_key(name))
        if node is None or self._branches[node] is None:
            return None
        return node

    def name(self, node: int) -> str:
        return self._names[node]

    def sort_key(self, node: int) -> Tuple[str, str]:
        """Orders nodes by name, independent of the order they were created in"""
        name = self._names[node]
        return self.name_key(name), name

    def nodes(self) -> List[int]:
        """The nodes that were not removed, in the order they were created"""
        return [n for n, branches in enumerate(self._branches) if branches is not None]

    def is_alive(self, node: int) -> bool:
        """False once the node was removed or merged into another one"""
        return self._branches[node] is not None

    def protect(self, node: int):
        self._protected[node] = True

    def is_protected(self, node: int) -> bool:
        return self._protected[node]

    def tie(self, node: int):
        """Mark a node as tied to ground (see the module docs)"""
        self._tied[node] = True

    def untie(self, node: int):
        self._tied[node] = False

    def is_tied(self, node: int) -> bool:
        return self._tied[node]

    def tied_nodes(self) -> List[int]:
        """The tied nodes that were not removed, in the order they were created"""
        return [n for n in self.nodes() if self._tied[n]]

    # -------------------------------------------------------------------- branches

    def branches(self, node: int) -> Dict[int, Branch]:
        """The branches of a node, by neighbour (read only: change them with the methods below)"""
        branches = self._branches[node]
        if branches is None:
            raise KeyError(f"Node {node} ({self._names[node]}) was removed")
        return branches

    def branch(self, node1: int, node2: int) -> Optional[Branch]:
        return self.branches(node1).get(node2)

    def add(self, node1: int, node2: int, conductance: float = 0.0, capacitance: float = 0.0):
        """
        Add a conductance [S] and a capacitance [F] between two nodes, in parallel to what is there.
        Between a node and itself they have no effect and are dropped.
        """
        if node1 == node2 or (conductance == 0.0 and capacitance == 0.0):
            return
        branches1 = self.branches(node1)
        branch = branches1.get(node2)
        if branch is None:
            branch = Branch()
            branches1[node2] = branch
            self.branches(node2)[node1] = branch
        branch.conductance += conductance
        branch.capacitance += capacitance

    def remove_node(self, node: int):
        """Remove a node and its branches"""
        for neighbour in self.branches(node):
            del self._branches[neighbour][node]
        self._branches[node] = None
        self._tied[node] = False

    def merge_node(self, node: int, into: int):
        """
        Short a node to another one: its branches move to ``into`` (adding up with those there),
        the branch between the two disappears, and the node is removed
        """
        for neighbour, branch in list(self.branches(node).items()):
            if neighbour != into:
                self.add(into, neighbour, branch.conductance, branch.capacitance)
        self.remove_node(node)

    def edges(self) -> List[Tuple[int, int, Branch]]:
        """Every branch once, as (node1, node2, branch) with node1 < node2"""
        return [(node1, node2, branch)
                for node1, branches in enumerate(self._branches) if branches is not None
                for node2, branch in branches.items() if node1 < node2]

    # ---------------------------------------------------------------- node metrics

    def conductance_sum(self, node: int) -> float:
        """γ_N, the sum of the conductances at a node [S]"""
        return sum(b.conductance for b in self.branches(node).values())

    def capacitance_sum(self, node: int) -> float:
        """χ_N, the sum of the capacitances at a node [F]"""
        return sum(b.capacitance for b in self.branches(node).values())

    def time_constant(self, node: int) -> float:
        """
        τ_N = χ_N / γ_N, the nodal time constant [s] (Sheehan, TICER, ICCAD 1999, (1.3)),
        infinite for a node without resistor
        """
        conductance = self.conductance_sum(node)
        if conductance == 0.0:
            return math.inf
        return self.capacitance_sum(node) / conductance

    def degree(self, node: int) -> int:
        """The number of neighbours, by resistor or capacitor"""
        return len(self.branches(node))

    def resistive_degree(self, node: int) -> int:
        """The number of neighbours by resistor (RDeg in Sheehan, TCAD 2007)"""
        return sum(1 for b in self.branches(node).values() if b.conductance != 0.0)

    # ------------------------------------------------------------------- summaries

    def resistor_count(self) -> int:
        """The number of node pairs with a resistor between them"""
        return sum(1 for _, _, b in self.edges() if b.conductance != 0.0)

    def capacitor_count(self) -> int:
        """The number of node pairs with a capacitor between them"""
        return sum(1 for _, _, b in self.edges() if b.capacitance != 0.0)

    def connected_node_count(self) -> int:
        """The number of nodes with at least one branch"""
        return sum(1 for branches in self._branches if branches)
