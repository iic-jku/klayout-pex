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

"""The passes of the RC network reduction: TICER and the exact removal of capacitor-only nodes (#214)"""

from __future__ import annotations

import math
from typing import *

import allure
import numpy as np
import pytest

from klayout_pex.netlist.rc_network import RCNetwork
from klayout_pex.netlist.rc_reduction import (
    TIE_RESISTANCE,
    ReductionOptions,
    eliminate_capacitor_only_node,
    eliminate_capacitor_only_nodes,
    eliminate_quick_node,
    eliminate_quick_nodes,
    merge_floating_islands,
    reduce_network,
)
from tests.common.rc_networks import (
    approx,
    build_network,
    capacitance_by_component_pair,
    copy_network,
    laplacian_matrices,
    random_extracted_network,
    random_rc_tree,
    relative_admittance_error,
    resistive_components,
    schur_complement_conductances,
    total_capacitance,
)

parent_suite = "Unit Tests"
tags = ("Netlist", "Reduction", "TICER")

SEEDS = range(8)


def protected_names(network: RCNetwork) -> List[str]:
    return [network.name(n) for n in network.nodes() if network.is_protected(n)]


def names(network: RCNetwork) -> List[str]:
    return sorted(network.name(n) for n in network.nodes() if network.degree(n) > 0)


def value_of(network: RCNetwork, name1: str, name2: str) -> Tuple[float, float]:
    branch = network.branch(network.find_node(name1), network.find_node(name2))
    return (branch.conductance, branch.capacitance) if branch else (0.0, 0.0)


# ------------------------------------------------------------------------- Sheehan 2007, Fig. 1 example

# g_d = g_13 = g_23 = 1 S, c_1 = c_2 = 1 F, c_3 = 0.01 F (Sheehan 2007, Sec. III and Fig. 1)
SHEEHAN_2007_EXAMPLE = [
    ('1', '0', 1.0, 1.0),
    ('1', '3', 1.0, 0.0),
    ('3', '2', 1.0, 0.0),
    ('2', '0', 0.0, 1.0),
    ('3', '0', 0.0, 0.01),
]
TAU_3 = 0.01 / 2  # c_3 / (g_13 + g_23)


def transfer_function_21(network: RCNetwork, omega: float) -> complex:
    """V_2 / J_1, the current source j(t) driving node 1 (Sheehan 2007, (11))"""
    names_ = ['0'] + sorted(n for n in names(network) if n != '0')
    g, c = laplacian_matrices(network, names_)
    y = (g + 1j * omega * c)[1:, 1:]  # ground's row and column removed
    return np.linalg.inv(y)[names_.index('2') - 1, names_.index('1') - 1]


def poles(network: RCNetwork) -> np.ndarray:
    names_ = ['0'] + sorted(n for n in names(network) if n != '0')
    g, c = laplacian_matrices(network, names_)
    return np.sort(np.linalg.eigvals(-np.linalg.solve(c[1:, 1:], g[1:, 1:])).real)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_quick_node_rules_on_the_2007_example():
    network = build_network(SHEEHAN_2007_EXAMPLE, protected=['0', '1', '2'])
    assert network.time_constant(network.find_node('3')) == approx(TAU_3, rel=1e-15)

    eliminate_quick_node(network, network.find_node('3'))

    # Fig. 2 without the negative c_12: g_12 = g_13 g_23 / G_3, c_10 = g_13 c_3 / G_3, c_20 = g_23 c_3 / G_3
    assert names(network) == ['0', '1', '2']
    assert value_of(network, '1', '2') == approx((0.5, 0.0), rel=1e-15)
    assert value_of(network, '1', '0') == approx((1.0, 1.005), rel=1e-15)
    assert value_of(network, '2', '0') == approx((0.0, 1.005), rel=1e-15)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_2007_example_keeps_the_dominant_poles_and_the_response_below_1_over_tau():
    original = build_network(SHEEHAN_2007_EXAMPLE, protected=['0', '1', '2'])
    reduced = copy_network(original)
    assert eliminate_quick_nodes(reduced, tau=TAU_3, max_degree=2) == 1

    # (13): poles -0.2916, -1.7059, -201.0; (14), recomputed: -0.29144, -1.69861 (the paper prints 0.2984)
    original_poles = poles(original)
    reduced_poles = poles(reduced)
    assert original_poles == pytest.approx([-201.0025, -1.705853, -0.291647], abs=1e-6)
    assert reduced_poles == pytest.approx([-1.698614, -0.291436], abs=1e-6)
    # NOTE: the error of the quasi-dc approximation is of the order |s τ_3| (Sheehan 2007, Theorem 1),
    #       evaluated at the pole itself
    for p, p_reduced in zip(original_poles[1:], reduced_poles):
        assert abs(p_reduced - p) <= abs(p) * TAU_3 * abs(p)

    # the response, from the DC gain (exact) up to ω τ_3 = 0.5: relative error below ω τ_3
    assert transfer_function_21(reduced, 0.0) == approx(transfer_function_21(original, 0.0), rel=1e-15)
    for omega in np.logspace(-2, 2, 41):
        h = transfer_function_21(original, omega)
        h_reduced = transfer_function_21(reduced, omega)
        assert abs(h_reduced - h) / abs(h) <= omega * TAU_3


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_ticer_keeps_the_2007_example_node_above_the_threshold():
    network = build_network(SHEEHAN_2007_EXAMPLE, protected=['0', '1', '2'])
    assert eliminate_quick_nodes(network, tau=TAU_3 * 0.999, max_degree=5) == 0
    assert names(network) == ['0', '1', '2', '3']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('order', ['ground first', 'ground last'])
