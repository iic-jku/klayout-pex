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
Reduction of the RC parasitics of a SPICE netlist (``netlist reduce``, #214):
each scope (.SUBCKT and top level) is reduced on its own, see :mod:`.rc_reduction` for the passes
and :mod:`.spice_rc_netlist` for what is read, protected and written.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import *

from .rc_network import RCNetwork
from .rc_reduction import ReductionOptions, ReductionStatistics, reduce_network
from .spice_rc_netlist import SpiceRCNetlist


class UnknownNodesError(Exception):
    """Nodes to keep that are in none of the RC networks"""

    def __init__(self, unknown_names: List[str], known_names: List[str]):
        self.unknown_names = unknown_names
        self.known_names = known_names
        listed = known_names[:20]
        more = f", … ({len(known_names) - len(listed)} more)" if len(known_names) > len(listed) else ''
        super().__init__(f"No RC network has the node(s) to keep {', '.join(unknown_names)}; "
                         f"the nodes are: {', '.join(listed)}{more}")


@dataclass(frozen=True)
class NetworkSize:
    resistors: int
    capacitors: int
    nodes: int
    """nodes with at least one resistor or capacitor"""

    @classmethod
    def of(cls, network: RCNetwork) -> NetworkSize:
        return cls(resistors=network.resistor_count(),
                   capacitors=network.capacitor_count(),
                   nodes=network.connected_node_count())

    def __str__(self) -> str:
        return f"{self.resistors} R, {self.capacitors} C, {self.nodes} nodes"


@dataclass(frozen=True)
class ScopeReduction:
    scope: str
    """'.SUBCKT <name>' or 'top level'"""
    resistors_read: int
    capacitors_read: int
    before: NetworkSize
    """after adding up parallel elements"""
    after: NetworkSize
    statistics: ReductionStatistics


@dataclass(frozen=True)
class NetlistReduction:
    output_path: str
    """the path written"""
    scopes: List[ScopeReduction]
    """the scopes with R or C elements, in the order of the netlist"""


def _describe_options(options: ReductionOptions) -> str:
    passes = []
    if options.ticer:
        passes.append(f"TICER tau={options.ticer_tau * 1e12:g}ps max degree {options.ticer_max_degree}")
    if options.floating:
        passes.append(f"floating max degree {options.floating_max_degree}")
    return ', '.join(passes)


def reduce_spice_netlist(input_path: str,
                         output_path: str,
                         options: ReductionOptions,
                         keep: Sequence[str] = ()) -> NetlistReduction:
    """
    Reduce the RC network of every scope of a SPICE netlist and write the result
    (creating the output's directory if needed).

    :param keep: nodes to keep in addition to the protected ones (case-insensitive),
                 each must be a node of at least one network
    :raises OSError: if the input can't be read or the output can't be written
    :raises NetlistReadError: if the netlist's .SUBCKT and .ENDS don't match
    :raises UnknownNodesError: if a node to keep is in none of the networks (nothing is written then)
    """
    netlist = SpiceRCNetlist.read(input_path)
    scopes = [s for s in netlist.scopes if s.resistors_read or s.capacitors_read]

    unknown = [name for name in keep
               if all(s.network.find_node(name) is None for s in scopes)]
    if unknown:
        known = sorted({s.network.name(n) for s in scopes for n in s.network.nodes()},
                       key=RCNetwork.name_key)
        raise UnknownNodesError(unknown_names=unknown, known_names=known)

    reductions: List[ScopeReduction] = []
    for scope in scopes:
        network = scope.network
        for name in keep:
            node = network.find_node(name)
            if node is not None:
                network.protect(node)
        before = NetworkSize.of(network)
        statistics = reduce_network(network, options)
        after = NetworkSize.of(network)
        scope.comment_lines.append(f"* netlist reduce ({_describe_options(options)}): "
                                   f"{before} -> {after}")
        reductions.append(ScopeReduction(scope=scope.title,
                                         resistors_read=scope.resistors_read,
                                         capacitors_read=scope.capacitors_read,
                                         before=before,
                                         after=after,
                                         statistics=statistics))

    output_directory = os.path.dirname(output_path)
    if output_directory:
        os.makedirs(output_directory, exist_ok=True)
    return NetlistReduction(output_path=netlist.write(output_path), scopes=reductions)
