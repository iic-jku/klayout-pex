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

from __future__ import annotations

import math

import allure
import pytest

from klayout_pex.netlist.rc_network import RCNetwork
from tests.common.rc_networks import approx, build_network

parent_suite = "Unit Tests"
tags = ("Netlist", "Reduction")


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_node_names_are_case_insensitive_and_keep_their_first_spelling():
    network = RCNetwork()
    node = network.node('Out')
    assert network.node('OUT') == node
    assert network.find_node('out') == node
    assert network.name(node) == 'Out'
    assert network.find_node('in') is None


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_parallel_elements_add_up_and_self_loops_are_dropped():
    network = RCNetwork()
    a, b = network.node('a'), network.node('b')
    network.add(a, b, conductance=1e-3)
    network.add(b, a, conductance=2e-3, capacitance=1e-15)
    network.add(a, a, conductance=5.0, capacitance=1e-12)
    branch = network.branch(a, b)
    assert (branch.conductance, branch.capacitance) == approx((3e-3, 1e-15))
    assert network.branch(b, a) is branch
    assert network.degree(a) == 1
    assert (network.resistor_count(), network.capacitor_count()) == (1, 1)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_node_metrics():
    network = build_network([('N', 'a', 1e-3, 1e-15), ('N', 'b', 3e-3, 0.0), ('N', 'c', 0.0, 3e-15)])
    node = network.find_node('N')
    assert network.conductance_sum(node) == approx(4e-3)
    assert network.capacitance_sum(node) == approx(4e-15)
    assert network.time_constant(node) == approx(1e-12)
    assert (network.degree(node), network.resistive_degree(node)) == (3, 2)
    assert network.time_constant(network.find_node('c')) == math.inf


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_remove_node_removes_its_branches():
    network = build_network([('a', 'b', 1.0, 0.0), ('b', 'c', 0.0, 1e-15)])
    b = network.find_node('b')
    network.remove_node(b)
    assert not network.is_alive(b)
    assert network.find_node('b') is None
    assert network.edges() == []
    assert network.connected_node_count() == 0
    with pytest.raises(KeyError, match=r'Node 1 \(b\) was removed'):
        network.branches(b)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_merge_node_shorts_it_into_the_other():
    network = build_network([('a', 'b', 1.0, 1e-15), ('b', 'c', 2.0, 0.0), ('a', 'c', 3.0, 2e-15), ('b', '0', 0.0, 4e-15)])
    network.merge_node(network.find_node('b'), into=network.find_node('a'))
    a, c, ground = network.find_node('a'), network.find_node('c'), network.find_node('0')
    assert network.find_node('b') is None
    assert (network.branch(a, c).conductance, network.branch(a, c).capacitance) == approx((5.0, 2e-15))
    assert network.branch(a, ground).capacitance == approx(4e-15)
    assert network.degree(a) == 2


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_ties_are_marks_of_nodes_and_go_with_them():
    network = build_network([('a', 'b', 0.0, 1e-15)])
    a = network.find_node('a')
    network.tie(a)
    assert network.is_tied(a) and network.tied_nodes() == [a]
    assert network.resistor_count() == 0 and network.degree(a) == 1
    network.untie(a)
    assert network.tied_nodes() == []
    network.tie(a)
    network.remove_node(a)
    assert network.tied_nodes() == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sort_key_orders_by_name_not_by_creation():
    network = RCNetwork()
    nodes = [network.node(name) for name in ('b', 'A', 'a2')]
    assert [network.name(n) for n in sorted(nodes, key=network.sort_key)] == ['A', 'a2', 'b']
