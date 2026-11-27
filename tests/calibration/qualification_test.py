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
import sys
from typing import Any, Callable, Dict, List, Tuple

import pytest
from google.protobuf.json_format import MessageToDict

from kpex.calibration.artifacts import read_message, sha256_file, write_message
from kpex.calibration.patterns import read_patterns
from kpex.calibration.prepare import prepare_calibration
from kpex.calibration.qualification import _diagnose, qualify_study
from kpex.calibration.solve import SolveOptions, solve_calibration
from kpex.calibration.validation import CalibrationError
from kpex.fastercap.fastercap_runner import FasterCapRunResult
from kpex.kpex_cli import KpexCLI
from kpex.tech_info import TechInfo
from kpex_protobuf.kpex.calibration.length_fit_pb2 import CalibrationLengthFitReport, CalibrationLengthFitResult
from kpex_protobuf.kpex.calibration.overlap_fit_pb2 import CalibrationOverlapFitReport, CalibrationOverlapFitResult
from kpex_protobuf.kpex.calibration.patterns_pb2 import PatternSetSpecification, TRAINING, VALIDATION
from kpex_protobuf.kpex.calibration.qualification_pb2 import (
    CalibrationQualificationReport, CalibrationQualificationStatus as Status,
    CalibrationQualificationStudy, CalibrationQualificationTolerance, CalibrationRefinementAxis as Axis,
)
from kpex_protobuf.kpex.calibration.solving_pb2 import CalibrationCollection, CalibrationRunManifest
from kpex_protobuf.kpex.result.capacitance_matrix_pb2 import MaxwellCapacitanceMatrix as Matrix
from kpex_protobuf.kpex.result.solver_execution_pb2 import SolverIdentity
from tests.common.cli_runner import run_cli
from tests.common.fastercap_report import numerical_report


def _study(root: Path, tech_info: TechInfo, pattern_data: Dict[str, Any],
           *, fake: bool = False, case_count: int = 1, adaptive: bool = False
           ) -> Tuple[CalibrationQualificationStudy, Path]:
    prepared = {}
    patterns = pattern_data['patterns'][:case_count]
    for margin in (2, 4, 8):
        specification = root / f'patterns-{margin}.pb.json'
        data = dict(pattern_data, domain_margin_um=str(margin), patterns=patterns)
        specification.write_text(json.dumps(data), encoding='utf-8')
        prepared[margin] = prepare_calibration(
            tech_info, read_patterns(specification), root / f'prepared-{margin}').manifest_path
    reference = SolveOptions(mesh_refinement=0.06, gmres_tolerance=1e-8, mesh_max_area_um2=0.25,
                             solver_timeout_seconds=120)
    variants = {
        'reference': (8, reference),
        'solver-coarse': (8, replace(reference, gmres_tolerance=1e-4)),
        'solver-medium': (8, replace(reference, gmres_tolerance=1e-6)),
        'mesh-coarse': (8, replace(reference, mesh_max_area_um2=2.0)),
        'mesh-medium': (8, replace(reference, mesh_max_area_um2=0.75)),
        'domain-small': (2, reference),
        'domain-medium': (4, reference),
    }
    if adaptive:
        variants['adaptive-coarse'] = (8, replace(reference, mesh_refinement=0.18))
        variants['adaptive-medium'] = (8, replace(reference, mesh_refinement=0.12))
    study = CalibrationQualificationStudy(schema_version=1)
    # Use an explicit 2% budget for the real pilot. The solver test verifies
    # the reported comparisons, allowing platform-dependent convergence.
    study.tolerance.absolute_floor_f = 2e-18
    study.tolerance.relative_tolerance = 0 if fake else 0.02
    for name, (margin, options) in variants.items():
        result = solve_calibration(prepared[margin], root / name, options=options)
        assert result.successful_cases == case_count, result
        entry = study.collections.add(id=name).collection
        entry.path = result.collection_path.relative_to(root).as_posix()
        entry.sha256 = sha256_file(result.collection_path)
    for pattern in patterns:
        case = study.cases.add(case_id=pattern['id'], reference_collection_id='reference')
        case.refinements.add(axis=Axis.GMRES_TOLERANCE, collection_ids=['solver-coarse', 'solver-medium', 'reference'])
        case.refinements.add(axis=Axis.INITIAL_MESH_MAX_AREA, collection_ids=['mesh-coarse', 'mesh-medium', 'reference'])
        case.refinements.add(axis=Axis.DOMAIN_MARGIN, collection_ids=['domain-small', 'domain-medium', 'reference'])
        if adaptive:
            case.refinements.add(axis=Axis.FASTERCAP_MESH_REFINEMENT,
                                 collection_ids=['adaptive-coarse', 'adaptive-medium', 'reference'])
    return study, write_message(root / 'study.pb.json', study)


