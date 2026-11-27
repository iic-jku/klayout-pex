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
"""Bind finite-length fits to independently verified solver evidence."""

from collections import defaultdict
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Tuple

from .artifacts import sha256_file, validate_output_directory, write_message
from .fit_evidence import (
    qualified_couplings, read_verified_qualification, recent_couplings, refinement_residual_violation,
)
from .length_fit import LengthFitPolicy, LengthObservation, fit_length_series
from .qualification_evidence import QualificationMeasurement
from .validation import CalibrationError
from ..version import __version__

from kpex_protobuf.kpex.calibration.length_fit_pb2 import (
    CalibrationLengthFitReport, CalibrationLengthFitResult, CalibrationLengthSeries,
)
from kpex_protobuf.kpex.calibration.patterns_pb2 import PARALLEL_PLATES, PARALLEL_WIRES
from kpex_protobuf.kpex.calibration.qualification_pb2 import (
    CalibrationQualificationCaseResult, CalibrationRefinementAxis as Axis,
)


def _series(reference: QualificationMeasurement) -> CalibrationLengthSeries:
    pattern = reference.pattern
    targets = {target.id: target for target in reference.run.preparation.targets}
    return CalibrationLengthSeries(
        physical_stack_sha256=reference.run.preparation.technology.physical_stack_sha256,
        pattern_family=pattern.family,
        layers=pattern.layers, units=reference.run.preparation.units,
        width_grid=pattern.dimensions_grid.width, gap_grid=pattern.dimensions_grid.gap,
        measurement=pattern.measurement, solver=reference.run.manifest.solver,
        targets=[targets[name] for name in sorted(pattern.target_ids)],
    )


def _observation(case: CalibrationQualificationCaseResult) -> Tuple[LengthObservation, float]:
    forward_f, reverse_f = qualified_couplings(case)
    units = case.units
    length_um = float(Fraction(case.pattern.dimensions_grid.length * units.grid_numerator, units.grid_denominator))
    observation = LengthObservation(case.case_id, case.pattern.role, length_um, forward_f)
    return observation, reverse_f


def _add_refinement_sensitivity(
    result: CalibrationLengthFitResult, observations: List[LengthObservation],
    cases: Dict[str, CalibrationQualificationCaseResult],
    policy: LengthFitPolicy,
):
    budget_f = policy.weight_floor_f * policy.max_weighted_residual
    reference_residuals = {item.case_id: item.residual_f for item in result.validation_samples}
    axes = sorted({ref.axis for item in observations for ref in cases[item.case_id].refinements})
    for axis in axes:
        sensitivity = result.refinement_sensitivity.add(axis=axis)
        refinements = [next((ref for ref in cases[item.case_id].refinements if ref.axis == axis), None)
                       for item in observations]
        if any(ref is None for ref in refinements):
            sensitivity.diagnostic = 'The cases do not share this refinement axis'
            result.diagnostics.append(f'{Axis.Name(axis)}: {sensitivity.diagnostic}')
            continue
        sensitivity.reference_parameter_value = refinements[0].levels[-1].parameter_value
        couplings = {item.case_id: recent_couplings(refinement, item.capacitance_f)
                     for item, refinement in zip(observations, refinements)}
        common = set.intersection(*(set(values) for values in couplings.values()))
        if len(common) < 2:
            sensitivity.diagnostic = 'Fewer than two recent refinement settings are shared by every case'
            result.diagnostics.append(f'{Axis.Name(axis)}: {sensitivity.diagnostic}')
        # Preserve the backend's recorded coarse-to-fine order, which need not
        # be numerically decreasing for another solver's refinement control.
        ordered = [level.parameter_value for level in refinements[0].levels[-3:-1]
                   if level.parameter_value in common]
        for value in ordered:
            level = sensitivity.levels.add(parameter_value=value)
            alternate = [replace(item, capacitance_f=couplings[item.case_id][value]) for item in observations]
            try:
                fit = fit_length_series(alternate, policy)
            except CalibrationError as exc:
                level.diagnostic = str(exc)
                result.diagnostics.append(f'{Axis.Name(axis)} at {value:g}: {level.diagnostic}')
                continue
            level.max_abs_training_residual_f = fit['training']['max_abs_residual_f']
            for item in fit['validation']['observations']:
                level.validation_samples.add(
                    case_id=item['case_id'], solver_coupling_f=item['measured_f'],
                    predicted_coupling_f=item['predicted_f'], residual_f=item['residual_f'],
                    residual_change_f=item['residual_f'] - reference_residuals[item['case_id']],
                )
            violation = refinement_residual_violation(
                level.max_abs_training_residual_f, (item.residual_f for item in level.validation_samples), budget_f,
            )
            if violation:
                level.diagnostic = violation
                result.diagnostics.append(f'{Axis.Name(axis)} at {value:g}: {violation}')


