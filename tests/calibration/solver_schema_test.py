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

"""Portable saved evidence and strict backend payloads at the schema boundary."""

import json
from pathlib import Path
from typing import List, Sequence
from unittest.mock import patch
import tarfile

from google.protobuf.any_pb2 import Any
from google.protobuf.json_format import MessageToJson
from google.protobuf.wrappers_pb2 import StringValue
import pytest

from kpex.calibration.artifacts import read_message, sha256_file, write_message
from kpex.calibration.backend import calibration_backend, RefinementControls
from kpex.calibration.collect import collect_calibration
from kpex.calibration.fit_evidence import read_verified_qualification
from kpex.calibration.qualification import evaluate_qualification, qualify_study, _refinement
from kpex.calibration.qualification_evidence import QualificationMeasurement, read_collection, read_measurement
from kpex.calibration.solve import SolveOptions, options_message, validate_options_message
from kpex.calibration.validation import CalibrationError
from kpex.fastercap.calibration_backend import (
    FasterCapCalibrationBackend, controls_message, statistics_message,
)
from kpex_protobuf.kpex.calibration import solving_pb2, qualification_pb2
from kpex_protobuf.kpex.calibration.qualification_pb2 import (
    CalibrationQualificationStudy, CalibrationQualificationReport, CalibrationRefinementAxis as Axis,
    CalibrationQualificationStatus as Status, CalibrationRefinementLevel,
)
from kpex_protobuf.kpex.calibration.solving_pb2 import CalibrationCaseResult, CalibrationCollection, CalibrationRunManifest
from kpex_protobuf.kpex.calibration.v1 import qualification_pb2 as qualification_v1
from kpex_protobuf.kpex.calibration.v1 import solving_pb2 as solving_v1
from kpex_protobuf.kpex.fastercap.calibration_pb2 import CalibrationControls, CalibrationStatistics


@pytest.fixture
def saved_v1(tmp_path: Path) -> Path:
    # Captured with the version-1 writer, not produced by an inverse of the
    # migration under test. See the adjacent README for provenance.
    fixture = Path(__file__).parents[2] / 'testdata/calibration/qualification-v1.tar.xz'
    root = tmp_path / 'saved study with spaces'
    with tarfile.open(fixture) as archive:
        archive.extractall(root, filter="data")
    return root


def test_v1_study_requalifies_without_solver_or_evidence_changes(saved_v1: Path, tmp_path: Path):
    before = {p.relative_to(saved_v1): sha256_file(p) for p in saved_v1.rglob('*') if p.is_file()}
    path = saved_v1 / 'study.pb.json'
    with patch('subprocess.Popen', side_effect=AssertionError('Offline evidence must never execute a solver')):
        result = qualify_study(path, tmp_path / 'qualified')
        _, verified = read_verified_qualification(path, result.report_path)
        recollected = collect_calibration(saved_v1 / 'reference/manifest.json', tmp_path / 'recollected')
    report = verified.report
    assert report.schema_version == report.study.schema_version == 2
    assert report.study_sha256 == before[Path('study.pb.json')]
    case, = report.cases
    assert case.status == Status.STABILIZED
    assert [r.axis for r in case.refinements] == [
        Axis.LINEAR_SOLVER_TOLERANCE, Axis.INITIAL_MESH_MAX_AREA, Axis.DOMAIN_MARGIN,
        Axis.ADAPTIVE_MESH_REFINEMENT,
    ]
    assert list(case.reference_matrix.rows[0].values) == pytest.approx([7e-15, -1e-15], abs=1e-30)
    counts = statistics_message(case.refinements[1].levels[0].solver_statistics)
    assert counts.input_panels == 20 and counts.refined_panels == 90
    collection = read_message(recollected.manifest_path, CalibrationCollection())
    assert collection.schema_version == 2 and collection.cases[0].status == 1
    assert collection.cases[0].measured_matrix == case.reference_matrix
    assert before == {p.relative_to(saved_v1): sha256_file(p) for p in saved_v1.rglob('*') if p.is_file()}


def test_old_qualification_report_requires_offline_requalification(saved_v1: Path):
    with pytest.raises(CalibrationError, match='rerun kpex calibrate qualify.*without solving again'):
        read_verified_qualification(saved_v1 / 'study.pb.json', saved_v1 / 'qualification/qualification.pb.json')


def test_v1_tampered_evidence_is_still_rejected(saved_v1: Path, tmp_path: Path):
    log = saved_v1 / 'reference/collection/runs/cases/plates/solver.log'
    log.write_text('changed', encoding='utf-8')
    with pytest.raises(CalibrationError, match='SHA256 mismatch'):
        qualify_study(saved_v1 / 'study.pb.json', tmp_path / 'qualified')
    assert not (tmp_path / 'qualified').exists()