def _mock_solver(monkeypatch: pytest.MonkeyPatch, matrix_for_case: Callable[[str, str], List[List[float]]],
                 adaptive_middle_panels: int = 60):
    executable = Path(sys.executable).resolve()
    identity = SolverIdentity(name='fastercap', version='6.4.0', executable_path=str(executable),
                              executable_sha256=sha256_file(executable), operating_system='test', architecture='test')
    monkeypatch.setattr('kpex.calibration.solve._solver_identity', lambda _: identity)

    def run(exe: str, deck: str, log: str, *args: Any, report_path: str, **kwargs: Any) -> FasterCapRunResult:
        variant = Path(log).parents[2].name
        input_panels = {'mesh-coarse': 20, 'mesh-medium': 30}.get(variant, 40)
        # Fixed -m can adapt a coarser input to a larger final mesh.
        panels = {'mesh-coarse': 90, 'mesh-medium': 60, 'adaptive-coarse': 50,
                  'adaptive-medium': adaptive_middle_panels}.get(variant, 80)
        names = ['g1_B', 'g2_substrate', 'g3_A']
        matrix = matrix_for_case(Path(log).parent.name, variant)
        external = numerical_report(names, matrix, deck)
        external['build']['version'] = 'FasterCap version 6.4.0'
        Path(report_path).write_text(json.dumps(external), encoding='utf-8')
        Path(log).write_text('Capacitance matrix is:\nSolve statistics:\n'
                             f'Number of input panels to solver engine: {input_panels}\n'
                             f'Number of panels after refinement: {panels}\n', encoding='utf-8')
        return FasterCapRunResult((exe, deck), 0, 0.1)

    monkeypatch.setattr('kpex.fastercap.fastercap_runner.run_fastercap', run)


@pytest.fixture
def study(tmp_path: Path, tech_info: TechInfo, pattern_data: Dict[str, Any],
          monkeypatch: pytest.MonkeyPatch) -> Tuple[CalibrationQualificationStudy, Path]:
    def matrix_for_case(case_id: str, variant: str) -> List[List[float]]:
        added = 0.001e-9 if variant == 'solver-coarse' else 0.0
        # Passive network with ground in a non-terminal position and a known change on A.
        return [[5e-9, -2e-9, -1e-9], [-2e-9, 6e-9, -3e-9], [-1e-9, -3e-9, 7e-9 + added]]

    _mock_solver(monkeypatch, matrix_for_case)
    return _study(tmp_path, tech_info, pattern_data, fake=True)


def _wire_patterns_and_coupling():
    lengths = {f'wire_{length}': length for length in (4, 8, 12, 16)}
    patterns = [
        {'id': name, 'role': 'VALIDATION' if length == 12 else 'TRAINING',
         'length_um': str(length), 'width_um': '0.4', 'parallel_wires': {'layer': 'M1', 'gap_um': '0.2'}}
        for name, length in lengths.items()
    ]

    def matrix_for_case(case_id: str, variant: str) -> List[List[float]]:
        coupling = (2e-16 * lengths.get(case_id, 4) + 1e-16) / 1e-6
        return [[9e-9, -2e-9, -coupling],
                [-2e-9, 8e-9, -2e-9], [-coupling, -2e-9, 9e-9]]

    return patterns, matrix_for_case


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
    patterns, coupling = _wire_patterns_and_coupling()
    cases = [
        *patterns,
        pattern_data['patterns'][0],  # A distinct, stabilized series with only one length.
        {'id': 'fringe', 'role': 'TRAINING', 'width_um': '2', 'length_um': '4',
         'directional_fringe': {'edge_layer': 'M1', 'receiver_layer': 'M2', 'receiver_width_um': '2',
                                'lateral_offset_um': '0.1'}},  # Valid for qualification, not fit-length.
        dict(patterns[0], id='unstabilized', width_um='0.8'),
    ]
    _mock_solver(monkeypatch, coupling)
    study, _ = _study(tmp_path, tech_info, dict(pattern_data, patterns=cases), fake=True, case_count=len(cases))
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


