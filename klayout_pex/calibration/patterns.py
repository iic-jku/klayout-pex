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
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple


class CalibrationError(Exception):
    """A calibration request or its technology could not be prepared."""


# The geometric validator uses KLayout's signed 32-bit integer XY coordinates.
MAX_COORDINATE = 2 ** 31 - 1
MAX_CASES = 1000
MAX_SPEC_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class PatternCase:
    case_id: str
    family: str
    layers: Tuple[str, str]
    width: int
    length: int
    gap: int
    role: str


@dataclass(frozen=True)
class PatternSpec:
    grid: Fraction
    domain_margin: int
    cases: Tuple[PatternCase, ...]
    source: bytes

    @property
    def source_sha256(self) -> str:
        return hashlib.sha256(self.source).hexdigest()


def _reject_nonfinite(value: str):
    raise CalibrationError(f'Non-finite JSON number {value} is not allowed')


def _object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CalibrationError(f"Pattern specification repeats key '{key}'")
        result[key] = value
    return result


def _fields(value: Any, required: Tuple[str, ...], where: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise CalibrationError(f'{where} must be a JSON object')
    if set(value) != set(required):
        missing = sorted(set(required) - set(value))
        unknown = sorted(set(value) - set(required))
        raise CalibrationError(f'{where}: missing fields {missing}, unknown fields {unknown}; '
                               f"valid fields: {', '.join(required)}")
    return value


def _positive(value: Any, where: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise CalibrationError(f'{where} must be a positive finite decimal in µm')
    try:
        decimal = Decimal(value)
        if not decimal.is_finite() or decimal <= 0 or abs(decimal.as_tuple().exponent) > 308:
            raise ValueError('outside finite decimal range')
        return Fraction(decimal)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise CalibrationError(f'{where} must be a positive finite decimal in µm') from exc


def _grid_value(value: Any, grid: Fraction, where: str) -> int:
    quantity = _positive(value, where) / grid
    if quantity.denominator != 1:
        raise CalibrationError(f'{where} must be an exact multiple of grid_um')
    if quantity > MAX_COORDINATE:
        raise CalibrationError(f'{where} exceeds the supported {MAX_COORDINATE} grid units')
    return int(quantity)


def read_patterns(path: Path) -> PatternSpec:
    """Read and validate all cheap inputs before technology loading or output creation."""
    try:
        with path.open('rb') as stream:
            source = stream.read(MAX_SPEC_BYTES + 1)
        if len(source) > MAX_SPEC_BYTES:
            raise CalibrationError(f'Pattern specification exceeds {MAX_SPEC_BYTES} bytes')
        raw = json.loads(source.decode('utf-8'), parse_float=Decimal, object_pairs_hook=_object,
                         parse_constant=_reject_nonfinite)
    except (OSError, UnicodeError, ValueError, RecursionError, InvalidOperation) as exc:
        raise CalibrationError(f"Cannot read pattern specification '{path}': {exc}") from exc
    _fields(raw, ('schema_version', 'grid_um', 'domain_margin_um', 'cases'), 'Pattern specification')
    if type(raw['schema_version']) is not int or raw['schema_version'] != 1:
        raise CalibrationError('schema_version must be 1')
    grid = _positive(raw['grid_um'], 'grid_um')
    if max(grid.numerator, grid.denominator) > 2 ** 63 - 1:
        raise CalibrationError('grid_um must fit the PEX25D signed 64-bit rational representation')
    margin = _grid_value(raw['domain_margin_um'], grid, 'domain_margin_um')
    if not isinstance(raw['cases'], list) or not 1 <= len(raw['cases']) <= MAX_CASES:
        raise CalibrationError(f'cases must contain between 1 and {MAX_CASES} explicit patterns')
    cases: List[PatternCase] = []
    identifiers = set()
    for index, data in enumerate(raw['cases']):
        where = f'cases[{index}]'
        if not isinstance(data, dict):
            raise CalibrationError(f'{where} must be a JSON object')
        family = data.get('family')
        if family not in ('parallel_plates', 'parallel_wires'):
            raise CalibrationError(f'{where}.family must be parallel_plates or parallel_wires')
        common = ('id', 'family', 'width_um', 'length_um', 'role')
        fields = ('lower_layer', 'upper_layer') if family == 'parallel_plates' else ('layer', 'gap_um')
        _fields(data, common + fields, where)
        case_id = data['id']
        if not isinstance(case_id, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', case_id) is None:
            raise CalibrationError(f'{where}.id must have 1–64 ASCII letters, digits, underscores or hyphens and start with a letter or digit')
        # Paths must stay unique on case-insensitive filesystems as well as Linux.
        if case_id.casefold() in identifiers:
            raise CalibrationError(f"{where}.id repeats '{case_id}' ignoring case")
        identifiers.add(case_id.casefold())
        if data['role'] not in ('training', 'validation'):
            raise CalibrationError(f'{where}.role must be training or validation')
        layers = ((data['lower_layer'], data['upper_layer']) if family == 'parallel_plates'
                  else (data['layer'], data['layer']))
        if any(not isinstance(layer, str) or not layer for layer in layers):
            raise CalibrationError(f'{where} layer names must be nonempty strings')
        width = _grid_value(data['width_um'], grid, where + '.width_um')
        length = _grid_value(data['length_um'], grid, where + '.length_um')
        gap = _grid_value(data['gap_um'], grid, where + '.gap_um') if family == 'parallel_wires' else 0
        xhigh = 2 * width + gap if family == 'parallel_wires' else width
        if max(xhigh, length) + margin > MAX_COORDINATE:
            raise CalibrationError(f'{where} including domain margin exceeds {MAX_COORDINATE} grid units')
        cases.append(PatternCase(case_id, family, layers, width, length, gap, data['role']))
    return PatternSpec(grid, margin, tuple(cases), source)
