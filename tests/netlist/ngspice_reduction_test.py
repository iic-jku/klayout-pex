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

"""AC analysis of original and reduced netlists in ngspice (skipped without ngspice on the PATH)"""

from __future__ import annotations

import math

import allure
import numpy as np
import pytest

from klayout_pex.netlist.netlist_reduction import reduce_spice_netlist
from klayout_pex.netlist.rc_reduction import ReductionOptions
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.rc_networks import port_admittance, random_extracted_network, spice_subcircuit, write

parent_suite = "kpex/netlist reduce"
tags = ("Netlist", "Reduction", "ngspice")


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@requires_ngspice
@pytest.mark.parametrize('seed', range(3))
def test_reduced_netlist_has_the_ac_response_of_the_original(tmp_path, seed: int):
    network = random_extracted_network(seed, plates=4)
    ports = sorted(network.name(n) for n in network.nodes() if network.is_protected(n) and network.name(n) != '0')
    original_path = write(str(tmp_path), 'random.spice', spice_subcircuit(network, 'random', ports))
    reduced_path = str(tmp_path / 'random_reduced.spice')
    tau = 1e-11
    statistics = reduce_spice_netlist(original_path, reduced_path, ReductionOptions(ticer_tau=tau)).scopes[0].statistics
    assert statistics.quick_nodes >= 15 and statistics.capacitor_only_nodes == 4

    frequencies, y = ngspice_port_admittance(original_path, 'random', ports, (6, 10), str(tmp_path))
    _, y_reduced = ngspice_port_admittance(reduced_path, 'random', ports, (6, 10), str(tmp_path))

    for f, y_f, y_reduced_f in zip(frequencies, y, y_reduced):
        # NOTE: the bench: ngspice agrees with the nodal analysis of the original network,
        #       to the 9 digits ngspice writes
        y_expected = port_admittance(network, ports + ['0'], f)[:-1, :-1]  # ground is the reference
        assert np.linalg.norm(y_f - y_expected) <= 1e-7 * np.linalg.norm(y_expected), f
        # NOTE: the error bound of TICER, see rc_reduction_test.test_reduction_error_at_the_ports_is_below_omega_tau
        error = np.linalg.norm(y_reduced_f - y_f) / np.linalg.norm(y_f)
        assert error <= 2 * math.pi * f * tau, f