@pytest.mark.parametrize('camel_case', [False, True])
def test_v1_aliases_and_explicit_zero_counts(tmp_path: Path, camel_case: bool):
    saved = solving_v1.CalibrationCollection(schema_version=1)
    record = saved.cases.add(case_id='a', input_panels=0, links=2**64 - 1)
    path = tmp_path / 'collection.json'
    path.write_text(MessageToJson(saved, preserving_proto_field_name=not camel_case), encoding='utf-8')
    current = read_message(path, CalibrationCollection())
    statistics = statistics_message(current.cases[0].solver_statistics)
    assert current.schema_version == 2
    assert statistics.HasField('input_panels') and statistics.input_panels == 0
    assert not statistics.HasField('refined_panels')
    assert statistics.links == record.links == 2**64 - 1


@pytest.mark.parametrize('axis', [qualification_v1.GMRES_TOLERANCE, qualification_v1.FASTERCAP_MESH_REFINEMENT])
@pytest.mark.parametrize('numeric', [False, True])
def test_v1_axis_names_and_numeric_wire_ids(tmp_path: Path, axis: int, numeric: bool):
    saved = qualification_v1.CalibrationQualificationStudy(schema_version=1)
    saved.cases.add(case_id='a').refinements.add(axis=axis)
    path = tmp_path / 'study.json'
    path.write_text(MessageToJson(saved, use_integers_for_enums=numeric), encoding='utf-8')
    current = read_message(path, CalibrationQualificationStudy())
    assert current.cases[0].refinements[0].axis == axis
    assert 'FASTERCAP' not in MessageToJson(current)
    assert 'GMRES' not in MessageToJson(current)


@pytest.mark.parametrize('options', [SolveOptions(), SolveOptions(mesh_refinement=0.1, gmres_tolerance=1e-7)])
def test_typed_controls_round_trip(options: SolveOptions, tmp_path: Path):
    manifest = CalibrationRunManifest(schema_version=2, options=options_message(options))
    manifest.solver.name = 'fastercap'
    path = write_message(tmp_path / 'run.json', manifest)
    saved = read_message(path, CalibrationRunManifest())
    assert saved == manifest
    assert validate_options_message(saved.options) == options
    payload = json.loads(path.read_text(encoding='utf-8'))['options']['solver_controls']
    assert payload['@type'] == 'type.googleapis.com/kpex.fastercap.CalibrationControls'
    assert 'fastercap' not in json.loads(path.read_text(encoding='utf-8'))['options']


@pytest.mark.parametrize('payload', [Any(), Any(type_url='unknown/type'),
                                    Any(type_url='type.googleapis.com/kpex.fastercap.CalibrationControls', value=b'\xff')])
def test_missing_wrong_and_malformed_controls_rejected(payload: Any):
    with pytest.raises(CalibrationError, match='CalibrationControls'):
        controls_message(payload)


def test_valid_message_of_wrong_type_is_rejected():
    payload = Any()
    payload.Pack(CalibrationStatistics(input_panels=1))
    with pytest.raises(CalibrationError, match='CalibrationControls'):
        controls_message(payload)
    payload.Pack(CalibrationControls())
    with pytest.raises(CalibrationError, match='CalibrationStatistics'):
        statistics_message(payload)
    with pytest.raises(CalibrationError, match='Unsupported calibration solver'):
        calibration_backend('not-installed')


@pytest.mark.parametrize('version', [0, 2, 99])
def test_old_field_names_cannot_masquerade_as_another_version(tmp_path: Path, version: int):
    saved = solving_v1.CalibrationRunManifest(schema_version=version)
    saved.options.fastercap.automatic_tolerance = 0.05
    path = write_message(tmp_path / 'run.json', saved)
    with pytest.raises(CalibrationError, match='require schema_version 1'):
        read_message(path, CalibrationRunManifest())


@pytest.mark.parametrize('counts,expected', [([0, 2, 3], False), ([1, 1, 3], False),
                                          ([1, 2, 3], True), ([3, 2, 1], False)])
def test_backend_panel_refinement_boundaries(counts: List[int], expected: bool):
    levels = [CalibrationRefinementLevel(parameter_value=value) for value in (0.3, 0.2, 0.1)]
    for level, count in zip(levels, counts):
        level.solver_statistics.Pack(CalibrationStatistics(refined_panels=count))
    diagnostics = FasterCapCalibrationBackend.refinement_diagnostics(Axis.ADAPTIVE_MESH_REFINEMENT, levels)
    assert (not diagnostics) == expected


