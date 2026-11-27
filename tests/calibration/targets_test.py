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

"""Targets must identify actual rows, proven physical profiles and relevant geometries."""

import copy
import json
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import allure
from google.protobuf.json_format import Parse
import pytest

from kpex.calibration.patterns import CalibrationError, MAX_COORDINATE
from kpex.calibration.prepare import prepare_calibration
from kpex.kpex_cli import KpexCLI
from kpex.pdk_config import PDK
from kpex.pex25d.reader import read_pex25d_text
from kpex.tech_info import TechInfo
from kpex_protobuf.kpex.calibration.preparation_pb2 import CalibrationManifest
from kpex_protobuf.kpex.calibration.targets_pb2 import HALO_NORMALIZED, UNSCALED
from tests.common.calibration import read_pattern_data
from tests.common.cli_runner import run_cli

pytestmark = allure.parent_suite('Unit Tests')


def binding(number: int) -> Dict[str, str]:
    return {'canonical_layer': f'routing{number}', 'process_profile': f'M{number}'}


@pytest.fixture
def targeted_data(pattern_data: Dict[str, Any]) -> Dict[str, Any]:
    data = copy.deepcopy(pattern_data)
    data['fringe_scale_mode'] = 'HALO_NORMALIZED'
    data['targets'] = [
        {'id': 'ground', 'substrate': {'layer': binding(1), 'parameters': ['AREA', 'PERIMETER']}},
        {'id': 'area', 'overlap': {'top': binding(2), 'bottom': binding(1)}},
        {'id': 'side', 'sidewall': {'layer': binding(2), 'parameters': ['COEFFICIENT', 'OFFSET']}},
        {'id': 'up', 'sideoverlap': {'edge': binding(1), 'receiver': binding(2)}},
        {'id': 'down', 'sideoverlap': {'edge': binding(2), 'receiver': binding(1)}},
    ]
    data['patterns'][0]['target_ids'] = ['area', 'up', 'down']
    data['patterns'][1]['target_ids'] = ['side']
    data['patterns'].extend([
        {'id': 'substrate', 'width_um': '2', 'length_um': '4', 'role': 'TRAINING',
         'substrate': {'layer': 'M1'}, 'target_ids': ['ground']},
        {'id': 'up', 'width_um': '2', 'length_um': '4', 'role': 'TRAINING', 'target_ids': ['up', 'area', 'ground'],
         'directional_fringe': {'edge_layer': 'M1', 'receiver_layer': 'M2', 'receiver_width_um': '4', 'lateral_offset_um': '-3'}},
        {'id': 'down', 'width_um': '2', 'length_um': '4', 'role': 'VALIDATION', 'target_ids': ['down'],
         'directional_fringe': {'edge_layer': 'M2', 'receiver_layer': 'M1', 'receiver_width_um': '4', 'lateral_offset_um': '-3'}},
    ])
    return data


def test_all_table_families_have_typed_targets_and_physical_evidence(
        tmp_path: Path, targeted_data: Dict[str, Any], targeted_technology: TechInfo):
    spec = read_pattern_data(tmp_path, targeted_data)
    result = prepare_calibration(targeted_technology, spec, tmp_path / 'prepared')
    manifest = Parse(result.manifest_path.read_text(encoding='utf-8'), CalibrationManifest())
    assert list(manifest.targets) == [target.definition for target in spec.targets]
    assert manifest.technology_side_halo_um == 8.0
    assert manifest.domain_margin_grid == 2000  # The numerical domain is not the extraction halo.
    assert manifest.fringe_scale_mode == HALO_NORMALIZED
    assert [list(case.target_ids) for case in manifest.cases] == [case['target_ids'] for case in targeted_data['patterns']]
    assert [list(case.measurement.conductor_order) for case in manifest.cases] == [['A', 'B'], ['A', 'B'], ['A'], ['A', 'B'], ['A', 'B']]
    assert all(case.measurement.reference.profile == 'substrate' for case in manifest.cases)
    assert (manifest.cases[3].dimensions_grid.receiver_width, manifest.cases[3].dimensions_grid.lateral_offset) == (4000, -3000)
    assert manifest.stage == CalibrationManifest.PREPARED


