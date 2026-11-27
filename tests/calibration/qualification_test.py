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
"""Qualification checks require independent, traceable numerical evidence."""

from dataclasses import replace
import json
import math
from pathlib import Path
import shutil
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import pytest
import numpy as np
from google.protobuf.json_format import MessageToDict

from kpex.fastercap.calibration_backend import statistics_message
from kpex.calibration.artifacts import read_message, sha256_file, write_message
from kpex.calibration.patterns import read_patterns
from kpex.calibration.prepare import prepare_calibration
from kpex.calibration.qualification import _diagnose, qualify_study
from kpex.calibration.solve import CalibrationSolveResult, SolveOptions, solve_calibration
from kpex.calibration.validation import CalibrationError
from kpex.kpex_cli import KpexCLI
from kpex.tech_info import TechInfo
from kpex_protobuf.kpex.calibration.fit_pb2 import CalibrationFitRefinementCoverage as Coverage
from kpex_protobuf.kpex.calibration.length_fit_pb2 import CalibrationLengthFitReport, CalibrationLengthFitResult
from kpex_protobuf.kpex.calibration.overlap_fit_pb2 import CalibrationOverlapFitReport, CalibrationOverlapFitResult
from kpex_protobuf.kpex.calibration.qualification_pb2 import (
    CalibrationQualificationReport, CalibrationQualificationStatus as Status,
    CalibrationQualificationStudy, CalibrationQualificationTolerance, CalibrationRefinementAxis as Axis,
)
from kpex_protobuf.kpex.calibration.solving_pb2 import CalibrationCollection, CalibrationRunManifest
from kpex_protobuf.kpex.calibration.preparation_pb2 import CalibrationManifest
from kpex_protobuf.kpex.result.capacitance_matrix_pb2 import MaxwellCapacitanceMatrix as Matrix
from tests.common.calibration_study import (
    assert_circuit_coupling, make_study, mock_solver, wire_patterns_and_coupling, overlap_patterns_and_coupling,
)
from tests.common.cli_runner import run_cli
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.xyce import xyce_port_admittance, requires_xyce
from tests.common.vacask import vacask_port_admittance, requires_vacask


@pytest.fixture
def study(tmp_path: Path, tech_info: TechInfo, pattern_data: Dict[str, Any],
          monkeypatch: pytest.MonkeyPatch) -> Tuple[CalibrationQualificationStudy, Path]:
    def matrix_for_case(case_id: str, variant: str) -> List[List[float]]:
        added = 0.001e-9 if variant == 'solver-coarse' else 0.0
        # Passive network with ground in a non-terminal position and a known change on A.
        return [[5e-9, -2e-9, -1e-9], [-2e-9, 6e-9, -3e-9], [-1e-9, -3e-9, 7e-9 + added]]

    mock_solver(monkeypatch, matrix_for_case)
    return make_study(tmp_path, tech_info, pattern_data, fake=True)


def _run_length_fit(study_path: Path, tmp_path: Path) -> CalibrationLengthFitReport:
    qualified = qualify_study(study_path, tmp_path / 'qualified')
    directory = tmp_path / 'fit'
    code, output = run_cli(KpexCLI().main, [
        'kpex', 'calibrate', 'fit-length', '--study', str(study_path),
        '--qualification', str(qualified.report_path), '--residual-budget-f', '1e-17',
        '--out-dir', str(directory),
    ])
    assert code == 1, output
    return read_message(directory / 'fit-length.pb.json', CalibrationLengthFitReport())


def test_failed_series_keep_successful_length_fits(tmp_path: Path, tech_info: TechInfo,
                                            pattern_data: Dict[str, Any], monkeypatch: pytest.MonkeyPatch):
    patterns, coupling = wire_patterns_and_coupling()
    cases = [
        *patterns,
        pattern_data['patterns'][0],  # A distinct, stabilized series with only one length.
        {'id': 'fringe', 'role': 'TRAINING', 'width_um': '2', 'length_um': '4',
         'directional_fringe': {'edge_layer': 'M1', 'receiver_layer': 'M2', 'receiver_width_um': '2',
                                'lateral_offset_um': '0.1'}},  # Valid for qualification, not fit-length.
        dict(patterns[0], id='unstabilized', width_um='0.8'),
    ]
    mock_solver(monkeypatch, coupling)
    study, _ = make_study(tmp_path, tech_info, dict(pattern_data, patterns=cases), fake=True, case_count=len(cases))
    next(item for item in study.cases if item.case_id == 'unstabilized').ClearField('refinements')
    path = write_message(tmp_path / 'study-with-unusable-cases.pb.json', study)

    report = _run_length_fit(path, tmp_path)
    accepted, few_lengths, unsupported, unstabilized = report.fits
    assert accepted.status == CalibrationLengthFitResult.ACCEPTED
    assert accepted.case_ids == ['wire_4', 'wire_8', 'wire_12', 'wire_16']
    assert accepted.distributed_coupling_f_per_um == pytest.approx(2e-16, abs=1e-29)
    for result, case_id, message in [
        (few_lengths, 'plates', 'at least 3 independent training lengths'),
        (unsupported, 'fringe', 'requires parallel plates or parallel wires'),
        (unstabilized, 'unstabilized', 'INCOMPLETE'),
    ]:
        assert result.status == CalibrationLengthFitResult.REJECTED
        assert result.case_ids == [case_id]
        assert any(message in diagnostic for diagnostic in result.diagnostics)
        assert not result.HasField('distributed_coupling_f_per_um')


