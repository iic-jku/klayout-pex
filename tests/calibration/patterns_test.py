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

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import allure
from google.protobuf.json_format import MessageToJson, Parse, ParseDict
import pytest

from klayout_pex.calibration.patterns import CalibrationError, MAX_CASES, MAX_COORDINATE, MAX_SPEC_BYTES, read_patterns
from klayout_pex_protobuf.kpex.calibration import patterns_pb2
from tests.common.calibration import read_pattern_data as read_data

pytestmark = allure.parent_suite('Unit Tests')




@pytest.mark.parametrize('value,expected', [('0.0009', None), ('0.001', 1), ('0.002', 2)])
def test_minimum_drawn_dimension_is_exactly_one_grid_unit(tmp_path: Path, pattern_data: Dict[str, Any],
                                                         value: str, expected: Optional[int]):
    # Just below the minimum is off-grid, not a shape that may be silently rounded away.
    pattern_data['patterns'][0]['width_um'] = value
    if expected is None:
        with pytest.raises(CalibrationError, match='exact multiple'):
            read_data(tmp_path, pattern_data)
    else:
        assert read_data(tmp_path, pattern_data).patterns[0].width == expected


@pytest.mark.parametrize('value', ['0', '-1', 'NaN', 'Infinity', '-Infinity', '', '1e999999'])
def test_nonpositive_nonfinite_and_nonnumeric_dimensions_are_rejected(tmp_path: Path, pattern_data: Dict[str, Any],
                                                                      value: Any):
    pattern_data['patterns'][1]['parallel_wires']['gap_um'] = value
    with pytest.raises(CalibrationError, match='positive finite decimal'):
        read_data(tmp_path, pattern_data)


def test_decimal_strings_and_exponents_preserve_exact_grid(tmp_path: Path, pattern_data: Dict[str, Any]):
    # Decimal strings retain both scientific notation and values that binary float
    # would round; the schema does not coerce numeric JSON tokens to strings.
    pattern_data['grid_um'] = '1e-4'
    pattern_data['domain_margin_um'] = '0.1'
    wire = pattern_data['patterns'][1]
    wire.update(width_um='0.3', length_um='3e-1')
    wire['parallel_wires']['gap_um'] = '.0001'
    pattern_data['patterns'] = [wire]
    spec = read_data(tmp_path, pattern_data)
    assert (spec.patterns[0].width, spec.patterns[0].length, spec.patterns[0].gap) == (3000, 3000, 1)
    wire['width_um'] = '0.3000000000000000000000000000000000001'
    with pytest.raises(CalibrationError, match='exact multiple'):
        read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('delta,accepted', [(-1, True), (0, True), (1, False)])
def test_combined_geometry_and_margin_obey_coordinate_limit(tmp_path: Path, pattern_data: Dict[str, Any],
                                                           delta: int, accepted: bool):
    # Width can fit alone while width plus margin overflows KLayout's XY coordinate.
    pattern_data['grid_um'] = '1'
    pattern_data['domain_margin_um'] = '1'
    pattern_data['patterns'] = pattern_data['patterns'][:1]
    pattern_data['patterns'][0]['width_um'] = str(MAX_COORDINATE - 1 + delta)
    if accepted:
        assert read_data(tmp_path, pattern_data).patterns[0].width == MAX_COORDINATE - 1 + delta
    else:
        with pytest.raises(CalibrationError, match='including domain margin exceeds'):
            read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('case_id', ['../outside', 'x/y', 'a.b', ' name', 'x\n', 'µm'])
def test_case_names_cannot_escape_or_confuse_output_paths(tmp_path: Path, pattern_data: Dict[str, Any], case_id: str):
    pattern_data['patterns'][0]['id'] = case_id
    with pytest.raises(CalibrationError, match='id must have'):
        read_data(tmp_path, pattern_data)


def test_names_are_unique_on_case_insensitive_filesystems(tmp_path: Path, pattern_data: Dict[str, Any]):
    pattern_data['patterns'][1]['id'] = 'PLATES'
    with pytest.raises(CalibrationError, match='ignoring case'):
        read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('change,expected', [
    ({'schema_version': True}, 'schema_version'),
    ({'schema_version': 2}, 'schema_version'),
    ({'patterns': []}, 'between 1'),
    ({'extra': 3}, 'extra'),
    ({'grid_um': '1e-30'}, '64-bit rational'),
    ({'domain_margin_um': '0'}, 'positive finite'),
])
def test_invalid_top_level_contract(tmp_path: Path, pattern_data: Dict[str, Any], change: Dict[str, Any], expected: str):
    pattern_data.update(change)
    with pytest.raises(CalibrationError, match=expected):
        read_data(tmp_path, pattern_data)