@pytest.mark.parametrize('offset,xlow,xhigh', [('-3', -1000, 3000), ('-0.001', 1999, 5999), ('0', 2000, 6000), ('0.001', 2001, 6001)])
@pytest.mark.parametrize('index', [3, 4], ids=['receiver-above', 'receiver-below'])
def test_directional_fringe_keeps_receiver_width_direction_and_exact_signed_offset(
        tmp_path: Path, targeted_data: Dict[str, Any], targeted_technology: TechInfo,
        offset: str, xlow: int, xhigh: int, index: int):
    # Gap/flush/overlap boundaries affect the fringe integral and must not be rounded or mirrored.
    targeted_data['patterns'][index]['directional_fringe']['lateral_offset_um'] = offset
    result = prepare_calibration(targeted_technology, read_pattern_data(tmp_path, targeted_data), tmp_path / 'prepared')
    case = targeted_data['patterns'][index]
    file = read_pex25d_text((result.manifest_path.parent / f"case_{case['id']}.pex25d").read_bytes(), 'prepared')
    assert [(shape.conductor, shape.layer) for shape in file.shapes] == [('A', case['directional_fringe']['edge_layer']), ('B', case['directional_fringe']['receiver_layer'])]
    assert [(shape.box.lower_left.x, shape.box.upper_right.x, shape.box.upper_right.y) for shape in file.shapes] == [(0, 2000, 4000), (xlow, xhigh, 4000)]


@pytest.mark.parametrize('parameters', [[], ['PARAMETER_UNSPECIFIED'], [0], [3], [-1], [True], [False], ['AREA', 'AREA'], ['missing']])
def test_substrate_parameter_selection_is_explicit_and_valid(
        tmp_path: Path, targeted_data: Dict[str, Any], parameters: Any):
    targeted_data['targets'][0]['substrate']['parameters'] = parameters
    with pytest.raises(CalibrationError):
        read_pattern_data(tmp_path, targeted_data)


@pytest.mark.parametrize('parameters', [[], [0], [3], [-1], [True], ['OFFSET', 'OFFSET'], ['missing']])
def test_sidewall_parameter_selection_is_explicit_and_valid(
        tmp_path: Path, targeted_data: Dict[str, Any], parameters: Any):
    targeted_data['targets'][2]['sidewall']['parameters'] = parameters
    with pytest.raises(CalibrationError):
        read_pattern_data(tmp_path, targeted_data)


@pytest.mark.parametrize('value', [None, 'FRINGE_SCALE_UNSPECIFIED', 0, 3, -1, True, False, 'true', 'false', 1.5])
def test_targeted_preparation_does_not_guess_or_coerce_fringe_scale(
        tmp_path: Path, targeted_data: Dict[str, Any], value: Any):
    targeted_data['fringe_scale_mode'] = value
    with pytest.raises(CalibrationError):
        read_pattern_data(tmp_path, targeted_data)


@pytest.mark.parametrize('mode,expected', [('HALO_NORMALIZED', HALO_NORMALIZED), ('UNSCALED', UNSCALED)])
def test_scale_mode_is_recorded_without_changing_the_physical_geometry(
        tmp_path: Path, targeted_data: Dict[str, Any], targeted_technology: TechInfo, mode: str, expected: int):
    targeted_data['fringe_scale_mode'] = mode
    result = prepare_calibration(targeted_technology, read_pattern_data(tmp_path, targeted_data), tmp_path / 'prepared')
    manifest = Parse(result.manifest_path.read_text(encoding='utf-8'), CalibrationManifest())
    assert manifest.fringe_scale_mode == expected
    assert manifest.cases[3].dimensions_grid.lateral_offset == -3000


@pytest.mark.parametrize('reference', ['missing', 'GROUND', 'side', 'down'])
def test_unknown_or_unrelated_target_references_fail_before_technology_loading(
        tmp_path: Path, targeted_data: Dict[str, Any], reference: str):
    targeted_data['patterns'][3]['target_ids'] = [reference]
    read_path = tmp_path / 'patterns.json'
    # The CLI must catch target errors before loading the selected catalog or creating output.
    read_path.write_text(json.dumps(targeted_data), encoding='utf-8')
    with mock.patch('kpex.calibration.cli.TechInfo.from_catalog') as load:
        code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'prepare', '--pdk', 'sky130A', '--patterns', str(read_path), '--out-dir', str(tmp_path / 'bad')])
    assert code != 0, output
    load.assert_not_called()
    assert not (tmp_path / 'bad').exists()