def _append_study(combined: CalibrationQualificationStudy, study: CalibrationQualificationStudy, group: str):
    combined.tolerance.CopyFrom(study.tolerance)
    for item in study.collections:
        collection = combined.collections.add(id=f'{group}_{item.id}').collection
        collection.CopyFrom(item.collection)
        collection.path = f'{group}/{collection.path}'
    for item in study.cases:
        case = combined.cases.add()
        case.CopyFrom(item)
        case.reference_collection_id = f'{group}_{item.reference_collection_id}'
        for refinement in case.refinements:
            refinement.collection_ids[:] = [f'{group}_{name}' for name in refinement.collection_ids]


def test_mixed_reference_controls_reject_length_series(tmp_path: Path, tech_info: TechInfo,
                                                       pattern_data: Dict[str, Any], monkeypatch: pytest.MonkeyPatch):
    patterns, coupling = wire_patterns_and_coupling()
    mock_solver(monkeypatch, coupling)
    combined = CalibrationQualificationStudy(schema_version=1)
    for index, gmres in enumerate((1e-8, 5e-9)):
        group = f'group_{index}'
        root = tmp_path / group
        root.mkdir()
        data = dict(pattern_data, patterns=patterns[2 * index:2 * index + 2])
        def solve_at_reference(manifest_path: Path, output_dir: Path, *, options: SolveOptions
                               ) -> CalibrationSolveResult:
            # Scale the entire GMRES series so each case stays independently qualified.
            return solve_original(manifest_path, output_dir,
                                  options=replace(options, gmres_tolerance=options.gmres_tolerance * gmres / 1e-8))

        solve_original = solve_calibration
        with monkeypatch.context() as scope:
            scope.setattr('tests.common.calibration_study.solve_calibration', solve_at_reference)
            study, _ = make_study(root, tech_info, data, fake=True, case_count=2)
        _append_study(combined, study, group)

    path = write_message(tmp_path / 'mixed-settings-study.pb.json', combined)
    report = _run_length_fit(path, tmp_path)
    result, = report.fits
    assert result.status == CalibrationLengthFitResult.REJECTED
    assert result.case_ids == ['wire_4', 'wire_8', 'wire_12', 'wire_16']
    assert list(result.diagnostics) == ['The cases use different reference numerical settings']
    assert not result.HasField('end_correction_f')



@pytest.mark.parametrize('residual, rejected', [
    (math.nextafter(1e-17, 0), False),
    (1e-17, False),
    (math.nextafter(1e-17, math.inf), True),
])
def test_refinement_budget_boundary(residual: float, rejected: bool):
    from kpex.calibration.fit_evidence import refinement_residual_violation

    assert bool(refinement_residual_violation(residual, [-1e-18], 1e-17)) == rejected
    assert bool(refinement_residual_violation(1e-18, [-residual], 1e-17)) == rejected