def test_quick_node_moves_capacitors_for_both_orders_of_neighbours(order: str):
    # NOTE: Fig. 5 of Sheehan 2007 has 'j > i' on line 6, which drops the capacitor g_iN c_jN / G_N
    #       when the capacitor's node comes first (j < i), e.g. a ground with the lowest index
    branches = [('N', '0', 0.0, 3e-15), ('N', 'a', 1e-3, 0.0), ('N', 'b', 3e-3, 0.0)]
    if order == 'ground last':
        branches = branches[1:] + branches[:1]
    network = build_network(branches, protected=['0', 'a', 'b'])
    eliminate_quick_node(network, network.find_node('N'))
    assert value_of(network, 'a', '0') == approx((0.0, 0.75e-15), rel=1e-14)
    assert value_of(network, 'b', '0') == approx((0.0, 2.25e-15), rel=1e-14)
    assert value_of(network, 'a', 'b') == approx((0.75e-3, 0.0), rel=1e-14)


# ---------------------------------------------------------------------------------------- invariants

def ticer_kept_nodes_after(network: RCNetwork, tau: float = 1e-12, max_degree: int = 5) -> RCNetwork:
    reduced = copy_network(network)
    eliminated = eliminate_quick_nodes(reduced, tau=tau, max_degree=max_degree)
    assert eliminated > 0
    return reduced


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('seed', SEEDS)
def test_ticer_is_dc_exact_at_every_kept_node(seed: int):
    original = random_extracted_network(seed, plates=0)
    reduced = ticer_kept_nodes_after(original)
    kept = names(reduced)
    # NOTE: the conductance rule is the Schur complement of G, so the reduced network's conductances are
    #       the original's DC behaviour at all kept nodes, not only at the protected ones
    g_reduced, _ = laplacian_matrices(reduced, kept)
    np.testing.assert_allclose(g_reduced, schur_complement_conductances(original, kept),
                               rtol=1e-9, atol=1e-12 * np.abs(g_reduced).max())


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('seed', SEEDS)
def test_ticer_conserves_the_capacitance_between_each_pair_of_nets(seed: int):
    original = random_extracted_network(seed)
    reduced = ticer_kept_nodes_after(original)
    nets = resistive_components(original)
    before = capacitance_by_component_pair(original, nets)
    after = capacitance_by_component_pair(reduced, nets)
    assert set(after) == set(before)
    for pair, capacitance in before.items():
        assert after[pair] == approx(capacitance, rel=1e-12), pair
    assert total_capacitance(reduced) == approx(total_capacitance(original), rel=1e-12)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_ticer_loses_only_the_capacitance_parallel_to_a_resistor():
    # NOTE: a capacitor in parallel to a resistor to the eliminated node is shorted where the node is quick,
    #       its part g_iN c_iN / G_N goes, the rest (to the other neighbours) stays
    network = build_network([('N', 'a', 2e-3, 4e-15), ('N', 'b', 6e-3, 0.0), ('N', '0', 0.0, 1e-15)],
                            protected=['a', 'b', '0'])
    before = total_capacitance(network)
    eliminate_quick_node(network, network.find_node('N'))
    assert total_capacitance(network) == approx(before - 2e-3 * 4e-15 / 8e-3, rel=1e-14)
    assert value_of(network, 'a', 'b') == approx((2e-3 * 6e-3 / 8e-3, 4e-15 * 6e-3 / 8e-3), rel=1e-14)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('seed', SEEDS)
