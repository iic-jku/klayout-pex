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

"""Finite geometry, provenance and output safety are observable preparation contracts."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, IO, Optional, Tuple
from unittest import mock

import allure
import klayout.db as kdb
from google.protobuf.json_format import MessageToJson, Parse, ParseError
import pytest

from kpex.calibration.patterns import CalibrationError, read_patterns
from kpex.calibration.prepare import prepare_calibration
from kpex.klayout.pex25d_stack import BuilderOptions, GeometryScope, build_pex25d_stack
from kpex.klayout.pex25d_builder import PEX25DBuilder
from kpex.pdk_config import PDK
from kpex.pex25d.artifact import infer_artifact_spec
from kpex.pex25d.codec import load_artifact
from kpex.pex25d.diagnostics import Diagnostic, DiagnosticsReport, Severity, SourceRef, Tier
from kpex.pex25d.reader import read_pex25d_text
from kpex.pex25d.resolver import resolve
from kpex.pex25d.validator import validate
from kpex.tech_identity import message_sha256
from kpex.tech_info import TechDefError, TechInfo
from kpex.util.multiple_choice import MultipleChoicePattern
from kpex_protobuf.kpex.calibration import patterns_pb2, preparation_pb2
from kpex_protobuf.kpex.pex25d.pex25d_diagnostics_pb2 import Diagnostic as DiagnosticMessage
from kpex_protobuf.kpex.pex25d.pex25d_units_pb2 import Units
from kpex_protobuf.kpex.tech.tech_pb2 import Technology
from tests.common.tech_catalog import add_scenario, write_test_catalog
from tests.common.fastercap_geometry import context_from_shapes

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
    text = first.manifest_path.read_text(encoding='utf-8')
    manifest = Parse(text, preparation_pb2.CalibrationManifest())
    assert Parse(MessageToJson(manifest), preparation_pb2.CalibrationManifest()) == manifest
    assert manifest.schema_version == 1
    assert manifest.pattern_generator_version == 1
    assert manifest.stage == preparation_pb2.CalibrationManifest.PREPARED
    assert manifest.kpex_version
    assert manifest.source_specification_sha256 == hashlib.sha256(spec.source).hexdigest()
    assert manifest.domain_margin_grid == 2000
    assert manifest.units.length == Units.LENGTH_UNIT_UM
    assert (manifest.units.grid_numerator, manifest.units.grid_denominator) == (1, 1000)
    assert not manifest.technology.HasField('selection')
    assert [case.role for case in manifest.cases] == [patterns_pb2.TRAINING, patterns_pb2.VALIDATION]
    assert [case.family for case in manifest.cases] == [patterns_pb2.PARALLEL_PLATES, patterns_pb2.PARALLEL_WIRES]
    assert [(case.dimensions_grid.width, case.dimensions_grid.length, case.dimensions_grid.gap)
            for case in manifest.cases] == [(2000, 4000, 0), (400, 8000, 200)]
    measurement = manifest.cases[0].measurement
    assert measurement.kind == preparation_pb2.CapacitanceMeasurement.MAXWELL_CAPACITANCE_MATRIX
    assert measurement.conductor_order == ['A', 'B']
    assert measurement.reference.profile == 'substrate'
    assert measurement.reference.potential_v == 0
    assert not measurement.floating_conductors
    assert measurement.capacitance_unit == preparation_pb2.CapacitanceMeasurement.FARAD
    assert measurement.convention == preparation_pb2.CapacitanceMeasurement.MAXWELL_GROUNDED_UNEXCITED
    assert measurement.exterior_boundary_condition == preparation_pb2.CapacitanceMeasurement.EXTERIOR_UNSPECIFIED
    raw = json.loads(text)
    assert raw['stage'] == 'PREPARED'
    assert raw['domain_margin_grid'] == '2000'  # Protobuf JSON represents int64 values as strings.
    assert raw['cases'][0]['dimensions_grid']['width'] == '2000'
    assert 'sourceSpecificationSha256' not in raw  # Files use the documented snake_case writer spelling.
    assert 'reference_solutions' not in raw and 'fitted_coefficients' not in raw
    # Every recorded case must work through the normal format-tool loader without explicit encoding overrides.
    for case in manifest.cases:
        for path in (case.file, case.scene):
            loaded = load_artifact(infer_artifact_spec(str(first.manifest_path.parent / path)))
            assert validate(loaded, strict=True).num_errors == 0
    for artifact in manifest.artifacts:
        assert hashlib.sha256((first.manifest_path.parent / artifact.path).read_bytes()).hexdigest() == artifact.sha256
    snapshot = Parse((first.manifest_path.parent / 'technology.pb.json').read_text(encoding='utf-8'), Technology())
    assert message_sha256(snapshot) == manifest.technology.resolved_technology_sha256
    assert message_sha256(snapshot.process_stack) == manifest.technology.physical_stack_sha256
    patterns = Parse((first.manifest_path.parent / 'patterns.json').read_text(encoding='utf-8'),
                     patterns_pb2.PatternSetSpecification())
    assert patterns == Parse(spec.source.decode('utf-8'), patterns_pb2.PatternSetSpecification())


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
    left, right = (Parse(result.manifest_path.read_text(encoding='utf-8'), preparation_pb2.CalibrationManifest())
                   for result in (first, after))
    assert left.technology.physical_stack_sha256 == right.technology.physical_stack_sha256
    assert left.technology.resolved_technology_sha256 != right.technology.resolved_technology_sha256
    for name in ('case_plates.pex25d', 'case_plates.pex25d.scene.pb', 'case_wires.pex25d', 'case_wires.pex25d.scene.pb'):
        assert (tmp_path / 'before' / name).read_bytes() == (tmp_path / 'after' / name).read_bytes()


@pytest.mark.parametrize('lower,upper', [('M2', 'M1'), ('M1', 'M1'), ('MISSING', 'M2')])
def test_invalid_layer_selection_leaves_no_output(tmp_path: Path, specification: Path, pattern_data: Dict[str, Any],
                                                tech_info: TechInfo, lower: str, upper: str):
    pattern_data['patterns'][0]['parallel_plates'].update(lower_layer=lower, upper_layer=upper)
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
@pytest.mark.parametrize('source', ['json', 'catalog'])
def test_all_shipped_stacks_prepare_finite_cases(tmp_path: Path, pattern_data: Dict[str, Any], pdk: PDK, source: str):
    technology = (TechInfo.from_catalog(pdk.config.tech_catalog_path, dielectric_filter=None)
                  if source == 'catalog' else TechInfo.from_json(pdk.config.tech_pb_json_path, dielectric_filter=None))
    pattern_data['grid_um'] = '0.0001'
    first, last = technology.process_metal_layers[0].name, technology.process_metal_layers[-1].name
    pattern_data['patterns'][0]['parallel_plates'].update(lower_layer=first, upper_layer=last)
    pattern_data['patterns'][1]['parallel_wires']['layer'] = last
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
    # Load real catalog provenance: the prepared evidence must retain descriptions,
    # source revisions, assumptions and history, not just a scenario label.
    path = tmp_path / 'catalog.pb.json'
    write_test_catalog(tech_info.tech, path)
    add_scenario(path, name='physical-test', physical_stack_matches=True)
    selected = TechInfo.from_catalog(str(path), None, scenario_id='physical-test')
    result = prepare_calibration(selected, read_patterns(specification), tmp_path / 'prepared')
    manifest = Parse(result.manifest_path.read_text(encoding='utf-8'), preparation_pb2.CalibrationManifest())
    assert manifest.technology.selection == selected.selection.to_proto()
    assert manifest.technology.physical_stack_sha256 == selected.selection.process_stack.sha256
    assert manifest.technology.resolved_technology_sha256 == selected.selection.resolved_technology_sha256
    assert manifest.technology.selection.datasets.process_stack.provenance.sources
    file = read_pex25d_text((result.manifest_path.parent / 'case_plates.pex25d').read_bytes(), '<prepared>')
    assert {item.key: item.value for item in file.metadata}['process_corner'] == 'physical-test'


@pytest.mark.parametrize('scenario,mutate_stack,error', [
    ('analytical-only', False, 'no matching physical stack'),
    ('nominal', True, 'Physical stack changed after corner'),
])
def test_unmatched_or_stale_stack_cannot_be_presented_as_physical_calibration(
        tmp_path: Path, specification: Path, tech_info: TechInfo, scenario: str, mutate_stack: bool, error: str):
    # A catalog may select valid empirical tables without a matching field-solver process stack.
    # Even a matching selection becomes stale if its physical dimensions change.
    path = tmp_path / 'catalog.pb.json'
    write_test_catalog(tech_info.tech, path)
    add_scenario(path, name='analytical-only')
    selected = TechInfo.from_catalog(str(path), None, scenario_id=scenario)
    if mutate_stack:
        selected.process_metal_layers[0].metal_layer.thickness += 0.001
    output = tmp_path / 'invalid'
    with pytest.raises(TechDefError, match=error):
        prepare_calibration(selected, read_patterns(specification), output)
    assert not output.exists()


@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('offset,accepted', [(-1, True), (0, False), (1, False)])
def test_finite_coating_and_margin_cannot_reach_native_endpoint(
        tmp_path: Path, pattern_data: Dict[str, Any], tech_info: TechInfo,
        axis: str, offset: int, accepted: bool):
    # The drawn box fits. A finite side coating reaches 80 extra grid units,
    # so only resolved bounds expose the unsafe endpoint before native validation.
    coat = next(layer for layer in tech_info.tech.process_stack.layers if layer.name == 'coat')
    coat.conformal_dielectric_layer.thickness_where_no_metal = 0
    pattern_data['patterns'] = pattern_data['patterns'][:1]
    dimension = 'width_um' if axis == 'x' else 'length_um'
    pattern_data['patterns'][0][dimension] = str((2**31 - 1 + offset - 2080) / 1000)
    specification = tmp_path / 'patterns.json'
    specification.write_text(json.dumps(pattern_data), encoding='utf-8')
    output = tmp_path / 'prepared'
    if accepted:
        result = prepare_calibration(tech_info, read_patterns(specification), output)
        scene = load_artifact(infer_artifact_spec(str(output / 'case_plates.pex25d.scene.pb')))
        assert getattr(scene.domain.box.upper_right, axis) == 2**31 - 2
        assert result.manifest_path.is_file()
    else:
        with mock.patch('kpex.calibration.prepare.validate', side_effect=AssertionError('unsafe native validation')):
            with pytest.raises(CalibrationError, match='supported native XY coordinate range'):
                prepare_calibration(tech_info, read_patterns(specification), output)
        assert not output.exists()


def test_unavailable_requested_profile_is_rejected_before_preparing_geometry(
        tmp_path: Path, specification: Path, tech_info: TechInfo):
    tech_info.process_metal_layers[0].metal_layer.physical_geometry_unavailable = True
    with pytest.raises(CalibrationError, match="no supported physical geometry for 'M1'"):
        prepare_calibration(tech_info, read_patterns(specification), tmp_path / 'prepared')
    assert not (tmp_path / 'prepared').exists()


@pytest.mark.parametrize('scope', list(GeometryScope))
def test_shared_stack_matches_layout_materials_for_identical_finite_geometry(
        tmp_path: Path, specification: Path, tech_info: TechInfo, scope: GeometryScope):
    # Build the same physical rectangles through layout connectivity and direct
    # preparation. Sharing methods must not drop the electrostatic materials,
    # change interconnect defaults or give the paths different z boundaries.
    for index, metal in enumerate(tech_info.process_metal_layers, start=1):
        mapped = tech_info.tech.layers.add(name=metal.name)
        mapped.drw_gds_pair.layer, mapped.drw_gds_pair.datatype = index, 0
    output = tmp_path / 'prepared'
    prepare_calibration(tech_info, read_patterns(specification), output)
    prepared = read_pex25d_text((output / 'case_plates.pex25d').read_bytes(), '<prepared>')
    options = BuilderOptions(grid_um='0.001', include_resistance=False, include_terminals=False,
                             geometry_scope=scope)
    stack = build_pex25d_stack(tech_info, options)
    stack.shapes.extend(prepared.shapes)
    stack.conductors.extend(prepared.conductors)
    stack.domain_margin.CopyFrom(prepared.domain_margin)
    context = context_from_shapes({}, kdb.Box(0, 0, 2000, 4000), dbu=0.001)
    next(context.top_circuit.each_net()).name = 'A'
    context.top_circuit.create_net('B')
    regions = {
        (shape.conductor, tech_info.gds_pair(shape.layer)): kdb.Region(kdb.Box(
            shape.box.lower_left.x, shape.box.lower_left.y,
            shape.box.upper_right.x, shape.box.upper_right.y))
        for shape in prepared.shapes
    }

    def shapes(gds_pair: Any, net: kdb.Net, **kwargs: Any) -> Optional[kdb.Region]:
        return regions.get((net.name, gds_pair))

    context.shapes_of_net.side_effect = shapes
    layout = PEX25DBuilder(context, tech_info, 'plates', options).build()
    layout.domain_margin.CopyFrom(prepared.domain_margin)
    assert layout.shapes == stack.shapes
    assert layout.metals == stack.metals
    assert layout.vias == stack.vias
    assert layout.dielectrics == stack.dielectrics
    assert layout.background == stack.background
    reference, actual = resolve(layout), resolve(stack)
    assert actual.layers == reference.layers
    assert actual.dielectrics == reference.dielectrics
    assert actual.domain == reference.domain
    assert not actual.required_capabilities  # No layout exclusions or charge partitions in these patterns.


@pytest.mark.parametrize('path,value', [
    (('unexpected_field',), 'not understood'),
    (('reference_solutions',), []),
    (('fitted_coefficients',), None),
    (('stage',), 'SOLVED'),
    (('schema_version',), -1),
    (('domain_margin_grid',), 'not an integer'),
    (('cases', 0, 'family'), 'parallel_plates'),
    (('cases', 0, 'role'), 'UNKNOWN_ROLE'),
    (('cases', 0, 'dimensions_grid', 'width'), '0.5'),
    (('cases', 0, 'measurement', 'kind'), 'UNKNOWN_MEASUREMENT'),
    (('technology', 'name'), []),
])
def test_preparation_manifest_schema_rejects_untyped_or_unknown_payloads(
        tmp_path: Path, specification: Path, tech_info: TechInfo, path: Tuple[Any, ...], value: Any):
    # This stage only writes manifests. The generated schema must be sufficient
    # for consumers to reject unknown fields and wrong wire types without a
    # second hand-maintained JSON field list or speculative solver-result fields.
    result = prepare_calibration(tech_info, read_patterns(specification), tmp_path / 'prepared')
    raw = json.loads(result.manifest_path.read_text(encoding='utf-8'))
    parent = raw
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ParseError):
        Parse(json.dumps(raw), preparation_pb2.CalibrationManifest())


def test_preparation_manifest_preserves_typed_geometry_diagnostics(
        tmp_path: Path, specification: Path, tech_info: TechInfo):
    note = Diagnostic('PEX25D-N0001', Severity.NOTE, Tier.SEMANTIC, 'Finite extent in µm',
                      source=SourceRef(file='case_plates.pex25d', line=3),
                      related=(SourceRef(file='patterns.json', line=8, column=2),))

    def validate_with_note(*args: Any, **kwargs: Any) -> DiagnosticsReport:
        report = validate(*args, **kwargs)
        report.add(note)
        return report

    with mock.patch('kpex.calibration.prepare.validate', side_effect=validate_with_note):
        result = prepare_calibration(tech_info, read_patterns(specification), tmp_path / 'prepared')
    manifest = Parse(result.manifest_path.read_text(encoding='utf-8'), preparation_pb2.CalibrationManifest())
    diagnostic = manifest.cases[0].diagnostics[-1]
    assert diagnostic.code == note.code
    assert diagnostic.severity == DiagnosticMessage.SEVERITY_NOTE
    assert diagnostic.tier == DiagnosticMessage.TIER_SEMANTIC
    assert diagnostic.message == note.message
    assert (diagnostic.source.file, diagnostic.source.line, diagnostic.source.column) == ('case_plates.pex25d', 3, 0)
    assert [(source.file, source.line, source.column) for source in diagnostic.related] == [('patterns.json', 8, 2)]