@pytest.mark.parametrize('holdout_offset_f,budget_f,accepted', [
    (0, 1e-17, True),
    (2e-17, 1e-17, False),
    (0, 5e-19, False),  # The reference passes, but a refit changes the holdout error by 1 aF.
])
def test_fit_qualified_wire_lengths(tmp_path: Path, tech_info: TechInfo, pattern_data: Dict[str, Any],
                                    monkeypatch: pytest.MonkeyPatch, holdout_offset_f: float,
                                    budget_f: float, accepted: bool):
    lengths = {f'wire_{length}': length for length in (4, 8, 12, 16)}
    pattern_data['patterns'] = [
        {'id': name, 'role': 'VALIDATION' if length == 12 else 'TRAINING',
         'length_um': str(length), 'width_um': '0.4', 'parallel_wires': {'layer': 'M1', 'gap_um': '0.2'}}
        for name, length in lengths.items()
    ]

    def matrix_for_case(case_id: str, variant: str) -> List[List[float]]:
        length = lengths[case_id]
        coupling_f = 2e-16 * length + 1e-16 + (holdout_offset_f if length == 12 else 0)
        if variant == 'mesh-medium':
            coupling_f += 1.5e-18 if length == 12 else 0.5e-18
        coupling = coupling_f / 1e-6  # The test report encodes values in microfarads.
        # The native matrix is excitation-major and B comes first. A small
        # in-budget asymmetry distinguishes directed selection from averaging.
        return [[9e-9, -2e-9, -coupling],
                [-2e-9, 8e-9, -2e-9], [-coupling + 1e-13, -2e-9, 9e-9]]

    mock_solver(monkeypatch, matrix_for_case)
    _, path = make_study(tmp_path, tech_info, pattern_data, fake=True, case_count=4)
    qualified = qualify_study(path, tmp_path / 'qualified')
    assert all(case.status == Status.STABILIZED for case in qualified.report.cases)
    # Requalification on another platform can change the last bits of an eigenvalue.
    diagnostics = qualified.report.cases[0].reference_diagnostics[0]
    diagnostics.minimum_energy_eigenvalue_f = math.nextafter(diagnostics.minimum_energy_eigenvalue_f, math.inf)
    write_message(qualified.report_path, qualified.report, replace=True)
    out_dir = tmp_path / 'fit'
    args = ['kpex', 'calibrate', 'fit-length', '--study', str(path),
            '--qualification', str(qualified.report_path), '--residual-budget-f', str(budget_f),
            '--out-dir', str(out_dir)]
    code, output = run_cli(KpexCLI().main, args)
    assert code == (0 if accepted else 1), output
    report = read_message(out_dir / 'fit-length.pb.json', CalibrationLengthFitReport())
    assert report.qualification_sha256 == sha256_file(qualified.report_path)
    assert report.study_sha256 == sha256_file(path)
    fit, = report.fits
    assert fit.status == (CalibrationLengthFitResult.REJECTED if not accepted
                          else CalibrationLengthFitResult.ACCEPTED)
    assert fit.distributed_coupling_f_per_um == pytest.approx(2e-16, abs=1e-29)
    assert fit.end_correction_f == pytest.approx(1e-16, abs=1e-29)
    assert [sample.length_um for sample in fit.training_samples] == [4, 8, 16]
    held, = fit.validation_samples
    assert held.length_um == 12
    assert held.residual_f == pytest.approx(-holdout_offset_f, abs=1e-29)
    assert held.solver_coupling_f - held.reverse_solver_coupling_f == pytest.approx(1e-19, abs=1e-29)
    assert [s.axis for s in fit.refinement_sensitivity] == [
        Axis.LINEAR_SOLVER_TOLERANCE, Axis.INITIAL_MESH_MAX_AREA, Axis.DOMAIN_MARGIN, Axis.ADAPTIVE_MESH_REFINEMENT,
    ]
    mesh = fit.refinement_sensitivity[1]
    assert not mesh.diagnostic
    assert mesh.reference_parameter_value == 0.25
    assert [level.parameter_value for level in mesh.levels] == [2.0, 0.75]
    alternative, = mesh.levels[1].validation_samples
    assert alternative.case_id == held.case_id
    # The held-out measurement moves by 1.5 aF. Only the 0.5 aF change
    # in training data moves the prediction, so the residual falls by 1 aF.
    assert alternative.solver_coupling_f - held.solver_coupling_f == pytest.approx(1.5e-18, abs=1e-29)
    assert alternative.predicted_coupling_f - held.predicted_coupling_f == pytest.approx(0.5e-18, abs=1e-29)
    assert alternative.residual_change_f == pytest.approx(-1e-18, abs=1e-29)
    assert mesh.levels[1].max_abs_training_residual_f == pytest.approx(0, abs=1e-29)
    if budget_f == 5e-19:
        assert any('INITIAL_MESH_MAX_AREA at 0.75' in message for message in fit.diagnostics)

    # Editing only the saved qualification must be detected even when the
    # evidence still supports a fit and the modified report parses correctly.
    qualified.report.cases[0].reference_matrix.rows[0].values[0] *= 2
    write_message(qualified.report_path, qualified.report, replace=True)
    args[-1] = str(tmp_path / 'edited')
    code, output = run_cli(KpexCLI().main, args)
    assert code == 2 and 'differs from the recomputed study' in output
    assert not Path(args[-1]).exists()


