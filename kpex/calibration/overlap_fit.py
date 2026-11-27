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

"""Fit an area term, edge term and signed corner correction to aligned plates."""

from dataclasses import dataclass
import math
from typing import Dict, List, Tuple

import numpy as np

from .validation import CalibrationError
from kpex_protobuf.kpex.calibration.patterns_pb2 import TRAINING, VALIDATION


@dataclass(frozen=True)
class OverlapObservation:
    case_id: str
    role: int
    width_um: float
    length_um: float
    coupling_f: float


@dataclass(frozen=True)
class OverlapFit:
    area_coupling_f_per_um2: float
    edge_coupling_f_per_um: float
    corner_correction_f: float
    condition_number: float
    predictions_f: Dict[str, float]


def _geometry(item: OverlapObservation) -> Tuple[float, float, float]:
    return item.width_um * item.length_um, 2 * (item.width_um + item.length_um), 1.0


def fit_overlap_rectangles(observations: List[OverlapObservation]) -> OverlapFit:
    """Use training rectangles only to fit the three terms."""
    geometries = set()
    identifiers = set()
    training = []
    for item in observations:
        dimensions = (item.width_um, item.length_um)
        if not all(math.isfinite(value) and value > 0 for value in (*dimensions, item.coupling_f)):
            raise CalibrationError(f"Case '{item.case_id}' needs finite positive dimensions and coupling")
        geometry = tuple(sorted(dimensions))
        if geometry in geometries or item.case_id in identifiers:
            raise CalibrationError(f"Case '{item.case_id}' repeats an ID or rectangle geometry")
        geometries.add(geometry)
        identifiers.add(item.case_id)
        if item.role == TRAINING:
            training.append(item)
        elif item.role != VALIDATION:
            raise CalibrationError(f"Case '{item.case_id}' has an unsupported fit role")
    if len(training) < 4 or len(training) == len(observations):
        raise CalibrationError('An overlap fit needs at least four training rectangles and one held-out rectangle')

    design = np.array([_geometry(item) for item in training])
    if not np.isfinite(design).all() or np.any(design[:, 0] == 0):
        raise CalibrationError('Overlap geometry exceeds the finite fitting range')
    # Scale by each column's magnitude before taking its norm. This avoids
    # overflow even for finite input geometry with large aspect ratios.
    scales = design.max(axis=0)
    normalized = design / scales
    norms = np.linalg.norm(normalized, axis=0)
    target_scale = max(item.coupling_f for item in training)
    target = np.array([item.coupling_f / target_scale for item in training])
    if np.any(target == 0) or np.any(normalized[:, :2] == 0):
        raise CalibrationError('Input dynamic range underflows normalized overlap coordinates')
    try:
        solution, _, rank, singular = np.linalg.lstsq(normalized / norms, target, rcond=None)
    except np.linalg.LinAlgError as exc:
        raise CalibrationError('Overlap least-squares fit failed') from exc
    condition = float(singular[0] / singular[-1]) if singular[-1] > 0 else math.inf
    if rank != 3 or not math.isfinite(condition) or condition > 1e8:
        raise CalibrationError(f'Overlap area, edge and corner terms are not identifiable (condition {condition:g})')
    coefficients = tuple(float(value) * target_scale / float(norm) / float(scale)
                         for value, norm, scale in zip(solution, norms, scales))
    if not all(map(math.isfinite, coefficients)):
        raise CalibrationError('Overlap fit coefficients exceed the finite fitting range')
    predictions = {
        item.case_id: sum(coefficient * feature for coefficient, feature in zip(coefficients, _geometry(item)))
        for item in observations
    }
    if not all(map(math.isfinite, predictions.values())):
        raise CalibrationError('Overlap fit predictions exceed the finite fitting range')
    return OverlapFit(*coefficients, condition, predictions)
