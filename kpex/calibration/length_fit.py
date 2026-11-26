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

"""Separate distributed capacitance and finite ends using declared fit weights."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .validation import CalibrationError


from kpex_protobuf.kpex.calibration.patterns_pb2 import TRAINING, VALIDATION

@dataclass(frozen=True)
class LengthObservation:
    case_id: str
    role: int
    length_um: float
    capacitance_f: float
    weight_scale_f: Optional[float] = None


@dataclass(frozen=True)
class LengthFitPolicy:
    weight_floor_f: float
    max_weighted_residual: float
    max_condition_number: float = 1e8

    def __post_init__(self):
        for name in ('weight_floor_f', 'max_weighted_residual', 'max_condition_number'):
            _number(getattr(self, name), name, positive=True)
        if self.max_condition_number < 1:
            raise CalibrationError('max_condition_number must be at least 1')


def _number(value: Any, name: str, *, positive: bool = False):
    try:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) \
                and (value > 0 if positive else value >= 0)
    except OverflowError:
        valid = False
    if not valid:
        sign = 'positive' if positive else 'nonnegative'
        raise CalibrationError(f'{name} must be a finite {sign} number')


def _rescale(value: float, numerator: float, denominator: float = 1.0) -> float:
    # Avoid an overflowing or underflowing intermediate scale ratio when the final
    # coefficient is representable. There are only two fitted coefficients.
    try:
        result = float(Fraction(value) * Fraction(numerator) / Fraction(denominator))
    except (ValueError, OverflowError) as exc:
        raise CalibrationError('Length separation coefficients exceed finite numeric range') from exc
    if result == 0 and value != 0:
        raise CalibrationError('Length separation coefficient underflows finite numeric range')
    return result

def _residuals(observations: Sequence[LengthObservation], slope: float, end: float,
               policy: LengthFitPolicy) -> List[Dict[str, Any]]:
    result = []
    for item in observations:
        scale = max(policy.weight_floor_f, item.weight_scale_f or 0.0)
        predicted = slope * item.length_um + end
        residual = predicted - item.capacitance_f
        weighted = residual / scale
        if not all(math.isfinite(value) for value in (predicted, residual, weighted)):
            raise CalibrationError(f"Fit residual for '{item.case_id}' exceeds finite numeric range")
        result.append({'case_id': item.case_id, 'length_um': item.length_um,
                       'measured_f': item.capacitance_f, 'predicted_f': predicted,
                       'residual_f': residual, 'weighted_residual': weighted,
                       'weight_scale_f': scale,
                       'weight_source': ('explicit_observation_scale' if item.weight_scale_f is not None
                                         and item.weight_scale_f > policy.weight_floor_f
                                         else 'explicit_fit_floor')})
    return result


def _metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    weighted = [row['weighted_residual'] for row in rows]
    physical = [row['residual_f'] for row in rows]
    # hypot avoids overflowing while summing the squares of otherwise finite values.
    weighted_l2 = math.hypot(*weighted)
    physical_l2 = math.hypot(*physical)
    if not math.isfinite(weighted_l2) or not math.isfinite(physical_l2):
        raise CalibrationError('Fit objective exceeds finite numeric range')
    return {'count': len(rows), 'weighted_residual_l2': weighted_l2,
            'weighted_residual_rms': weighted_l2 / math.sqrt(len(rows)),
            'max_abs_weighted_residual': max(abs(value) for value in weighted),
            'residual_rms_f': physical_l2 / math.sqrt(len(rows)),
            'max_abs_residual_f': max(abs(value) for value in physical),
            'observations': rows}


def fit_length_series(observations: Sequence[LengthObservation], policy: LengthFitPolicy) -> Dict[str, Any]:
    """Fit C(L) = c_infinite * L + C_end without fitting technology coefficients.

    At least three distinct training lengths and one independent held-out length
    are required. The slope is nonnegative; the end residual has no sign constraint.
    A report can be inadequate even when the numerical least-squares solve succeeds.
    Weight scales are not automatically statistical standard deviations or certified
    numerical error bounds, so no confidence intervals are inferred from them.
    """
    if not isinstance(policy, LengthFitPolicy):
        raise CalibrationError('policy must be a LengthFitPolicy')
    identifiers = set()
    lengths = set()
    for item in observations:
        if not isinstance(item, LengthObservation):
            raise CalibrationError('observations must contain LengthObservation values')
        if not isinstance(item.case_id, str) or not item.case_id or item.case_id.casefold() in identifiers:
            raise CalibrationError('Observation case IDs must be nonempty and unique ignoring case')
        identifiers.add(item.case_id.casefold())
        if item.role not in (TRAINING, VALIDATION):
            raise CalibrationError(f"Observation '{item.case_id}' role must be training or validation")
        _number(item.length_um, f'{item.case_id}.length_um', positive=True)
        _number(item.capacitance_f, f'{item.case_id}.capacitance_f')
        if item.weight_scale_f is not None:
            _number(item.weight_scale_f, f'{item.case_id}.weight_scale_f')
        if item.length_um in lengths:
            raise CalibrationError('Every observation must use an independent, distinct length; repeated lengths '
                                   'cannot increase training information or enter the held-out set')
        lengths.add(item.length_um)
    training = sorted((item for item in observations if item.role == TRAINING), key=lambda item: item.length_um)
    validation = sorted((item for item in observations if item.role == VALIDATION), key=lambda item: item.length_um)
    if len(training) < 3 or not validation:
        raise CalibrationError('Length separation requires at least 3 independent training lengths '
                               'and 1 distinct held-out validation length')
    length_scale = max(item.length_um for item in training)
    capacitance_scale = max(item.capacitance_f for item in training) or policy.weight_floor_f
    x = np.array([item.length_um / length_scale for item in training], dtype=float)
    y = np.array([item.capacitance_f / capacitance_scale for item in training], dtype=float)
    scales = [max(policy.weight_floor_f, item.weight_scale_f or 0.0) for item in training]
    weight_normalization = min(scales)
    weights = np.array([weight_normalization / scale for scale in scales], dtype=float)
    if np.any(weights == 0) or np.any(x == 0) or any(value == 0 and item.capacitance_f != 0
                                                       for value, item in zip(y, training)):
        raise CalibrationError('Input dynamic range underflows normalized fitting coordinates')
    design = np.column_stack((x, np.ones(len(training)))) * weights[:, None]
    columns = np.array([math.hypot(*design[:, index]) for index in range(2)])
    if np.any(columns == 0):
        raise CalibrationError('Weighted sensitivity underflows normalized fitting coordinates')
    normalized = design / columns
    try:
        solution, _, rank, singular = np.linalg.lstsq(normalized, y * weights, rcond=None)
        inverse = np.linalg.pinv(normalized, rcond=np.finfo(float).eps * max(normalized.shape))
    except np.linalg.LinAlgError as exc:
        raise CalibrationError(f'NumPy length separation least-squares solve failed: {exc}') from exc
    condition = float(singular[0] / singular[-1]) if singular[-1] > 0 else math.inf
    if rank != 2 or not math.isfinite(condition) or condition > policy.max_condition_number:
        raise CalibrationError(f'Length separation is not identifiable: sensitivity rank {rank}/2, '
                               f'condition {condition:.6g}, allowed maximum {policy.max_condition_number:.6g}')
    scaled_slope, scaled_end = solution / columns
    slope = _rescale(float(scaled_slope), capacitance_scale, length_scale)
    end = _rescale(float(scaled_end), capacitance_scale)
    boundary = slope < 0
    if boundary:
        slope = 0.0
        end = _rescale(float(np.dot(weights * weights, y) / np.dot(weights, weights)), capacitance_scale)
    if not math.isfinite(slope) or not math.isfinite(end):
        raise CalibrationError('Length separation coefficients exceed finite numeric range')
    train_rows = _residuals(training, slope, end, policy)
    validation_rows = _residuals(validation, slope, end, policy)
    train_metrics, validation_metrics = _metrics(train_rows), _metrics(validation_rows)
    reasons = []
    if train_metrics['max_abs_weighted_residual'] > policy.max_weighted_residual:
        reasons.append('training_residual_exceeds_declared_budget')
    if validation_metrics['max_abs_weighted_residual'] > policy.max_weighted_residual:
        reasons.append('held_out_residual_exceeds_declared_budget')
    if any(row['predicted_f'] < 0 for row in (*train_rows, *validation_rows)):
        reasons.append('negative_predicted_capacitance_in_observed_domain')
    correlation = float(np.dot(normalized[:, 0], normalized[:, 1]))
    response = np.sum(np.abs(inverse), axis=1) / columns
    slope_response = _rescale(float(response[0]), weight_normalization, length_scale)
    end_response = _rescale(float(response[1]), weight_normalization)
    return {
        'model': 'finite_length_affine_v1', 'equation': 'C(L) = c_infinite * L + C_end',
        'status': 'inadequate' if reasons else 'consistent_with_declared_fit_budget',
        'diagnostics': reasons,
        'parameters': {'c_infinite_f_per_um': slope, 'c_end_f': end},
        'constraints': {'c_infinite_min': 0.0, 'c_end_sign': 'unconstrained',
                        'active': ['c_infinite_min'] if boundary or slope == 0 else []},
        'domain': {'training_length_um': [training[0].length_um, training[-1].length_um],
                   'validation_lengths_um': [item.length_um for item in validation],
                   'validation_extends_training_range': any(item.length_um < training[0].length_um
                                                 or item.length_um > training[-1].length_um for item in validation)},
        'weighting': {'floor_f': policy.weight_floor_f, 'max_abs_weighted_residual': policy.max_weighted_residual,
                      'confidence_intervals': 'not inferred from numerical weighting scales'},
        'sensitivity': {'rank': int(rank), 'parameter_count': 2,
                        'dimensionless_condition_number': condition,
                        'max_condition_number': policy.max_condition_number,
                        'singular_values': singular.tolist(), 'sensitivity_column_cosine': correlation,
                        'scope': 'unconstrained two-parameter design; active constraints reported separately',
                        'hypothetical_parameter_response': {
                            'assumption': 'each training value perturbed by at most its declared weight scale',
                            'c_infinite_f_per_um': slope_response, 'c_end_f': end_response,
                            'slope_exceeds_response': slope > slope_response,
                            'interpretation': 'deterministic sensitivity of unconstrained fit, not confidence bounds'},
                        'length_normalization_um': length_scale,
                        'weight_normalization_f': weight_normalization,
                        'row_weights': weights.tolist(), 'column_norms': columns.tolist(),
                        'normalized_jacobian': normalized.tolist(),
                        'convention': 'columns [L/max_training_L, 1], rows min_scale/scale, then unit column norms'},
        'training': train_metrics, 'validation': validation_metrics,
        'scope': 'finite-length separation only; no production-law coefficients or technology tables updated',
    }
