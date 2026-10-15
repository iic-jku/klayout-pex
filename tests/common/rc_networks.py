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
RC networks for the tests of the netlist reduction: builders, and the nodal analysis
to compare a reduced network with its original (the admittance seen at a set of port nodes,
with every other node eliminated exactly).
"""

from __future__ import annotations

from collections import defaultdict
import math
import os
import random
import textwrap
from typing import *

import numpy as np
import pytest

from klayout_pex.netlist.rc_network import RCNetwork
from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist, SpiceScope


def approx(expected: Any, rel: float = 1e-14) -> Any:
    """pytest.approx without its absolute tolerance of 1e-12, which would accept any femtofarad"""
    return pytest.approx(expected, rel=rel, abs=0.0)


# ------------------------------------------------------------------------------------------ builders

# NOTE: an RC line A - m1 - m2 - B (R = 100 Ω each, 1 fF each to ground), a device at B,
#       and a floating plate between A and B
LINE_NETLIST = textwrap.dedent("""\
    .SUBCKT line A B gnd!
    Xdev B gnd! dev
    C1 m1 gnd! 1f
    C2 m2 gnd! 1f
    C3 A plate 2f
    C4 plate B 3f
    R1 A m1 100
    R2 m1 m2 100
    R3 m2 B 100
    .ENDS line
    """)


def write(directory: str, name: str, text: str) -> str:
    """Write a text file, return its path"""
    path = os.path.join(directory, name)
    with open(path, 'w') as f:
        f.write(text)
    return path


# ------------------------------------------------------------------------------------------- queries

def node_names(network: RCNetwork) -> List[str]:
    """The names of the nodes with elements, sorted"""
    return sorted(network.name(n) for n in network.nodes() if network.degree(n) > 0)


def protected_names(network: RCNetwork) -> List[str]:
    """The names of the protected nodes, sorted"""
    return sorted(network.name(n) for n in network.nodes() if network.is_protected(n))


def value_of(network: RCNetwork, name1: str, name2: str) -> Tuple[float, float]:
    """The conductance and capacitance between two nodes, (0, 0) without a branch between them"""
    branch = network.branch(network.find_node(name1), network.find_node(name2))
    return (branch.conductance, branch.capacitance) if branch else (0.0, 0.0)


def scope_named(netlist: SpiceRCNetlist, name: Optional[str]) -> SpiceScope:
    """The scope of the .SUBCKT of this name, the top level for None"""
    return next(s for s in netlist.scopes if s.name == name)


def build_network(branches: Sequence[Tuple[str, str, float, float]],
                  protected: Sequence[str] = ()) -> RCNetwork:
    """A network of (node1, node2, conductance [S], capacitance [F]) branches"""
    network = RCNetwork()
    for name1, name2, conductance, capacitance in branches:
        network.add(network.node(name1), network.node(name2),
                    conductance=conductance, capacitance=capacitance)
    for name in protected:
        network.protect(network.node(name))
    return network


def random_extracted_network(seed: int,
                             nets: int = 4,
                             nodes_per_net: int = 12,
                             plates: int = 3,
                             couplings: int = 40) -> RCNetwork:
    """
    A network like an extracted one: per net a resistor tree (plus a loop) with one or two
    protected ports, capacitors to the protected ground '0' and between the nets,
    and floating plates (capacitor-only nodes) coupling to random nodes.
    Resistances 1 Ω … 1 kΩ, capacitances 0.1 … 50 fF, so that the time constants are 1e-16 … 1e-11 s.
    """
    rng = random.Random(seed)
    network = RCNetwork()
    ground = network.node('0')
    network.protect(ground)
    all_nodes: List[int] = []
    net_of: Dict[int, int] = {}
    for net in range(nets):
        nodes = [network.node(f"n{net}_{i}") for i in range(nodes_per_net)]
        for i in range(1, nodes_per_net):
            network.add(nodes[i], nodes[rng.randrange(i)], conductance=1.0 / rng.uniform(1.0, 1000.0))
        network.add(nodes[-1], nodes[rng.randrange(nodes_per_net - 1)], conductance=1.0 / rng.uniform(1.0, 1000.0))
        for port in rng.sample(nodes, rng.choice((1, 2))):
            network.protect(port)
        for node in nodes:
            if rng.random() < 0.8:
                network.add(node, ground, capacitance=rng.uniform(0.1e-15, 50e-15))
        all_nodes.extend(nodes)
        net_of.update((node, net) for node in nodes)
    for _ in range(couplings):
        node1, node2 = rng.sample(all_nodes, 2)
        if net_of[node1] != net_of[node2]:
            network.add(node1, node2, capacitance=rng.uniform(0.1e-15, 20e-15))
    for p in range(plates):
        plate = network.node(f"plate{p}")
        for node in rng.sample(all_nodes, rng.randint(1, 6)):
            network.add(plate, node, capacitance=rng.uniform(0.1e-15, 20e-15))
    return network


def random_rc_tree(seed: int, nodes: int = 40) -> RCNetwork:
    """
    An RC tree driven at its protected node 'root': resistors 1 … 100 Ω, a capacitor of 1 … 10 fF
    from every other node to the protected ground '0', every other leaf protected (a receiver, the rest are stubs)
    """
    rng = random.Random(seed)
    network = RCNetwork()
    ground = network.node('0')
    root = network.node('root')
    tree = [root]
    for i in range(1, nodes):
        node = network.node(f"t{i}")
        network.add(node, tree[rng.randrange(len(tree))], conductance=1.0 / rng.uniform(1.0, 100.0))
        network.add(node, ground, capacitance=rng.uniform(1e-15, 10e-15))
        tree.append(node)
    leaves = [n for n in tree[1:] if network.resistive_degree(n) == 1]
    for node in [ground, root] + leaves[::2]:
        network.protect(node)
    return network


def spice_subcircuit(network: RCNetwork, name: str, ports: Sequence[str]) -> str:
    """The network as a SPICE subcircuit, its values in full precision"""
    lines = [f".SUBCKT {name} {' '.join(ports)}"]
    for number, (node1, node2, branch) in enumerate(network.edges(), start=1):
        if branch.capacitance:
            lines.append(f"C{number} {network.name(node1)} {network.name(node2)} {branch.capacitance!r}")
        if branch.conductance:
            lines.append(f"R{number} {network.name(node1)} {network.name(node2)} {1.0 / branch.conductance!r}")
    lines.append(f".ENDS {name}")
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------------- nodal analysis


def laplacian_matrices(network: RCNetwork, node_names: Sequence[str]) -> Tuple[np.ndarray, np.ndarray]:
    """
    The indefinite conductance and capacitance matrices (G, C) of a network, rows and columns in the order
    of node_names; names the network does not have get zero rows (e.g. a ground that only one side has)
    """
    index_by_key = {RCNetwork.name_key(name): i for i, name in enumerate(node_names)}
    size = len(node_names)
    g = np.zeros((size, size))
    c = np.zeros((size, size))
    for node1, node2, branch in network.edges():
        i = index_by_key[RCNetwork.name_key(network.name(node1))]
        j = index_by_key[RCNetwork.name_key(network.name(node2))]
        for matrix, value in ((g, branch.conductance), (c, branch.capacitance)):
            matrix[i, i] += value
            matrix[j, j] += value
            matrix[i, j] -= value
            matrix[j, i] -= value
    return g, c


def port_admittance(network: RCNetwork, ports: Sequence[str], frequency: float) -> np.ndarray:
    """
    Y(s) = G + sC at s = 2πjf, with every node but the ports eliminated (Schur complement):
    the currents into the ports for the port voltages, exact at that frequency.
    At DC (frequency 0), the internal nodes need a resistive path to a port.
    """
    port_keys = {RCNetwork.name_key(p) for p in ports}
    internal = [network.name(n) for n in network.nodes()
                if RCNetwork.name_key(network.name(n)) not in port_keys and network.degree(n) > 0]
    names = list(ports) + internal
    g, c = laplacian_matrices(network, names)
    y = g + 2j * math.pi * frequency * c
    p = len(ports)
    y_pp, y_pi, y_ip, y_ii = y[:p, :p], y[:p, p:], y[p:, :p], y[p:, p:]
    if not internal:
        return y_pp
    return y_pp - y_pi @ np.linalg.solve(y_ii, y_ip)


def relative_admittance_error(original: RCNetwork, reduced: RCNetwork,
                              ports: Sequence[str], frequency: float) -> float:
    """‖Y_reduced − Y_original‖ / ‖Y_original‖ at the ports (Frobenius norms)"""
    y_original = port_admittance(original, ports, frequency)
    y_reduced = port_admittance(reduced, ports, frequency)
    return float(np.linalg.norm(y_reduced - y_original) / np.linalg.norm(y_original))


def schur_complement_conductances(network: RCNetwork, kept: Sequence[str]) -> np.ndarray:
    """The DC admittance (conductance matrix) at the kept nodes, every other node eliminated exactly"""
    return port_admittance(network, kept, frequency=0.0).real


def resistive_components(network: RCNetwork) -> Dict[str, int]:
    """Component number by node name key: nodes connected by resistors share their number"""
    component_by_key: Dict[str, int] = {}
    for start in network.nodes():
        start_key = RCNetwork.name_key(network.name(start))
        if start_key in component_by_key:
            continue
        number = len(set(component_by_key.values()))
        stack = [start]
        component_by_key[start_key] = number
        while stack:
            node = stack.pop()
            for neighbour, branch in network.branches(node).items():
                key = RCNetwork.name_key(network.name(neighbour))
                if branch.conductance != 0.0 and key not in component_by_key:
                    component_by_key[key] = number
                    stack.append(neighbour)
    return component_by_key


def capacitance_by_component_pair(network: RCNetwork,
                                  component_by_key: Mapping[str, int]) -> Dict[Tuple[int, int], float]:
    """
    The total capacitance between each pair of components (e.g. nets: the resistive components
    of the original network), capacitances within a component included as (k, k)
    """
    totals: Dict[Tuple[int, int], float] = defaultdict(float)
    for node1, node2, branch in network.edges():
        if branch.capacitance == 0.0:
            continue
        k1 = component_by_key[RCNetwork.name_key(network.name(node1))]
        k2 = component_by_key[RCNetwork.name_key(network.name(node2))]
        totals[(min(k1, k2), max(k1, k2))] += branch.capacitance
    return dict(totals)


def total_capacitance(network: RCNetwork) -> float:
    return sum(branch.capacitance for _, _, branch in network.edges())


def copy_network(network: RCNetwork) -> RCNetwork:
    """A copy with the same node names, branches and protection (removed nodes are left out)"""
    copy = RCNetwork()
    for node in network.nodes():
        copied = copy.node(network.name(node))
        if network.is_protected(node):
            copy.protect(copied)
    for node1, node2, branch in network.edges():
        copy.add(copy.node(network.name(node1)), copy.node(network.name(node2)),
                 conductance=branch.conductance, capacitance=branch.capacitance)
    return copy
