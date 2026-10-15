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

"""``netlist reduce`` on the RC netlists KPEX writes (2.5D, RC mode) for small test patterns"""

from __future__ import annotations

import math
import os
from typing import *

import allure
import numpy as np
import pytest

from klayout_pex.netlist.netlist_reduction import reduce_spice_netlist
from klayout_pex.netlist.rc_network import RCNetwork
from klayout_pex.netlist.rc_reduction import ReductionOptions
from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist
from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.rc_networks import (
    approx,
    capacitance_by_component_pair,
    port_admittance,
    relative_admittance_error,
    resistive_components,
    schur_complement_conductances,
)
from tests.rcx25.rcx25_test_helpers import PDKName, PDKTestConfig, RCX25Extraction

parent_suite = "kpex/netlist reduce"
tags = ("Netlist", "Reduction", "PEX", "2.5D")

extraction = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.RC, blackbox=False)


def extract_and_reduce(gds_name: str, output_dir: str, options: ReductionOptions) \
        -> Tuple[str, str, RCNetwork, RCNetwork]:
    """
    :return: the paths of the KPEX netlist and the reduced one, and their (single) networks
    """
    _, csv_path = extraction.run_rcx25d_single_cell('test_patterns', gds_name)
    spice_path = f"{os.path.splitext(csv_path)[0]}.spice"
    reduced_path = os.path.join(output_dir, os.path.basename(spice_path).replace('.spice', '_reduced.spice'))
    assert reduce_spice_netlist(spice_path, reduced_path, options).output_path == reduced_path

    networks = []
    for path in (spice_path, reduced_path):
        scopes = [s for s in SpiceRCNetlist.read(path).scopes if s.network.nodes()]
        assert len(scopes) == 1
        networks.append(scopes[0].network)
    return spice_path, reduced_path, networks[0], networks[1]


def protected_names(network: RCNetwork) -> List[str]:
    return sorted(network.name(n) for n in network.nodes() if network.is_protected(n))


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_nfet_keeps_ports_and_device_terminals_dc_and_capacitances_between_nets(tmp_path):
    options = ReductionOptions()
    spice_path, reduced_path, original, reduced = extract_and_reduce('nfet_li1.gds.gz', str(tmp_path), options)

    # NOTE: the ports D, G, S, the substrate sky130_gnd, and the device terminals
    ports = protected_names(original)
    assert ports == ['D', 'D.P0.nsdm', 'G', 'G.P0.poly', 'S', 'S.P0.nsdm', 'sky130_gnd']
    assert protected_names(reduced) == ports
    assert reduced.connected_node_count() < original.connected_node_count()
    assert reduced.resistor_count() < original.resistor_count()

    with open(spice_path) as f:
        device_lines = [line for line in f.read().splitlines() if line.startswith(('X', '+'))]
    with open(reduced_path) as f:
        reduced_lines = f.read().splitlines()
    assert device_lines and all(line in reduced_lines for line in device_lines)

    # NOTE: DC is exact (resistances are written with 12 digits)
    np.testing.assert_allclose(schur_complement_conductances(reduced, ports),
                               schur_complement_conductances(original, ports), rtol=1e-9, atol=1e-15)

    # NOTE: no node is capacitor-only, so TICER alone runs, which keeps the capacitance between each pair of nets
    #       (to the 6 digits the capacitances are written with)
    nets = resistive_components(original)
    before = capacitance_by_component_pair(original, nets)
    after = capacitance_by_component_pair(reduced, nets)
    assert set(after) == set(before)
    for pair, capacitance in before.items():
        assert after[pair] == approx(capacitance, rel=1e-5), pair

    for frequency in (1e9, 1e10, 1e11):
        error = relative_admittance_error(original, reduced, ports, frequency)
        assert error <= 2 * math.pi * frequency * options.ticer_tau, frequency


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mom_capacitor_with_floating_plate(tmp_path):
    options = ReductionOptions()
    _, _, original, reduced = extract_and_reduce('cap_vpp_04p4x04p6_l1m1m2_noshield_m2_wire.gds.gz',
                                                 str(tmp_path), options)
    ports = protected_names(original)
    assert ports == ['C0', 'C1', 'SUB']
    capacitor_only = [original.name(n) for n in original.nodes()
                      if original.resistive_degree(n) == 0 and not original.is_protected(n)]
    assert capacitor_only == ['X']
    assert protected_names(reduced) == ports
    assert reduced.find_node('X') is None and reduced.find_node('0') is None  # eliminated, not tied
    assert reduced.connected_node_count() < original.connected_node_count() / 2

    # NOTE: the capacitances between the ports (Im Y / ω where the resistances don't matter yet) are kept,
    #       to the 6 digits the capacitances are written with
    frequency = 1e7
    capacitances = port_admittance(original, ports, frequency).imag
    reduced_capacitances = port_admittance(reduced, ports, frequency).imag
    assert np.linalg.norm(reduced_capacitances - capacitances) <= 1e-5 * np.linalg.norm(capacitances)

    for frequency in (1e9, 1e10, 1e11):
        error = relative_admittance_error(original, reduced, ports, frequency)
        assert error <= 2 * math.pi * frequency * options.ticer_tau, frequency
