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

"""Explicit finite pattern dimensions, with no inferred process design rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
from pathlib import Path
from typing import List, Tuple

from google.protobuf.json_format import ParseError

from .targets import CalibrationTargetSpec, read_targets, validate_case_targets
from .validation import CalibrationError, validate_identifier
from ..klayout.native_coordinates import NATIVE_COORDINATE_MAX
from ..util.protobuf_json import parse_protobuf_json
from klayout_pex_protobuf.kpex.calibration.patterns_pb2 import (
    CalibrationPatternFamily, CalibrationPatternRole, PatternSetSpecification, PARALLEL_PLATES, PARALLEL_WIRES,
    SUBSTRATE, DIRECTIONAL_FRINGE, TRAINING, VALIDATION,
)

from klayout_pex_protobuf.kpex.calibration.targets_pb2 import FringeScaleMode, HALO_NORMALIZED, UNSCALED


# The native kernel cannot safely process its signed int32 endpoint itself.
MAX_COORDINATE = NATIVE_COORDINATE_MAX - 1
MAX_CASES = 1000
MAX_SPEC_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class CalibrationPatternCase:
    case_id: str
    family: CalibrationPatternFamily.ValueType
    layers: Tuple[str, ...]
    width: int
    length: int
    gap: int
    role: CalibrationPatternRole.ValueType
    receiver_width: int = 0
    lateral_offset: int = 0
    target_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CalibrationPatternSpec:
    grid: Fraction
    domain_margin: int
    patterns: Tuple[CalibrationPatternCase, ...]
    source: bytes
    targets: Tuple[CalibrationTargetSpec, ...] = ()
    fringe_scale_mode: FringeScaleMode.ValueType = HALO_NORMALIZED

    @property
    def source_sha256(self) -> str:
        return hashlib.sha256(self.source).hexdigest()


def _decimal_quantity(value: str, where: str, positive: bool) -> Fraction:
    try:
        decimal = Decimal(value)
        if not decimal.is_finite() or (positive and decimal <= 0) or abs(decimal.as_tuple().exponent) > 308:
            raise ValueError('outside finite decimal range')
        return Fraction(decimal)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        constraint = 'positive finite' if positive else 'finite signed'
        raise CalibrationError(f'{where} must be a {constraint} decimal in µm') from exc


def _positive(value: str, where: str) -> Fraction:
    return _decimal_quantity(value, where, positive=True)


def _grid_value(value: str, grid: Fraction, where: str, positive: bool = True) -> int:
    quantity = _decimal_quantity(value, where, positive=positive) / grid
    if quantity.denominator != 1:
        raise CalibrationError(f'{where} must be an exact multiple of grid_um')
    if abs(quantity) > MAX_COORDINATE:
        raise CalibrationError(f'{where} exceeds the supported {MAX_COORDINATE} grid units')
    return int(quantity)


def read_patterns(path: Path) -> CalibrationPatternSpec:
    """Parse protobuf JSON and validate physical inputs before technology loading."""
    try:
        with path.open('rb') as stream:
            source = stream.read(MAX_SPEC_BYTES + 1)
        if len(source) > MAX_SPEC_BYTES:
            raise CalibrationError(f'Pattern specification exceeds {MAX_SPEC_BYTES} bytes')
        specification = PatternSetSpecification()
        parse_protobuf_json(source.decode('utf-8'), specification)
    except (OSError, UnicodeError, ParseError, ValueError, RecursionError) as exc:
        raise CalibrationError(f"Cannot read pattern specification '{path}': {exc}") from exc
    if specification.schema_version != 1:
        raise CalibrationError('schema_version must be 1')
    grid = _positive(specification.grid_um, 'grid_um')
    if max(grid.numerator, grid.denominator) > 2 ** 63 - 1:
        raise CalibrationError('grid_um must fit the PEX25D signed 64-bit rational representation')
    margin = _grid_value(specification.domain_margin_um, grid, 'domain_margin_um')
    if not 1 <= len(specification.patterns) <= MAX_CASES:
        raise CalibrationError(f'patterns must contain between 1 and {MAX_CASES} explicit patterns')
    targets = read_targets(specification.targets)
    if targets and not specification.HasField('fringe_scale_mode'):
        raise CalibrationError('Targeted patterns require explicit fringe_scale_mode: HALO_NORMALIZED or UNSCALED')
    fringe_scale = specification.fringe_scale_mode if specification.HasField('fringe_scale_mode') else HALO_NORMALIZED
    if fringe_scale not in (HALO_NORMALIZED, UNSCALED):
        raise CalibrationError('fringe_scale_mode must be HALO_NORMALIZED or UNSCALED')
    patterns: List[CalibrationPatternCase] = []
    identifiers = set()
    for index, data in enumerate(specification.patterns):
        where = f'patterns[{index}]'
        receiver_width = lateral_offset = 0
        if data.HasField('parallel_plates'):
            family = PARALLEL_PLATES
            layers = (data.parallel_plates.lower_layer, data.parallel_plates.upper_layer)
            gap = 0
        elif data.HasField('parallel_wires'):
            family = PARALLEL_WIRES
            layers = (data.parallel_wires.layer, data.parallel_wires.layer)
            gap = _grid_value(data.parallel_wires.gap_um, grid, where + '.parallel_wires.gap_um')
        elif data.HasField('substrate'):
            family = SUBSTRATE
            layers = (data.substrate.layer,)
            gap = 0
        elif data.HasField('directional_fringe'):
            family = DIRECTIONAL_FRINGE
            geometry = data.directional_fringe
            layers = (geometry.edge_layer, geometry.receiver_layer)
            if layers[0] == layers[1]:
                raise CalibrationError(f'{where}.directional_fringe needs two distinct process profiles')
            gap = 0
            receiver_width = _grid_value(geometry.receiver_width_um, grid, where + '.directional_fringe.receiver_width_um')
            lateral_offset = _grid_value(geometry.lateral_offset_um, grid, where + '.directional_fringe.lateral_offset_um', positive=False)
        else:
            raise CalibrationError(f'{where} must select parallel_plates, parallel_wires, substrate or directional_fringe')
        case_id = data.id
        validate_identifier(case_id, where + '.id')
        # Paths must stay unique on case-insensitive filesystems as well as Linux.
        if case_id.casefold() in identifiers:
            raise CalibrationError(f"{where}.id repeats '{case_id}' ignoring case")
        identifiers.add(case_id.casefold())
        if data.role not in (TRAINING, VALIDATION):
            raise CalibrationError(f'{where}.role must be TRAINING or VALIDATION')
        if any(not layer for layer in layers):
            raise CalibrationError(f'{where} layer names must be nonempty strings')
        width = _grid_value(data.width_um, grid, where + '.width_um')
        length = _grid_value(data.length_um, grid, where + '.length_um')
        xlow = 0
        match family:
            case CalibrationPatternFamily.PARALLEL_WIRES:
                xhigh = 2 * width + gap
            case CalibrationPatternFamily.PARALLEL_PLATES | CalibrationPatternFamily.SUBSTRATE:
                xhigh = width
            case CalibrationPatternFamily.DIRECTIONAL_FRINGE:
                xlow = min(0, width + lateral_offset)
                xhigh = max(width, width + lateral_offset + receiver_width)
            case _:
                raise NotImplementedError(f'Calibration extent for pattern family {family} is not implemented')
        if max(abs(xlow), xhigh, length) + margin > MAX_COORDINATE:
            raise CalibrationError(f'{where} including domain margin exceeds {MAX_COORDINATE} grid units')
        case = CalibrationPatternCase(case_id, family, layers, width, length, gap, data.role,
                                      receiver_width, lateral_offset, tuple(data.target_ids))
        validate_case_targets(case, targets)
        patterns.append(case)
    used = {target_id for case in patterns for target_id in case.target_ids}
    unused = sorted(target.target_id for target in targets if target.target_id not in used)
    if unused:
        raise CalibrationError('Targets have no referring pattern: ' + ', '.join(unused))
    return CalibrationPatternSpec(grid, margin, tuple(patterns), source, targets, fringe_scale)
