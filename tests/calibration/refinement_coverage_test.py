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
"""Optional refinement evidence must not penalize otherwise valid fits."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import pytest
from google.protobuf.json_format import MessageToDict

from kpex.calibration.artifacts import read_message, write_message
from kpex.calibration.fit_evidence import refinement_settings
from kpex.calibration.qualification import qualify_study
from kpex.kpex_cli import KpexCLI
from kpex.tech_info import TechInfo
from kpex_protobuf.kpex.calibration.fit_pb2 import CalibrationFitRefinementCoverage as Coverage
from kpex_protobuf.kpex.calibration.qualification_pb2 import (
    CalibrationRefinementAxis as Axis, CalibrationQualificationStatus as Status,
    CalibrationQualificationCaseResult, CalibrationQualificationReport, CalibrationQualificationStudy,
)
from kpex_protobuf.kpex.calibration.length_fit_pb2 import CalibrationLengthFitReport
from kpex_protobuf.kpex.calibration.overlap_fit_pb2 import CalibrationOverlapFitReport
from tests.common.calibration_study import (
    assert_circuit_coupling, make_study, mock_solver, wire_patterns_and_coupling, overlap_patterns_and_coupling,
)
from tests.common.cli_runner import run_cli
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.xyce import xyce_port_admittance, requires_xyce
from tests.common.vacask import vacask_port_admittance, requires_vacask


def _fit(study: CalibrationQualificationStudy, root: Path, kind: str, name: str
         ) -> Tuple[int, str, Optional[Union[CalibrationLengthFitReport, CalibrationOverlapFitReport]],
                    CalibrationQualificationReport]:
    path = write_message(root / f'{name}.pb.json', study)
    qualification = qualify_study(path, root / f'{name}-qualified')
    output_dir = root / f'{name}-fit'
    code, output = run_cli(KpexCLI().main, [
        'kpex', 'calibrate', f'fit-{kind}', '--study', str(path),
        '--qualification', str(qualification.report_path), '--residual-budget-f', '1e-17',
        '--out-dir', str(output_dir),
    ])
    report_path = output_dir / f'fit-{kind}.pb.json'
    schema = CalibrationLengthFitReport if kind == 'length' else CalibrationOverlapFitReport
    report = read_message(report_path, schema()) if report_path.exists() else None
    return code, output, report, qualification.report


def _study_without_some_sweeps(study: CalibrationQualificationStudy, count: int,
                               axis: int = Axis.ADAPTIVE_MESH_REFINEMENT) -> CalibrationQualificationStudy:
    edited = CalibrationQualificationStudy()
    edited.CopyFrom(study)
    for case in edited.cases[count:]:
        for index, refinement in reversed(list(enumerate(case.refinements))):
            if refinement.axis == axis:
                del case.refinements[index]
    return edited


def _make_fit_study(tmp_path: Path, tech_info: TechInfo, pattern_data: Dict[str, Any],
                    monkeypatch: pytest.MonkeyPatch, kind: str, failure: str = '') -> CalibrationQualificationStudy:
    if kind == 'length':
        patterns, coupling = wire_patterns_and_coupling()
        data = dict(pattern_data, patterns=patterns)
        held_out = 'wire_12'
    else:
        specification, coupling = overlap_patterns_and_coupling()
        data = MessageToDict(specification, preserving_proto_field_name=True)
        held_out = 'held_out'

    def matrix(case_id: str, variant: str) -> List[List[float]]:
        result = coupling(case_id, variant)
        if variant == 'adaptive-medium':
            if failure == 'physical':
                result[0][0] = -1e-9  # Negative self capacitance cannot be qualified.
            elif failure == 'residual' and case_id == held_out:
                result[0][2] -= 3e-17 / 1e-6
                result[2][0] -= 3e-17 / 1e-6
        return result

    mock_solver(monkeypatch, matrix, adaptive_middle_panels=80 if failure == 'panels' else 60)
    study, _ = make_study(tmp_path, tech_info, data, fake=True, case_count=len(data['patterns']), adaptive=True)
    if failure == 'residual':
        # A 40 aF qualification allowance can resolve the 30 aF variation,
        # while the independently declared 10 aF fit budget must reject it.
        study.tolerance.absolute_floor_f = 4e-17
    return study


@pytest.mark.parametrize('kind', ['length', 'overlap'])
def test_partial_optional_refinement_preserves_accepted_fit(
        tmp_path: Path, targeted_technology: TechInfo, pattern_data: Dict[str, Any],
        monkeypatch: pytest.MonkeyPatch, kind: str):
    study = _make_fit_study(tmp_path, targeted_technology, pattern_data, monkeypatch, kind)
    baseline = None
    # Presence boundaries: absent, one supplied, one missing, and complete.
    for count in (0, 1, len(study.cases) - 1, len(study.cases)):
        edited = _study_without_some_sweeps(study, count)
        code, output, report, qualification = _fit(edited, tmp_path, kind, f'coverage-{count}')
        assert all(case.status == Status.STABILIZED for case in qualification.cases)
        assert code == 0, output
        fit = report.fits[0] if kind == 'length' else report.fit
        assert fit.status == fit.ACCEPTED and not fit.diagnostics
        sensitivities = fit.refinement_sensitivity if kind == 'length' else report.refinement_sensitivity
        adaptive, = [s for s in sensitivities if s.axis == Axis.ADAPTIVE_MESH_REFINEMENT]
        expected = Coverage.COMPLETE if count == len(study.cases) else Coverage.PARTIAL if count else Coverage.NOT_PROVIDED
        assert adaptive.coverage == expected
        assert list(adaptive.missing_case_ids) == [case.case_id for case in study.cases[count:]]
        assert adaptive.HasField('reference_parameter_value') == (expected == Coverage.COMPLETE)
        if expected == Coverage.COMPLETE:
            assert [level.parameter_value for level in adaptive.levels] == [0.18, 0.12]
            assert not adaptive.diagnostic
        else:
            assert not adaptive.levels
            assert 'Sensitivity not evaluated' in output
            assert all(case_id in adaptive.diagnostic for case_id in adaptive.missing_case_ids)
        required = [s for s in sensitivities if s.axis != Axis.ADAPTIVE_MESH_REFINEMENT]
        assert all(s.coverage == Coverage.COMPLETE and len(s.levels) == 2 for s in required)
        # Adding or withholding optional evidence must not change the reference fit.
        samples = (list(fit.training_samples), list(fit.validation_samples))
        if baseline is None:
            baseline = samples
        assert samples == baseline
        assert fit.validation_samples[0].residual_f == pytest.approx(0, abs=1e-29)

    incomplete = _study_without_some_sweeps(study, len(study.cases) - 1, Axis.DOMAIN_MARGIN)
    code, output, report, qualification = _fit(incomplete, tmp_path, kind, 'missing-required')
    assert qualification.cases[-1].status == Status.INCOMPLETE
    assert code == (1 if kind == 'length' else 2), output
    if kind == 'length':
        assert report.fits[0].status == report.fits[0].REJECTED
    else:
        assert report is None


@pytest.mark.parametrize('failure,expected', [('physical', Status.REJECTED), ('panels', Status.INCOMPLETE)])
@pytest.mark.parametrize('kind', ['length', 'overlap'])
def test_partial_optional_evidence_cannot_hide_failed_qualification(
        tmp_path: Path, targeted_technology: TechInfo, pattern_data: Dict[str, Any],
        monkeypatch: pytest.MonkeyPatch, kind: str, failure: str, expected: int):
    study = _make_fit_study(tmp_path, targeted_technology, pattern_data, monkeypatch, kind, failure)
    study = _study_without_some_sweeps(study, 1)
    code, output, report, qualification = _fit(study, tmp_path, kind, 'bad-optional')
    assert qualification.cases[0].status == expected
    assert all(case.status == Status.STABILIZED for case in qualification.cases[1:])
    assert code == (1 if kind == 'length' else 2), output
    if report is not None:
        assert report.fits[0].status == report.fits[0].REJECTED


@pytest.mark.parametrize('kind', ['length', 'overlap'])
def test_complete_optional_sweep_enforces_fit_budget(
        tmp_path: Path, targeted_technology: TechInfo, pattern_data: Dict[str, Any],
        monkeypatch: pytest.MonkeyPatch, kind: str):
    study = _make_fit_study(tmp_path, targeted_technology, pattern_data, monkeypatch, kind, 'residual')
    code, output, report, qualification = _fit(study, tmp_path, kind, 'refit-budget')
    assert all(case.status == Status.STABILIZED for case in qualification.cases)
    assert code == 1, output
    fit = report.fits[0] if kind == 'length' else report.fit
    assert fit.status == fit.REJECTED
    assert fit.validation_samples[0].residual_f == pytest.approx(0, abs=1e-29)
    assert any('ADAPTIVE_MESH_REFINEMENT at 0.12' in reason and 'exceeds' in reason for reason in fit.diagnostics)


@pytest.mark.parametrize('shared', [0, 1, 2])
def test_complete_coverage_still_requires_shared_settings(shared: int):
    # Different coarse settings are legal qualification evidence. They cannot
    # support a cross-case refit unless two recent settings match exactly.
    cases = [CalibrationQualificationCaseResult(case_id=name) for name in ('a', 'b')]
    for index, case in enumerate(cases):
        values = [0.18, 0.12, 0.06]
        if index:
            values[:2-shared] = [0.20, 0.14][:2-shared]
        ref = case.refinements.add(axis=Axis.ADAPTIVE_MESH_REFINEMENT)
        for value in values:
            ref.levels.add(parameter_value=value)
        for _ in range(2):
            entry = ref.changes.add().entries.add(signed_delta_f=0)
            entry.entry.charge_conductor_id, entry.entry.excitation_conductor_id = 'A', 'B'
    settings = list(refinement_settings(cases, {'a': 1e-15, 'b': 1e-15}, 'fastercap'))
    adaptive, = [s for s in settings if s.axis == Axis.ADAPTIVE_MESH_REFINEMENT]
    assert adaptive.coverage == Coverage.COMPLETE
    assert not adaptive.missing_case_ids
    assert adaptive.rejects_fit == (shared < 2)
    assert len(adaptive.parameter_values) == shared
    # Missing required axes remain fatal even though this helper also reports
    # missing optional evidence without rejecting a fit.
    assert all(s.rejects_fit for s in settings if s.axis != Axis.ADAPTIVE_MESH_REFINEMENT)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', [pytest.param(ngspice_port_admittance, marks=requires_ngspice, id='ngspice'),
                                     pytest.param(xyce_port_admittance, marks=requires_xyce, id='Xyce'),
                                     pytest.param(vacask_port_admittance, marks=requires_vacask, id='VACASK')])
@pytest.mark.parametrize('kind', ['length', 'overlap'])
def test_partial_optional_sweep_predicts_circuit_coupling(
        tmp_path: Path, targeted_technology: TechInfo, pattern_data: Dict[str, Any],
        monkeypatch: pytest.MonkeyPatch, kind: str, simulator: Callable):
    study = _make_fit_study(tmp_path, targeted_technology, pattern_data, monkeypatch, kind)
    study = _study_without_some_sweeps(study, 1)
    code, output, report, _ = _fit(study, tmp_path, kind, 'partial-circuit')
    assert code == 0, output
    fit = report.fits[0] if kind == 'length' else report.fit
    holdout, = fit.validation_samples
    # Independent capacitor circuit at the held-out geometry. Its capacitance
    # comes from the analytic input, not from the fitted prediction.
    coupling_f = 2e-16 * 12 + 1e-16 if kind == 'length' else 1e-16 * 18 + 2e-17 * 18 - 4e-17
    assert_circuit_coupling(tmp_path, simulator, coupling_f, holdout.predicted_coupling_f)
