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

"""Check independent geometry and rank boundaries of the overlap fit."""

from typing import List, Tuple

import pytest

from kpex.calibration.overlap_fit import OverlapObservation, fit_overlap_rectangles
from kpex.calibration.validation import CalibrationError
from kpex_protobuf.kpex.calibration.patterns_pb2 import TRAINING, VALIDATION


def samples(sizes: List[Tuple[float, float]]) -> List[OverlapObservation]:
    return [
        OverlapObservation(f'plate_{index}', TRAINING if index < len(sizes) - 1 else VALIDATION,
                           width, length, 1e-16 * width * length + 2e-17 * 2 * (width + length) - 4e-17)
        for index, (width, length) in enumerate(sizes)
    ]


def test_constant_width_cannot_identify_area_and_perimeter():
    # With fixed width, area and perimeter are affine functions of length.
    observations = samples([(2, 4), (2, 5), (2, 6), (2, 8), (3, 4)])
    with pytest.raises(CalibrationError, match='not identifiable'):
        fit_overlap_rectangles(observations)


def test_rotated_duplicate_cannot_be_counted_as_holdout():
    observations = samples([(2, 4), (2, 8), (4, 4), (4, 8), (4, 2)])
    with pytest.raises(CalibrationError, match='repeats an ID or rectangle geometry'):
        fit_overlap_rectangles(observations)


def test_three_training_points_do_not_supply_a_residual_check():
    observations = samples([(2, 4), (2, 8), (4, 4), (3, 6)])
    with pytest.raises(CalibrationError, match='four training rectangles'):
        fit_overlap_rectangles(observations)


def test_shape_with_nonfinite_area_is_rejected():
    observations = samples([(2, 4), (2, 8), (4, 4), (4, 8), (3, 6)])
    observations[0] = OverlapObservation('enormous', TRAINING, 1e200, 1e200, 1e-15)
    with pytest.raises(CalibrationError, match='finite fitting range'):
        fit_overlap_rectangles(observations)