def test_duplicate_json_keys_are_rejected(tmp_path: Path, pattern_data: Dict[str, Any]):
    path = tmp_path / 'spec.json'
    source = json.dumps(pattern_data).replace('"grid_um": "0.001"', '"grid_um": "0.001", "grid_um": "0.0001"')
    path.write_text(source, encoding='utf-8')
    with pytest.raises(CalibrationError, match='grid_um'):
        read_patterns(path)


@pytest.mark.parametrize('text', ['{"x":NaN}', '[', '{"x":1e99999999999999999999999}'])
def test_malformed_or_nonfinite_json_is_a_domain_error(tmp_path: Path, text: str):
    path = tmp_path / 'spec.json'
    path.write_text(text, encoding='utf-8')
    with pytest.raises(CalibrationError):
        read_patterns(path)


@pytest.mark.parametrize('count,accepted', [(0, False), (1, True), (MAX_CASES, True), (MAX_CASES + 1, False)])
def test_case_count_boundaries(tmp_path: Path, pattern_data: Dict[str, Any], count: int, accepted: bool):
    template = pattern_data['patterns'][0]
    pattern_data['patterns'] = [dict(template, id=f'case_{index}') for index in range(count)]
    if accepted:
        assert len(read_data(tmp_path, pattern_data).patterns) == count
    else:
        with pytest.raises(CalibrationError, match='between 1'):
            read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('extra,accepted', [(-1, True), (0, True), (1, False)])
def test_input_byte_limit_includes_insignificant_whitespace(tmp_path: Path, pattern_data: Dict[str, Any],
                                                          extra: int, accepted: bool):
    path = tmp_path / 'patterns.json'
    source = json.dumps(pattern_data).encode('utf-8')
    path.write_bytes(source + b' ' * (MAX_SPEC_BYTES - len(source) + extra))
    if accepted:
        assert len(read_patterns(path).source) == MAX_SPEC_BYTES + extra
    else:
        with pytest.raises(CalibrationError, match='bytes'):
            read_patterns(path)


@pytest.mark.parametrize('delta,accepted', [(-1, True), (0, True), (1, False)])
def test_wire_pair_extent_includes_both_widths_and_the_gap(tmp_path: Path, pattern_data: Dict[str, Any],
                                                         delta: int, accepted: bool):
    pattern_data['grid_um'] = '1'
    pattern_data['domain_margin_um'] = '1'
    wire = pattern_data['patterns'][1]
    width = (MAX_COORDINATE - 3) // 2
    gap = MAX_COORDINATE - 2 * width - 1 + delta
    wire.update(width_um=str(width), length_um='4')
    wire['parallel_wires']['gap_um'] = str(gap)
    pattern_data['patterns'] = [wire]
    if accepted:
        assert read_data(tmp_path, pattern_data).patterns[0].gap == gap
    else:
        with pytest.raises(CalibrationError, match='including domain margin exceeds'):
            read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('offset,accepted', [(-1, True), (0, False), (1, False)])
def test_native_positive_endpoint_is_excluded_before_technology_loading(
        tmp_path: Path, pattern_data: Dict[str, Any], offset: int, accepted: bool):
    # The int32 endpoint itself is unsafe for native booleans, not only overflow.
    pattern_data['grid_um'] = '1'
    pattern_data['domain_margin_um'] = '1'
    pattern_data['patterns'] = pattern_data['patterns'][:1]
    pattern_data['patterns'][0]['width_um'] = str(2**31 - 2 + offset)
    if accepted:
        read_data(tmp_path, pattern_data)
    else:
        with pytest.raises(CalibrationError, match='exceeds'):
            read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('preserve_field_names', [False, True])
@pytest.mark.parametrize('line_ending', ['\n', '\r\n'], ids=['lf', 'crlf'])
def test_pattern_specification_is_protobuf_json_with_supported_field_aliases(
        tmp_path: Path, pattern_data: Dict[str, Any], preserve_field_names: bool, line_ending: str):
    message = ParseDict(pattern_data, patterns_pb2.PatternSetSpecification())
    encoded = MessageToJson(message, preserving_proto_field_name=preserve_field_names, sort_keys=True)
    assert Parse(encoded, patterns_pb2.PatternSetSpecification()) == message
    path = tmp_path / 'patterns.json'
    # Source identity includes line endings. Exercise both encodings on every
    # platform instead of relying on write_text's platform-specific translation.
    source = encoded.replace('\n', line_ending).encode('utf-8')
    path.write_bytes(source)
    spec = read_patterns(path)
    assert spec.source == source
    assert spec.source_sha256 == hashlib.sha256(source).hexdigest()
    assert [case.family for case in spec.patterns] == [patterns_pb2.PARALLEL_PLATES, patterns_pb2.PARALLEL_WIRES]
    assert [case.role for case in spec.patterns] == [patterns_pb2.TRAINING, patterns_pb2.VALIDATION]
    assert (spec.patterns[0].width, spec.patterns[1].gap) == (2000, 200)
    assert ('grid_um' if preserve_field_names else 'gridUm') in encoded