def test_shared_schemas_have_no_backend_dependency():
    for descriptor in (solving_pb2.DESCRIPTOR, qualification_pb2.DESCRIPTOR):
        assert all('fastercap' not in item.name for item in descriptor.dependencies)
        assert all('FasterCap' not in name for name in descriptor.message_types_by_name)
    assert set(Axis.keys()) == {'REFINEMENT_AXIS_UNSPECIFIED', 'LINEAR_SOLVER_TOLERANCE',
                                'INITIAL_MESH_MAX_AREA', 'DOMAIN_MARGIN', 'ADAPTIVE_MESH_REFINEMENT'}


def test_shared_qualification_accepts_backend_ordering_without_panels(
        saved_v1: Path, monkeypatch: pytest.MonkeyPatch):
    # An independent test backend refines by increasing a level index and has
    # no panel counts. Generic qualification must delegate both decisions.
    study = read_message(saved_v1 / 'study.pb.json', CalibrationQualificationStudy())
    spec = study.cases[0].refinements[0]
    references = {item.id: item.collection for item in study.collections}
    measurements = {name: read_measurement(read_collection(saved_v1 / references[name].path,
                                                          references[name].sha256), 'plates')
                    for name in spec.collection_ids}
    by_hash = {measurements[name].run.run_sha256: float(i + 1) for i, name in enumerate(spec.collection_ids)}
    target = measurements[spec.collection_ids[-1]]

    class LevelBackend:
        def refinement_controls(self, measurement: QualificationMeasurement, axis: int) -> RefinementControls:
            return RefinementControls(by_hash[measurement.run.run_sha256], target.run.manifest.options,
                                      target.scene, True)

        def refinement_statistics(self, record: CalibrationCaseResult) -> Any:
            payload = Any()
            payload.Pack(StringValue(value='independent mesh evidence'))
            return payload

        def requires_unchanged_inputs(self, axis: int) -> bool:
            return True

        def refinement_diagnostics(self, axis: int, levels: Sequence[CalibrationRefinementLevel]) -> List[str]:
            assert [item.parameter_value for item in levels] == [1, 2, 3]
            return []

    monkeypatch.setattr('kpex.calibration.qualification.calibration_backend', lambda _: LevelBackend())
    result = _refinement(spec, target, measurements, study.tolerance)
    assert result.status == Status.STABILIZED, result
    assert all(item.solver_statistics.Is(StringValue.DESCRIPTOR) for item in result.levels)


@pytest.mark.parametrize('kind', ['length', 'overlap'])
@pytest.mark.parametrize('axis', [Axis.LINEAR_SOLVER_TOLERANCE, Axis.ADAPTIVE_MESH_REFINEMENT])
def test_saved_fit_report_preserves_refinement_evidence(tmp_path: Path, kind: str, axis: int):
    # Reports persist the old enum names too. Reading them must preserve their
    # historical fit result, not claim that qualification was rerun.
    from kpex_protobuf.kpex.calibration import length_fit_pb2, overlap_fit_pb2
    from kpex_protobuf.kpex.calibration.v1 import length_fit_pb2 as old_length
    from kpex_protobuf.kpex.calibration.v1 import overlap_fit_pb2 as old_overlap

    if kind == 'length':
        saved = old_length.CalibrationLengthFitReport(schema_version=1)
        fit = saved.fits.add(status=old_length.CalibrationLengthFitResult.REJECTED)
        refinement = fit.refinement_sensitivity.add(axis=axis)
        current = length_fit_pb2.CalibrationLengthFitReport()
    else:
        saved = old_overlap.CalibrationOverlapFitReport(schema_version=1)
        saved.fit.status = old_overlap.CalibrationOverlapFitResult.REJECTED
        refinement = saved.refinement_sensitivity.add(axis=axis)
        current = overlap_fit_pb2.CalibrationOverlapFitReport()
    saved.study_sha256 = '1' * 64
    saved.qualification_sha256 = '2' * 64
    refinement.reference_parameter_value = 0.06
    refinement.levels.add(parameter_value=0.12).validation_samples.add(
        case_id='holdout', residual_f=3e-18, residual_change_f=2e-18)
    path = tmp_path / 'fit.pb.json'
    write_message(path, saved)
    original = path.read_bytes()
    result = read_message(path, current)
    expected = type(current).FromString(saved.SerializeToString())
    expected.schema_version = 3
    assert result == expected
    assert path.read_bytes() == original