def fit_qualified_lengths(study_path: Path, qualification_path: Path, output_dir: Path, policy: LengthFitPolicy
                          ) -> Tuple[Path, CalibrationLengthFitReport]:
    """Recompute qualification before accepting its measurements for fitting."""
    validate_output_directory(output_dir)
    qualification_sha256, evaluation = read_verified_qualification(study_path, qualification_path)

    report = CalibrationLengthFitReport(
        schema_version=3, kpex_version=__version__, study_sha256=evaluation.report.study_sha256,
        qualification_sha256=qualification_sha256,
        residual_budget_f=policy.weight_floor_f * policy.max_weighted_residual,
        max_condition_number=policy.max_condition_number,
    )
    series_by_key: Dict[bytes, CalibrationLengthSeries] = {}
    grouped_cases: Dict[bytes, List[CalibrationQualificationCaseResult]] = defaultdict(list)
    cases = {case.case_id: case for case in evaluation.report.cases}
    for case in evaluation.report.cases:
        series = _series(evaluation.references[case.case_id])
        key = series.SerializeToString(deterministic=True)
        series_by_key[key] = series
        grouped_cases[key].append(case)

    for key, series in series_by_key.items():
        members = grouped_cases[key]
        result = report.fits.add(series=series, case_ids=[case.case_id for case in members])
        for case in members:
            result.case_technologies[case.case_id].CopyFrom(case.technology)
        observations, reverse = [], {}
        try:
            if series.pattern_family not in (PARALLEL_PLATES, PARALLEL_WIRES):
                raise CalibrationError('A length fit requires parallel plates or parallel wires')
            settings = set()
            for case in members:
                run = evaluation.references[case.case_id].run
                options = run.manifest.options
                settings.add((run.preparation.domain_margin_grid, options.threads_per_job,
                              options.solver_controls.SerializeToString(deterministic=True)))
                observation, reverse[case.case_id] = _observation(case)
                observations.append(observation)
            if len(settings) != 1:
                raise CalibrationError('The cases use different reference numerical settings')
            fit = fit_length_series(observations, policy)
        except CalibrationError as exc:
            result.status = CalibrationLengthFitResult.REJECTED
            result.diagnostics.append(str(exc))
            continue

        result.distributed_coupling_f_per_um = fit['parameters']['c_infinite_f_per_um']
        result.end_correction_f = fit['parameters']['c_end_f']
        result.condition_number = fit['sensitivity']['dimensionless_condition_number']
        result.zero_slope_constraint_active = bool(fit['constraints']['active'])
        result.diagnostics.extend(fit['diagnostics'])
        for subset, samples in (('training', result.training_samples), ('validation', result.validation_samples)):
            for item in fit[subset]['observations']:
                samples.add(
                    case_id=item['case_id'], length_um=item['length_um'], solver_coupling_f=item['measured_f'],
                    reverse_solver_coupling_f=reverse[item['case_id']],
                    predicted_coupling_f=item['predicted_f'], residual_f=item['residual_f'],
                )
        _add_refinement_sensitivity(result, observations, cases, policy)
        result.status = (CalibrationLengthFitResult.REJECTED if result.diagnostics
                         else CalibrationLengthFitResult.ACCEPTED)
    if sha256_file(qualification_path) != qualification_sha256:
        raise CalibrationError('Qualification report changed during fitting')
    output_dir.mkdir()
    try:
        return write_message(output_dir / 'fit-length.pb.json', report), report
    except CalibrationError:
        try:
            output_dir.rmdir()
        except OSError:
            pass
        raise
