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

"""Contracts and boundary cases for intentional capacitance approximations."""

import copy
import math
from typing import Dict, Optional

import allure
import pytest

from klayout_pex.rcx25.coupling import CouplingPolicy, CouplingPolicyError, apply_coupling_policy
from klayout_pex.rcx25.extraction_results import DeviceTerminalKey, ExtractionSummary, NetCoupleKey

pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('RCX25', 'Capacitance Modes')]


def pair(a: str, b: str) -> NetCoupleKey:
    return NetCoupleKey(a, b).normed()


def test_three_node_network_grounds_each_inter_net_pair_with_full_value():
    original = ExtractionSummary({pair('A', 'B'): 2, pair('A', 'G'): 1, pair('B', 'G'): 3}, {})
    # With B held at G, A sees 3 fF. With A held at G, B sees 5 fF.
    # Grounding preserves those two driving-point loads, not the transfer term.
    grounded = apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G')
    assert grounded.capacitances == {pair('A', 'G'): 3, pair('B', 'G'): 5}
    assert apply_coupling_policy(original, CouplingPolicy.COUPLED, 'G') is original


def test_floating_node_is_eliminated_before_grounding():
    # A--2fF--floating--2fF--G is a 1 fF series load at A.
    original = ExtractionSummary({pair('A', 'floating'): 2, pair('floating', 'G'): 2}, {})
    grounded = apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G', floating_net_names={'floating'})
    assert grounded.capacitances == {pair('A', 'G'): 1}


def test_reference_alias_and_distributed_reference_nodes_are_kept():
    original = ExtractionSummary(
        {pair('A', 'VSUBS'): 1, pair('A', 'sub!'): 2, pair('A', 'sub!.$1'): 4, pair('A', 'B'): 8},
        {pair('sub!', 'sub!.$1'): 10}, net_by_node={'sub!.$1': 'sub!'})
    obtained = apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'VSUBS', substrate_net_name='sub!')
    expected = {pair('A', 'VSUBS'): 9, pair('A', 'sub!'): 2, pair('A', 'sub!.$1'): 4,
                pair('B', 'VSUBS'): 8}
    assert obtained.capacitances == expected
    assert obtained.resistances == original.resistances


def test_internal_nodes_keep_their_names_and_resistive_connections():
    original = ExtractionSummary(
        {pair('A.$1', 'B.$1'): 2}, {pair('A', 'A.$1'): 10, pair('B', 'B.$1'): 20},
        device_terminal_nodes={DeviceTerminalKey(1, 0): 'A.$1'}, label_ports={'A': ['A', 'P']},
        exclusion_ports={'A': ['P']}, net_by_node={'A.$1': 'A', 'B.$1': 'B'})
    before = copy.deepcopy(original)
    grounded = apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G')
    assert original == before
    assert grounded.capacitances == {pair('A.$1', 'G'): 2, pair('B.$1', 'G'): 2}
    for name in ('resistances', 'device_terminal_nodes', 'label_ports', 'exclusion_ports', 'net_by_node'):
        assert getattr(grounded, name) == getattr(before, name)


@pytest.mark.parametrize('capacitances', [{}, {pair('A', 'A'): 2}, {pair('A', 'B'): 0}])
def test_empty_self_and_zero_capacitances_create_no_load(capacitances: Dict[NetCoupleKey, float]):
    assert apply_coupling_policy(ExtractionSummary(capacitances, {}), CouplingPolicy.GROUNDED, 'G').capacitances == {}


@pytest.mark.parametrize('value', [math.nextafter(0, 1), 1e-100, 2, 1e100])
def test_grounding_does_not_impose_a_capacitance_floor(value: float):
    grounded = apply_coupling_policy(ExtractionSummary({pair('A', 'B'): value}, {}),
                                     CouplingPolicy.GROUNDED, 'G')
    assert grounded.capacitances == {pair('A', 'G'): value, pair('B', 'G'): value}


@pytest.mark.parametrize('value', [math.nextafter(0, -1), -1, math.inf, -math.inf, math.nan])
def test_invalid_capacitance_is_rejected_before_approximating(value: float):
    original = ExtractionSummary({pair('A', 'B'): value}, {})
    with pytest.raises(CouplingPolicyError, match='finite and non-negative'):
        apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G')


@pytest.mark.parametrize('reference', ['', ' ', None])
def test_reference_must_be_named(reference: Optional[str]):
    with pytest.raises(CouplingPolicyError, match='non-empty name'):
        apply_coupling_policy(ExtractionSummary({}, {}), CouplingPolicy.GROUNDED, reference)


def test_grounded_sum_cannot_silently_overflow():
    original = ExtractionSummary({pair('A', 'B'): 1e308, pair('A', 'C'): 1e308}, {})
    with pytest.raises(CouplingPolicyError, match='finite numeric range'):
        apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G')


def test_floating_chain_and_branch_are_reduced_to_observable_loads():
    chain = ExtractionSummary({pair('A', 'F1'): 2, pair('F1', 'F2'): 3, pair('F2', 'G'): 6}, {})
    assert apply_coupling_policy(chain, CouplingPolicy.GROUNDED, 'G', floating_net_names={'F1', 'F2'}) \
        .capacitances == {pair('A', 'G'): pytest.approx(1, rel=1e-15, abs=0)}
    star = ExtractionSummary({pair('A', 'F'): 2, pair('B', 'F'): 3, pair('F', 'G'): 5}, {})
    assert apply_coupling_policy(star, CouplingPolicy.GROUNDED, 'G', floating_net_names={'F'}) \
        .capacitances == {pair('A', 'G'): pytest.approx(1.6), pair('B', 'G'): pytest.approx(2.1)}


