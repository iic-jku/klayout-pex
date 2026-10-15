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

"""Reducing SPICE netlists: the files written, the nodes kept, the response at the ports"""

from __future__ import annotations

import math
import os
import textwrap
from typing import *

import allure
import numpy as np
import pytest

from klayout_pex.netlist.netlist_reduction import NetworkSize, UnknownNodesError, reduce_spice_netlist
from klayout_pex.netlist.rc_reduction import ReductionOptions, ReductionStatistics
from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist, SpiceScope
from tests.common.rc_networks import (
    LINE_NETLIST,
    port_admittance,
    random_extracted_network,
    spice_subcircuit,
    write,
)

parent_suite = "Unit Tests"
tags = ("Netlist", "Reduction")


def scope_named(path: str, name: str) -> SpiceScope:
    return next(s for s in SpiceRCNetlist.read(path).scopes if s.name == name)


def node_names(scope: SpiceScope) -> List[str]:
    return sorted(scope.network.name(n) for n in scope.network.nodes() if scope.network.degree(n) > 0)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_reduces_writes_and_returns_the_path(tmp_path):
    input_path = write(str(tmp_path), 'line.spice', LINE_NETLIST)
    output_path = str(tmp_path / 'line_reduced.spice')

    reduction = reduce_spice_netlist(input_path, output_path, ReductionOptions(ticer_tau=1e-12))

    assert reduction.output_path == output_path
    assert [s.scope for s in reduction.scopes] == ['.SUBCKT line']
    scope = reduction.scopes[0]
    assert (scope.resistors_read, scope.capacitors_read) == (3, 4)
    assert scope.before == NetworkSize(resistors=3, capacitors=4, nodes=6)
    # NOTE: τ(m1) = τ(m2) = 1 fF / 20 mS = 50 fs, the plate becomes 1.2 fF between A and B
    assert scope.after == NetworkSize(resistors=1, capacitors=3, nodes=3)
    assert scope.statistics == ReductionStatistics(quick_nodes=2, capacitor_only_nodes=1)
    with open(output_path) as f:
        text = f.read()
    assert textwrap.dedent("""\
        .SUBCKT line A B gnd!
        Xdev B gnd! dev
        * netlist reduce (TICER tau=1ps max degree 5, floating max degree 64): 3 R, 4 C, 6 nodes -> 1 R, 3 C, 3 nodes
        Cred_1 A B 1.2f
        Cred_2 A gnd! 1f
        Cred_3 B gnd! 1f
        Rred_1 A B 300
        .ENDS line
        """) == text


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_keeps_the_nodes_asked_for(tmp_path):
    input_path = write(str(tmp_path), 'line.spice', LINE_NETLIST)
    output_path = str(tmp_path / 'line_reduced.spice')
    reduce_spice_netlist(input_path, output_path, ReductionOptions(ticer_tau=1e-12), keep=['M1', 'plate'])
    assert node_names(scope_named(output_path, 'line')) == ['A', 'B', 'gnd!', 'm1', 'plate']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_nodes_to_keep_must_exist(tmp_path):
    input_path = write(str(tmp_path), 'line.spice', LINE_NETLIST)
    output_path = str(tmp_path / 'out' / 'line_reduced.spice')
    with pytest.raises(UnknownNodesError,
                       match=r"No RC network has the node\(s\) to keep m3, x; "
                             r"the nodes are: A, B, gnd!, m1, m2, plate"):
        reduce_spice_netlist(input_path, output_path, ReductionOptions(), keep=['m1', 'm3', 'x'])
    assert not os.path.exists(tmp_path / 'out')


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_every_subcircuit_is_reduced_on_its_own(tmp_path):
    text = LINE_NETLIST + LINE_NETLIST.replace('line', 'line2').replace('A B', 'A m2 B')
    input_path = write(str(tmp_path), 'lines.spice', text)
    output_path = str(tmp_path / 'lines_reduced.spice')
    reduction = reduce_spice_netlist(input_path, output_path, ReductionOptions(ticer_tau=1e-12))
    assert [s.scope for s in reduction.scopes] == ['.SUBCKT line', '.SUBCKT line2']
    assert node_names(scope_named(output_path, 'line')) == ['A', 'B', 'gnd!']
    assert node_names(scope_named(output_path, 'line2')) == ['A', 'B', 'gnd!', 'm2']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('seed', range(4))
def test_written_netlist_has_the_response_of_the_reduced_network(tmp_path, seed: int):
    # NOTE: the values are written with 6 (C) and 12 (R) significant digits, as KPEX writes them
    network = random_extracted_network(seed)
    ports = sorted(network.name(n) for n in network.nodes() if network.is_protected(n))
    input_path = write(str(tmp_path), 'random.spice', spice_subcircuit(network, 'random', ports))
    output_path = str(tmp_path / 'random_reduced.spice')
    tau = 1e-11
    reduce_spice_netlist(input_path, output_path, ReductionOptions(ticer_tau=tau))
    reduced = scope_named(output_path, 'random').network
    for frequency in (1e6, 1e8, 1e10):
        y = port_admittance(network, ports, frequency)
        y_reduced = port_admittance(reduced, ports, frequency)
        error = np.linalg.norm(y_reduced - y) / np.linalg.norm(y)
        assert error <= 2 * math.pi * frequency * tau, frequency