@pytest.mark.parametrize('holdout_offset_f,budget_f,accepted', [
    (0, 1e-17, True),
    (2e-17, 1e-17, False),
    (0, 5e-19, False),  # The reference passes, but a refit changes the holdout error by 1 aF.
])
def test_fit_qualified_overlap(tmp_path: Path, targeted_technology: TechInfo,
                               monkeypatch: pytest.MonkeyPatch, holdout_offset_f: float,
                                    budget_f: float, accepted: bool):
    specification, matrix_for_case = overlap_patterns_and_coupling(holdout_offset_f)
    overlap = specification.targets[0].overlap
    mock_solver(monkeypatch, matrix_for_case)
    pattern_data = MessageToDict(specification, preserving_proto_field_name=True)
    study, path = make_study(tmp_path, targeted_technology, pattern_data, fake=True, case_count=len(specification.patterns))
    qualified = qualify_study(path, tmp_path / 'qualified')
    assert all(case.status == Status.STABILIZED for case in qualified.report.cases)
    out_dir = tmp_path / 'fit'
    code, output = run_cli(KpexCLI().main, [
        'kpex', 'calibrate', 'fit-overlap', '--study', str(path),
        '--qualification', str(qualified.report_path), '--residual-budget-f', str(budget_f), '--out-dir', str(out_dir),
    ])
    assert code == (0 if accepted else 1), output
    report = read_message(out_dir / 'fit-overlap.pb.json', CalibrationOverlapFitReport())
    assert report.target.overlap == overlap
    assert report.study_sha256 == sha256_file(path)
    assert report.qualification_sha256 == sha256_file(qualified.report_path)
    assert report.fit.status == (CalibrationOverlapFitResult.REJECTED if not accepted
                                 else CalibrationOverlapFitResult.ACCEPTED)
    assert report.fit.area_coupling_f_per_um2 == pytest.approx(1e-16, abs=1e-29)
    assert report.fit.edge_coupling_f_per_um == pytest.approx(2e-17, abs=1e-29)
    assert report.fit.corner_correction_f == pytest.approx(-4e-17, abs=1e-29)
    assert len(report.fit.training_samples) == 4
    holdout, = report.fit.validation_samples
    assert holdout.residual_f == pytest.approx(-holdout_offset_f, abs=1e-29)
    assert holdout.solver_coupling_f - holdout.reverse_solver_coupling_f == pytest.approx(1e-19, abs=1e-29)
    solver, mesh, domain, adaptive = report.refinement_sensitivity
    assert adaptive.coverage == Coverage.NOT_PROVIDED
    assert (solver.axis, mesh.axis, domain.axis) == (Axis.LINEAR_SOLVER_TOLERANCE, Axis.INITIAL_MESH_MAX_AREA, Axis.DOMAIN_MARGIN)
    assert domain.reference_parameter_value == 8
    assert [level.parameter_value for level in domain.levels] == [2, 4]
    alternate, = mesh.levels[1].validation_samples
    assert alternate.case_id == holdout.case_id
    # The 0.5 aF common training shift belongs wholly to the corner term.
    # A 1.5 aF held-out measurement shift thus decreases the residual by 1 aF.
    assert mesh.levels[1].area_coupling_change_f_per_um2 == pytest.approx(0, abs=1e-29)
    assert mesh.levels[1].max_abs_training_residual_f == pytest.approx(0, abs=1e-29)
    if budget_f == 5e-19:
        assert any('INITIAL_MESH_MAX_AREA at 0.75' in message for message in report.fit.diagnostics)
    assert alternate.residual_change_f == pytest.approx(-1e-18, abs=1e-29)

    # Without independent domain evidence for the holdout, a small residual
    # cannot turn it into a qualified input.
    if accepted:
        del study.cases[-1].refinements[-1]
        incomplete = write_message(tmp_path / 'incomplete-overlap-study.pb.json', study)
        report_path = qualify_study(incomplete, tmp_path / 'incomplete-qualification').report_path
        rejected = tmp_path / 'unqualified-fit'
        code, output = run_cli(KpexCLI().main, [
            'kpex', 'calibrate', 'fit-overlap', '--study', str(incomplete),
            '--qualification', str(report_path), '--residual-budget-f', str(budget_f), '--out-dir', str(rejected),
        ])
        assert code == 2 and "Case 'held_out' is INCOMPLETE" in output
        assert not rejected.exists()



def test_qualified_report_and_budget_boundary(study: Tuple[CalibrationQualificationStudy, Path], tmp_path: Path):
    specification, path = study
    qualified = qualify_study(path, tmp_path / 'qualified')
    assert read_message(qualified.report_path, CalibrationQualificationReport()) == qualified.report
    case = qualified.report.cases[0]
    assert case.status == Status.STABILIZED
    assert [item.status for item in case.refinements] == [Status.STABILIZED] * 3
    assert case.reference_matrix.rows[0].values[0] == pytest.approx(7e-15, abs=1e-30)
    change = max(abs(entry.signed_delta_f) for entry in case.refinements[0].changes[0].entries)
    assert change == pytest.approx(1e-18, abs=1e-29)
    # The entry-wise budget is inclusive. Just below the observed change
    # the same solver runs must give an incomplete result.
    for i, (threshold, status) in enumerate([
        (math.nextafter(change, 0), Status.INCOMPLETE),
        (change, Status.STABILIZED),
        (math.nextafter(change, math.inf), Status.STABILIZED),
    ]):
        specification.tolerance.absolute_floor_f = threshold
        threshold_study = write_message(tmp_path / f'threshold-{i}.pb.json', specification)
        assert qualify_study(threshold_study, tmp_path / f'qualified-{i}').report.cases[0].status == status