@pytest.mark.parametrize('mutation', ['duplicate-id', 'casefold-id', 'duplicate-row', 'unused', 'duplicate-ref', 'missing-quantity', 'conflicting-quantity', 'unknown-field'])
def test_target_sets_are_unambiguous(tmp_path: Path, targeted_data: Dict[str, Any], mutation: str):
    if mutation in ('duplicate-id', 'casefold-id', 'duplicate-row', 'unused'):
        extra = copy.deepcopy(targeted_data['targets'][0])
        extra['id'] = {'duplicate-id': 'ground', 'casefold-id': 'GROUND', 'duplicate-row': 'extra', 'unused': 'unused'}[mutation]
        if mutation == 'unused':
            extra['substrate']['layer'] = binding(2)
        targeted_data['targets'].append(extra)
    elif mutation == 'duplicate-ref':
        targeted_data['patterns'][2]['target_ids'] = ['ground', 'ground']
    elif mutation == 'missing-quantity':
        targeted_data['targets'][0] = {'id': 'ground'}
    elif mutation == 'conflicting-quantity':
        targeted_data['targets'][0]['overlap'] = targeted_data['targets'][1]['overlap']
    elif mutation == 'unknown-field':
        targeted_data['targets'][0]['untyped_parameters'] = {}
    else:
        raise AssertionError(mutation)
    with pytest.raises(CalibrationError):
        read_pattern_data(tmp_path, targeted_data)


