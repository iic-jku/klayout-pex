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
Reduction of RC networks, keeping their behaviour at the protected nodes (#214).

Two passes, both realizable (the result is again an RC network with positive values):

TICER (Sheehan, ICCAD 1999 and TCAD 2007) eliminates the *quick* nodes, those whose time constant
τ_N = χ_N / γ_N (capacitance and conductance sums at the node) is at most a threshold τ_max,
by the star-mesh transform: each pair of former neighbours i, j gets

    g_ij += g_iN g_jN / γ_N                         (exact: the Schur complement of G, so DC is exact)
    c_ij += (g_iN c_jN + c_iN g_jN) / γ_N            (the quasi-DC approximation, error O(2π f τ_N))

The capacitance at N is moved, not lost: between N's net and every other net it is conserved exactly,
and in total it only shrinks by Σ g_iN c_iN / γ_N for neighbours with a resistor *and* a capacitor to N
(that capacitor is shorted at the frequencies where N is quick).
With τ_max = ε / (2π f_max), the relative error per eliminated node is about ε at f_max (Theorem 1),
the errors of many eliminations can add up (Sec. VIII).

So TICER keeps DC and the capacitances, the response to first order in f. The next order is not kept:
the losses of the AC currents in the eliminated resistors, e.g. the series resistance (the Q) of a MOM
capacitor, shrink or vanish, unless τ_max is small against 1 / (2π f Q).

Capacitor-only nodes (no resistor, e.g. floating metal) are eliminated exactly, at every frequency,
by the capacitive star-mesh, the Schur complement of C (TICER's slow-node rule in its exact limit γ_N = 0):

    c_ij += c_iN c_jN / χ_N

A plate between two nets becomes their series capacitance. Before that, every *floating island*
(nodes connected by resistors, none of them protected) is merged into one node: exact at DC, at other
frequencies it neglects the island's internal resistances.

Slow nodes with resistors (the general slow-node rule, Sheehan 1999, (4.1)) are not eliminated: the rule is
exact only at DC and at infinite frequency, in between it needs a lowest frequency of interest,
but operating points and transients start at DC.

Both passes skip nodes with too many neighbours, to bound the fill-in: TICER those with more than
a maximum number of resistors (RDeg in Sheehan 2007; d resistors give up to d(d-1)/2 new ones),
the capacitor-only pass those with more than a maximum number of capacitors (d(d-1)/2 new ones).
The capacitor-only nodes kept for that have no DC path, so they are tied to ground by a large resistor
(see :data:`TIE_RESISTANCE`), a mark of the node (see :meth:`RCNetwork.tie`), which TICER doesn't see as a resistor.
The capacitor-only pass drops the ties it is given and ties again what it keeps, so that a reduced network
can be reduced again (e.g. with a higher degree limit).
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import *

from .rc_network import RCNetwork


GROUND_NODE_NAME = '0'
"""The node the capacitor-only nodes are tied to (SPICE's global ground)"""

TIE_RESISTANCE = 1e12
"""Ω, ties a capacitor-only node above the degree limit to ground, so that DC has a solution"""


@dataclass(frozen=True)
class ReductionOptions:
    """
    Which passes run, and their limits (the defaults are those of #214)
    """

    ticer: bool = True
    ticer_tau: float = 0.1e-12
    """τ_max [s]: nodes with a time constant up to this are quick"""
    ticer_max_degree: int = 5
    """TICER keeps nodes with more resistors than this"""

    floating: bool = True
    """merge the floating islands, eliminate the capacitor-only nodes, tie the rest to ground"""
    floating_max_degree: int = 64
    """capacitor-only nodes with more capacitors than this are kept and tied to ground"""

    def __post_init__(self):
        """
        :raises ValueError: naming every invalid value and the valid ones
        """
        problems: List[str] = []
        tau = self.ticer_tau
        if isinstance(tau, bool) or not isinstance(tau, (int, float)) or not math.isfinite(tau) or tau <= 0:
            problems.append(f"ticer_tau must be a finite number of seconds > 0, got {tau!r}")
        for name in ('ticer_max_degree', 'floating_max_degree'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                problems.append(f"{name} must be an integer ≥ 1, got {value!r}")
        for name in ('ticer', 'floating'):
            value = getattr(self, name)
            if not isinstance(value, bool):
                problems.append(f"{name} must be True or False, got {value!r}")
        if not problems and not (self.ticer or self.floating):
            problems.append("ticer and floating are both False, there is nothing to do")
        if problems:
            raise ValueError('; '.join(problems))


@dataclass
class ReductionStatistics:
    floating_islands: int = 0
    """floating islands (resistor-connected, no protected node) merged into one node each"""
    floating_island_nodes: int = 0
    """nodes merged away by that"""
    quick_nodes: int = 0
    """nodes eliminated by TICER"""
    capacitor_only_nodes: int = 0
    """capacitor-only nodes eliminated (exactly)"""
    tied_nodes: int = 0
    """capacitor-only nodes kept for their degree, tied to ground"""


# --------------------------------------------------------------------------------- elementary steps

def eliminate_quick_node(network: RCNetwork, node: int):
    """
    Remove a node with resistors by TICER's quick-node rules (Sheehan 2007, (27)), applied to every
    unordered pair of neighbours (unlike Fig. 5 of the paper, whose 'j > i' on line 6 drops
    the capacitors g_iN c_jN / G_N of the pairs with j < i)
    """
    neighbours = list(network.branches(node).items())
    conductance = sum(b.conductance for _, b in neighbours)
    if conductance <= 0.0:
        raise ValueError(f"Node {network.name(node)} has no resistor, TICER does not apply")
    for index, (node_i, branch_i) in enumerate(neighbours):
        g_i, c_i = branch_i.conductance, branch_i.capacitance
        for node_j, branch_j in neighbours[index + 1:]:
            g_j, c_j = branch_j.conductance, branch_j.capacitance
            network.add(node_i, node_j,
                        conductance=g_i * g_j / conductance,
                        capacitance=(g_i * c_j + c_i * g_j) / conductance)
    network.remove_node(node)


def eliminate_capacitor_only_node(network: RCNetwork, node: int):
    """
    Remove a node without resistors exactly, by the capacitive star-mesh c_ij += c_iN c_jN / χ_N
    """
    neighbours = list(network.branches(node).items())
    if any(b.conductance != 0.0 for _, b in neighbours):
        raise ValueError(f"Node {network.name(node)} has a resistor, it is not capacitor-only")
    capacitance = sum(b.capacitance for _, b in neighbours)
    if capacitance != 0.0:
        for index, (node_i, branch_i) in enumerate(neighbours):
            for node_j, branch_j in neighbours[index + 1:]:
                network.add(node_i, node_j,
                            capacitance=branch_i.capacitance * branch_j.capacitance / capacitance)
    network.remove_node(node)


# ------------------------------------------------------------------------------------------- passes

def merge_floating_islands(network: RCNetwork) -> Tuple[int, int]:
    """
    Merge each floating island (two or more nodes connected by resistors, none of them protected)
    into its node with the smallest name.

    :return: the number of islands, and of the nodes merged away
    """
    islands = 0
    merged_nodes = 0
    visited: Set[int] = set()
    for start in network.nodes():
        if start in visited:
            continue
        island = [start]
        visited.add(start)
        index = 0
        while index < len(island):
            for neighbour, branch in network.branches(island[index]).items():
                if branch.conductance != 0.0 and neighbour not in visited:
                    visited.add(neighbour)
                    island.append(neighbour)
            index += 1
        if len(island) < 2 or any(network.is_protected(n) for n in island):
            continue
        island.sort(key=network.sort_key)
        for node in island[1:]:
            network.merge_node(node, into=island[0])
        islands += 1
        merged_nodes += len(island) - 1
    return islands, merged_nodes


HeapKey = Tuple[Any, ...]


def _eliminate_in_order(network: RCNetwork,
                        heap_key: Callable[[int], Optional[HeapKey]],
                        eliminate: Callable[[RCNetwork, int], None]) -> int:
    """
    Eliminate the nodes that have a heap key (None for those to keep), smallest key first.
    An elimination changes the neighbours' branches, so they get new keys
    (a heap with lazy deletion: entries whose key is no longer the node's key are skipped).

    :return: the number of nodes eliminated
    """
    heap: List[Tuple[HeapKey, int]] = []
    queued: Dict[int, HeapKey] = {}  # node → the key of its valid heap entry

    def queue(node: int):
        key = heap_key(node)
        if key is None:
            queued.pop(node, None)
        elif queued.get(node) != key:
            queued[node] = key
            heapq.heappush(heap, (key, node))

    for node in network.nodes():
        queue(node)

    eliminated = 0
    while heap:
        key, node = heapq.heappop(heap)
        if queued.get(node) != key:
            continue
        del queued[node]
        neighbours = list(network.branches(node))
        eliminate(network, node)
        eliminated += 1
        for neighbour in neighbours:
            queue(neighbour)
    return eliminated


def eliminate_quick_nodes(network: RCNetwork, tau: float, max_degree: int) -> int:
    """
    TICER (Sheehan 2007, Fig. 6, with a heap as in Sec. IV-D): eliminate the unprotected quick nodes
    (time constant ≤ tau) with at most max_degree resistors, those with fewer resistors and smaller
    time constants first. Nodes with one resistor (leaves) are deferred to a final sweep
    (Sec. IV-B), so that stubs are not eaten from their end one node at a time.

    :return: the number of nodes eliminated
    """
    def heap_key(node: int) -> Optional[HeapKey]:
        if network.is_protected(node):
            return None
        degree = network.resistive_degree(node)
        if degree < 2 or degree > max_degree:
            return None
        time_constant = network.time_constant(node)
        if time_constant > tau:
            return None
        return degree, time_constant, network.sort_key(node)

    eliminated = _eliminate_in_order(network, heap_key, eliminate_quick_node)

    leaves = [n for n in network.nodes()
              if not network.is_protected(n) and network.resistive_degree(n) == 1]
    leaves.sort(key=lambda n: (network.time_constant(n), network.sort_key(n)))
    for node in leaves:
        if network.is_alive(node) and network.resistive_degree(node) == 1 \
                and network.time_constant(node) <= tau:
            eliminate_quick_node(network, node)
            eliminated += 1
    return eliminated


def eliminate_capacitor_only_nodes(network: RCNetwork, max_degree: int) -> int:
    """
    Eliminate the unprotected nodes without resistor with at most max_degree capacitors exactly,
    those with fewer capacitors first.

    :return: the number of nodes eliminated
    """
    def heap_key(node: int) -> Optional[HeapKey]:
        if network.is_protected(node) or network.resistive_degree(node) != 0:
            return None
        degree = network.degree(node)
        if degree == 0 or degree > max_degree:
            return None
        return degree, network.sort_key(node)

    return _eliminate_in_order(network, heap_key, eliminate_capacitor_only_node)


def tie_capacitor_only_nodes(network: RCNetwork) -> int:
    """
    Tie every unprotected node that has capacitors but no resistor to ground (node '0'),
    by :data:`TIE_RESISTANCE`, so that DC has a solution (see :meth:`RCNetwork.tie`).

    :return: the number of nodes tied
    """
    nodes = [n for n in network.nodes()
             if not network.is_protected(n) and network.degree(n) > 0 and network.resistive_degree(n) == 0]
    for node in nodes:
        network.tie(node)
    return len(nodes)


def reduce_network(network: RCNetwork, options: ReductionOptions) -> ReductionStatistics:
    """
    Run the passes the options enable, in this order:
    merge the floating islands, TICER, eliminate the capacitor-only nodes, tie the remaining ones to ground.

    TICER runs before the capacitor-only elimination, so that a plate's neighbours along a wire are
    merged first: the plate then has fewer capacitors, gives fewer new ones (d(d-1)/2)
    and stays below its degree limit more often. The protected nodes are never eliminated or merged.
    The floating passes drop the ties of the network first, the last one ties again what is left.
    """
    statistics = ReductionStatistics()
    if options.floating:
        for node in network.tied_nodes():
            network.untie(node)
        statistics.floating_islands, statistics.floating_island_nodes = merge_floating_islands(network)
    if options.ticer:
        statistics.quick_nodes = eliminate_quick_nodes(network, tau=options.ticer_tau,
                                                       max_degree=options.ticer_max_degree)
    if options.floating:
        statistics.capacitor_only_nodes = eliminate_capacitor_only_nodes(
            network, max_degree=options.floating_max_degree)
        statistics.tied_nodes = tie_capacitor_only_nodes(network)
    return statistics
