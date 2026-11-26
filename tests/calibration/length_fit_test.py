#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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

"""Analytic algorithm tests, not field-solver qualification evidence."""

from dataclasses import replace
import math
from typing import List, Optional

import allure
import pytest

from kpex.calibration.length_fit import LengthFitPolicy, LengthObservation, fit_length_series
from kpex.calibration.validation import CalibrationError


from kpex_protobuf.kpex.calibration.patterns_pb2 import TRAINING, VALIDATION
pytestmark = allure.parent_suite('Unit Tests')


def exact_series(slope: float = 2e-18, end: float = 1e-18) -> List[LengthObservation]:
    return [LengthObservation(f'length_{length}', VALIDATION if length == 8 else TRAINING,
                              float(length), slope * length + end)
            for length in (1, 2, 4, 8)]


@pytest.mark.parametrize('end', [-1e-18, 0.0, 1e-18])
def test_independent_affine_series_separates_signed_end_residual(end: float):
    result = fit_length_series(exact_series(end=end), LengthFitPolicy(1e-22, 1.0))
    assert result['status'] == 'consistent_with_declared_fit_budget'
    assert result['parameters']['c_infinite_f_per_um'] == pytest.approx(2e-18, rel=1e-14, abs=0)
    assert result['parameters']['c_end_f'] == pytest.approx(end, rel=1e-14, abs=1e-32)
    assert result['sensitivity']['rank'] == 2
    assert result['constraints']['c_end_sign'] == 'unconstrained'
    assert result['domain']['validation_extends_training_range']
    assert result['training']['max_abs_residual_f'] < 1e-31
    assert result['validation']['max_abs_residual_f'] < 1e-31
    assert 'no production-law coefficients' in result['scope']


def test_weighted_fit_agrees_with_independent_rational_solution():
    # Exact normal-equation sums give slope 7/3 and intercept 5/9 for weights
    # [1, 1, 1/4]. This checks numerical weighting without duplicating the SVD.
    data = [LengthObservation(str(i), TRAINING, float(i), y * 1e-15, sigma * 1e-16)
            for i, y, sigma in ((1, 3, 1), (2, 5, 1), (3, 8, 2))]
    data.append(LengthObservation('held', VALIDATION, 4.0, (89 / 9) * 1e-15, 1e-16))
    result = fit_length_series(data, LengthFitPolicy(1e-18, 3.0))
    assert result['parameters']['c_infinite_f_per_um'] == pytest.approx((7 / 3) * 1e-15, rel=1e-14, abs=0)
    assert result['parameters']['c_end_f'] == pytest.approx((5 / 9) * 1e-15, rel=1e-14, abs=0)
    assert result['training']['max_abs_weighted_residual'] == pytest.approx(20 / 9)
    assert result['status'] == 'consistent_with_declared_fit_budget'
    assert all(row['weight_source'] == 'explicit_observation_scale'
               for row in result['training']['observations'])


@pytest.mark.parametrize('uncertainty', [None, 0.0, 1e-24])
def test_zero_or_absent_uncertainty_uses_positive_explicit_floor(uncertainty: Optional[float]):
    data = [replace(item, weight_scale_f=uncertainty) for item in exact_series()]
    result = fit_length_series(data, LengthFitPolicy(1e-22, 1.0))
    assert all(row['weight_scale_f'] == 1e-22 and row['weight_source'] == 'explicit_fit_floor'
               for row in result['training']['observations'])


def test_holdout_is_never_used_to_fit_parameters():
    data = exact_series()
    data[-1] = replace(data[-1], capacitance_f=1e-12)
    result = fit_length_series(data, LengthFitPolicy(1e-22, 1.0))
    assert result['parameters']['c_infinite_f_per_um'] == pytest.approx(2e-18, rel=1e-14, abs=0)
    assert result['parameters']['c_end_f'] == pytest.approx(1e-18, rel=1e-14, abs=0)
    assert result['status'] == 'inadequate'
    assert result['diagnostics'] == ['held_out_residual_exceeds_declared_budget']


