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

"""Fit a declared overlap target using qualified Maxwell matrices."""

from dataclasses import replace
from fractions import Fraction
import math
from pathlib import Path
from typing import Dict, List, Tuple

from .artifacts import sha256_file, validate_output_directory, write_message
from .fit_evidence import (
    qualified_couplings, read_verified_qualification, recent_couplings, refinement_residual_violation,
)
from .overlap_fit import OverlapFit, OverlapObservation, fit_overlap_rectangles
from .qualification import QualificationEvaluation
from .validation import CalibrationError
from ..version import __version__

from kpex_protobuf.kpex.calibration.overlap_fit_pb2 import CalibrationOverlapFitReport, CalibrationOverlapFitResult
from kpex_protobuf.kpex.calibration.patterns_pb2 import PARALLEL_PLATES, TRAINING
from kpex_protobuf.kpex.calibration.qualification_pb2 import CalibrationRefinementAxis as Axis
from kpex_protobuf.kpex.calibration.targets_pb2 import CalibrationTarget


def _plate_observations(report: CalibrationOverlapFitReport, evaluation: QualificationEvaluation
                        ) -> Tuple[List[OverlapObservation], Dict[str, float], Fraction]:
    observations: List[OverlapObservation] = []
    reverse_couplings: Dict[str, float] = {}
    first = evaluation.report.cases[0]
    first_run = evaluation.references[first.case_id].run
    report.technology.CopyFrom(first.technology)
    report.solver.CopyFrom(first_run.manifest.solver)
    report.measurement.CopyFrom(first.pattern.measurement)
    units = first.units
    grid = Fraction(units.grid_numerator, units.grid_denominator)

    for case in evaluation.report.cases:
        forward_f, reverse_f = qualified_couplings(case)
        if case.pattern.family != PARALLEL_PLATES or len(case.pattern.target_ids) != 1:
            raise CalibrationError(f"Case '{case.case_id}' needs aligned parallel plates and one overlap target")
        run = evaluation.references[case.case_id].run
        target = next((item for item in run.preparation.targets if item.id == case.pattern.target_ids[0]), None)
        if (not isinstance(target, CalibrationTarget) or not target.HasField('overlap')
                or list(case.pattern.layers) != [
                    target.overlap.bottom.process_profile, target.overlap.top.process_profile,
                ]):
            raise CalibrationError(f"Case '{case.case_id}' needs an overlap target bound to its bottom and top plates")
        if case.case_id == first.case_id:
            report.target.CopyFrom(target)
        if (target != report.target or case.technology != report.technology or case.units != units
                or case.pattern.measurement != report.measurement or run.manifest.solver != report.solver
                or run.manifest.options.threads_per_job != first_run.manifest.options.threads_per_job
                or run.manifest.options.solver_controls != first_run.manifest.options.solver_controls
                or run.preparation.domain_margin_grid != first_run.preparation.domain_margin_grid):
            raise CalibrationError(f"Case '{case.case_id}' does not share the overlap fit's target or reference settings")
        dimensions = case.pattern.dimensions_grid
        observations.append(OverlapObservation(case.case_id, case.pattern.role, float(dimensions.width * grid),
                                               float(dimensions.length * grid), forward_f))
        reverse_couplings[case.case_id] = reverse_f
    return observations, reverse_couplings, grid


def _record_fit(result: CalibrationOverlapFitResult, observations: List[OverlapObservation],
                reverse_couplings: Dict[str, float], fit: OverlapFit, budget_f: float):
    result.area_coupling_f_per_um2 = fit.area_coupling_f_per_um2
    result.edge_coupling_f_per_um = fit.edge_coupling_f_per_um
    result.corner_correction_f = fit.corner_correction_f
    result.condition_number = fit.condition_number
    if fit.area_coupling_f_per_um2 <= 0:
        result.diagnostics.append('The fitted overlap area coefficient is nonpositive')
    for item in observations:
        prediction = fit.predictions_f[item.case_id]
        residual = prediction - item.coupling_f
        samples = result.training_samples if item.role == TRAINING else result.validation_samples
        samples.add(case_id=item.case_id, width_um=item.width_um, length_um=item.length_um,
                    solver_coupling_f=item.coupling_f, reverse_solver_coupling_f=reverse_couplings[item.case_id],
                    predicted_coupling_f=prediction, residual_f=residual)
        if prediction < 0:
            result.diagnostics.append(f"Case '{item.case_id}' has negative predicted coupling")
        if abs(residual) > budget_f:
            result.diagnostics.append(f"Case '{item.case_id}' exceeds the declared residual budget")


