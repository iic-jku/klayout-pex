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
The resistors and capacitors of a SPICE netlist as RC networks, one per scope, to be reduced and written back.

Reading:
    - a scope is a .SUBCKT … .ENDS definition, or the top level outside of them
    - the network of a scope has its *plain* R and C elements: exactly two nodes and a number as value
      (e.g. 'Rext_1 A B 426.67', 'Cext_1 A B 223.458a'), resistances > 0, capacitances ≥ 0;
      parallel elements add up
    - every other line stays as it is, in its place: devices, subcircuit instances, sources, directives,
      comments, and R/C elements with other values (models, parameters, expressions, R ≤ 0, C < 0)
    - tie elements of a reduction (e.g. 'Rtie_1 plate 0 1e+12') are ties of their node (see RCNetwork.tie),
      no resistors
    - protected nodes (never eliminated): the .SUBCKT ports, the ground nodes '0' and 'gnd',
      the .GLOBAL nodes, and every node named on another line of the scope (device terminals, sources,
      control statements); the caller may protect more

Writing:
    - the RC elements of a scope replace its plain R and C elements, at the place of the first of them:
      the capacitors first, then the resistors, each sorted by node names, the nodes of each element sorted
    - named Cred_<n> and Rred_<n>, skipping the names of the other elements of the scope,
      followed by the ties of the network, named Rtie_<n>, to ground '0'
    - the values are written in the precision KPEX writes them (see NetlistPrinter)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import itertools
import math
import re
from typing import *

from ..util.unit_formatter import format_spice_number, format_spice_resistance, parse_spice_number
from .rc_network import RCNetwork
from .rc_reduction import GROUND_NODE_NAME, TIE_RESISTANCE


GROUND_NODE_NAMES = ('0', 'gnd')
"""Ground in SPICE: '0', and 'gnd', which ngspice reads as '0'"""

REDUCED_CAPACITOR_PREFIX = 'Cred_'
REDUCED_RESISTOR_PREFIX = 'Rred_'
TIE_PREFIX = 'Rtie_'


class NetlistReadError(Exception):
    """A netlist that can't be split into scopes (e.g. .ENDS without .SUBCKT)"""
    pass


@dataclass
class SpiceScope:
    """A .SUBCKT definition (or the top level, with name None) and the RC network of its plain R and C"""

    name: Optional[str]
    ports: List[str]
    network: RCNetwork = field(default_factory=RCNetwork)
    resistors_read: int = 0
    """the plain R elements read (parallel ones count separately)"""
    capacitors_read: int = 0
    """the plain C elements read"""
    other_element_names: Set[str] = field(default_factory=set)
    """the case-folded names of the elements that are no network elements"""
    names_on_other_lines: Set[str] = field(default_factory=set)
    """the words of the scope's other lines, which protect the nodes of these names"""
    comment_lines: List[str] = field(default_factory=list)
    """written above the RC elements, e.g. a summary of the reduction"""

    @property
    def title(self) -> str:
        return f".SUBCKT {self.name}" if self.name is not None else "top level"


class _ElementsPlaceholder:
    """Where the RC elements of a scope are written"""

    def __init__(self, scope: SpiceScope):
        self.scope = scope


_NAME_SEPARATORS = re.compile(r'[\s(),=]+')