@pytest.mark.parametrize('path', [
    ('schema_version',), ('grid_um',), ('domain_margin_um',), ('patterns',),
    ('patterns', 0, 'id'), ('patterns', 0, 'role'), ('patterns', 0, 'width_um'), ('patterns', 0, 'length_um'),
    ('patterns', 0, 'parallel_plates'), ('patterns', 0, 'parallel_plates', 'lower_layer'),
    ('patterns', 0, 'parallel_plates', 'upper_layer'), ('patterns', 1, 'parallel_wires'),
    ('patterns', 1, 'parallel_wires', 'layer'), ('patterns', 1, 'parallel_wires', 'gap_um'),
])
@pytest.mark.parametrize('use_null', [False, True], ids=['missing', 'null'])
def test_missing_or_null_required_input_cannot_become_implicit_geometry(
        tmp_path: Path, pattern_data: Dict[str, Any], path: Tuple[Any, ...], use_null: bool):
    # Proto3 maps null and missing fields to defaults. Those defaults must not
    # invent dimensions, layers, a geometry family or a training/validation role.
    parent = pattern_data
    for key in path[:-1]:
        parent = parent[key]
    if use_null:
        parent[path[-1]] = None
    else:
        del parent[path[-1]]
    with pytest.raises(CalibrationError):
        read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('field', ['grid_um', 'domain_margin_um', 'width_um', 'length_um', 'gap_um'])
@pytest.mark.parametrize('value', [1, 0.001, True, False, [], {}])
def test_exact_dimensions_require_json_strings(
        tmp_path: Path, pattern_data: Dict[str, Any], field: str, value: Any):
    if field in ('grid_um', 'domain_margin_um'):
        parent = pattern_data
    elif field == 'gap_um':
        parent = pattern_data['patterns'][1]['parallel_wires']
    else:
        parent = pattern_data['patterns'][0]
    parent[field] = value
    with pytest.raises(CalibrationError, match=field):
        read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('location', ['specification', 'case', 'geometry'])
def test_unknown_schema_fields_are_rejected_at_each_input_level(
        tmp_path: Path, pattern_data: Dict[str, Any], location: str):
    parent = {'specification': pattern_data, 'case': pattern_data['patterns'][0],
              'geometry': pattern_data['patterns'][0]['parallel_plates']}[location]
    parent['unexpected_field'] = 'not understood'
    with pytest.raises(CalibrationError, match='unexpected_field'):
        read_data(tmp_path, pattern_data)


def test_mutually_exclusive_geometries_cannot_both_be_supplied(tmp_path: Path, pattern_data: Dict[str, Any]):
    # Both shapes are individually valid. Accepting either would silently ignore
    # the user's other physical definition, so the protobuf oneof must reject it.
    pattern_data['patterns'][0]['parallel_wires'] = {'layer': 'M1', 'gap_um': '1'}
    with pytest.raises(CalibrationError, match='geometry'):
        read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('value', ['training', 'UNKNOWN_ROLE', 0, -1, 123456789, True, False, [], {}])
def test_invalid_role_names_types_and_unknown_numeric_values_are_rejected(
        tmp_path: Path, pattern_data: Dict[str, Any], value: Any):
    # Proto3 retains unknown numeric enum values for forward compatibility. A
    # calibration operation must still refuse a role it cannot interpret.
    pattern_data['patterns'][0]['role'] = value
    with pytest.raises(CalibrationError, match='role'):
        read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('role', [patterns_pb2.TRAINING, patterns_pb2.VALIDATION])
def test_known_numeric_roles_follow_standard_protobuf_json(
        tmp_path: Path, pattern_data: Dict[str, Any], role: int):
    pattern_data['patterns'][0]['role'] = role
    assert read_data(tmp_path, pattern_data).patterns[0].role == role


