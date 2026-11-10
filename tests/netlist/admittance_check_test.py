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

"""Independent nodal-analysis and boundary checks for reduction verification."""

import math
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import allure
import numpy as np
import pytest

from klayout_pex.netlist import admittance_check
from klayout_pex.netlist.admittance_check import (
    AdmittanceCheck, AdmittanceCheckOptions, check_reduction_admittance, terminal_admittance,
)
from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist
from tests.common.rc_networks import build_network, port_admittance, random_extracted_network, write


@allure.parent_suite('Unit Tests')
@allure.tag('Netlist', 'Reduction', 'Admittance')
@pytest.mark.parametrize('seed', range(6))
@pytest.mark.parametrize('frequency', [1e6, 1e10])
def test_sparse_elimination_matches_independent_dense_nodal_analysis(seed: int, frequency: float):
    network = random_extracted_network(seed)
    terminals = [network.name(node) for node in network.nodes() if network.is_protected(node)]
    expected = port_admittance(network, terminals, frequency)
    obtained = terminal_admittance(network, terminals, frequency)
    matrix = np.array([[obtained.get((a.casefold(), b.casefold()), 0j) for b in terminals] for a in terminals])
    assert np.linalg.norm(matrix - expected) <= 1e-12 * np.linalg.norm(expected)


@pytest.mark.parametrize('frequency', [0, 1e-6, 1e3, 1e9])
def test_series_rc_has_the_analytic_admittance_and_dc_is_open(frequency: float):
    network = build_network([('A', 'n', 0.01, 0), ('n', 'B', 0, 1e-12)])
    obtained = terminal_admittance(network, ['a', 'b'], frequency)
    if frequency == 0:
        assert obtained == {}
    else:
        expected = 1 / (100 + 1 / (math.tau * frequency * 1j * 1e-12))
        assert obtained == pytest.approx({('a', 'a'): expected, ('a', 'b'): -expected,
                                          ('b', 'a'): -expected, ('b', 'b'): expected}, rel=1e-13, abs=0)


@pytest.mark.parametrize('frequency', [0, 1e9])
def test_disconnected_floating_components_need_no_shunts(frequency: float):
    network = build_network([('A', 'B', 0.5, 0), ('x', 'y', 0.1, 0), ('u', 'v', 0, 1e-12)])
    assert terminal_admittance(network, ['A', 'B'], frequency) == {
        ('a', 'a'): 0.5, ('a', 'b'): -0.5, ('b', 'a'): -0.5, ('b', 'b'): 0.5}
    assert terminal_admittance(network, [], frequency) == {}


@pytest.mark.parametrize('frequency', [-1, math.nan, math.inf, -math.inf, True, '1g'])
def test_invalid_frequencies_are_rejected(frequency: Any):
    with pytest.raises(ValueError, match='finite number of Hz'):
        AdmittanceCheckOptions(frequency)


@pytest.mark.parametrize('limit', [0, -1, 1, math.nan, math.inf, True, '0.01'])
def test_invalid_error_limits_are_rejected(limit: Any):
    with pytest.raises(ValueError, match='finite number > 0 and < 1'):
        AdmittanceCheckOptions(1e9, limit)


def compare(tmp_path: Path, original: str, reduced: str, options: AdmittanceCheckOptions,
            keep: Sequence[str] = ()) -> List[AdmittanceCheck]:
    before = write(str(tmp_path), 'original.spice', original)
    after = write(str(tmp_path), 'reduced.spice', reduced)
    return check_reduction_admittance(before, after, options, keep)


@pytest.mark.parametrize('before, after, expected', [('0', '0', 0), ('0', '1e-200', math.inf),
                                                   ('1e-200', '2e-200', 1)])