class SpiceRCNetlist:
    """
    A SPICE netlist, its plain R and C elements as one RC network per scope (see the module docs)
    """

    def __init__(self,
                 items: List[Union[str, _ElementsPlaceholder]],
                 scopes: List[SpiceScope]):
        self._items = items
        self.scopes = scopes

    # ----------------------------------------------------------------------------------------- reading

    @classmethod
    def read(cls, path: str) -> SpiceRCNetlist:
        """
        :raises OSError: if the file can't be read
        :raises NetlistReadError: if its .SUBCKT and .ENDS don't match
        """
        # NOTE: bytes that are no UTF-8 (e.g. in comments) are written back as they were
        with open(path, encoding='utf-8', errors='surrogateescape') as f:
            return cls.parse(f.read(), source=path)

    @classmethod
    def parse(cls, text: str, source: str = '<text>') -> SpiceRCNetlist:
        """
        :raises NetlistReadError: if the .SUBCKT and .ENDS don't match
        """
        # NOTE: logical lines, a line starting with '+' continues the line before it
        logical_lines: List[Tuple[int, List[str]]] = []  # (line number, physical lines)
        for number, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith('+') and logical_lines:
                logical_lines[-1][1].append(line)
            else:
                logical_lines.append((number, [line]))

        items: List[Union[str, _ElementsPlaceholder]] = []
        scopes: List[SpiceScope] = []
        global_names: Set[str] = set()
        top_level = SpiceScope(name=None, ports=[])
        stack: List[SpiceScope] = [top_level]
        scopes_with_elements: Set[int] = set()  # by id()
        in_control_block = False

        def protect_names_of(line: str):
            stack[-1].names_on_other_lines.update(name for name in _NAME_SEPARATORS.split(line) if name)

        for number, physical_lines in logical_lines:
            verbatim = '\n'.join(physical_lines)
            text_line = ' '.join([physical_lines[0]] + [l.lstrip()[1:] for l in physical_lines[1:]])
            tokens = text_line.split()
            first = tokens[0] if tokens else ''

            if not tokens or first.startswith('*'):
                items.append(verbatim)
                continue

            keyword = first.lower()
            if in_control_block:
                items.append(verbatim)
                protect_names_of(text_line)
                if keyword == '.endc':
                    in_control_block = False
                continue

            if keyword == '.subckt':
                if len(tokens) < 2:
                    raise NetlistReadError(f"{source}:{number}: .SUBCKT without name")
                ports = []
                for token in tokens[2:]:
                    if '=' in token or token.lower() == 'params:':
                        break
                    ports.append(token)
                stack.append(SpiceScope(name=tokens[1], ports=ports))
                items.append(verbatim)
                continue

            if keyword == '.ends':
                if len(stack) < 2:
                    raise NetlistReadError(f"{source}:{number}: .ENDS without .SUBCKT")
                scopes.append(stack.pop())
                items.append(verbatim)
                continue

            if keyword == '.global':
                global_names.update(tokens[1:])
                items.append(verbatim)
                continue

            if keyword == '.control':
                in_control_block = True

            if keyword[0] in 'rc' and len(tokens) == 4:
                value = cls._element_value(tokens[3], resistor=keyword[0] == 'r')
                if value is not None:
                    scope = stack[-1]
                    network = scope.network
                    tied_name = cls._tied_node_name(tokens)
                    if tied_name is not None:
                        network.tie(network.node(tied_name))
                    elif keyword[0] == 'r':
                        network.add(network.node(tokens[1]), network.node(tokens[2]), conductance=1.0 / value)
                        scope.resistors_read += 1
                    else:
                        network.add(network.node(tokens[1]), network.node(tokens[2]), capacitance=value)
                        scope.capacitors_read += 1
                    if id(scope) not in scopes_with_elements:
                        scopes_with_elements.add(id(scope))
                        items.append(_ElementsPlaceholder(scope))
                    continue

            if not keyword.startswith('.'):
                stack[-1].other_element_names.add(first.casefold())
            protect_names_of(text_line)
            items.append(verbatim)

        if len(stack) > 1:
            raise NetlistReadError(f"{source}: .SUBCKT {stack[-1].name} without .ENDS")
        scopes.append(top_level)

        for scope in scopes:
            network = scope.network
            for name in itertools.chain(scope.ports, GROUND_NODE_NAMES, global_names, scope.names_on_other_lines):
                node = network.find_node(name)
                if node is not None:
                    network.protect(node)

        # NOTE: scopes in the order of the file, the top level last
        return cls(items=items, scopes=scopes)

    @staticmethod
    def _tied_node_name(tokens: List[str]) -> Optional[str]:
        """The node of a tie element (named Rtie_<n>, between a node and ground), None for other elements"""
        if not tokens[0].casefold().startswith(TIE_PREFIX.casefold()):
            return None
        grounds = [name.casefold() in GROUND_NODE_NAMES for name in tokens[1:3]]
        if grounds == [False, True]:
            return tokens[1]
        if grounds == [True, False]:
            return tokens[2]
        return None

    @staticmethod
    def _element_value(text: str, resistor: bool) -> Optional[float]:
        """The value of a plain R (> 0) or C (≥ 0) element, None for anything else"""
        try:
            value = parse_spice_number(text)
        except ValueError:
            return None
        if not math.isfinite(value):
            return None
        if resistor:
            return value if value > 0.0 else None
        return value if value >= 0.0 else None

    # ----------------------------------------------------------------------------------------- writing

    @staticmethod
    def element_lines(scope: SpiceScope) -> List[str]:
        """The RC elements of a scope's network, as written (see the module docs)"""
        network = scope.network
        capacitors: List[Tuple[Tuple, str, str, float]] = []
        resistors: List[Tuple[Tuple, str, str, float]] = []
        for node1, node2, branch in network.edges():
            if network.sort_key(node2) < network.sort_key(node1):
                node1, node2 = node2, node1
            key = (network.sort_key(node1), network.sort_key(node2))
            if branch.capacitance != 0.0:
                capacitors.append((key, network.name(node1), network.name(node2), branch.capacitance))
            if branch.conductance != 0.0:
                resistors.append((key, network.name(node1), network.name(node2), branch.conductance))
        capacitors.sort()
        resistors.sort()

        taken = scope.other_element_names

        def names(prefix: str) -> Iterator[str]:
            number = 0
            while True:
                number += 1
                name = f"{prefix}{number}"
                if name.casefold() not in taken:
                    yield name

        lines = list(scope.comment_lines)
        for name, (_, net1, net2, capacitance) in zip(names(REDUCED_CAPACITOR_PREFIX), capacitors):
            lines.append(f"{name} {net1} {net2} {format_spice_number(capacitance)}")
        for name, (_, net1, net2, conductance) in zip(names(REDUCED_RESISTOR_PREFIX), resistors):
            lines.append(f"{name} {net1} {net2} {format_spice_resistance(1.0 / conductance)}")
        tied_nodes = sorted(network.tied_nodes(), key=network.sort_key)
        for name, node in zip(names(TIE_PREFIX), tied_nodes):
            lines.append(f"{name} {network.name(node)} {GROUND_NODE_NAME} {format_spice_resistance(TIE_RESISTANCE)}")
        return lines

    def format(self) -> str:
        lines: List[str] = []
        for item in self._items:
            if isinstance(item, _ElementsPlaceholder):
                lines.extend(self.element_lines(item.scope))
            else:
                lines.append(item)
        return '\n'.join(lines) + '\n'

    def write(self, path: str) -> str:
        """
        :return: the path written
        """
        with open(path, 'w', encoding='utf-8', errors='surrogateescape') as f:
            f.write(self.format())
        return path
