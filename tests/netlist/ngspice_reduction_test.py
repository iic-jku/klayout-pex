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
from pathlib import Path
from typing import Callable, Tuple

import allure
import numpy as np
import pytest

from klayout_pex.netlist.netlist_reduction import reduce_spice_netlist
from klayout_pex.netlist.admittance_check import AdmittanceCheckOptions, check_reduction_admittance
from klayout_pex.netlist.rc_reduction import ReductionOptions
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.xyce import xyce_port_admittance, requires_xyce
from tests.common.rc_networks import port_admittance, random_extracted_network, spice_subcircuit, write

parent_suite = "kpex/netlist reduce"
tags = ("Netlist", "Reduction", "ngspice")
SIMULATORS = [pytest.param(ngspice_port_admittance, marks=requires_ngspice, id='ngspice'),
              pytest.param(xyce_port_admittance, marks=requires_xyce, id='Xyce')]


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


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.parametrize('simulate', SIMULATORS)
@pytest.mark.parametrize('range_mode', [False, True])
@pytest.mark.parametrize('decades', [(9, 9), (8, 9), (9, 10)])
def test_requested_check_error_matches_independent_simulation(
        tmp_path: Path, simulate: Callable[..., Tuple[np.ndarray, np.ndarray]], decades: Tuple[int, int],
        range_mode: bool):
    original = write(str(tmp_path), 'series.spice', '.SUBCKT cell A B\nR1 A n 100\nC1 n B 1p\n.ENDS cell\n')
    reduced = str(tmp_path / 'reduced.spice')
    options = (AdmittanceCheckOptions(frequency_range=(10.0 ** decades[0], 10.0 ** decades[1]),
                                      points_per_decade=1) if range_mode else AdmittanceCheckOptions(1e9))
    result = reduce_spice_netlist(original, reduced, ReductionOptions(ticer_tau=1e-9), check_options=options)
    # The requested frequency may be the only point or either endpoint of a sweep.
    frequencies, before = simulate(original, 'cell', ['A', 'B'], decades, str(tmp_path))
    after_frequencies, after = simulate(reduced, 'cell', ['A', 'B'], decades, str(tmp_path))
    expected = np.array([10.0 ** decade for decade in range(decades[0], decades[1] + 1)])
    assert frequencies == pytest.approx(expected)
    assert after_frequencies == pytest.approx(expected)
    observed_errors = np.linalg.norm(after - before, axis=(1, 2)) / np.linalg.norm(before, axis=(1, 2))
    index = int(np.argmax(observed_errors)) if range_mode else 9 - decades[0]
    observed = observed_errors[index]
    check, = result.admittance_checks
    assert not check.passed
    assert check.relative_error == pytest.approx(observed, rel=1e-7)
    assert check.worst_frequency == pytest.approx(frequencies[index])
    assert check.checked_points == (len(frequencies) if range_mode else 1)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.parametrize('simulate', SIMULATORS)
def test_frequency_range_interior_peak_matches_independent_simulation(
        tmp_path: Path, simulate: Callable[..., Tuple[np.ndarray, np.ndarray]]):
    # Both ends pass 1%, but the parallel resistor makes the interior error peak.
    source = '.SUBCKT cell A B\nRbase A B 100\nR1 A n 100\nC1 n B 1p\n.ENDS cell\n'
    original = write(str(tmp_path), 'original.spice', source)
    changed = write(str(tmp_path), 'changed.spice', source.replace('1p', '2p'))
    options = AdmittanceCheckOptions(frequency_range=(1e6, 1e11), points_per_decade=1)
    check, = check_reduction_admittance(original, changed, options)
    frequencies, before = simulate(original, 'cell', ['A', 'B'], (6, 11), str(tmp_path))
    after_frequencies, after = simulate(changed, 'cell', ['A', 'B'], (6, 11), str(tmp_path))
    assert frequencies == pytest.approx(options.frequencies)
    assert after_frequencies == pytest.approx(options.frequencies)
    observed_errors = np.linalg.norm(after - before, axis=(1, 2)) / np.linalg.norm(before, axis=(1, 2))
    worst = int(np.argmax(observed_errors))
    assert observed_errors[0] < 0.01 and observed_errors[-1] < 0.01
    assert 0 < worst < len(frequencies) - 1
    assert not check.passed
    assert check.relative_error == pytest.approx(observed_errors[worst], rel=1e-7)
    assert check.worst_frequency == pytest.approx(frequencies[worst])