def test_zero_reference_and_tiny_capacitances_have_no_absolute_error_floor(tmp_path: Path, before: str,
                                                                          after: str, expected: float):
    source = '.SUBCKT small A B\nC1 A B VALUE\n.ENDS small\n'
    check, = compare(tmp_path, source.replace('VALUE', before), source.replace('VALUE', after),
                      AdmittanceCheckOptions(1))
    assert check.relative_error == pytest.approx(expected)
    assert check.passed == (expected == 0)


@pytest.mark.parametrize('frequency_options', [{'frequency': 1e9}, {'frequency_range': (1e8, 1e10)}])
def test_error_limit_is_inclusive_at_the_floating_point_boundary(tmp_path: Path,
                                                               frequency_options: Dict[str, Any]):
    source = '.SUBCKT cell A B\nC1 A B 1p\n.ENDS cell\n'
    changed = source.replace('1p', '1.25p')
    check, = compare(tmp_path, source, changed, AdmittanceCheckOptions(**frequency_options, max_relative_error=0.5))
    # Adjacent representable limits distinguish the inclusive boundary without
    # depending on decimal rounding in the matrix calculation.
    error = check.relative_error
    for limit, passed in ((math.nextafter(error, 0), False), (error, True),
                           (math.nextafter(error, 1), True)):
        check, = compare(tmp_path, source, changed, AdmittanceCheckOptions(**frequency_options, max_relative_error=limit))
        assert check.passed == passed


@pytest.mark.parametrize('limit, passed', [(4, False), (5, True), (6, True)])
def test_network_size_limit_fails_instead_of_silently_skipping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                             limit: int, passed: bool):
    # Two terminals, the reference, and the two directed coupling entries need 5.
    monkeypatch.setattr(admittance_check, '_MAX_ENTRIES', limit)
    source = '.SUBCKT cell A B\nR1 A B 100\n.ENDS cell\n'
    check, = compare(tmp_path, source, source, AdmittanceCheckOptions(1e9))
    assert check.passed == passed
    if not passed:
        assert 'check limit' in check.error


@pytest.mark.parametrize('limit, passed', [(0, False), (1, True), (2, True)])
def test_elimination_work_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: int, passed: bool):
    monkeypatch.setattr(admittance_check, '_MAX_UPDATES', limit)
    source = '.SUBCKT cell A B\nR1 A n 100\nR2 n B 100\n.ENDS cell\n'
    check, = compare(tmp_path, source, source, AdmittanceCheckOptions(1e9))
    assert check.passed == passed
    if not passed:
        assert 'coupling updates' in check.error


def test_real_tie_resistances_are_included_in_the_comparison(tmp_path: Path):
    source = '.SUBCKT cell A B\nC1 A p 1p\nC2 p B 1p\nRtie_1 p 0 1k\n.ENDS cell\n'
    check, = compare(tmp_path, source, source.replace('1k', '1e12'), AdmittanceCheckOptions(1e6))
    assert not check.passed
    assert check.relative_error > 0.1


def test_device_terminals_and_requested_nodes_are_observed(tmp_path: Path):
    source = '.SUBCKT cell A B\nR1 A n 100\nR2 n B 100\n.ENDS cell\n'
    reduced = '.SUBCKT cell A B\nR1 A B 200\n.ENDS cell\n'
    check, = compare(tmp_path, source, reduced, AdmittanceCheckOptions(0))
    assert check.passed
    check, = compare(tmp_path, source, reduced, AdmittanceCheckOptions(0), keep=['N'])
    assert not check.passed
    source = source.replace('.ENDS', 'Xdevice n B model\n.ENDS')
    reduced = reduced.replace('.ENDS', 'Xdevice n B model\n.ENDS')
    check, = compare(tmp_path, source, reduced, AdmittanceCheckOptions(0))
    assert not check.passed


def test_subcircuits_and_top_level_are_checked_separately(tmp_path: Path):
    # The source makes the top-level node observable, rather than a dangling stub.
    source = '.SUBCKT cell A B\nR1 A B 100\n.ENDS cell\nVdrive C 0 DC 0\nRtop C 0 200\n'
    checks = compare(tmp_path, source, source.replace('200', '400'), AdmittanceCheckOptions(0))
    assert [(check.scope, check.passed) for check in checks] == [('.SUBCKT cell', True), ('top level', False)]