@pytest.mark.parametrize('change, expected', [
    ('jobs', Status.STABILIZED),
    ('timeout', Status.STABILIZED),
    ('coefficients', Status.STABILIZED),
    ('process-stack', Status.INCOMPLETE),
    ('threads', Status.INCOMPLETE),
])
def test_qualification_compares_physics_and_numerical_settings(
        study: Tuple[CalibrationQualificationStudy, Path], tmp_path: Path, tech_info: TechInfo,
        change: str, expected: int):
    specification, baseline_path = study
    baseline = qualify_study(baseline_path, tmp_path / 'baseline').report.cases[0]
    assert baseline.status == Status.STABILIZED
    options = SolveOptions(mesh_refinement=0.06, gmres_tolerance=1e-8, mesh_max_area_um2=0.25,
                           solver_timeout_seconds=120)
    prepared = tmp_path / 'prepared-8' / 'manifest.json'
    if change == 'jobs':
        options = replace(options, jobs=2)
    elif change == 'timeout':
        options = replace(options, solver_timeout_seconds=3600)
    elif change == 'threads':
        options = replace(options, threads_per_job=2)
    else:
        if change == 'coefficients':
            tech_info.tech.process_parasitics.side_halo += 1
        else:
            tech_info.process_metal_layers[0].metal_layer.thickness += 0.05
        prepared = prepare_calibration(tech_info, read_patterns(tmp_path / 'patterns-8.pb.json'),
                                       tmp_path / 'prepared-changed').manifest_path
        if change == 'coefficients':
            scene_name = 'case_plates.pex25d.scene.pb'
            assert (prepared.parent / scene_name).read_bytes() == (
                tmp_path / 'prepared-8' / scene_name).read_bytes()

    new_reference = solve_calibration(prepared, tmp_path / 'reference-changed', options=options)
    collection = next(item.collection for item in specification.collections if item.id == 'reference')
    collection.path = new_reference.collection_path.relative_to(tmp_path).as_posix()
    collection.sha256 = sha256_file(new_reference.collection_path)
    path = write_message(tmp_path / 'changed-study.pb.json', specification)
    case = qualify_study(path, tmp_path / 'qualification-changed').report.cases[0]

    assert case.status == expected
    if change == 'coefficients':
        assert case.technology.resolved_technology_sha256 != baseline.technology.resolved_technology_sha256
        assert case.technology.physical_stack_sha256 == baseline.technology.physical_stack_sha256
    elif change == 'process-stack':
        assert case.technology.physical_stack_sha256 != baseline.technology.physical_stack_sha256


def test_incomplete_evidence_cannot_qualify(study: Tuple[CalibrationQualificationStudy, Path], tmp_path: Path):
    specification, _ = study
    case = specification.cases[0]
    del case.refinements[2:]
    del case.refinements[1].collection_ids[0]
    path = write_message(tmp_path / 'incomplete.pb.json', specification)
    outcome = qualify_study(path, tmp_path / 'incomplete').report.cases[0]
    assert outcome.status == Status.INCOMPLETE
    assert 'DOMAIN_MARGIN' in outcome.diagnostics[0]
    assert 'three refinement levels' in outcome.refinements[1].diagnostics[0]


def test_mixed_controls_leave_evidence_incomplete(study: Tuple[CalibrationQualificationStudy, Path], tmp_path: Path):
    specification, _ = study
    levels = specification.cases[0].refinements[0].collection_ids
    levels[0] = 'mesh-coarse'
    path = write_message(tmp_path / 'mixed.pb.json', specification)
    output = qualify_study(path, tmp_path / 'mixed').report.cases[0]
    assert output.status == Status.INCOMPLETE
    assert any('numerical controls changed' in diagnostic for diagnostic in output.refinements[0].diagnostics)