@pytest.mark.parametrize('value', [None, 'case', [], 1])
def test_cases_cannot_contain_nonmessage_elements(tmp_path: Path, pattern_data: Dict[str, Any], value: Any):
    pattern_data['patterns'][0] = value
    with pytest.raises(CalibrationError):
        read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('path,alias,value', [
    ((), 'gridUm', '0.0001'),
    (('patterns', 0), 'widthUm', '1'),
    (('patterns', 0), 'parallelPlates', {'lower_layer': 'M1', 'upper_layer': 'M2'}),
    (('patterns', 0, 'parallel_plates'), 'lowerLayer', 'M1'),
])
@pytest.mark.parametrize('alias_first', [False, True])
def test_field_aliases_cannot_supply_the_same_protobuf_field_twice(
        tmp_path: Path, pattern_data: Dict[str, Any], path: Tuple[Any, ...], alias: str, value: Any, alias_first: bool):
    # Conflicting spellings otherwise make the result depend on JSON key order,
    # even though both names address one authoritative schema field.
    parent = pattern_data
    for key in path:
        parent = parent[key]
    if alias_first:
        fields = dict(parent)
        parent.clear()
        parent[alias] = value
        parent.update(fields)
    else:
        parent[alias] = value
    with pytest.raises(CalibrationError):
        read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('token,expected', [
    ('0.999', None), ('1', patterns_pb2.TRAINING), ('1.0', patterns_pb2.TRAINING), ('1.001', None),
    ('1.999', None), ('2', patterns_pb2.VALIDATION), ('2e0', patterns_pb2.VALIDATION), ('2.001', None),
    ('1.0000000000000000000000001', None), ('2.0000000000000000000000001', None),
])
def test_numeric_role_values_are_integral_without_truncation_or_rounding(
        tmp_path: Path, pattern_data: Dict[str, Any], token: str, expected: Optional[int]):
    # Some protobuf versions truncate enum floats. Even a token which Python
    # float rounds to 1 must not silently select TRAINING instead of being rejected.
    pattern_data['patterns'][0]['role'] = 'ENUM_TOKEN'
    path = tmp_path / 'patterns.json'
    path.write_text(json.dumps(pattern_data).replace('"ENUM_TOKEN"', token), encoding='utf-8')
    if expected is None:
        with pytest.raises(CalibrationError, match='role'):
            read_patterns(path)
    else:
        assert read_patterns(path).patterns[0].role == expected


@pytest.mark.parametrize('length,accepted', [(0, False), (1, True), (64, True), (65, False)])
def test_case_identifier_length_boundaries(
        tmp_path: Path, pattern_data: Dict[str, Any], length: int, accepted: bool):
    pattern_data['patterns'][0]['id'] = 'A' * length
    if accepted:
        assert read_data(tmp_path, pattern_data).patterns[0].case_id == 'A' * length
    else:
        with pytest.raises(CalibrationError, match='id must have'):
            read_data(tmp_path, pattern_data)


@pytest.mark.parametrize('token,accepted', [
    ('1', True), ('1.0', True), ('1e0', True),
    ('0.999', False), ('1.001', False), ('1.0000000000000000000000001', False),
])
def test_schema_version_cannot_be_rounded_to_a_supported_integer(
        tmp_path: Path, pattern_data: Dict[str, Any], token: str, accepted: bool):
    pattern_data['schema_version'] = 'VERSION_TOKEN'
    path = tmp_path / 'patterns.json'
    path.write_text(json.dumps(pattern_data).replace('"VERSION_TOKEN"', token), encoding='utf-8')
    if accepted:
        assert len(read_patterns(path).patterns) == 2
    else:
        with pytest.raises(CalibrationError):
            read_patterns(path)


@pytest.mark.parametrize('token', ['NaN', 'Infinity', '-Infinity', '1e999999', '-1e999999', '1e-999999'])
def test_nonfinite_or_underflowed_role_tokens_are_domain_errors(
        tmp_path: Path, pattern_data: Dict[str, Any], token: str):
    pattern_data['patterns'][0]['role'] = 'ENUM_TOKEN'
    path = tmp_path / 'patterns.json'
    path.write_text(json.dumps(pattern_data).replace('"ENUM_TOKEN"', token), encoding='utf-8')
    with pytest.raises(CalibrationError):
        read_patterns(path)


@pytest.mark.parametrize('include_patterns', [False, True])
def test_case_collection_is_output_only(
        tmp_path: Path, pattern_data: Dict[str, Any], include_patterns: bool):
    # Prepared manifest cases are outputs. Accepting that field in a pattern
    # specification could silently ignore the user's intended input collection.
    pattern_data['cases'] = pattern_data['patterns']
    if not include_patterns:
        del pattern_data['patterns']
    with pytest.raises(CalibrationError, match='field named "cases"'):
        read_data(tmp_path, pattern_data)