@pytest.mark.parametrize('value', ['false', 0, None])
def test_reader_requires_a_boolean_tie_mode_before_reading(tmp_path: Path, value: Any):
    with pytest.raises(ValueError, match='recognize_ties must be True or False'):
        SpiceRCNetlist.read(str(tmp_path / 'missing.spice'), recognize_ties=value)
    with pytest.raises(ValueError, match='recognize_ties must be True or False'):
        SpiceRCNetlist.parse('', recognize_ties=value)


def test_large_frequency_and_small_capacitance_need_not_overflow():
    network = build_network([('A', 'B', 0, 1e-308)])
    matrix = terminal_admittance(network, ['A', 'B'], 1e308)
    assert matrix['a', 'a'] == pytest.approx(1j * math.tau)


def test_large_conductance_norms_are_scaled_before_subtraction(tmp_path: Path):
    source = '.SUBCKT cell A B\nR1 A B 1e-300\n.ENDS cell\n'
    check, = compare(tmp_path, source, source.replace('1e-300', '2e-300'), AdmittanceCheckOptions(0))
    assert check.relative_error == pytest.approx(0.5)
    assert not check.passed


def test_numeric_overflow_is_a_failed_check_not_a_false_match(tmp_path: Path):
    source = '.SUBCKT cell A B\nC1 A B 1e308\n.ENDS cell\n'
    check, = compare(tmp_path, source, source, AdmittanceCheckOptions(1e308))
    assert not check.passed
    assert check.error == 'non-finite nodal admittance'


def test_representable_capacitive_admittance_does_not_underflow_early():
    # Multiplying f*C first loses this response before the factor 2*pi is applied.
    network = build_network([('A', 'B', 0, 1e-308)])
    obtained = terminal_admittance(network, ['A', 'B'], 1e-16)
    assert obtained['a', 'a'] == 1j * math.nextafter(0, 1)


@pytest.mark.parametrize('conductances', [(1e-200, 1e200), (1e200, 1e-200)])
def test_series_conductance_does_not_underflow_before_multiplication(conductances: Sequence[float]):
    # The smaller conductance determines this series pair. Dividing it by the
    # larger one first underflows, although the final admittance is representable.
    network = build_network([('A', 'n', conductances[0], 0), ('n', 'B', conductances[1], 0)])
    obtained = terminal_admittance(network, ['A', 'B'], 0)
    assert obtained == pytest.approx({('a', 'a'): 1e-200, ('a', 'b'): -1e-200,
                                      ('b', 'a'): -1e-200, ('b', 'b'): 1e-200}, rel=1e-13, abs=0)


def test_unrepresentable_admittance_fails_instead_of_becoming_zero(tmp_path: Path):
    source = '.SUBCKT cell A B\nC1 A B 1e-308\n.ENDS cell\n'
    check, = compare(tmp_path, source, source, AdmittanceCheckOptions(1e-308))
    assert not check.passed
    assert 'underflow' in check.error


def test_default_frequency_range_has_exact_endpoints_and_logarithmic_spacing():
    options = AdmittanceCheckOptions(frequency_range=(1e6, 1e10))
    assert len(options.frequencies) == 41
    assert options.frequencies[0] == 1e6
    assert options.frequencies[-1] == 1e10
    ratios = [right / left for left, right in zip(options.frequencies, options.frequencies[1:])]
    assert ratios == pytest.approx([10 ** 0.1] * 40, rel=1e-14, abs=0)