def test_reduction_error_at_the_ports_is_below_omega_tau(seed: int):
    original = random_extracted_network(seed)
    tau = 1e-11  # NOTE: about half of the nodes are quick then
    reduced = copy_network(original)
    statistics = reduce_network(reduced, ReductionOptions(ticer_tau=tau))
    assert statistics.quick_nodes >= 15
    ports = protected_names(reduced)
    for frequency in (1e7, 1e8, 1e9, 1e10):
        # NOTE: per eliminated node, the error is of the order ε = 2π f τ_N ≤ 2π f τ (Sheehan 2007, Theorem 1);
        #       the errors of nodes that are no neighbours do not add up (Theorem 5), and here the error
        #       of the whole reduction stays below the bound for one node (at most 0.7 ε for these seeds)
        error = relative_admittance_error(original, reduced, ports, frequency)
        assert error <= 2 * math.pi * frequency * tau, frequency


def elmore_delays(network: RCNetwork, nodes: Sequence[str]) -> np.ndarray:
    """
    The Elmore delays from 'root' to the nodes, ground '0': with the root at 1 V, the deviations e = 1 - v
    of the other nodes follow C de/dt = -G e, so the first moments ∫ e dt are G⁻¹ C 1
    """
    internal = [network.name(n) for n in network.nodes()
                if network.degree(n) > 0 and network.name(n) not in ('0', 'root', *nodes)]
    g, c = laplacian_matrices(network, ['0', 'root', *nodes, *internal])
    g, c = g[2:, 2:], c[2:, 2:]
    return np.linalg.solve(g, c @ np.ones(len(g)))[:len(nodes)]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('seed', SEEDS)
def test_ticer_keeps_elmore_delays_of_rc_trees(seed: int):
    # NOTE: Sheehan 2007, Sec. V, for internal nodes that are no forks; it holds for forks and stubs as well:
    #       without resistive path to ground, all nodes end at the root's voltage (the vector 1), and
    #       C_TICER 1 = C_dc_proj 1, as the dropped negative capacitors have ΔC 1 = 0 (Sec. IV-F, (42))
    original = random_rc_tree(seed)
    reduced = copy_network(original)
    assert eliminate_quick_nodes(reduced, tau=1.0, max_degree=5) >= 20
    kept = [n for n in names(reduced) if n not in ('0', 'root')]
    np.testing.assert_allclose(elmore_delays(reduced, kept), elmore_delays(original, kept), rtol=1e-12)


# ------------------------------------------------------------------------------- capacitor-only nodes

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_plate_between_two_nets_gives_exactly_the_series_capacitance():
    network = build_network([('A', 'plate', 0.0, 2e-15), ('plate', 'B', 0.0, 3e-15)], protected=['A', 'B'])
    statistics = reduce_network(network, ReductionOptions())
    assert statistics.capacitor_only_nodes == 1 and statistics.tied_nodes == 0
    assert names(network) == ['A', 'B']
    assert value_of(network, 'A', 'B') == (0.0, 2e-15 * 3e-15 / 5e-15)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('seed', SEEDS)
