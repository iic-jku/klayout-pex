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

"""Shared, layout-independent grounding after exact floating-capacitance elimination."""

from collections import defaultdict
from enum import StrEnum
import math
from typing import Collection, Dict, Mapping, Optional, Tuple

from .rc_network import RCNetwork
from .rc_reduction import ReductionOptions, eliminate_capacitor_only_nodes


class CouplingPolicy(StrEnum):
    COUPLED = 'coupled'
    GROUNDED = 'grounded'


class CouplingPolicyError(ValueError):
    """The requested capacitance approximation cannot be applied safely."""


def ground_capacitances(capacitance_by_pair: Mapping[Tuple[str, str], float],
                         reference_net_name: str,
                         *,
                         net_by_node: Optional[Mapping[str, str]] = None,
                         floating_net_names: Collection[str] = (),
                         resistive_nodes: Collection[str] = (),
                         reference_net_names: Collection[str] = (),
                         protected_net_names: Collection[str] = ()) -> Dict[Tuple[str, str], float]:
    """Ground inter-net capacitance using caller-supplied conductor identities.

    All capacitances use the same unit, which is preserved. Names are case-sensitive
    here. SPICE adapters canonicalize them before calling this function.
    Capacitor-only floating conductors are eliminated exactly first. Remaining
    inter-net C(A,B) becomes C(A,reference) and C(B,reference), each with its full
    value. Intra-net and reference-connected capacitance stays at its endpoints.
    The input is not mutated. Floating resistive nets and excessive fill-in fail
    explicitly instead of approximating their dynamics or inserting ground ties.
    """
    if not isinstance(reference_net_name, str) or not reference_net_name.strip():
        raise CouplingPolicyError('The capacitance reference net must have a non-empty name')

    references = {reference_net_name, *reference_net_names}
    net_by_node = net_by_node or {}

    def net_of(node: str) -> str:
        return net_by_node.get(node, node)

    def is_reference(node: str) -> bool:
        return node in references or net_of(node) in references

    capacitances: Dict[Tuple[str, str], float] = defaultdict(float)
    for pair, capacitance in capacitance_by_pair.items():
        if not math.isfinite(capacitance) or capacitance < 0:
            raise CouplingPolicyError(
                f'Capacitance {pair[0]} to {pair[1]} must be finite and non-negative, got {capacitance!r}')
        if pair[0] != pair[1] and capacitance != 0:
            capacitances[tuple(sorted(pair))] += capacitance
    if any(not math.isfinite(value) for value in capacitances.values()):
        raise CouplingPolicyError('Approximated capacitance exceeds the finite numeric range')

    # Adapters supply the observable boundaries before any floating elimination.
    floating_nets = set(floating_net_names) - references - set(protected_net_names)

    def is_floating(node: str) -> bool:
        return net_of(node) in floating_nets and not is_reference(node)

    resistive_floating = {net_of(node) for node in resistive_nodes
                         if is_floating(node)}
    if resistive_floating:
        raise CouplingPolicyError(
            'Grounded RC output cannot eliminate floating resistive nets exactly at every frequency: '
            + ', '.join(sorted(resistive_floating)))

    if floating_nets:
        network = RCNetwork()
        names = sorted({node for pair in capacitances for node in (pair[0], pair[1])})
        # RCNetwork follows SPICE's case-insensitive identity. The extraction
        # summary does not, so use opaque tokens and preserve the original names.
        nodes = {name: network.node(str(index)) for index, name in enumerate(names)}
        name_by_node = {node: name for name, node in nodes.items()}
        for name, node in nodes.items():
            if not is_floating(name):
                network.protect(node)
        for pair, capacitance in capacitances.items():
            network.add(nodes[pair[0]], nodes[pair[1]], capacitance=capacitance)

        # A purely capacitive component touching zero or one retained node adds
        # no load there. Remove it before degree limits can reject a dense but
        # unobservable floating component.
        visited = set()
        for start in network.nodes():
            if network.is_protected(start) or start in visited:
                continue
            component = [start]
            boundaries = set()
            visited.add(start)
            for node in component:
                for neighbor in network.branches(node):
                    if network.is_protected(neighbor):
                        boundaries.add(neighbor)
                    elif neighbor not in visited:
                        component.append(neighbor)
                        visited.add(neighbor)
            if len(boundaries) <= 1:
                for node in component:
                    network.remove_node(node)

        max_degree = ReductionOptions().floating_max_degree
        eliminate_capacitor_only_nodes(network, max_degree=max_degree)
        survivors = [name_by_node[node] for node in network.nodes()
                     if not network.is_protected(node) and network.degree(node) > 0]
        if survivors:
            raise CouplingPolicyError(
                f'Exact floating-capacitance elimination exceeds the {max_degree}-neighbor limit for '
                + ', '.join(sorted(survivors)))
        capacitances = {tuple(sorted((name_by_node[a], name_by_node[b]))): branch.capacitance
                        for a, b, branch in network.edges()}

    grounded: Dict[Tuple[str, str], float] = defaultdict(float)
    for pair, capacitance in capacitances.items():
        if is_reference(pair[0]) or is_reference(pair[1]) or net_of(pair[0]) == net_of(pair[1]):
            grounded[pair] += capacitance
        else:
            for node in (pair[0], pair[1]):
                grounded[tuple(sorted((node, reference_net_name)))] += capacitance
    if any(not math.isfinite(value) for value in grounded.values()):
        raise CouplingPolicyError('Approximated capacitance exceeds the finite numeric range')
    return dict(grounded)