def test_nonlinear_training_residual_is_reported_as_model_inadequacy():
    data = [replace(item, capacitance_f=item.length_um ** 2 * 1e-18) for item in exact_series()]
    result = fit_length_series(data, LengthFitPolicy(1e-22, 1.0))
    assert result['status'] == 'inadequate'
    assert 'training_residual_exceeds_declared_budget' in result['diagnostics']


@pytest.mark.parametrize('change,acceptable', [(0.999999, True), (1.0, True), (1.000001, False)])
def test_declared_residual_budget_boundary_is_inclusive(change: float, acceptable: bool):
    # A constant zero training response is exactly representable; the holdout
    # difference is therefore the declared scale, without cancellation noise.
    data = exact_series(slope=0.0, end=0.0)
    data[-1] = replace(data[-1], capacitance_f=change * 1e-18)
    result = fit_length_series(data, LengthFitPolicy(1e-18, 1.0))
    assert (result['status'] == 'consistent_with_declared_fit_budget') == acceptable


def test_negative_slope_activates_constraint_without_clipping_end():
    data = [replace(item, capacitance_f=(10 - item.length_um) * 1e-18) for item in exact_series()]
    result = fit_length_series(data, LengthFitPolicy(1e-22, 1.0))
    assert result['parameters']['c_infinite_f_per_um'] == 0
    assert result['parameters']['c_end_f'] == pytest.approx((23 / 3) * 1e-18, rel=1e-14, abs=0)
    assert result['constraints']['active'] == ['c_infinite_min']
    assert result['status'] == 'inadequate'


def test_reordering_preserves_fit_and_report():
    data = exact_series()
    assert fit_length_series(data, LengthFitPolicy(1e-22, 1.0)) == \
           fit_length_series(list(reversed(data)), LengthFitPolicy(1e-22, 1.0))


@pytest.mark.parametrize('scale', [1e-90, 1e90])
def test_dimensional_scaling_does_not_change_condition_or_acceptance(scale: float):
    data = exact_series()
    scaled = [replace(item, length_um=item.length_um * scale, capacitance_f=item.capacitance_f * scale)
              for item in data]
    base = fit_length_series(data, LengthFitPolicy(1e-22, 1.0))
    result = fit_length_series(scaled, LengthFitPolicy(1e-22 * scale, 1.0))
    assert result['parameters']['c_infinite_f_per_um'] == pytest.approx(base['parameters']['c_infinite_f_per_um'], rel=1e-13, abs=0)
    assert result['parameters']['c_end_f'] == pytest.approx(base['parameters']['c_end_f'] * scale, rel=1e-13, abs=0)
    assert result['sensitivity']['dimensionless_condition_number'] == pytest.approx(
        base['sensitivity']['dimensionless_condition_number'])


@pytest.mark.parametrize('count', [0, 1, 2])
def test_insufficient_training_never_becomes_fit(count: int):
    data = exact_series()
    with pytest.raises(CalibrationError, match='at least 3'):
        fit_length_series(data[:count] + [data[-1]], LengthFitPolicy(1e-22, 1.0))


def test_missing_holdout_never_becomes_fit():
    with pytest.raises(CalibrationError, match='held-out'):
        fit_length_series(exact_series()[:-1], LengthFitPolicy(1e-22, 1.0))


@pytest.mark.parametrize('role', [TRAINING, VALIDATION])
def test_duplicate_length_is_not_independent_evidence(role: int):
    data = exact_series() + [LengthObservation('duplicate', role, 1.0, 3e-18)]
    with pytest.raises(CalibrationError, match='distinct length'):
        fit_length_series(data, LengthFitPolicy(1e-22, 1.0))


def test_nearly_identical_lengths_are_numerically_unidentifiable():
    data = [LengthObservation(str(i), VALIDATION if i == 3 else TRAINING,
                              1.0 + i * 1e-12, 2e-18) for i in range(4)]
    with pytest.raises(CalibrationError, match='not identifiable'):
        fit_length_series(data, LengthFitPolicy(1e-22, 1.0))