@pytest.mark.parametrize('recompute_hash', [False, True])
def test_changed_raw_collection_is_detected(study: Tuple[CalibrationQualificationStudy, Path], tmp_path: Path,
                                            recompute_hash: bool):
    specification, path = study
    artifact = specification.collections[0].collection
    original = tmp_path / artifact.path
    data = read_message(original, CalibrationCollection())
    data.cases[0].measured_matrix.rows[0].values[0] *= 2
    write_message(original, data, replace=True)
    if recompute_hash:
        artifact.sha256 = sha256_file(original)
        write_message(path, specification, replace=True)
    message = 'differs from the native report' if recompute_hash else 'SHA256 mismatch'
    with pytest.raises(CalibrationError, match=message):
        qualify_study(path, tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()


def test_older_solver_report_cannot_qualify(study: Tuple[CalibrationQualificationStudy, Path], tmp_path: Path):
    specification, path = study
    artifact = specification.collections[0].collection
    collection_path = tmp_path / artifact.path
    collection = read_message(collection_path, CalibrationCollection())
    relative_run = collection.run_manifest.path
    run_path = collection_path.parent / relative_run
    run = read_message(run_path, CalibrationRunManifest())
    run.solver.version = '6.3.0'
    write_message(run_path, run, replace=True)
    digest = sha256_file(run_path)
    collection.run_manifest.sha256 = digest
    next(item for item in collection.artifacts if item.path == relative_run).sha256 = digest
    write_message(collection_path, collection, replace=True)
    artifact.sha256 = sha256_file(collection_path)
    write_message(path, specification, replace=True)
    with pytest.raises(CalibrationError, match='Qualification requires FasterCap.*6.3.0'):
        qualify_study(path, tmp_path / 'old-solver')


def test_invalid_study_is_not_written(tmp_path: Path):
    path = tmp_path / 'study.pb.json'
    path.write_text('{"schema_version":1,"unrecognized_key":true}', encoding='utf-8')
    with pytest.raises(CalibrationError, match='unrecognized_key'):
        qualify_study(path, tmp_path / 'bad')


def test_physical_checks_use_charge_rows():
    # Native excitation rows both sum to a positive value. Charge row A
    # is negative after transposition and is physically inconsistent.
    matrix = Matrix(unit=Matrix.FARAD, index_convention=Matrix.EXCITATION_ROWS,
                    conductor_ids=['A', 'B'])
    matrix.rows.add(values=[2e-15, -1e-15])
    matrix.rows.add(values=[-3e-15, 4e-15])
    report = _diagnose(matrix, CalibrationQualificationTolerance(absolute_floor_f=1e-18))
    assert list(report.charge_row_sums_f) == pytest.approx([-1e-15, 3e-15], abs=1e-30)
    assert 'Negative charge-row sum for A' in report.violations
    assert 'Reciprocity defect for A / B' in report.violations


@pytest.mark.slow
@pytest.mark.fastercap
@pytest.mark.skipif(shutil.which('FasterCap') is None, reason='FasterCap is not installed')
def test_refinement_axes_with_fastercap(tmp_path: Path, tech_info: TechInfo, pattern_data: Dict[str, Any]):
    _, path = make_study(tmp_path, tech_info, pattern_data, adaptive=True)
    result = qualify_study(path, tmp_path / 'qualify')
    report = read_message(result.report_path, CalibrationQualificationReport())
    case = report.cases[0]
    assert case.reference_matrix.rows[0].values[0] > 0
    assert [axis.axis for axis in case.refinements] == [
        Axis.LINEAR_SOLVER_TOLERANCE, Axis.INITIAL_MESH_MAX_AREA, Axis.DOMAIN_MARGIN,
        Axis.ADAPTIVE_MESH_REFINEMENT,
    ]
    for axis in case.refinements:
        assert len(axis.levels) == 3
        assert all(statistics_message(level.solver_statistics).refined_panels > 0 and len(level.matrix_diagnostics) == 2 for level in axis.levels)
        assert not any('geometry' in diagnostic or 'controls changed' in diagnostic for diagnostic in axis.diagnostics)
        if axis.status == Status.STABILIZED:
            assert len(axis.changes) == 2
            assert all(change.within_budget for change in axis.changes)
        else:
            assert axis.diagnostics


@pytest.mark.parametrize('middle_panels, expected', [(60, Status.STABILIZED), (80, Status.INCOMPLETE)])
def test_initial_and_adaptive_mesh_axes_use_their_own_panel_counts(
        tmp_path: Path, tech_info: TechInfo, pattern_data: Dict[str, Any], monkeypatch: pytest.MonkeyPatch,
        middle_panels: int, expected: int):
    def constant_matrix(case_id: str, variant: str) -> List[List[float]]:
        return [[5e-9, -2e-9, -1e-9], [-2e-9, 6e-9, -3e-9], [-1e-9, -3e-9, 7e-9]]

    mock_solver(monkeypatch, constant_matrix, adaptive_middle_panels=middle_panels)
    _, path = make_study(tmp_path, tech_info, pattern_data, fake=True, adaptive=True)
    case, = qualify_study(path, tmp_path / 'qualify').report.cases
    by_axis = {refinement.axis: refinement for refinement in case.refinements}
    initial = by_axis[Axis.INITIAL_MESH_MAX_AREA]
    assert [statistics_message(level.solver_statistics).input_panels for level in initial.levels] == [20, 30, 40]
    assert [statistics_message(level.solver_statistics).refined_panels for level in initial.levels] == [90, 60, 80]
    assert initial.status == Status.STABILIZED

    adaptive = by_axis[Axis.ADAPTIVE_MESH_REFINEMENT]
    assert [statistics_message(level.solver_statistics).input_panels for level in adaptive.levels] == [40, 40, 40]
    assert [level.parameter_value for level in adaptive.levels] == [0.18, 0.12, 0.06]
    assert adaptive.status == expected and case.status == expected
    if expected == Status.INCOMPLETE:
        assert any('adaptive panel counts' in reason for reason in adaptive.diagnostics)


def _cross_revision_study(tmp_path: Path, tech_info: TechInfo, monkeypatch: pytest.MonkeyPatch,
                          kind: str, change: str) -> Tuple[Path, Path, CalibrationQualificationReport]:
    if kind == 'length':
        patterns, coupling = wire_patterns_and_coupling()
        data = {'schema_version': 1, 'grid_um': '0.001', 'patterns': patterns}
    else:
        specification, coupling = overlap_patterns_and_coupling()
        data = MessageToDict(specification, preserving_proto_field_name=True)
        patterns = data['patterns']
    mock_solver(monkeypatch, coupling)
    combined = CalibrationQualificationStudy(schema_version=1)
    for index in range(2):
        root = tmp_path / f'group_{index}'
        root.mkdir()
        if index == 1:
            if change == 'coefficient':
                row = tech_info.tech.process_parasitics.capacitance.overlaps[0]
                # One representable step is enough to change coefficient provenance.
                row.capacitance = math.nextafter(row.capacitance, math.inf)
            elif change == 'halo':
                tech_info.tech.process_parasitics.side_halo += 1
            elif change == 'name':
                tech_info.tech.name += '_revision_b'
            elif change == 'stack':
                dielectric = tech_info.field_oxide_layer.field_oxide_layer
                # Even a tiny physical-stack change must not be treated as a
                # coefficient update. Both groups remain independently qualified.
                dielectric.dielectric_k = math.nextafter(dielectric.dielectric_k, math.inf)
        subset = patterns[:2] if index == 0 else patterns[2:]
        options_scale = 0.5 if index == 1 and change == 'controls' else 1
        solve_original = solve_calibration

        def solve_at_reference(manifest_path: Path, output_dir: Path, *, options: SolveOptions
                               ) -> CalibrationSolveResult:
            return solve_original(manifest_path, output_dir, options=replace(
                options, gmres_tolerance=options.gmres_tolerance * options_scale))

        with monkeypatch.context() as scope:
            scope.setattr('tests.common.calibration_study.solve_calibration', solve_at_reference)
            study, _ = make_study(root, tech_info, dict(data, patterns=subset), fake=True, case_count=len(subset))
        _append_study(combined, study, f'group_{index}')
    path = write_message(tmp_path / 'combined-study.pb.json', combined)
    qualified = qualify_study(path, tmp_path / 'qualified')
    assert all(case.status == Status.STABILIZED for case in qualified.report.cases)
    return path, qualified.report_path, qualified.report


def _cross_revision_fit(tmp_path: Path, tech_info: TechInfo, monkeypatch: pytest.MonkeyPatch,
                        kind: str, change: str
                        ) -> Tuple[int, str, Optional[Union[CalibrationLengthFitReport, CalibrationOverlapFitReport]],
                                   CalibrationQualificationReport]:
    path, qualification, evidence = _cross_revision_study(tmp_path, tech_info, monkeypatch, kind, change)
    input_hashes = {item: sha256_file(item) for item in (path, qualification)}
    output_dir = tmp_path / 'fit'
    code, output = run_cli(KpexCLI().main, [
        'kpex', 'calibrate', f'fit-{kind}', '--study', str(path), '--qualification', str(qualification),
        '--residual-budget-f', '1e-17', '--out-dir', str(output_dir),
    ])
    assert input_hashes == {item: sha256_file(item) for item in input_hashes}
    report = None
    if code != 2:
        schema = CalibrationLengthFitReport if kind == 'length' else CalibrationOverlapFitReport
        report = read_message(output_dir / f'fit-{kind}.pb.json', schema())
    return code, output, report, evidence


@pytest.mark.parametrize('kind', ['length', 'overlap'])
@pytest.mark.parametrize('change', ['none', 'coefficient', 'halo', 'name', 'stack', 'controls'])
def test_fits_across_technology_revisions(tmp_path: Path, targeted_technology: TechInfo,
                                         monkeypatch: pytest.MonkeyPatch, kind: str, change: str):
    code, output, report, evidence = _cross_revision_fit(tmp_path, targeted_technology, monkeypatch, kind, change)
    compatible = change not in ('stack', 'controls')
    expected_code = 0 if compatible else (1 if kind == 'length' else 2)
    assert code == expected_code, output
    hashes = {case.technology.physical_stack_sha256 for case in evidence.cases}
    assert len(hashes) == (2 if change == 'stack' else 1)
    revisions = {case.technology.resolved_technology_sha256 for case in evidence.cases}
    assert len(revisions) == (1 if change in ('none', 'controls') else 2)
    if code == 2:
        assert "does not share the overlap fit's target or reference settings" in output
        assert not (tmp_path / 'fit').exists()
        return
    assert report.schema_version == 1
    expected_sources = {case.case_id: case.technology for case in evidence.cases}
    if kind == 'length':
        assert len(report.fits) == (2 if change == 'stack' else 1)
        actual_sources = {case_id: source for fit in report.fits
                          for case_id, source in fit.case_technologies.items()}
        assert actual_sources == expected_sources
        for fit in report.fits:
            assert set(fit.case_technologies) == set(fit.case_ids)
            assert all(source.physical_stack_sha256 == fit.series.physical_stack_sha256
                       for source in fit.case_technologies.values())
            assert fit.status == (fit.ACCEPTED if compatible else fit.REJECTED)
        if compatible:
            fit, = report.fits
            assert fit.distributed_coupling_f_per_um == pytest.approx(2e-16, abs=1e-29)
            assert fit.end_correction_f == pytest.approx(1e-16, abs=1e-29)
    else:
        assert dict(report.case_technologies) == expected_sources
        assert report.physical_stack_sha256 == next(iter(hashes))
        assert report.fit.status == report.fit.ACCEPTED
        assert report.fit.area_coupling_f_per_um2 == pytest.approx(1e-16, abs=1e-29)
        assert report.fit.edge_coupling_f_per_um == pytest.approx(2e-17, abs=1e-29)
        assert report.fit.corner_correction_f == pytest.approx(-4e-17, abs=1e-29)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', [pytest.param(ngspice_port_admittance, marks=requires_ngspice, id='ngspice'),
                                     pytest.param(xyce_port_admittance, marks=requires_xyce, id='Xyce'),
                                     pytest.param(vacask_port_admittance, marks=requires_vacask, id='VACASK')])
