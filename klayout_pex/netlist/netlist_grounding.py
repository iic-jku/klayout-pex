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

"""Ground selected SPICE parasitics with the extraction engine's shared policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
import json
import math
import os
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .coupling import CouplingPolicyError, ground_capacitances
from .rc_network import RCNetwork
from .spice_rc_netlist import SpiceRCNetlist, SpiceScope
from .spice_syntax import GROUND_NODE_NAMES
from ..util.disjoint_sets import DisjointSets


def _name(value: str, description: str):
    if not isinstance(value, str) or not value or any(c.isspace() or c in '(),=' for c in value):
        raise ValueError(f'{description} must be a non-empty SPICE name without whitespace, commas, parentheses or =')


@dataclass(frozen=True)
class GroundingOptions:
    reference: str
    capacitor_patterns: Tuple[str, ...] = ('Cext_*', 'Cgrnd_*')
    resistor_patterns: Tuple[str, ...] = ('Rext_*',)
    keep_nodes: Tuple[str, ...] = ()
    cell_name: Optional[str] = None
    top_level: bool = False
    net_by_node: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        _name(self.reference, 'reference')
        if not isinstance(self.top_level, bool):
            raise ValueError('top_level must be True or False')
        if self.cell_name is not None:
            _name(self.cell_name, 'cell_name')
            if self.top_level:
                raise ValueError('Choose cell_name or top_level, not both')
        for patterns, kind in ((self.capacitor_patterns, 'capacitor'), (self.resistor_patterns, 'resistor')):
            if isinstance(patterns, str) or not isinstance(patterns, Sequence) or not patterns:
                raise ValueError(f'{kind}_patterns must be a non-empty sequence of name patterns')
            for pattern in patterns:
                _name(pattern, f'{kind} pattern')
                # Keep element selection unambiguous even when a broad glob is requested.
                if not pattern.casefold().startswith(kind[0]):
                    raise ValueError(f'{kind} patterns must start with {kind[0].upper()}, e.g. {kind[0].upper()}ext_*')
        if isinstance(self.keep_nodes, str) or not isinstance(self.keep_nodes, Sequence):
            raise ValueError('keep_nodes must be a sequence of node names')
        for node in self.keep_nodes:
            _name(node, 'kept node')
        if not isinstance(self.net_by_node, Mapping):
            raise ValueError('net_by_node must map node names to conductor names')
        seen = set()
        for node, net in self.net_by_node.items():
            _name(node, 'mapped node')
            _name(net, 'mapped conductor')
            if node.casefold() in seen:
                raise ValueError(f'Duplicate mapped node (SPICE names are case-insensitive): {node}')
            seen.add(node.casefold())


def read_net_map(path: str) -> Dict[str, str]:
    """Read a flat JSON node-to-conductor map, rejecting duplicate keys."""
    def unique_pairs(pairs: Sequence[Tuple[str, str]]) -> Dict[str, str]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate net-map key: {key}')
            result[key] = value
        return result

    with open(path, encoding='utf-8') as stream:
        data = json.load(stream, object_pairs_hook=unique_pairs)
    if not isinstance(data, dict):
        raise ValueError('The net map must be a JSON object mapping node names to conductor names')
    return data


@dataclass(frozen=True)
class GroundedNetlist:
    output_path: str
    scope: str
    capacitors_read: int
    capacitors_written: int
    floating_nodes: List[str]


def grounded_netlist_path(input_path: str) -> str:
    stem, extension = os.path.splitext(input_path)
    return stem + '_grounded' + extension


def _element_selected(scope: SpiceScope, tokens: Sequence[str], options: GroundingOptions) -> bool:
    name = tokens[0].casefold()
    patterns = options.capacitor_patterns if name.startswith('c') else options.resistor_patterns
    selected = any(fnmatchcase(name, pattern.casefold()) for pattern in patterns)
    if selected:
        resistor = name.startswith('r')
        value = SpiceRCNetlist._element_value(tokens[3], resistor) if len(tokens) == 4 else None
        if value is None or resistor and not math.isfinite(1.0 / value):
            raise CouplingPolicyError(
                f'{scope.title}: selected element {tokens[0]} must have exactly two nodes and a finite '
                f'numeric {"positive resistance" if resistor else "non-negative capacitance"}. '
                'Narrow --capacitor/--resistor to exclude intentional or parameterized devices')
    return selected


def _conductor_names(network: RCNetwork, net_by_node: Mapping[str, str]) -> Dict[str, str]:
    """Infer conductors from selected resistors and explicit identities, without shorting their nodes."""
    components = DisjointSets(network.nodes())
    # SPICE reads gnd as node 0. Their resistor-connected components must share
    # one conductor identity even when only the other alias was selected as reference.
    ground_nodes = [node for name in GROUND_NODE_NAMES if (node := network.find_node(name)) is not None]
    for node in ground_nodes[1:]:
        components.union(ground_nodes[0], node)
    for a, b, branch in network.edges():
        if branch.conductance:
            components.union(a, b)
    explicit: Dict[int, str] = {}
    component_by_label: Dict[str, int] = {}
    known = sorted(network.name(node) for node in network.nodes())
    for name, label in net_by_node.items():
        node = network.find_node(name)
        if node is None:
            raise ValueError(f'Unknown mapped node {name!r}. Valid nodes: {", ".join(known)}')
        component = components.find(node)
        folded = label.casefold()
        if component in explicit and explicit[component] != folded:
            raise ValueError(f'Conflicting conductor names on one resistor-connected component at {name!r}')
        explicit[component] = folded
    for component, label in explicit.items():
        target = network.find_node(label)
        if target is not None:
            target_component = components.find(target)
            if target_component in explicit and explicit[target_component] != label:
                raise ValueError(f'Conductor label {label!r} names a node assigned to a different conductor')
    for component, label in explicit.items():
        target = network.find_node(label)
        if target is not None:
            components.union(component, target)
        if label in component_by_label:
            components.union(component_by_label[label], component)
        component_by_label[label] = component
    # Name each conductor after an actual node for useful diagnostics. Explicit map
    # labels group components but never create or rename netlist nodes.
    representative: Dict[int, str] = {}
    for node in sorted(network.nodes(), key=network.sort_key):
        representative.setdefault(components.find(node), network.name(node))
    return {network.name(node): representative[components.find(node)] for node in network.nodes()}


def ground_spice_netlist(input_path: str, output_path: str, options: GroundingOptions) -> GroundedNetlist:
    """Ground one selected scope and preserve all other circuitry verbatim.

    Only selected numeric parasitics participate. Selected resistors define conductor
    membership and are preserved verbatim. Ports, globals, unselected devices and
    --keep nodes protect entire conductors from floating elimination. An explicit
    node map may join otherwise disconnected parts of one conductor.
    Nothing is written until scope, names, selected elements and grounding succeed.
    """
    if os.path.exists(output_path) and os.path.samefile(input_path, output_path):
        raise ValueError('The output would overwrite the input netlist')
    with open(input_path, encoding='utf-8', errors='surrogateescape', newline='') as stream:
        source = stream.read()

    def requested(scope: SpiceScope) -> bool:
        if options.top_level:
            return scope.name is None
        return options.cell_name is None or scope.name is not None and scope.name.casefold() == options.cell_name.casefold()

    def select(scope: SpiceScope, tokens: Sequence[str]) -> bool:
        return requested(scope) and _element_selected(scope, tokens, options)

    inspected = SpiceRCNetlist.parse(source, source=input_path, recognize_ties=False,
                                     element_filter=select, preserve_resistors=True)
    candidates = [scope for scope in inspected.scopes if scope.capacitors_read]
    if len(candidates) != 1:
        names = ', '.join(scope.title for scope in inspected.scopes)
        raise ValueError(f'Expected one scope with selected capacitors, found {len(candidates)}. '
                         f'Use --cell NAME or --top-level and --capacitor PATTERN. Available scopes: {names}')
    chosen = candidates[0]
    def same_scope(scope: SpiceScope) -> bool:
        return (None if scope.name is None else scope.name.casefold()) == \
               (None if chosen.name is None else chosen.name.casefold())

    if sum(same_scope(scope) for scope in inspected.scopes) != 1:
        raise ValueError(f'Ambiguous repeated scope name: {chosen.name!r}')
    # Parse the same text again with only this scope selected. The other scopes stay
    # verbatim, including numeric capacitors with the same names as selected ones.
    netlist = SpiceRCNetlist.parse(
        source, source=input_path, recognize_ties=False, preserve_resistors=True,
        element_filter=lambda scope, tokens: same_scope(scope) and _element_selected(scope, tokens, options))
    scope = next(scope for scope in netlist.scopes if same_scope(scope))
    network = scope.network
    for name in (*scope.ports, *scope.global_names, *scope.retained_terminals.values()):
        network.protect(network.node(name))
    known = sorted(network.name(node) for node in network.nodes())
    for name in (options.reference, *options.keep_nodes):
        node = network.find_node(name)
        if node is None:
            if name.casefold() in GROUND_NODE_NAMES:
                node = network.node(name)
            else:
                raise ValueError(f'Unknown reference/kept node {name!r}. Valid nodes: {", ".join(known)}')
        network.protect(node)
    reference = network.find_node(options.reference)
    nets = _conductor_names(network, options.net_by_node)
    observable = {nets[network.name(node)] for node in network.nodes() if network.is_protected(node)}
    floating = set(nets.values()) - observable
    floating_nodes = sorted(name for name, net in nets.items() if net in floating)
    caps = {(network.name(a), network.name(b)): branch.capacitance for a, b, branch in network.edges()
            if branch.capacitance}
    resistive_nodes = {network.name(node) for a, b, branch in network.edges() if branch.conductance for node in (a, b)}
    grounded = ground_capacitances(caps, network.name(reference), net_by_node=nets,
                                  floating_net_names=floating, resistive_nodes=resistive_nodes,
                                  reference_net_names=(nets[network.name(reference)],))
    rewritten = RCNetwork()
    for (a, b), value in grounded.items():
        rewritten.add(rewritten.node(a), rewritten.node(b), capacitance=value)
    scope.network = rewritten
    scope.capacitor_prefix = 'Cgrnd_'
    scope.comment_lines.append('* netlist ground: exact floating elimination, then full inter-net loads to '
                               + network.name(reference))
    directory = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(directory, exist_ok=True)
    written_path = netlist.write(output_path)
    return GroundedNetlist(written_path, scope.title, scope.capacitors_read, len(grounded), floating_nodes)