def test_capacitor_only_elimination_is_exact_at_every_frequency(seed: int):
    original = random_extracted_network(seed, plates=6)
    reduced = copy_network(original)
    assert eliminate_capacitor_only_nodes(reduced, max_degree=64) == 6
    ports = names(reduced)
    for frequency in (1e3, 1e6, 1e9, 1e12):
        assert relative_admittance_error(original, reduced, ports, frequency) <= 1e-12, frequency


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_capacitor_only_node_with_one_neighbour_disappears():
    network = build_network([('A', 'stub', 0.0, 2e-15), ('A', '0', 1e-3, 0.0)], protected=['A', '0'])
    eliminate_capacitor_only_node(network, network.find_node('stub'))
    assert names(network) == ['0', 'A']
    assert value_of(network, 'A', '0') == (1e-3, 0.0)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_nodes_without_branches_are_no_capacitor_only_nodes():
    network = build_network([('A', 'B', 0.0, 1e-15)], protected=['A'])
    network.node('lonely')  # NOTE: e.g. of a 0 F capacitor
    statistics = reduce_network(network, ReductionOptions())
    assert (statistics.capacitor_only_nodes, statistics.tied_nodes) == (1, 0)
    assert network.find_node('lonely') is not None and network.connected_node_count() == 0


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_capacitor_only_nodes_above_the_degree_limit_are_tied_to_ground():
    branches = [('plate', f"n{i}", 0.0, (i + 1) * 1e-15) for i in range(4)]
    network = build_network(branches, protected=[f"n{i}" for i in range(4)])
    statistics = reduce_network(network, ReductionOptions(ticer=False, floating_max_degree=3))
    assert (statistics.capacitor_only_nodes, statistics.tied_nodes) == (0, 1)
    # NOTE: a mark, no resistor
    assert [network.name(n) for n in network.tied_nodes()] == ['plate']
    assert network.resistor_count() == 0 and network.find_node('0') is None

    network = build_network(branches, protected=[f"n{i}" for i in range(4)])
    statistics = reduce_network(network, ReductionOptions(ticer=False, floating_max_degree=4))
    assert (statistics.capacitor_only_nodes, statistics.tied_nodes) == (1, 0)
    assert network.find_node('plate') is None and network.find_node('0') is None
    assert network.capacitor_count() == 6


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_floating_passes_drop_the_ties_and_tie_again():
    # NOTE: e.g. a netlist reduced before, with a lower degree limit: 'plate' can be eliminated now, 'big' not,
    #       and 'wired' has a resistor, so it needs no tie
    nets = [f"n{i}" for i in range(4)]
    network = build_network([('plate', 'A', 0.0, 1e-15), ('plate', 'B', 0.0, 2e-15), ('wired', 'A', 1.0, 0.0)]
                            + [('big', net, 0.0, 1e-15) for net in nets], protected=['A', 'B', *nets])
    for name in ('plate', 'big', 'wired'):
        network.tie(network.find_node(name))
    statistics = reduce_network(network, ReductionOptions(ticer=False, floating_max_degree=3))
    assert (statistics.capacitor_only_nodes, statistics.tied_nodes) == (1, 1)
    assert network.find_node('plate') is None and network.find_node('wired') is not None
    assert [network.name(n) for n in network.tied_nodes()] == ['big']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_ties_are_no_resistors_for_ticer_and_stay_without_the_floating_passes():
    # NOTE: as a resistor of 1 TΩ, the tie would make 'plate' a leaf with τ = 1 ms, which TICER eliminates at 1 s
    network = build_network([('plate', 'A', 0.0, 1e-15)], protected=['A'])
    plate = network.find_node('plate')
    network.tie(plate)
    statistics = reduce_network(network, ReductionOptions(ticer_tau=1.0, floating=False))
    assert statistics.quick_nodes == 0
    assert network.is_alive(plate) and network.is_tied(plate)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_floating_islands_are_merged_then_eliminated():
    # NOTE: a floating wire (resistors, no protected node) between two nets: merged into one node,
    #       whose capacitors to A and B add up, then exactly the series capacitance of the sums
    network = build_network([('w1', 'w2', 1e-2, 0.0), ('w2', 'w3', 1e-2, 0.0),
                             ('A', 'w1', 0.0, 1e-15), ('A', 'w2', 0.0, 1e-15), ('B', 'w3', 0.0, 2e-15),
                             ('A', 'B', 1e-3, 0.0)],
                            protected=['A', 'B'])
    assert merge_floating_islands(copy_network(network)) == (1, 2)
    statistics = reduce_network(network, ReductionOptions())
    assert (statistics.floating_islands, statistics.floating_island_nodes) == (1, 2)
    assert statistics.capacitor_only_nodes == 1
    assert names(network) == ['A', 'B']
    assert value_of(network, 'A', 'B') == approx((1e-3, 2e-15 * 2e-15 / 4e-15), rel=1e-15)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_island_with_a_protected_node_is_not_merged():
    network = build_network([('w1', 'w2', 1e-2, 0.0), ('w2', 'A', 0.0, 1e-15)], protected=['w1'])
    assert merge_floating_islands(network) == (0, 0)
    assert names(network) == ['A', 'w1', 'w2']


