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
           *, fake: bool = False, case_count: int = 1) -> Tuple[CalibrationQualificationStudy, Path]:
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
    return study, write_message(root / 'study.pb.json', study)


def _mock_solver(monkeypatch: pytest.MonkeyPatch, matrix_for_case: Callable[[str, str], List[List[float]]]):
    executable = Path(sys.executable).resolve()
    identity = SolverIdentity(name='fastercap', version='6.4.0', executable_path=str(executable),
                              executable_sha256=sha256_file(executable), operating_system='test', architecture='test')
    monkeypatch.setattr('kpex.calibration.solve._solver_identity', lambda _: identity)

    def run(exe: str, deck: str, log: str, *args: Any, report_path: str, **kwargs: Any) -> FasterCapRunResult:
        variant = Path(log).parents[2].name
        panels = {'mesh-coarse': 40, 'mesh-medium': 60}.get(variant, 80)
        names = ['g1_B', 'g2_substrate', 'g3_A']
        matrix = matrix_for_case(Path(log).parent.name, variant)
        external = numerical_report(names, matrix, deck)
        external['build']['version'] = 'FasterCap version 6.4.0'
        Path(report_path).write_text(json.dumps(external), encoding='utf-8')
        Path(log).write_text('Capacitance matrix is:\nSolve statistics:\n'
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


@pytest.mark.parametrize('holdout_offset_f', [0, 2e-17])
def test_fit_qualified_wire_lengths(tmp_path: Path, tech_info: TechInfo, pattern_data: Dict[str, Any],
                                    monkeypatch: pytest.MonkeyPatch, holdout_offset_f: float):
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
            '--qualification', str(qualified.report_path), '--residual-budget-f', '1e-17',
            '--out-dir', str(out_dir)]
    code, output = run_cli(KpexCLI().main, args)
    assert code == (1 if holdout_offset_f else 0), output
    report = read_message(out_dir / 'fit-length.pb.json', CalibrationLengthFitReport())
    assert report.qualification_sha256 == sha256_file(qualified.report_path)
    assert report.study_sha256 == sha256_file(path)
    fit, = report.fits
    assert fit.status == (CalibrationLengthFitResult.REJECTED if holdout_offset_f
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

    # Editing only the saved qualification must be detected even when the
    # evidence still supports a fit and the modified report parses correctly.
    qualified.report.cases[0].reference_matrix.rows[0].values[0] *= 2
    write_message(qualified.report_path, qualified.report, replace=True)
    args[-1] = str(tmp_path / 'edited')
    code, output = run_cli(KpexCLI().main, args)
    assert code == 2 and 'differs from the recomputed study' in output
    assert not Path(args[-1]).exists()


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
def test_three_refinement_axes_with_fastercap(tmp_path: Path, tech_info: TechInfo, pattern_data: Dict[str, Any]):
    _, path = _study(tmp_path, tech_info, pattern_data)
    result = qualify_study(path, tmp_path / 'qualify')
    report = read_message(result.report_path, CalibrationQualificationReport())
    case = report.cases[0]
    assert case.reference_matrix.rows[0].values[0] > 0
    assert [axis.axis for axis in case.refinements] == [
        Axis.GMRES_TOLERANCE, Axis.INITIAL_MESH_MAX_AREA, Axis.DOMAIN_MARGIN,
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