@pytest.mark.parametrize('bounds, density, expected', [
    ((3, 30), 1, (3, 30)),
    ((1, 20), 1, (1, 10, 20)),
    ((1, 10), 2, (1, math.sqrt(10), 10)),
    ((1, 1), 10, (1,)),
    ((1, math.nextafter(1, math.inf)), 10, (1, math.nextafter(1, math.inf))),
])
def test_frequency_range_keeps_partial_decades_and_degenerate_endpoints(
        bounds: Tuple[float, float], density: int, expected: Tuple[float, ...]):
    options = AdmittanceCheckOptions(frequency_range=bounds, points_per_decade=density)
    assert options.frequencies == pytest.approx(expected, rel=1e-14, abs=0)
    assert options.frequencies[0] == bounds[0]
    assert options.frequencies[-1] == bounds[1]
    assert all(left < right for left, right in zip(options.frequencies, options.frequencies[1:]))


@pytest.mark.parametrize('bounds', [(1e-300, 1e300), (math.nextafter(0, 1), 1e308)])
def test_wide_frequency_ranges_do_not_overflow_the_frequency_ratio(bounds: Tuple[float, float]):
    # stop/start overflows, although every requested frequency is representable.
    options = AdmittanceCheckOptions(frequency_range=bounds, points_per_decade=1)
    assert options.frequencies[0] == bounds[0]
    assert options.frequencies[-1] == bounds[1]
    assert all(math.isfinite(value) and value > 0 for value in options.frequencies)
    assert all(left < right for left, right in zip(options.frequencies, options.frequencies[1:]))


@pytest.mark.parametrize('arguments', [
    {}, {'frequency': 1, 'frequency_range': (1, 2)},
    {'frequency_range': (0, 1)}, {'frequency_range': (-1, 1)}, {'frequency_range': (2, 1)},
    {'frequency_range': (1, math.inf)}, {'frequency_range': (math.nan, 1)},
    {'frequency_range': (True, 2)}, {'frequency_range': (1,)}, {'frequency_range': (1, 2, 3)},
    {'frequency_range': '1:2'},
    {'frequency': 1, 'points_per_decade': 10}, {'frequency': 1, 'include_dc': True},
    {'frequency_range': (1, 2), 'points_per_decade': 0},
    {'frequency_range': (1, 2), 'points_per_decade': -1},
    {'frequency_range': (1, 2), 'points_per_decade': True},
    {'frequency_range': (1, 2), 'points_per_decade': 1.5},
    {'frequency_range': (1, 2), 'points_per_decade': '10'},
    {'frequency_range': (1, 2), 'include_dc': 'false'},
    {'frequency_range': (1, 2), 'include_dc': 0},
])
def test_invalid_frequency_modes_and_modifiers_are_rejected(arguments: Dict[str, Any]):
    with pytest.raises(ValueError):
        AdmittanceCheckOptions(**arguments)


@pytest.mark.parametrize('density, include_dc, allowed', [
    (999, False, True), (1000, False, True), (1001, False, False),
    (999, True, True), (1000, True, False),
])
def test_frequency_point_limit_includes_both_endpoints_and_optional_dc(
        density: int, include_dc: bool, allowed: bool):
    # One decade needs density + 1 points, with a further point for DC.
    arguments = dict(frequency_range=(1, 10), points_per_decade=density, include_dc=include_dc)
    if not allowed:
        with pytest.raises(ValueError, match='frequency points'):
            AdmittanceCheckOptions(**arguments)
    else:
        options = AdmittanceCheckOptions(**arguments)
        assert len(options.frequencies) == density + 1 + int(include_dc)
        assert options.frequencies[0] == (0 if include_dc else 1)
        assert options.frequencies[-1] == 10


@pytest.mark.parametrize('bounds, density', [
    ((math.nextafter(0, 1), 1e-320), 10), ((1, 2), 10 ** 100),
])
def test_unrepresentable_frequency_grids_are_rejected(bounds: Tuple[float, float], density: int):
    with pytest.raises(ValueError, match='distinct'):
        AdmittanceCheckOptions(frequency_range=bounds, points_per_decade=density)