@pytest.mark.parametrize('problem', ['missing-row', 'duplicate-row', 'wrong-canonical', 'unproven-profile', 'reversed-overlap', 'wrong-direction', 'nonfinite-offset'])
def test_binding_requires_one_actual_row_and_the_explicit_computed_mapping(
        tmp_path: Path, targeted_data: Dict[str, Any], targeted_technology: TechInfo, problem: str):
    tech = targeted_technology.tech
    caps = tech.process_parasitics.capacitance
    if problem == 'missing-row':
        del caps.substrates[:]
    elif problem == 'duplicate-row':
        caps.substrates.add().CopyFrom(caps.substrates[0])
    elif problem == 'wrong-canonical':
        targeted_data['targets'][0]['substrate']['layer']['canonical_layer'] = 'M1'
    elif problem == 'unproven-profile':
        tech.lvs_computed_layers[0].original_layer_name = 'different-canonical'
    elif problem == 'reversed-overlap':
        row = caps.overlaps[0]
        row.top_layer_name, row.bottom_layer_name = row.bottom_layer_name, row.top_layer_name
    elif problem == 'wrong-direction':
        del caps.sideoverlaps[1]
    elif problem == 'nonfinite-offset':
        caps.sidewalls[0].offset = float('nan')
    else:
        raise AssertionError(problem)
    with pytest.raises(CalibrationError):
        prepare_calibration(TechInfo(tech, dielectric_filter=None), read_pattern_data(tmp_path, targeted_data), tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()


@pytest.mark.parametrize('separation,accepted', [(-0.001, False), (0.0, False), (0.001, True)])
def test_fringe_vertical_profiles_need_a_strict_dielectric_gap(
        tmp_path: Path, targeted_data: Dict[str, Any], targeted_technology: TechInfo, separation: float, accepted: bool):
    # Even with a lateral gap, coincident Z profiles would represent a different calibration family.
    targeted_technology.process_metal_layers[1].metal_layer.z = 1.2 + separation
    # Omit targets/plates so this specifically probes the fringe geometry validator.
    targeted_data['targets'] = []
    targeted_data['patterns'] = [targeted_data['patterns'][3]]
    targeted_data['patterns'][0]['target_ids'] = []
    if accepted:
        prepare_calibration(targeted_technology, read_pattern_data(tmp_path, targeted_data), tmp_path / 'good')
    else:
        with pytest.raises(CalibrationError, match='nonzero dielectric gap'):
            prepare_calibration(targeted_technology, read_pattern_data(tmp_path, targeted_data), tmp_path / 'bad')
        assert not (tmp_path / 'bad').exists()


@pytest.mark.parametrize('field', ['receiver_width_um', 'lateral_offset_um'])
@pytest.mark.parametrize('value', ['', 'NaN', 'Infinity', '0.0001', 1, True, False, None])
def test_new_geometry_dimensions_are_exact_and_required(
        tmp_path: Path, targeted_data: Dict[str, Any], field: str, value: Any):
    targeted_data['patterns'][3]['directional_fringe'][field] = value
    with pytest.raises(CalibrationError):
        read_pattern_data(tmp_path, targeted_data)


@pytest.mark.parametrize('delta,accepted', [(-1, True), (0, True), (1, False)])
@pytest.mark.parametrize('side', ['left', 'right'])
def test_fringe_offset_and_receiver_sum_respect_native_bounds_with_margin(
        tmp_path: Path, targeted_data: Dict[str, Any], delta: int, accepted: bool, side: str):
    data = targeted_data
    data['grid_um'], data['domain_margin_um'] = '1', '2'
    data['targets'] = []
    case = data['patterns'][3]
    case.update(width_um='1', length_um='1', target_ids=[])
    geometry = case['directional_fringe']
    geometry['receiver_width_um'] = '1'
    # The raw offset is legal; only the assembled receiver plus domain crosses the bound.
    offset = MAX_COORDINATE - 4 + delta if side == 'right' else -MAX_COORDINATE + 1 - delta
    geometry['lateral_offset_um'] = str(offset)
    data['patterns'] = [case]
    if accepted:
        assert read_pattern_data(tmp_path, data).patterns[0].lateral_offset == offset
    else:
        with pytest.raises(CalibrationError, match='including domain margin exceeds'):
            read_pattern_data(tmp_path, data)


@pytest.mark.parametrize('pdk,canonical,profile,lower', [
    (PDK.GF180MCUD, 'Metal4', 'metal4_n_cap', 'Metal3'),
    (PDK.IHP_SG13G2, 'Metal5', 'metal5_n_cap', 'Metal4'),
    (PDK.IHP_SG13CMOS5L, 'Metal4', 'Metal4', 'Metal3'),
    (PDK.SKY130A, 'met3', 'met3_ncap', 'met2'),
])
def test_all_bundled_pdks_resolve_actual_rows_and_explicit_profile_variants(
        tmp_path: Path, pdk: PDK, canonical: str, profile: str, lower: str):
    # These named physical variants catch accidental equality matching between
    # canonical row keys and process profiles; they are deliberately different.
    upper_binding = {'canonical_layer': canonical, 'process_profile': profile}
    lower_binding = {'canonical_layer': lower, 'process_profile': lower}
    data = {
        'schema_version': 1, 'grid_um': '0.0001', 'domain_margin_um': '2', 'fringe_scale_mode': 'UNSCALED',
        'targets': [
            {'id': 'substrate', 'substrate': {'layer': upper_binding, 'parameters': ['AREA', 'PERIMETER']}},
            {'id': 'area', 'overlap': {'top': upper_binding, 'bottom': lower_binding}},
            {'id': 'side', 'sidewall': {'layer': upper_binding, 'parameters': ['COEFFICIENT', 'OFFSET']}},
            {'id': 'fringe', 'sideoverlap': {'edge': upper_binding, 'receiver': lower_binding}},
        ],
        'patterns': [
            {'id': 'fringe', 'width_um': '2', 'length_um': '4', 'role': 'TRAINING',
             'target_ids': ['substrate', 'area', 'fringe'],
             'directional_fringe': {'edge_layer': profile, 'receiver_layer': lower,
                                    'receiver_width_um': '4', 'lateral_offset_um': '-3'}},
            {'id': 'side', 'width_um': '1', 'length_um': '4', 'role': 'VALIDATION', 'target_ids': ['side'],
             'parallel_wires': {'layer': profile, 'gap_um': '0.2'}},
        ],
    }
    selected = TechInfo.from_catalog(pdk.config.tech_catalog_path, None, scenario_id='nominal')
    result = prepare_calibration(selected, read_pattern_data(tmp_path, data), tmp_path / 'prepared')
    manifest = Parse(result.manifest_path.read_text(encoding='utf-8'), CalibrationManifest())
    assert manifest.technology.selection == selected.selection.to_proto()
    assert manifest.technology_side_halo_um == selected.tech.process_parasitics.side_halo
    assert manifest.fringe_scale_mode == UNSCALED
    assert manifest.targets[0].substrate.layer.canonical_layer == canonical
    assert manifest.targets[0].substrate.layer.process_profile == profile


@pytest.mark.parametrize('value', [-1.0, 0.0, float('nan'), float('inf')])
def test_invalid_actual_technology_halo_cannot_enter_manifest(
        tmp_path: Path, targeted_data: Dict[str, Any], targeted_technology: TechInfo, value: float):
    targeted_technology.tech.process_parasitics.side_halo = value
    with pytest.raises(CalibrationError, match='side_halo must be positive and finite'):
        prepare_calibration(targeted_technology, read_pattern_data(tmp_path, targeted_data), tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()


@pytest.mark.parametrize('field', ['canonical_layer', 'process_profile'])
@pytest.mark.parametrize('value', ['', None])
def test_empty_target_binding_is_not_inferred_from_other_names(
        tmp_path: Path, targeted_data: Dict[str, Any], field: str, value: Any):
    targeted_data['targets'][0]['substrate']['layer'][field] = value
    with pytest.raises(CalibrationError, match='nonempty canonical_layer and process_profile'):
        read_pattern_data(tmp_path, targeted_data)


def test_one_actual_row_cannot_be_duplicated_using_another_profile_binding(
        tmp_path: Path, targeted_data: Dict[str, Any]):
    extra = copy.deepcopy(targeted_data['targets'][0])
    extra['id'] = 'other-profile'
    extra['substrate']['layer']['process_profile'] = 'another-physical-variant'
    targeted_data['targets'].append(extra)
    with pytest.raises(CalibrationError, match='duplicates a canonical table row'):
        read_pattern_data(tmp_path, targeted_data)


def test_same_named_canonical_and_process_layers_still_require_explicit_mapping(
        tmp_path: Path, targeted_data: Dict[str, Any], targeted_technology: TechInfo):
    tech = targeted_technology.tech
    tech.layers[0].name = 'M1'
    tech.process_parasitics.capacitance.substrates[0].layer_name = 'M1'
    targeted_data['targets'][0]['substrate']['layer']['canonical_layer'] = 'M1'
    # A matching spelling or GDS pair cannot replace the computed-layer declaration.
    with pytest.raises(CalibrationError, match='no explicit validated mapping'):
        prepare_calibration(TechInfo(tech, None), read_pattern_data(tmp_path, targeted_data), tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()


@pytest.mark.parametrize('target_index,parameters', [
    (0, ['AREA']), (0, ['PERIMETER']), (0, ['AREA', 'PERIMETER']),
    (2, ['COEFFICIENT']), (2, ['OFFSET']), (2, ['COEFFICIENT', 'OFFSET']),
])
def test_selected_parameter_subsets_are_retained_explicitly(
        tmp_path: Path, targeted_data: Dict[str, Any], targeted_technology: TechInfo,
        target_index: int, parameters: Any):
    family = 'substrate' if target_index == 0 else 'sidewall'
    targeted_data['targets'][target_index][family]['parameters'] = parameters
    spec = read_pattern_data(tmp_path, targeted_data)
    result = prepare_calibration(targeted_technology, spec, tmp_path / 'prepared')
    manifest = Parse(result.manifest_path.read_text(encoding='utf-8'), CalibrationManifest())
    assert manifest.targets[target_index] == spec.targets[target_index].definition


@pytest.mark.parametrize('value,accepted', [('-0.001', False), ('0', False), ('0.0009', False), ('0.001', True), ('0.002', True)])
def test_receiver_width_minimum_is_one_positive_grid_unit(
        tmp_path: Path, targeted_data: Dict[str, Any], value: str, accepted: bool):
    targeted_data['patterns'][3]['directional_fringe']['receiver_width_um'] = value
    if accepted:
        assert read_pattern_data(tmp_path, targeted_data).patterns[3].receiver_width in (1, 2)
    else:
        with pytest.raises(CalibrationError):
            read_pattern_data(tmp_path, targeted_data)


def test_directional_fringe_rejects_one_profile_before_loading_technology(
        tmp_path: Path, targeted_data: Dict[str, Any]):
    targeted_data['patterns'][3]['directional_fringe']['receiver_layer'] = 'M1'
    with pytest.raises(CalibrationError, match='two distinct process profiles'):
        read_pattern_data(tmp_path, targeted_data)
