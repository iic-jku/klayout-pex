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

from dataclasses import dataclass
import math
from typing import Callable


@dataclass(frozen=True)
class EdgeCapacitanceProfile:
    """Capacitance in a fractional interval of an edge, including previous clipping."""
    integral: Callable[[float, float], float]
    start: float = 0.0
    stop: float = 1.0

    def between(self, start: float, stop: float) -> float:
        span = self.stop - self.start
        return self.integral(self.start + start * span, self.start + stop * span)

    def part(self, start: float, stop: float) -> 'EdgeCapacitanceProfile':
        span = self.stop - self.start
        return EdgeCapacitanceProfile(self.integral, self.start + start * span, self.start + stop * span)


def sidewall_separation(distance_um: float, offset_um: float) -> float:
    """
    The fitted separation, bounded by half the physical distance for negative offsets.

    The branches meet at distance=-2*offset. Below that point the original fit
    would diverge and become negative, whereas capacitance grows as 1/distance.
    """
    return max(distance_um + offset_um, distance_um / 2.0)


def _log_ratio(first: float, last: float) -> float:
    ratio = (last - first) / first
    return math.log1p(ratio) if math.isfinite(ratio) else math.log(last) - math.log(first)


def sidewall_capacitance(length_um: float, first_um: float, last_um: float,
                         coefficient: float, offset_um: float,
                         start: float = 0.0, stop: float = 1.0) -> float:
    """
    Integrate one directed edge's half of the full sidewall pair fit, in fF.

    The coefficient is the full pair numerator in aF. Extraction visits both
    facing edges, so their contributions must sum to that fit exactly once.
    """
    first = first_um + (last_um - first_um) * start
    last = first_um + (last_um - first_um) * stop
    length = length_um * (stop - start)
    if first == last:
        return ((length * coefficient) / sidewall_separation(first, offset_um) / 2.0 / 1000.0)

    low, high = sorted((first, last))
    boundary = -2.0 * offset_um
    intervals = [low, high]
    if low < boundary < high:
        intervals.insert(1, boundary)
    integral = math.fsum(2.0 * _log_ratio(a, b) if b <= boundary else
                         _log_ratio(a + offset_um, b + offset_um)
                         for a, b in zip(intervals, intervals[1:]))
    return length * coefficient * (integral / (high - low)) / 2.0 / 1000.0


def fringe_alpha(overlap_coefficient: float) -> float:
    # The overlap scaling is 1/50, as in MAGIC's overlap multiplier.
    return overlap_coefficient * (0.02 * 0.01 * 0.5 * 200.0)


def fringe_normalization(alpha: float, halo_um: float, scale_to_halo: bool) -> float:
    return min((2.0 / math.pi) * math.atan(alpha * halo_um), 1.0) if scale_to_halo else 1.0


def _mean_atan(first: float, last: float) -> float:
    """Mean atan over a nonnegative interval, without subtracting close primitives."""
    low, high = sorted((first, last))
    if low == high or math.isinf(high):
        return math.atan(high)
    if high < 1e-8:
        # The cubic term is below double precision here. This also prevents
        # underflow of the quadratic primitive before halo normalization.
        return low + (high - low) / 2.0
    delta = high - low
    angle = math.atan2(delta / high, low + 1.0 / high) if high > 1.0 else \
        math.atan2(delta, 1.0 + low * high)
    norm = math.hypot(1.0, low)
    ratio = (delta / norm) * (high / norm + low / norm)
    log_ratio = 0.5 * math.log1p(ratio) if math.isfinite(ratio) else \
        math.log(math.hypot(1.0, high)) - math.log(norm)
    # Integral atan(z) dz = z*atan(z) - log(hypot(1,z)).
    return math.atan(high) + (low * angle - log_ratio) / delta


def _mean_fringe_fraction(first_um: float, last_um: float, alpha: float) -> float:
    low, high = sorted((first_um, last_um))
    if high <= 0.0:
        return 0.0
    fraction = high / (high - low) if low < 0.0 else 1.0
    return fraction * (2.0 / math.pi) * _mean_atan(alpha * max(0.0, low), alpha * high)


def fringe_capacitance(length_um: float, near_first_um: float, near_last_um: float,
                       far_first_um: float, far_last_um: float, alpha: float,
                       coefficient: float, normalization: float,
                       start: float = 0.0, stop: float = 1.0) -> float:
    """Integrate the existing fringe model over a trapezoid or part of it, in fF."""
    if alpha == 0.0:
        return 0.0
    near = _mean_fringe_fraction(near_first_um + (near_last_um - near_first_um) * start,
                                near_first_um + (near_last_um - near_first_um) * stop, alpha)
    far = _mean_fringe_fraction(far_first_um + (far_last_um - far_first_um) * start,
                               far_first_um + (far_last_um - far_first_um) * stop, alpha)
    if normalization < 1.0:
        near /= normalization
        far /= normalization
    return max(0.0, far - near) * (length_um * (stop - start)) * coefficient / 1000.0
