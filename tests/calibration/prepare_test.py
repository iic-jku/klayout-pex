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

"""Finite geometry, provenance and output safety are observable preparation contracts."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, IO
from unittest import mock

import allure
from google.protobuf.json_format import Parse
import pytest

from klayout_pex.calibration.patterns import CalibrationError, read_patterns
from klayout_pex.calibration.prepare import prepare_calibration
from klayout_pex.klayout.pex25d_stack import BuilderOptions, build_pex25d_stack
from klayout_pex.pdk_config import PDK
from klayout_pex.pex25d.artifact import infer_artifact_spec
from klayout_pex.pex25d.codec import load_artifact
from klayout_pex.pex25d.reader import read_pex25d_text
from klayout_pex.pex25d.validator import validate
from klayout_pex.tech_identity import message_sha256
from klayout_pex.tech_info import TechDefError, TechInfo
from klayout_pex.util.multiple_choice import MultipleChoicePattern
from klayout_pex_protobuf.kpex.tech.tech_pb2 import Technology

pytestmark = allure.parent_suite('Unit Tests')


@pytest.fixture
def specification(tmp_path: Path, pattern_data: Dict[str, Any]) -> Path:
    path = tmp_path / 'spec.json'
    path.write_text(json.dumps(pattern_data), encoding='utf-8')
    return path


def test_preparation_writes_complete_reproducible_cases(tmp_path: Path, specification: Path, tech_info: TechInfo):
    spec = read_patterns(specification)
    first = prepare_calibration(tech_info, spec, tmp_path / 'first')
    second = prepare_calibration(tech_info, spec, tmp_path / 'second')
    assert first.manifest_path == first.written_paths[-1]
    assert [p.name for p in first.written_paths] == [p.name for p in second.written_paths]
    assert [p.read_bytes() for p in first.written_paths] == [p.read_bytes() for p in second.written_paths]
    manifest = json.loads(first.manifest_path.read_text(encoding='utf-8'))
    assert manifest['stage'] == 'prepared'
    assert manifest['reference_solutions'] == []
    assert manifest['fitted_coefficients'] is None
    assert [case['role'] for case in manifest['cases']] == ['training', 'validation']
    assert manifest['cases'][0]['measurement']['conductor_order'] == ['A', 'B']
    assert manifest['cases'][0]['measurement']['reference'] == {
        'kind': 'ground_plane', 'profile': 'substrate', 'potential_V': 0}
    # Every recorded case must work through the normal format-tool loader without explicit encoding overrides.
    for case in manifest['cases']:
        for kind in ('file', 'scene'):
            loaded = load_artifact(infer_artifact_spec(str(first.manifest_path.parent / case[kind])))
            assert validate(loaded, strict=True).num_errors == 0
    for artifact in manifest['artifacts']:
        assert hashlib.sha256((first.manifest_path.parent / artifact['path']).read_bytes()).hexdigest() == artifact['sha256']
    snapshot = Parse((first.manifest_path.parent / 'technology.pb.json').read_text(encoding='utf-8'), Technology())
    assert message_sha256(snapshot) == manifest['technology']['resolved_technology_sha256']
    assert message_sha256(snapshot.process_stack) == manifest['technology']['physical_stack_sha256']


def test_resolved_geometry_has_independent_dimensions_and_top_coating(tmp_path: Path, specification: Path,
                                                                      tech_info: TechInfo):
    output = tmp_path / 'prepared'
    prepare_calibration(tech_info, read_patterns(specification), output)
    scene = load_artifact(infer_artifact_spec(str(output / 'case_wires.pex25d.scene.pb')))
    assert validate(scene, strict=True).num_errors == 0
    assert [(c.name, c.floating) for c in scene.conductors] == [('A', False), ('B', False)]
    assert all(not c.terminals for c in scene.conductors)  # Electrostatic electrodes need no resistance terminals.
    boxes = [c.regions[0].boxes[0] for c in scene.conductors]
    assert [(b.lower_left.x, b.upper_right.x, b.upper_right.y) for b in boxes] == [(0, 400, 8000), (600, 1000, 8000)]
    metals = {layer.name: layer for layer in scene.layers}
    assert (metals['M1'].zlow, metals['M1'].zhigh) == (1000, 1200)
    assert (metals['M2'].zlow, metals['M2'].zhigh) == (2000, 2300)
    assert scene.ground_plane.zhigh == -100
    coat = next(d for d in scene.dielectrics if d.name == 'coat')
    assert coat.permittivity == 7.3
    assert (coat.thickness_over_wrapped, coat.thickness_beside_wrapped,
            coat.thickness_on_field) == (100, 80, 50)
    # DOMAIN_MARGIN expands finite geometry; a film present on the field is laterally unbounded.
    assert scene.domain.box.upper_right.z == 4300  # 2.3 µm conductor + 2 µm requested margin.
    file = read_pex25d_text((output / 'case_wires.pex25d').read_bytes(), '<prepared>')
    assert validate(file, strict=True).num_errors == 0
    assert (file.units.source_dbu_numerator, file.units.source_dbu_denominator) == (0, 0)


def test_fitted_data_changes_do_not_change_physical_patterns(tmp_path: Path, specification: Path, tech_info: TechInfo):
    spec = read_patterns(specification)
    first = prepare_calibration(tech_info, spec, tmp_path / 'before')
    tech_info.tech.process_parasitics.side_halo = 12.0
    after = prepare_calibration(tech_info, spec, tmp_path / 'after')
    left, right = (json.loads(result.manifest_path.read_text(encoding='utf-8')) for result in (first, after))
    assert left['technology']['physical_stack_sha256'] == right['technology']['physical_stack_sha256']
    assert left['technology']['resolved_technology_sha256'] != right['technology']['resolved_technology_sha256']
    for name in ('case_plates.pex25d', 'case_plates.pex25d.scene.pb', 'case_wires.pex25d', 'case_wires.pex25d.scene.pb'):
        assert (tmp_path / 'before' / name).read_bytes() == (tmp_path / 'after' / name).read_bytes()


@pytest.mark.parametrize('lower,upper', [('M2', 'M1'), ('M1', 'M1'), ('MISSING', 'M2')])
def test_invalid_layer_selection_leaves_no_output(tmp_path: Path, specification: Path, pattern_data: Dict[str, Any],
                                                tech_info: TechInfo, lower: str, upper: str):
    pattern_data['cases'][0].update(lower_layer=lower, upper_layer=upper)
    specification.write_text(json.dumps(pattern_data), encoding='utf-8')
    output = tmp_path / 'bad'
    with pytest.raises(CalibrationError):
        prepare_calibration(tech_info, read_patterns(specification), output)
    assert not output.exists()


@pytest.mark.parametrize('separation,accepted', [(-0.001, False), (0.0, False), (0.001, True)])
def test_plates_need_a_strictly_positive_vertical_gap(tmp_path: Path, specification: Path, tech_info: TechInfo,
                                                     separation: float, accepted: bool):
    # A coincident face electrically shorts the plates; it is not a limiting capacitance sample.
    tech_info.process_metal_layers[1].metal_layer.z = 1.2 + separation
    if accepted:
        result = prepare_calibration(tech_info, read_patterns(specification), tmp_path / 'valid')
        assert result.manifest_path.is_file()
    else:
        with pytest.raises(CalibrationError, match='nonzero dielectric gap'):
            prepare_calibration(tech_info, read_patterns(specification), tmp_path / 'invalid')


def test_filtered_or_unrepresentable_films_are_not_silently_calibrated(tmp_path: Path, specification: Path,
                                                                     tech_info: TechInfo):
    tech_info.dielectric_filter = MultipleChoicePattern(pattern='-coat')
    with pytest.raises(CalibrationError, match='omitted dielectrics: coat'):
        prepare_calibration(tech_info, read_patterns(specification), tmp_path / 'invalid')
    assert not (tmp_path / 'invalid').exists()


@pytest.mark.parametrize('kind', ['directory', 'file', 'broken_symlink'])
def test_existing_output_paths_are_preserved(tmp_path: Path, specification: Path, tech_info: TechInfo, kind: str):
    output = tmp_path / 'existing'
    if kind == 'directory':
        output.mkdir()
        (output / 'keep.txt').write_text('preserve me', encoding='utf-8')
    elif kind == 'file':
        output.write_text('preserve me', encoding='utf-8')
    else:
        try:
            output.symlink_to(tmp_path / 'missing')
        except OSError as exc:
            pytest.skip(f'Symlinks unavailable: {exc}')
    with pytest.raises(CalibrationError, match='already exists'):
        prepare_calibration(tech_info, read_patterns(specification), output)
    assert output.exists() or output.is_symlink()
    if kind != 'broken_symlink':
        preserved = output / 'keep.txt' if kind == 'directory' else output
        assert preserved.read_text(encoding='utf-8') == 'preserve me'


def test_write_failure_never_leaves_a_success_manifest_or_removes_unrelated_work(tmp_path: Path, specification: Path,
                                                                               tech_info: TechInfo):
    output = tmp_path / 'prepared'
    original = Path.open

    def fail_scene(path: Path, *args: Any, **kwargs: Any) -> IO[Any]:
        if path.name == 'case_plates.pex25d.scene.pb' and args == ('xb',):
            (output / 'keep.txt').write_text('concurrent work', encoding='utf-8')
            raise OSError('disk full')
        return original(path, *args, **kwargs)

    with mock.patch.object(Path, 'open', fail_scene):
        with pytest.raises(CalibrationError, match='disk full'):
            prepare_calibration(tech_info, read_patterns(specification), output)
    assert sorted(p.name for p in output.iterdir()) == ['keep.txt']
    assert (output / 'keep.txt').read_text(encoding='utf-8') == 'concurrent work'


@pytest.mark.parametrize('pdk', list(PDK))
def test_all_shipped_stacks_prepare_finite_cases(tmp_path: Path, pattern_data: Dict[str, Any], pdk: PDK):
    technology = TechInfo.from_json(pdk.config.tech_pb_json_path, dielectric_filter=None)
    pattern_data['grid_um'] = '0.0001'
    first, last = technology.process_metal_layers[0].name, technology.process_metal_layers[-1].name
    pattern_data['cases'][0].update(lower_layer=first, upper_layer=last)
    pattern_data['cases'][1]['layer'] = last
    path = tmp_path / 'patterns.json'
    path.write_text(json.dumps(pattern_data), encoding='utf-8')
    result = prepare_calibration(technology, read_patterns(path), tmp_path / 'prepared')
    assert result.manifest_path.is_file()
    # Calibration and layout generation must preserve the same complete shared stack.
    stack = build_pex25d_stack(technology, BuilderOptions(grid_um='0.0001'))
    prepared = read_pex25d_text((tmp_path / 'prepared' / 'case_plates.pex25d').read_bytes(), '<prepared>')
    assert prepared.metals == stack.metals
    assert prepared.dielectrics == stack.dielectrics
    assert prepared.background == stack.background


def test_supplied_corner_selection_is_preserved_and_physically_checked(tmp_path: Path, specification: Path,
                                                                       tech_info: TechInfo):
    # The corners loader owns scenario resolution; preparation consumes its resolved identity without refitting it.
    identity = {'technology_id': 'test_stack', 'scenario_id': 'scenario_test',
                'datasets': {'process_stack': {'id': 'stack_test', 'sha256': message_sha256(tech_info.tech.process_stack)}}}
    selection = mock.Mock(scenario_id='scenario_test')
    selection.to_json.return_value = identity
    tech_info.selection = selection
    result = prepare_calibration(tech_info, read_patterns(specification), tmp_path / 'prepared')
    manifest = json.loads(result.manifest_path.read_text(encoding='utf-8'))
    assert manifest['technology']['selection'] == identity
    selection.require_physical_stack.assert_called_once_with(tech_info.tech.process_stack)
    file = read_pex25d_text((result.manifest_path.parent / 'case_plates.pex25d').read_bytes(), '<prepared>')
    assert {item.key: item.value for item in file.metadata}['process_corner'] == 'scenario_test'


def test_empirical_only_scenario_cannot_be_presented_as_physical_calibration(tmp_path: Path, specification: Path,
                                                                          tech_info: TechInfo):
    selection = mock.Mock()
    selection.require_physical_stack.side_effect = TechDefError('Scenario has no matching physical stack')
    tech_info.selection = selection
    output = tmp_path / 'invalid'
    with pytest.raises(TechDefError, match='no matching physical stack'):
        prepare_calibration(tech_info, read_patterns(specification), output)
    assert not output.exists()