def test_mixed_reference_controls_reject_length_series(tmp_path: Path, tech_info: TechInfo,
                                                       pattern_data: Dict[str, Any], monkeypatch: pytest.MonkeyPatch):
    patterns, coupling = _wire_patterns_and_coupling()
    _mock_solver(monkeypatch, coupling)
    combined = CalibrationQualificationStudy(schema_version=1)
    for index, gmres in enumerate((1e-8, 5e-9)):
        group = f'group_{index}'
        root = tmp_path / group
        root.mkdir()
        data = dict(pattern_data, patterns=patterns[2 * index:2 * index + 2])
        def solve_at_reference(manifest_path, output_dir, *, options):
            # Scale the entire GMRES series so each case stays independently qualified.
            return solve_original(manifest_path, output_dir,
                                  options=replace(options, gmres_tolerance=options.gmres_tolerance * gmres / 1e-8))

        solve_original = solve_calibration
        with monkeypatch.context() as scope:
            scope.setattr(sys.modules[__name__], 'solve_calibration', solve_at_reference)
            study, _ = _study(root, tech_info, data, fake=True, case_count=2)
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

    _mock_solver(monkeypatch, matrix_for_case)
    _, path = _study(tmp_path, tech_info, pattern_data, fake=True, case_count=4)
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
        Axis.GMRES_TOLERANCE, Axis.INITIAL_MESH_MAX_AREA, Axis.DOMAIN_MARGIN,
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
    specification = PatternSetSpecification(schema_version=1, grid_um='0.001', fringe_scale_mode='HALO_NORMALIZED')
    overlap = specification.targets.add(id='overlap').overlap
    overlap.top.canonical_layer, overlap.top.process_profile = 'routing2', 'M2'
    overlap.bottom.canonical_layer, overlap.bottom.process_profile = 'routing1', 'M1'
    rectangles = dict(training_1=(2, 4), training_2=(2, 8), training_3=(4, 4), training_4=(4, 8), held_out=(3, 6))
    for case_id, (width, length) in rectangles.items():
        pattern = specification.patterns.add(id=case_id, width_um=str(width), length_um=str(length),
                                             role=VALIDATION if case_id == 'held_out' else TRAINING,
                                             target_ids=['overlap'])
        pattern.parallel_plates.lower_layer = 'M1'
        pattern.parallel_plates.upper_layer = 'M2'

    def matrix_for_case(case_id: str, variant: str) -> List[List[float]]:
        width, length = rectangles[case_id]
        coupling = 1e-16 * width * length + 2e-17 * 2 * (width + length) - 4e-17
        if case_id == 'held_out':
            coupling += holdout_offset_f
        if variant == 'mesh-medium':
            coupling += 1.5e-18 if case_id == 'held_out' else 0.5e-18
        coupling /= 1e-6  # The native solver report fixture is in microfarads.
        return [[9e-9, -2e-9, -coupling],
                [-2e-9, 8e-9, -2e-9], [-coupling + 1e-13, -2e-9, 9e-9]]

    _mock_solver(monkeypatch, matrix_for_case)
    pattern_data = MessageToDict(specification, preserving_proto_field_name=True)
    study, path = _study(tmp_path, targeted_technology, pattern_data, fake=True, case_count=len(rectangles))
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
    solver, mesh, domain = report.refinement_sensitivity
    assert (solver.axis, mesh.axis, domain.axis) == (Axis.GMRES_TOLERANCE, Axis.INITIAL_MESH_MAX_AREA, Axis.DOMAIN_MARGIN)
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
    _, path = _study(tmp_path, tech_info, pattern_data, adaptive=True)
    result = qualify_study(path, tmp_path / 'qualify')
    report = read_message(result.report_path, CalibrationQualificationReport())
    case = report.cases[0]
    assert case.reference_matrix.rows[0].values[0] > 0
    assert [axis.axis for axis in case.refinements] == [
        Axis.GMRES_TOLERANCE, Axis.INITIAL_MESH_MAX_AREA, Axis.DOMAIN_MARGIN,
        Axis.FASTERCAP_MESH_REFINEMENT,
    ]
    for axis in case.refinements:
        assert len(axis.levels) == 3
        assert all(level.refined_panels > 0 and len(level.matrix_diagnostics) == 2 for level in axis.levels)
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

    _mock_solver(monkeypatch, constant_matrix, adaptive_middle_panels=middle_panels)
    _, path = _study(tmp_path, tech_info, pattern_data, fake=True, adaptive=True)
    case, = qualify_study(path, tmp_path / 'qualify').report.cases
    by_axis = {refinement.axis: refinement for refinement in case.refinements}
    initial = by_axis[Axis.INITIAL_MESH_MAX_AREA]
    assert [level.input_panels for level in initial.levels] == [20, 30, 40]
    assert [level.refined_panels for level in initial.levels] == [90, 60, 80]
    assert initial.status == Status.STABILIZED

    adaptive = by_axis[Axis.FASTERCAP_MESH_REFINEMENT]
    assert [level.input_panels for level in adaptive.levels] == [40, 40, 40]
    assert [level.parameter_value for level in adaptive.levels] == [0.18, 0.12, 0.06]
    assert adaptive.status == expected and case.status == expected
    if expected == Status.INCOMPLETE:
        assert any('adaptive panel counts' in reason for reason in adaptive.diagnostics)