def test_frequency_sweep_detects_an_interior_error_that_both_endpoints_miss(tmp_path: Path):
    original = '.SUBCKT cell A B\nRbase A B 100\nR1 A n 100\nC1 n B 1p\n.ENDS cell\n'
    changed = original.replace('1p', '2p')
    for frequency in (1e6, 1e11):
        endpoint, = compare(tmp_path, original, changed, AdmittanceCheckOptions(frequency))
        assert endpoint.passed
    options = AdmittanceCheckOptions(frequency_range=(1e6, 1e11))
    check, = compare(tmp_path, original, changed, options)
    # For R || (R + C), doubling C gives relative error x/(1+4*x*x), x=2*pi*f*R*C.
    errors = [(math.tau * frequency * 1e-10) / (1 + 4 * (math.tau * frequency * 1e-10) ** 2)
              for frequency in options.frequencies]
    index = max(range(len(errors)), key=errors.__getitem__)
    assert check.relative_error == pytest.approx(errors[index], rel=1e-13, abs=0)
    assert check.relative_error > 0.249
    assert check.worst_frequency == options.frequencies[index]
    assert check.checked_points == len(options.frequencies)
    assert not check.passed
    assert 'sampled frequencies' in check.describe()
    assert 'worst relative Frobenius error' in check.describe()


def test_optional_dc_detects_a_path_that_is_negligible_in_the_ac_range(tmp_path: Path):
    original = '.SUBCKT cell A B\nC1 A B 1p\n.ENDS cell\n'
    changed = original.replace('.ENDS', 'Rleak A B 1G\n.ENDS')
    ac_only, = compare(tmp_path, original, changed, AdmittanceCheckOptions(frequency_range=(1e9, 1e10)))
    with_dc, = compare(tmp_path, original, changed,
                       AdmittanceCheckOptions(frequency_range=(1e9, 1e10), include_dc=True))
    assert ac_only.passed
    assert not with_dc.passed
    assert math.isinf(with_dc.relative_error)
    assert with_dc.worst_frequency == 0
    assert with_dc.checked_points == ac_only.checked_points + 1


@pytest.mark.parametrize('limit, passed', [(19, False), (20, True), (21, True)])
def test_total_work_limit_covers_both_networks_at_every_frequency(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: int, passed: bool):
    # Two terminals + reference + two directed couplings cost 5 per network.
    # Both networks at two frequencies cost exactly 20 work units.
    monkeypatch.setattr(admittance_check, '_MAX_TOTAL_WORK', limit)
    source = '.SUBCKT cell A B\nR1 A B 100\n.ENDS cell\n'
    check, = compare(tmp_path, source, source,
                      AdmittanceCheckOptions(frequency_range=(1, 10), points_per_decade=1))
    assert check.passed == passed
    if not passed:
        assert 'total work limit' in check.error
        assert check.checked_points == 1
        assert check.error_frequency == 10
        assert check.relative_error is None


def test_total_work_limit_is_shared_between_scopes_without_silently_skipping(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(admittance_check, '_MAX_TOTAL_WORK', 19)
    source = ''.join(f'.SUBCKT cell{i} A B\nR1 A B 100\n.ENDS cell{i}\n' for i in range(3))
    checks = compare(tmp_path, source, source, AdmittanceCheckOptions(frequency_range=(1, 1)))
    assert [check.passed for check in checks] == [True, False, False]
    assert all('total work limit' in check.error for check in checks[1:])
    assert [check.checked_points for check in checks] == [1, 0, 0]


def test_unevaluable_frequency_cannot_turn_a_partial_sweep_into_a_pass(tmp_path: Path):
    source = '.SUBCKT cell A B\nC1 A B 1\n.ENDS cell\n'
    check, = compare(tmp_path, source, source,
                      AdmittanceCheckOptions(frequency_range=(1e307, 1e308), points_per_decade=1))
    assert not check.passed
    assert check.checked_points == 1
    assert check.error_frequency == 1e308
    assert check.relative_error is None
    assert check.worst_frequency is None
    assert 'non-finite' in check.error
