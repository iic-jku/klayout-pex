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

"""Boundary cases protect geometry and file identity before any technology is loaded."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

import allure
import pytest

from klayout_pex.calibration.patterns import CalibrationError, MAX_CASES, MAX_COORDINATE, MAX_SPEC_BYTES, PatternSpec, read_patterns

pytestmark = allure.parent_suite('Unit Tests')


def read_data(tmp_path: Path, data: Dict[str, Any]) -> PatternSpec:
    path = tmp_path / 'patterns.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return read_patterns(path)


@pytest.mark.parametrize('value,expected', [('0.0009', None), ('0.001', 1), ('0.002', 2)])
def test_minimum_drawn_dimension_is_exactly_one_grid_unit(tmp_path: Path, pattern_data: Dict[str, Any],
                                                         value: str, expected: Optional[int]):
    # Just below the minimum is off-grid, not a shape that may be silently rounded away.
    pattern_data['cases'][0]['width_um'] = value
    if expected is None:
        with pytest.raises(CalibrationError, match='exact multiple'):
            read_data(tmp_path, pattern_data)
    else:
        assert read_data(tmp_path, pattern_data).cases[0].width == expected


@pytest.mark.parametrize('value', [0, -1, True, False, 'NaN', 'Infinity', '-Infinity', '', [], None, '1e999999'])
def test_nonpositive_nonfinite_and_nonnumeric_dimensions_are_rejected(tmp_path: Path, pattern_data: Dict[str, Any],
                                                                      value: Any):
    pattern_data['cases'][1]['gap_um'] = value
    with pytest.raises(CalibrationError, match='positive finite decimal'):
        read_data(tmp_path, pattern_data)


def test_decimal_json_numbers_and_exponents_preserve_exact_grid(tmp_path: Path):
    text = ('{"schema_version":1,"grid_um":1e-4,"domain_margin_um":0.1,"cases":'
            '[{"id":"w","family":"parallel_wires","layer":"M1","width_um":0.3,'
            '"length_um":3e-1,"gap_um":".0001","role":"training"}]}')
    path = tmp_path / 'spec.json'
    path.write_text(text, encoding='utf-8')
    spec = read_patterns(path)
    assert (spec.cases[0].width, spec.cases[0].length, spec.cases[0].gap) == (3000, 3000, 1)


@pytest.mark.parametrize('delta,accepted', [(-1, True), (0, True), (1, False)])
def test_combined_geometry_and_margin_obey_coordinate_limit(tmp_path: Path, pattern_data: Dict[str, Any],
                                                           delta: int, accepted: bool):
    # Width can fit alone while width plus margin overflows KLayout's XY coordinate.
    pattern_data['grid_um'] = '1'
    pattern_data['domain_margin_um'] = '1'
    pattern_data['cases'] = pattern_data['cases'][:1]
    pattern_data['cases'][0]['width_um'] = str(MAX_COORDINATE - 1 + delta)
    if accepted:
        assert read_data(tmp_path, pattern_data).cases[0].width == MAX_COORDINATE - 1 + delta
    else:
        with pytest.raises(CalibrationError, match='including domain margin exceeds'):
            read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('case_id', ['../outside', 'x/y', 'a.b', ' name', 'x\n', 'µm', 'x' * 65])
def test_case_names_cannot_escape_or_confuse_output_paths(tmp_path: Path, pattern_data: Dict[str, Any], case_id: str):
    pattern_data['cases'][0]['id'] = case_id
    with pytest.raises(CalibrationError, match='id must have'):
        read_data(tmp_path, pattern_data)


def test_names_are_unique_on_case_insensitive_filesystems(tmp_path: Path, pattern_data: Dict[str, Any]):
    pattern_data['cases'][1]['id'] = 'PLATES'
    with pytest.raises(CalibrationError, match='ignoring case'):
        read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('change,expected', [
    ({'schema_version': True}, 'schema_version'),
    ({'schema_version': 2}, 'schema_version'),
    ({'cases': []}, 'between 1'),
    ({'extra': 3}, 'unknown fields'),
    ({'grid_um': '1e-30'}, '64-bit rational'),
    ({'domain_margin_um': '0'}, 'positive finite'),
])
def test_invalid_top_level_contract(tmp_path: Path, pattern_data: Dict[str, Any], change: Dict[str, Any], expected: str):
    pattern_data.update(change)
    with pytest.raises(CalibrationError, match=expected):
        read_data(tmp_path, pattern_data)


def test_duplicate_json_keys_are_rejected(tmp_path: Path):
    path = tmp_path / 'spec.json'
    path.write_text('{"grid_um":1,"grid_um":2}', encoding='utf-8')
    with pytest.raises(CalibrationError, match="repeats key 'grid_um'"):
        read_patterns(path)


@pytest.mark.parametrize('text', ['{"x":NaN}', '[', '{"x":1e99999999999999999999999}'])
def test_malformed_or_nonfinite_json_is_a_domain_error(tmp_path: Path, text: str):
    path = tmp_path / 'spec.json'
    path.write_text(text, encoding='utf-8')
    with pytest.raises(CalibrationError):
        read_patterns(path)


@pytest.mark.parametrize('count,accepted', [(0, False), (1, True), (MAX_CASES, True), (MAX_CASES + 1, False)])
def test_case_count_boundaries(tmp_path: Path, pattern_data: Dict[str, Any], count: int, accepted: bool):
    template = pattern_data['cases'][0]
    pattern_data['cases'] = [dict(template, id=f'case_{index}') for index in range(count)]
    if accepted:
        assert len(read_data(tmp_path, pattern_data).cases) == count
    else:
        with pytest.raises(CalibrationError, match='between 1'):
            read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('extra,accepted', [(0, True), (1, False)])
def test_input_byte_limit_includes_insignificant_whitespace(tmp_path: Path, pattern_data: Dict[str, Any],
                                                          extra: int, accepted: bool):
    path = tmp_path / 'patterns.json'
    source = json.dumps(pattern_data).encode('utf-8')
    path.write_bytes(source + b' ' * (MAX_SPEC_BYTES - len(source) + extra))
    if accepted:
        assert len(read_patterns(path).source) == MAX_SPEC_BYTES
    else:
        with pytest.raises(CalibrationError, match='bytes'):
            read_patterns(path)


@pytest.mark.parametrize('delta,accepted', [(-1, True), (0, True), (1, False)])
def test_wire_pair_extent_includes_both_widths_and_the_gap(tmp_path: Path, pattern_data: Dict[str, Any],
                                                         delta: int, accepted: bool):
    pattern_data['grid_um'] = '1'
    pattern_data['domain_margin_um'] = '1'
    wire = pattern_data['cases'][1]
    wire.update(width_um=str((MAX_COORDINATE - 3) // 2), gap_um=str(2 + delta), length_um='4')
    pattern_data['cases'] = [wire]
    if accepted:
        assert read_data(tmp_path, pattern_data).cases[0].gap == 2 + delta
    else:
        with pytest.raises(CalibrationError, match='including domain margin exceeds'):
            read_data(tmp_path, pattern_data)