@pytest.mark.parametrize('one_boundary', [False, True])
def test_floating_component_with_at_most_one_boundary_adds_no_load(one_boundary: bool):
    caps = {pair('F1', 'F2'): 3}
    if one_boundary:
        caps[pair('A', 'F1')] = 2
    original = ExtractionSummary(caps, {})
    assert apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G', floating_net_names={'F1', 'F2'}) \
        .capacitances == {}


def test_floating_elimination_preserves_all_retained_resistors_and_internal_capacitance():
    original = ExtractionSummary(
        {pair('A1', 'F'): 2, pair('A2', 'F'): 2, pair('A2', 'G'): 3},
        {pair('A', 'A1'): 100, pair('A1', 'A2'): 200},
        net_by_node={'A1': 'A', 'A2': 'A'})
    before = copy.deepcopy(original)
    grounded = apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G', floating_net_names={'F'})
    assert grounded.capacitances == {pair('A1', 'A2'): 1, pair('A2', 'G'): 3}
    assert grounded.resistances == before.resistances
    assert grounded.net_by_node == before.net_by_node
    assert original == before


def test_floating_plate_next_to_driven_rc_node_gives_series_load():
    original = ExtractionSummary({pair('A1', 'F'): 2, pair('F', 'G'): 2},
                                 {pair('A', 'A1'): 100}, net_by_node={'A1': 'A'})
    grounded = apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G', floating_net_names={'F'})
    assert grounded.capacitances == {pair('A1', 'G'): 1}
    assert grounded.resistances == original.resistances


@pytest.mark.parametrize('resistance', [0, 1e-12, 100, 1e100])
def test_floating_resistive_net_requires_coupled_output(resistance: float):
    original = ExtractionSummary({pair('A', 'F1'): 2, pair('F2', 'G'): 2},
                                 {pair('F1', 'F2'): resistance}, net_by_node={'F1': 'F', 'F2': 'F'})
    with pytest.raises(CouplingPolicyError, match='floating resistive nets.*F'):
        apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G', floating_net_names={'F'})


@pytest.mark.parametrize('degree', [63, 64])
def test_exact_floating_elimination_through_degree_limit(degree: int):
    original = ExtractionSummary({pair(f'A{i}', 'F'): 1 for i in range(degree)}, {})
    grounded = apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G', floating_net_names={'F'})
    assert len(grounded.capacitances) == degree
    assert all(value == pytest.approx((degree - 1) / degree, rel=1e-14, abs=0)
               for value in grounded.capacitances.values())


def test_exact_floating_elimination_above_degree_limit_fails_without_grounding_plate():
    original = ExtractionSummary({pair(f'A{i}', 'F'): 1 for i in range(65)}, {})
    with pytest.raises(CouplingPolicyError, match='64-neighbor limit.*F'):
        apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G', floating_net_names={'F'})


def test_dense_unobservable_component_does_not_hit_degree_limit():
    names = [f'F{i}' for i in range(66)]
    original = ExtractionSummary({pair(a, b): 1 for i, a in enumerate(names) for b in names[i + 1:]}, {})
    assert apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G', floating_net_names=names).capacitances == {}


def test_capacitance_graph_preserves_case_sensitive_extraction_names():
    original = ExtractionSummary({pair('A', 'F'): 2, pair('a', 'F'): 4, pair('F', 'G'): 6}, {})
    grounded = apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G', floating_net_names={'F'})
    assert grounded.capacitances == {pair('A', 'G'): pytest.approx(5 / 3), pair('a', 'G'): pytest.approx(8 / 3)}


@pytest.mark.parametrize('field', ['label_ports', 'exclusion_ports'])
def test_declared_ports_override_float_classification(field: str):
    original = ExtractionSummary({pair('A', 'P'): 2, pair('P', 'G'): 3}, {},
                                 net_by_node={'P': 'F'}, **{field: {'F': ['P']}})
    grounded = apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G', floating_net_names={'F'})
    assert grounded.capacitances == {pair('A', 'G'): 2, pair('P', 'G'): 5}


def test_internal_reference_alias_cannot_be_eliminated_as_float():
    original = ExtractionSummary({pair('A', 'sub!.$1'): 2}, {}, net_by_node={'sub!.$1': 'sub!'})
    grounded = apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'VSUBS',
                                     substrate_net_name='sub!', floating_net_names={'sub!'})
    assert grounded.capacitances == original.capacitances


def test_node_named_zero_is_not_assumed_to_be_extraction_reference():
    original = ExtractionSummary({pair('A', '0'): 2, pair('0', 'G'): 2}, {})
    assert apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G', floating_net_names={'0'}) \
        .capacitances == {pair('A', 'G'): 1}



def test_dense_one_boundary_float_does_not_traverse_a_driven_capacitor():
    names = [f'F{i}' for i in range(66)]
    caps = {pair(a, b): 1 for i, a in enumerate(names) for b in names[i + 1:]}
    caps.update({pair('A', 'F0'): 2, pair('A', 'B'): 3})
    grounded = apply_coupling_policy(ExtractionSummary(caps, {}), CouplingPolicy.GROUNDED, 'G',
                                     floating_net_names=names)
    assert grounded.capacitances == {pair('A', 'G'): 3, pair('B', 'G'): 3}
