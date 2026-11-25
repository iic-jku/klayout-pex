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
import math
from pathlib import Path
from typing import Dict, List, Tuple

from .artifacts import read_message, sha256_file, validate_output_directory, write_message
from .length_fit import LengthFitPolicy, LengthObservation, fit_length_series
from .qualification import REFINEMENT_AXES, charge_rows, evaluate_qualification
from .qualification_evidence import QualificationMeasurement
from .validation import CalibrationError
from ..version import __version__

from kpex_protobuf.kpex.calibration.length_fit_pb2 import (
    CalibrationLengthFamily, CalibrationLengthFitReport, CalibrationLengthFitResult,
)
from kpex_protobuf.kpex.calibration.patterns_pb2 import PARALLEL_PLATES, PARALLEL_WIRES
from kpex_protobuf.kpex.calibration.qualification_pb2 import (
    CalibrationQualificationCaseResult, CalibrationQualificationReport, CalibrationQualificationStatus as Status,
    CalibrationRefinementAxis as Axis, CalibrationRefinementResult,
)
from kpex_protobuf.kpex.result.capacitance_matrix_pb2 import MaxwellCapacitanceMatrix as Matrix


def _family(reference: QualificationMeasurement) -> CalibrationLengthFamily:
    pattern = reference.pattern
    if pattern.family not in (PARALLEL_PLATES, PARALLEL_WIRES):
        raise CalibrationError(f"Case '{pattern.id}' must be a parallel-plate or parallel-wire pattern")
    targets = {target.id: target for target in reference.run.preparation.targets}
    return CalibrationLengthFamily(
        technology=reference.run.preparation.technology, pattern_family=pattern.family,
        layers=pattern.layers, units=reference.run.preparation.units,
        width_grid=pattern.dimensions_grid.width, gap_grid=pattern.dimensions_grid.gap,
        measurement=pattern.measurement, solver=reference.run.manifest.solver,
        targets=[targets[name] for name in sorted(pattern.target_ids)],
    )


def _observation(case: CalibrationQualificationCaseResult) -> Tuple[LengthObservation, float]:
    if case.status != Status.STABILIZED:
        raise CalibrationError(f"Case '{case.case_id}' is {Status.Name(case.status)}. "
                               'Fit requires all cases to be numerically stabilized')
    matrix = case.reference_matrix
    order = list(matrix.conductor_ids)
    if matrix.reference_convention != Matrix.GROUNDED_PRINCIPAL_SUBMATRIX or sorted(order) != ['A', 'B']:
        raise CalibrationError(f"Case '{case.case_id}' requires a grounded A/B Maxwell matrix")
    if any({entry.charge_conductor_id, entry.excitation_conductor_id} == {'A', 'B'}
           for entry in case.unresolved_entries):
        raise CalibrationError(f"Case '{case.case_id}' A/B coupling is below qualification resolution")
    capacitance = charge_rows(matrix)
    a, b = order.index('A'), order.index('B')
    units = case.units
    length_um = float(Fraction(case.pattern.dimensions_grid.length * units.grid_numerator, units.grid_denominator))
    observation = LengthObservation(case.case_id, case.pattern.role, length_um, -float(capacitance[a, b]))
    return observation, -float(capacitance[b, a])


def _ignore_eigensolver_roundoff(report: CalibrationQualificationReport):
    # Eigensolver output can differ across platforms even when the matrices and
    # every qualification decision are identical. The fit uses the recomputed
    # classification. Preserve violation checks and compare the actual matrices.
    for case in report.cases:
        diagnostics = [*case.reference_diagnostics,
                       *(diagnostic for refinement in case.refinements for level in refinement.levels
                         for diagnostic in level.matrix_diagnostics)]
        for diagnostic in diagnostics:
            if not math.isfinite(diagnostic.minimum_energy_eigenvalue_f):
                raise CalibrationError('Qualification report contains a nonfinite energy diagnostic')
            diagnostic.ClearField('minimum_energy_eigenvalue_f')


def _recent_couplings(refinement: CalibrationRefinementResult, reference_f: float) -> Dict[float, float]:
    couplings = {}
    value_f = reference_f
    for level, step in zip(reversed(refinement.levels[-3:-1]), reversed(refinement.changes[-2:])):
        # The qualification deltas are in charge-row convention. Coupling is
        # -C[A,B], so walking backward adds the signed change in C[A,B].
        value_f += next(entry.signed_delta_f for entry in step.entries
                        if (entry.entry.charge_conductor_id, entry.entry.excitation_conductor_id) == ('A', 'B'))
        couplings[level.parameter_value] = value_f
    return couplings