@pytest.mark.parametrize('field,value', [('length_um', 0), ('length_um', -1), ('length_um', math.inf),
                                        ('capacitance_f', -1e-18), ('capacitance_f', math.nan),
                                        ('weight_scale_f', -1), ('weight_scale_f', True),
                                        ('role', 'test'), ('case_id', '')])
def test_invalid_observations_fail_explicitly(field: str, value: object):
    data = exact_series()
    data[0] = replace(data[0], **{field: value})
    with pytest.raises(CalibrationError):
        fit_length_series(data, LengthFitPolicy(1e-22, 1.0))


@pytest.mark.parametrize('value', [0, -1, math.nan, math.inf, True])
def test_invalid_positive_weight_floor_is_rejected(value: float):
    with pytest.raises(CalibrationError, match='weight_floor_f'):
        LengthFitPolicy(value, 1.0)


def test_declared_scale_sensitivity_has_independent_analytic_bound():
    # For training lengths 1,2,4 the slope sensitivities are -2/7,-1/14,5/14
    # and the intercept sensitivities are 1,1/2,-1/2. Absolute sums bound the
    # response to hypothetical per-sample perturbations; no probability is assumed.
    result = fit_length_series(exact_series(), LengthFitPolicy(1e-22, 1.0))
    response = result['sensitivity']['hypothetical_parameter_response']
    assert response['c_infinite_f_per_um'] == pytest.approx((5 / 7) * 1e-22, rel=1e-14, abs=0)
    assert response['c_end_f'] == pytest.approx(2e-22, rel=1e-14, abs=0)
    assert response['slope_exceeds_response']
    weak = fit_length_series(exact_series(), LengthFitPolicy(1e-12, 1.0))
    assert not weak['sensitivity']['hypothetical_parameter_response']['slope_exceeds_response']


@pytest.mark.parametrize('direction,passes', [(-1, False), (0, True), (1, True)])
def test_condition_limit_boundary(direction: int, passes: bool):
    data = exact_series()
    condition = fit_length_series(data, LengthFitPolicy(1e-22, 1.0))['sensitivity']['dimensionless_condition_number']
    limit = math.nextafter(condition, -math.inf if direction < 0 else math.inf) if direction else condition
    if passes:
        fit_length_series(data, LengthFitPolicy(1e-22, 1.0, limit))
    else:
        with pytest.raises(CalibrationError, match='not identifiable'):
            fit_length_series(data, LengthFitPolicy(1e-22, 1.0, limit))


@pytest.mark.parametrize('field,value', [('length_um', 10 ** 400), ('capacitance_f', 10 ** 400),
                                        ('weight_scale_f', 10 ** 400)])
def test_extreme_integer_input_has_domain_diagnostic(field: str, value: int):
    data = exact_series()
    data[0] = replace(data[0], **{field: value})
    with pytest.raises(CalibrationError, match='finite'):
        fit_length_series(data, LengthFitPolicy(1e-22, 1.0))


def test_signed_end_cannot_make_observed_prediction_negative():
    data = exact_series(end=-1e-18)
    data[-1] = replace(data[-1], length_um=0.1, capacitance_f=0.1e-18)
    result = fit_length_series(data, LengthFitPolicy(1e-15, 1.0))
    assert result['status'] == 'inadequate'
    assert result['diagnostics'] == ['negative_predicted_capacitance_in_observed_domain']


def test_extreme_relative_weights_fail_instead_of_dropping_observation():
    data = exact_series()
    data[0] = replace(data[0], weight_scale_f=1e300)
    with pytest.raises(CalibrationError, match='dynamic range'):
        fit_length_series(data, LengthFitPolicy(1e-300, 1.0))


def test_extreme_response_range_fails_instead_of_rounding_sample_to_zero():
    data = exact_series()
    data[0] = replace(data[0], capacitance_f=1e308)
    data[1] = replace(data[1], capacitance_f=5e-324)
    with pytest.raises(CalibrationError, match='dynamic range'):
        fit_length_series(data, LengthFitPolicy(1e-22, 1.0))