# --------------------------------------------------------------------------------- protected nodes

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('seed', SEEDS)
def test_protected_nodes_are_never_eliminated(seed: int):
    network = random_extracted_network(seed, plates=6)
    protected = sorted(protected_names(network))
    # NOTE: every time constant is far below 1 s, without degree limits everything else goes
    reduce_network(network, ReductionOptions(ticer_tau=1.0, ticer_max_degree=1000, floating_max_degree=1000))
    assert sorted(protected_names(network)) == protected
    assert names(network) == sorted(protected)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_ground_tied_to_two_islands_is_kept():
    # NOTE: #214: once ground had been tied to two floating islands, it looked like an ordinary node
    #       with two neighbours, TICER eliminated it, and the islands floated
    network = build_network([('0', 'i1', 1.0 / TIE_RESISTANCE, 0.0), ('i1', 'A', 0.0, 1e-15),
                             ('0', 'i2', 1.0 / TIE_RESISTANCE, 0.0), ('i2', 'B', 0.0, 1e-15)],
                            protected=['0', 'A', 'B'])
    reduce_network(network, ReductionOptions(ticer_tau=1.0, ticer_max_degree=1000))
    assert network.find_node('0') is not None


# ------------------------------------------------------------------------------------- degree limits

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('max_degree, eliminated', [(5, 0), (6, 1)])
def test_ticer_keeps_nodes_with_more_resistors_than_the_limit(max_degree: int, eliminated: int):
    network = build_network([('N', f"p{i}", 1e-3, 1e-18) for i in range(6)], protected=[f"p{i}" for i in range(6)])
    assert eliminate_quick_nodes(network, tau=1e-12, max_degree=max_degree) == eliminated


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_ticer_limit_counts_resistors_not_capacitors():
    branches = [('N', 'a', 1e-3, 0.0), ('N', 'b', 1e-3, 0.0)] + [('N', f"c{i}", 0.0, 1e-18) for i in range(10)]
    network = build_network(branches, protected=['a', 'b'] + [f"c{i}" for i in range(10)])
    assert eliminate_quick_nodes(network, tau=1e-12, max_degree=2) == 1


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_ticer_defers_leaves_to_the_end():
    # NOTE: J (protected) -1Ω- a -1Ω- b (leaf), 1 F at a and at b, threshold 1.2 s:
    #       a (τ = 0.5 s) goes first, which makes b a leaf with 2 Ω and 1.5 F (τ = 3 s), which stays;
    #       eating the leaf first (τ = 1 s) would have removed the end of the stub instead
    network = build_network([('J', 'a', 1.0, 0.0), ('a', 'b', 1.0, 0.0), ('a', '0', 0.0, 1.0), ('b', '0', 0.0, 1.0)],
                            protected=['J', '0'])
    assert eliminate_quick_nodes(network, tau=1.2, max_degree=5) == 1
    assert names(network) == ['0', 'J', 'b']
    assert value_of(network, 'J', 'b') == approx((0.5, 0.0), rel=1e-15)
    assert value_of(network, 'b', '0') == approx((0.0, 1.5), rel=1e-15)


# -------------------------------------------------------------------------------------- determinism

def edge_list(network: RCNetwork) -> List[Tuple[str, str, float, float]]:
    return sorted((*sorted((network.name(a), network.name(b))), branch.conductance, branch.capacitance)
                  for a, b, branch in network.edges())


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('seed', SEEDS)
def test_reduction_is_deterministic(seed: int):
    results = []
    for _ in range(2):
        network = random_extracted_network(seed, plates=6)
        reduce_network(network, ReductionOptions(ticer_tau=1e-12, floating_max_degree=3))
        results.append(edge_list(network))
    assert results[0] == results[1]


# ------------------------------------------------------------------------------------------- options

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('arguments, message', [
    ({'ticer_tau': 0.0}, 'ticer_tau must be a finite number of seconds > 0, got 0.0'),
    ({'ticer_tau': -1e-12}, 'ticer_tau must be'),
    ({'ticer_tau': math.inf}, 'ticer_tau must be'),
    ({'ticer_tau': '1e-13'}, "ticer_tau must be a finite number of seconds > 0, got '1e-13'"),
    ({'ticer_max_degree': 0}, 'ticer_max_degree must be an integer ≥ 1, got 0'),
    ({'floating_max_degree': 2.5}, 'floating_max_degree must be an integer ≥ 1, got 2.5'),
    ({'ticer': 'false'}, "ticer must be True or False, got 'false'"),
    ({'ticer': False, 'floating': False}, 'ticer and floating are both False'),
])
def test_invalid_options_are_rejected(arguments: Dict[str, Any], message: str):
    with pytest.raises(ValueError, match=message.replace('(', r'\(').replace('.', r'\.')):
        ReductionOptions(**arguments)