@pytest.mark.parametrize('kind', ['length', 'overlap'])
def test_cross_revision_fit_predicts_circuit_coupling(tmp_path: Path, targeted_technology: TechInfo,
                                                     monkeypatch: pytest.MonkeyPatch, kind: str, simulator: Callable):
    code, output, report, _ = _cross_revision_fit(tmp_path, targeted_technology, monkeypatch, kind, 'coefficient')
    assert code == 0, output
    fit = report.fits[0] if kind == 'length' else report.fit
    holdout, = fit.validation_samples
    # Independent capacitor circuit at the held-out geometry. Its capacitance
    # is specified from the analytic input, not from the fitted prediction.
    coupling_f = 2e-16 * 12 + 1e-16 if kind == 'length' else 1e-16 * 18 + 2e-17 * 18 - 4e-17
    assert_circuit_coupling(tmp_path, simulator, coupling_f, holdout.predicted_coupling_f)


@pytest.mark.slow
@pytest.mark.fastercap
@pytest.mark.skipif(shutil.which('FasterCap') is None, reason='FasterCap is not installed')
def test_coefficient_update_preserves_field_solve(tmp_path: Path, targeted_technology: TechInfo,
                                                 pattern_data: Dict[str, Any]):
    matrices, technologies, scenes = [], [], []
    options = SolveOptions(jobs=1, threads_per_job=1, mesh_refinement=0.18, gmres_tolerance=1e-6,
                           mesh_max_area_um2=2.0, solver_timeout_seconds=120)
    specification = tmp_path / 'patterns.pb.json'
    specification.write_text(json.dumps(pattern_data), encoding='utf-8')
    for revision in range(2):
        if revision:
            targeted_technology.tech.process_parasitics.capacitance.overlaps[0].capacitance += 1
            targeted_technology.tech.process_parasitics.side_halo += 1
        prepared = prepare_calibration(targeted_technology, read_patterns(specification),
                                       tmp_path / f'prepared-{revision}')
        manifest = read_message(prepared.manifest_path, CalibrationManifest())
        technologies.append(manifest.technology)
        scenes.append([(prepared.manifest_path.parent / case.scene).read_bytes() for case in manifest.cases])
        solved = solve_calibration(prepared.manifest_path, tmp_path / f'solved-{revision}', options=options)
        collection = read_message(solved.collection_path, CalibrationCollection())
        assert solved.successful_cases == 2, [(case.case_id, list(case.diagnostics))
                                              for case in collection.cases if case.status != case.COLLECTED]
        matrices.append([case.measured_matrix for case in collection.cases])
    assert technologies[0].resolved_technology_sha256 != technologies[1].resolved_technology_sha256
    assert technologies[0].physical_stack_sha256 == technologies[1].physical_stack_sha256
    assert scenes[0] == scenes[1]
    # Same geometry and solver controls must yield the same matrices despite
    # coefficient provenance changing. This is an invariance check, not an
    # assertion that this deliberately coarse solve is a calibrated reference.
    for before, after in zip(matrices[0], matrices[1]):
        assert before.conductor_ids == after.conductor_ids
        np.testing.assert_allclose([row.values for row in after.rows], [row.values for row in before.rows],
                                   rtol=1e-12, atol=0)