def _add_sensitivity(report: CalibrationOverlapFitReport, evaluation: QualificationEvaluation,
                     observations: List[OverlapObservation], fit: OverlapFit, grid: Fraction):
    reference_errors = {sample.case_id: sample.residual_f for sample in report.fit.validation_samples}
    cases = {case.case_id: case for case in evaluation.report.cases}
    axes = sorted({ref.axis for case in cases.values() for ref in case.refinements})
    for axis in axes:
        result = report.refinement_sensitivity.add(axis=axis)
        refinements = {item.case_id: next((ref for ref in cases[item.case_id].refinements if ref.axis == axis), None)
                       for item in observations}
        if any(ref is None for ref in refinements.values()):
            result.diagnostic = 'The cases do not share this refinement axis'
            report.fit.diagnostics.append(f'{Axis.Name(axis)}: {result.diagnostic}')
            continue
        scale = float(grid) if axis == Axis.DOMAIN_MARGIN else 1
        result.reference_parameter_value = next(iter(refinements.values())).levels[-1].parameter_value * scale
        couplings = {item.case_id: recent_couplings(refinements[item.case_id], item.coupling_f)
                     for item in observations}
        common = set.intersection(*(set(values) for values in couplings.values()))
        if len(common) < 2:
            result.diagnostic = 'Fewer than two recent refinement settings are shared by every case'
            report.fit.diagnostics.append(f'{Axis.Name(axis)}: {result.diagnostic}')
        # Preserve the backend's recorded coarse-to-fine order, which need not
        # be numerically decreasing for another solver's refinement control.
        ordered = [level.parameter_value for level in next(iter(refinements.values())).levels[-3:-1]
                   if level.parameter_value in common]
        for setting in ordered:
            level = result.levels.add(parameter_value=setting * scale)
            alternate = [replace(item, coupling_f=couplings[item.case_id][setting]) for item in observations]
            try:
                alternative_fit = fit_overlap_rectangles(alternate)
            except CalibrationError as exc:
                level.diagnostic = str(exc)
                report.fit.diagnostics.append(f'{Axis.Name(axis)} at {level.parameter_value:g}: {level.diagnostic}')
                continue
            level.area_coupling_f_per_um2 = alternative_fit.area_coupling_f_per_um2
            level.area_coupling_change_f_per_um2 = alternative_fit.area_coupling_f_per_um2 - fit.area_coupling_f_per_um2
            training_residuals = []
            for item in alternate:
                prediction = alternative_fit.predictions_f[item.case_id]
                residual = prediction - item.coupling_f
                if item.role == TRAINING:
                    training_residuals.append(abs(residual))
                    continue
                level.validation_samples.add(case_id=item.case_id, solver_coupling_f=item.coupling_f,
                                             predicted_coupling_f=prediction, residual_f=residual,
                                             residual_change_f=residual - reference_errors[item.case_id])
            level.max_abs_training_residual_f = max(training_residuals)
            violation = refinement_residual_violation(
                level.max_abs_training_residual_f, (item.residual_f for item in level.validation_samples),
                report.residual_budget_f,
            )
            if violation:
                level.diagnostic = violation
                report.fit.diagnostics.append(f'{Axis.Name(axis)} at {level.parameter_value:g}: {violation}')


def fit_qualified_overlap(study_path: Path, qualification_path: Path, output_dir: Path, budget_f: float
                          ) -> Tuple[Path, CalibrationOverlapFitReport]:
    """Fit one overlap target and write a report without changing technology data."""
    if not math.isfinite(budget_f) or budget_f <= 0:
        raise CalibrationError('The residual budget must be finite and positive')
    validate_output_directory(output_dir)
    qualification_sha256, evaluation = read_verified_qualification(study_path, qualification_path)
    report = CalibrationOverlapFitReport(
        schema_version=2, kpex_version=__version__, study_sha256=evaluation.report.study_sha256,
        qualification_sha256=qualification_sha256, residual_budget_f=budget_f,
    )
    observations, reverse_couplings, grid = _plate_observations(report, evaluation)
    fit = fit_overlap_rectangles(observations)
    _record_fit(report.fit, observations, reverse_couplings, fit, budget_f)
    _add_sensitivity(report, evaluation, observations, fit, grid)
    report.fit.status = (CalibrationOverlapFitResult.REJECTED if report.fit.diagnostics
                         else CalibrationOverlapFitResult.ACCEPTED)
    if sha256_file(qualification_path) != qualification_sha256:
        raise CalibrationError('Qualification report changed during fitting')
    output_dir.mkdir()
    try:
        return write_message(output_dir / 'fit-overlap.pb.json', report), report
    except CalibrationError:
        try:
            output_dir.rmdir()
        except OSError:
            pass
        raise