def _add_solver_sensitivity(result: CalibrationLengthFitResult, observations: List[LengthObservation],
                            cases: Dict[str, CalibrationQualificationCaseResult],
                            references: Dict[str, QualificationMeasurement], policy: LengthFitPolicy):
    settings = set()
    for item in observations:
        run = references[item.case_id].run
        settings.add((run.preparation.domain_margin_grid,
                      run.manifest.options.fastercap.SerializeToString(deterministic=True)))

    reference_residuals = {item.case_id: item.residual_f for item in result.validation}
    for axis in REFINEMENT_AXES:
        sensitivity = result.solver_sensitivity.add(axis=axis)
        if len(settings) != 1:
            sensitivity.diagnostic = 'The cases use different reference numerical settings'
            continue

        refinements = [next(ref for ref in cases[item.case_id].refinements if ref.axis == axis)
                       for item in observations]
        sensitivity.reference_parameter_value = refinements[0].levels[-1].parameter_value
        couplings = {item.case_id: _recent_couplings(refinement, item.capacitance_f)
                     for item, refinement in zip(observations, refinements)}
        common = set.intersection(*(set(values) for values in couplings.values()))
        if len(common) < 2:
            sensitivity.diagnostic = 'Fewer than two recent refinement settings are shared by every case'
        for value in sorted(common, reverse=axis != Axis.DOMAIN_MARGIN):
            level = sensitivity.levels.add(parameter_value=value)
            alternate = [replace(item, capacitance_f=couplings[item.case_id][value]) for item in observations]
            try:
                fit = fit_length_series(alternate, policy)
            except CalibrationError as exc:
                level.diagnostic = str(exc)
                continue
            level.max_abs_training_residual_f = fit['training']['max_abs_residual_f']
            for item in fit['validation']['observations']:
                level.validation.add(case_id=item['case_id'], measured_f=item['measured_f'],
                                     predicted_f=item['predicted_f'], residual_f=item['residual_f'],
                                     residual_change_f=item['residual_f'] - reference_residuals[item['case_id']])


def fit_qualified_lengths(study_path: Path, qualification_path: Path, output_dir: Path, policy: LengthFitPolicy
                          ) -> Tuple[Path, CalibrationLengthFitReport]:
    """Recompute qualification before accepting its measurements for fitting."""
    validate_output_directory(output_dir)
    qualification_sha256 = sha256_file(qualification_path)
    saved = read_message(qualification_path, CalibrationQualificationReport())
    evaluation = evaluate_qualification(study_path)
    # A package version change alone does not invalidate evidence produced by the same method.
    evaluation.report.kpex_version = saved.kpex_version
    _ignore_eigensolver_roundoff(saved)
    _ignore_eigensolver_roundoff(evaluation.report)
    if not saved.kpex_version or saved != evaluation.report:
        raise CalibrationError('Qualification report differs from the recomputed study and solver evidence')

    report = CalibrationLengthFitReport(
        schema_version=1, kpex_version=__version__, study_sha256=saved.study_sha256,
        qualification_sha256=qualification_sha256,
        residual_budget_f=policy.weight_floor_f * policy.max_weighted_residual,
        max_condition_number=policy.max_condition_number,
    )
    families: Dict[bytes, CalibrationLengthFamily] = {}
    observations: Dict[bytes, List[LengthObservation]] = defaultdict(list)
    reverse: Dict[str, float] = {}
    cases = {case.case_id: case for case in evaluation.report.cases}
    for case in evaluation.report.cases:
        observation, reverse[case.case_id] = _observation(case)
        family = _family(evaluation.references[case.case_id])
        key = family.SerializeToString(deterministic=True)
        families[key] = family
        observations[key].append(observation)

    for key, family in families.items():
        try:
            fit = fit_length_series(observations[key], policy)
        except CalibrationError as exc:
            exc.add_note('Length family with cases ' + ', '.join(obs.case_id for obs in observations[key]))
            raise
        result = report.families.add(
            family=family,
            status=(CalibrationLengthFitResult.INADEQUATE if fit['diagnostics']
                    else CalibrationLengthFitResult.WITHIN_BUDGET),
            distributed_f_per_um=fit['parameters']['c_infinite_f_per_um'],
            end_f=fit['parameters']['c_end_f'],
            condition_number=fit['sensitivity']['dimensionless_condition_number'],
            zero_slope_constraint_active=bool(fit['constraints']['active']),
            diagnostics=fit['diagnostics'],
        )
        for subset, samples in (('training', result.training), ('validation', result.validation)):
            for item in fit[subset]['observations']:
                samples.add(case_id=item['case_id'], length_um=item['length_um'], measured_f=item['measured_f'],
                            reverse_measured_f=reverse[item['case_id']], predicted_f=item['predicted_f'],
                            residual_f=item['residual_f'])
        _add_solver_sensitivity(result, observations[key], cases, evaluation.references, policy)
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
