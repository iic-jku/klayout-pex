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

"""Shared grounding against an independent nodal-capacitance calculation."""

import copy
from typing import Dict, Tuple

import allure
import numpy as np
import pytest

from klayout_pex.netlist.coupling import ground_capacitances

pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('Netlist', 'Grounding')]


@pytest.mark.parametrize('scale', [1e-200, 1e-15, 1.0, 1e200])
def test_grounded_loads_match_independent_schur_complement(scale: float):
    # Distinct A/a names exercise the case-sensitive extraction contract. Two
    # retained nodes share one conductor, so their induced C must stay mutual.
    names = ['A', 'a', 'B', 'G', 'F0', 'F1', 'F2']
    rng = np.random.default_rng(530)
    for _ in range(12):
        matrix = np.zeros((len(names), len(names)))
        caps: Dict[Tuple[str, str], float] = {}
        for a in range(len(names)):
            for b in range(a + 1, len(names)):
                value = 10.0 ** rng.uniform(-3, 3)
                matrix[a, a] += value
                matrix[b, b] += value
                matrix[a, b] -= value
                matrix[b, a] -= value
                caps[(names[a], names[b])] = value * scale
        before = copy.deepcopy(caps)
        reduced = matrix[:4, :4] - matrix[:4, 4:] @ np.linalg.solve(matrix[4:, 4:], matrix[4:, :4])
        actual = ground_capacitances(caps, 'G', net_by_node={'A': 'one', 'a': 'one'},
                                    floating_net_names={'F0', 'F1', 'F2'})
        expected = {('A', 'a'): -reduced[0, 1] * scale,
                    ('A', 'G'): (reduced[0, 0] + reduced[0, 1]) * scale,
                    ('G', 'a'): (reduced[1, 1] + reduced[0, 1]) * scale,
                    ('B', 'G'): reduced[2, 2] * scale}
        assert actual == pytest.approx(expected, rel=2e-12, abs=0)
        assert caps == before


def test_parallel_pairs_and_reference_alias_keep_original_endpoints():
    caps = {('A', 'B'): 2.0, ('B', 'A'): 3.0, ('A', 'G1'): 4.0}
    assert ground_capacitances(caps, 'G', net_by_node={'G1': 'reference'},
                              reference_net_names={'reference'}) == {
        ('A', 'G'): 5.0, ('B', 'G'): 5.0, ('A', 'G1'): 4.0}


def test_explicit_protection_overrides_floating_classification():
    caps = {('A', 'F'): 2.0, ('F', 'G'): 3.0}
    assert ground_capacitances(caps, 'G', floating_net_names={'F'}, protected_net_names={'F'}) == {
        ('A', 'G'): 2.0, ('F', 'G'): 5.0}
