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
"""Qualify observed numerical stabilization of collected calibration matrices."""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from .artifacts import read_message, sha256_file, validate_output_directory, verify_artifacts, write_message
from .qualification_evidence import QualificationMeasurement, read_collection, read_measurement
from .validation import CalibrationError, validate_identifier
from ..version import __version__

from kpex_protobuf.kpex.calibration.qualification_pb2 import (
    CalibrationMatrixDiagnostics, CalibrationQualificationCaseResult, CalibrationQualificationCaseStudy,
    CalibrationQualificationReport, CalibrationQualificationStatus as Status,
    CalibrationQualificationStudy, CalibrationQualificationTolerance, CalibrationRefinementAxis as Axis,
    CalibrationRefinementResult, CalibrationRefinementStudy,
)
from kpex_protobuf.kpex.calibration.solving_pb2 import CalibrationCaseResult, CalibrationSolveOptions
from kpex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene
from kpex_protobuf.kpex.result.capacitance_matrix_pb2 import MaxwellCapacitanceMatrix as Matrix

REFINEMENT_AXES = (Axis.GMRES_TOLERANCE, Axis.INITIAL_MESH_MAX_AREA, Axis.DOMAIN_MARGIN)
METHOD_VERSION = 2


@dataclass(frozen=True)
class QualificationOutput:
    report_path: Path
    report: CalibrationQualificationReport


@dataclass(frozen=True)
class QualificationEvaluation:
    report: CalibrationQualificationReport
    references: Dict[str, QualificationMeasurement]


def charge_rows(matrix: Matrix) -> np.ndarray:
    values = np.array([list(row.values) for row in matrix.rows], dtype=float)
    names = matrix.conductor_ids
    if (matrix.unit != Matrix.FARAD or not names or len(set(names)) != len(names)
            or values.shape != (len(names), len(names)) or not np.isfinite(values).all()):
        raise CalibrationError('Expected a finite square Maxwell matrix in farads')
    match matrix.index_convention:
        case Matrix.CHARGE_ROWS:
            return values
        case Matrix.EXCITATION_ROWS:
            return values.T
        case _:
            raise CalibrationError('Undefined Maxwell matrix index convention')


def _diagnose(matrix: Matrix, tolerance: CalibrationQualificationTolerance) -> CalibrationMatrixDiagnostics:
    values = charge_rows(matrix)
    names = matrix.conductor_ids
    bounds = np.maximum(tolerance.absolute_floor_f, tolerance.relative_tolerance * np.abs(values))
    scale = float(np.max(np.abs(values)))
    normalized = values / scale if scale else values
    try:
        with np.errstate(over='raise', invalid='raise'):
            rows = values.sum(axis=1)
            row_budgets = bounds.sum(axis=1)
            energy_budget = float(np.maximum(bounds, bounds.T).sum(axis=1).max())
            # Use the symmetric part for the quadratic energy form only. Report the
            # original matrix and check reciprocity separately.
            eigenvalue = float(np.linalg.eigvalsh((normalized + normalized.T) / 2)[0]) * scale
            asymmetry = np.abs(values - values.T)
    except (ArithmeticError, np.linalg.LinAlgError) as exc:
        raise CalibrationError(f'Cannot evaluate Maxwell diagnostics in farads: {exc}') from exc
    if not math.isfinite(eigenvalue):
        raise CalibrationError('Maxwell energy diagnostic exceeds the finite range')
    result = CalibrationMatrixDiagnostics(
        reference_convention=matrix.reference_convention, maximum_reciprocity_error_f=float(asymmetry.max()),
        minimum_energy_eigenvalue_f=eigenvalue, charge_row_sums_f=rows,
    )
    for i, name in enumerate(names):
        if values[i, i] < -bounds[i, i]:
            result.violations.append(f'Negative diagonal for {name}')
        if rows[i] < -row_budgets[i]:
            result.violations.append(f'Negative charge-row sum for {name}')
        for j, other in enumerate(names):
            if i != j and values[i, j] > bounds[i, j]:
                result.violations.append(f'Positive off-diagonal for {name} / {other}')
            if j > i and asymmetry[i, j] > max(bounds[i, j], bounds[j, i]):
                result.violations.append(f'Reciprocity defect for {name} / {other}')
    if eigenvalue < -energy_budget:
        result.violations.append('Negative energy beyond the entry-wise perturbation budget')
    return result


def _physical(measurement: QualificationMeasurement, tolerance: CalibrationQualificationTolerance
              ) -> Tuple[List[CalibrationMatrixDiagnostics], List[str]]:
    record = measurement.record
    if record.status != CalibrationCaseResult.COLLECTED:
        return [], [f'Raw collection status: {CalibrationCaseResult.CollectionStatus.Name(record.status)}']
    try:
        diagnostics = [_diagnose(record.native_matrix, tolerance), _diagnose(record.measured_matrix, tolerance)]
    except (CalibrationError, ValueError) as exc:
        return [], [str(exc)]
    errors = [violation for report in diagnostics for violation in report.violations]
    errors.extend(item for item in record.diagnostics if item.casefold().startswith('error:'))
    return diagnostics, errors


def _controls(level: QualificationMeasurement, axis: int) -> Tuple[float, CalibrationSolveOptions, PEX25DScene]:
    fixed = CalibrationSolveOptions()
    fixed.CopyFrom(level.run.manifest.options)
    # Scheduling and time limits do not change a completed solve's inputs.
    fixed.ClearField('jobs')
    fixed.ClearField('solver_timeout_seconds')
    scene = PEX25DScene()
    scene.CopyFrom(level.scene)
    match axis:
        case Axis.GMRES_TOLERANCE:
            value = fixed.fastercap.gmres_tolerance
            fixed.fastercap.ClearField('gmres_tolerance')
        case Axis.INITIAL_MESH_MAX_AREA:
            value = fixed.fastercap.mesh_max_area_um2
            fixed.fastercap.ClearField('mesh_max_area_um2')
        case Axis.DOMAIN_MARGIN:
            value = level.run.preparation.domain_margin_grid
            scene.domain.ClearField('box')
            scene.domain.ClearField('applied_margin')
        case _:
            raise NotImplementedError(f'Calibration refinement axis {axis}')
    return value, fixed, scene


def _refinement(spec: CalibrationRefinementStudy, target: QualificationMeasurement,
                measurements: Dict[str, QualificationMeasurement], tolerance: CalibrationQualificationTolerance
                ) -> CalibrationRefinementResult:
    result = CalibrationRefinementResult(axis=spec.axis, status=Status.INCOMPLETE)
    levels = [measurements[name] for name in spec.collection_ids]
    if len(levels) < 3:
        result.diagnostics.append('At least three refinement levels are required')
        return result
    if len({level.run.run_sha256 for level in levels}) != len(levels):
        result.diagnostics.append('Repeated solver run is not independent refinement evidence')
    _, target_controls, target_scene = _controls(target, spec.axis)
    rejected = False
    missing_matrix = False
    physical_messages = []
    parameters: List[float] = []
    for name, measurement in zip(spec.collection_ids, levels):
        value, controls, scene = _controls(measurement, spec.axis)
        parameters.append(value)
        level = result.levels.add(collection_id=name, parameter_value=value)
        record = measurement.record
        if record.HasField('refined_panels'):
            level.refined_panels = record.refined_panels
        pattern, target_pattern = measurement.pattern, target.pattern
        technology, target_tech = measurement.run.preparation.technology, target.run.preparation.technology
        if (scene != target_scene or pattern.family != target_pattern.family
                or pattern.layers != target_pattern.layers or pattern.dimensions_grid != target_pattern.dimensions_grid
                or pattern.measurement != target_pattern.measurement
                or technology.physical_stack_sha256 != target_tech.physical_stack_sha256
                or measurement.run.manifest.solver != target.run.manifest.solver):
            result.diagnostics.append(f'{name}: physical geometry, measurement or solver identity changed')
        if spec.axis == Axis.GMRES_TOLERANCE and measurement.solver_inputs != target.solver_inputs:
            result.diagnostics.append(f'{name}: solver input files changed in the GMRES study')
        if controls != target_controls or controls.fastercap.HasField('automatic_tolerance'):
            result.diagnostics.append(f'{name}: fixed numerical controls changed or automatic refinement is active')
        diagnostics, errors = _physical(measurement, tolerance)
        level.matrix_diagnostics.extend(diagnostics)
        if errors:
            rejected |= record.status != CalibrationCaseResult.INCOMPLETE
            missing_matrix |= not diagnostics
            physical_messages.extend(f'{name}: {error}' for error in errors)

    increasing = spec.axis == Axis.DOMAIN_MARGIN
    if any(value <= 0 for value in parameters) or any(
            not (left < right if increasing else left > right) for left, right in zip(parameters, parameters[1:])):
        result.diagnostics.append('Refinement controls must be positive and strictly ordered from coarse to fine')
    if spec.axis == Axis.INITIAL_MESH_MAX_AREA:
        counts = [level.refined_panels for level in result.levels]
        if not all(counts) or any(left >= right for left, right in zip(counts, counts[1:])):
            result.diagnostics.append('Observed refined panel counts must be present and strictly increase')
    incompatible = bool(result.diagnostics)
    result.diagnostics.extend(physical_messages)
    if rejected:
        result.status = Status.REJECTED
    if incompatible or missing_matrix:
        return result

    order = list(target.record.measured_matrix.conductor_ids)
    matrices = []
    for measurement in levels:
        matrix = measurement.record.measured_matrix
        native_order = list(matrix.conductor_ids)
        positions = [native_order.index(name) for name in order]
        matrices.append(charge_rows(matrix)[np.ix_(positions, positions)])
    budgets = np.maximum(tolerance.absolute_floor_f, tolerance.relative_tolerance * np.abs(matrices[-1]))
    for index, (previous, current) in enumerate(zip(matrices, matrices[1:])):
        with np.errstate(over='ignore', invalid='ignore'):
            delta = current - previous
        if not np.isfinite(delta).all():
            result.status = Status.REJECTED
            result.diagnostics.append('Refinement change exceeds the finite range in farads')
            return result
        transition = result.changes.add(previous_collection_id=spec.collection_ids[index],
                                       next_collection_id=spec.collection_ids[index + 1],
                                       within_budget=bool(np.all(np.abs(delta) <= budgets)))
        for i, charge in enumerate(order):
            for j, excitation in enumerate(order):
                entry = transition.entries.add(signed_delta_f=delta[i, j], allowed_change_f=budgets[i, j])
                entry.entry.charge_conductor_id = charge
                entry.entry.excitation_conductor_id = excitation
    if not all(change.within_budget for change in result.changes[-2:]):
        result.diagnostics.append('Both most recent entry-wise changes must meet the declared budget')
    elif not rejected:
        result.status = Status.STABILIZED
    return result


def _validated_study(study: CalibrationQualificationStudy):
    tolerance = study.tolerance
    if (study.schema_version != 1 or not study.collections or not study.cases
            or not math.isfinite(tolerance.absolute_floor_f) or tolerance.absolute_floor_f <= 0
            or not 0 <= tolerance.relative_tolerance < 1):
        raise CalibrationError('Study needs schema version 1, collections, cases, a positive finite absolute floor '
                               'in farads and a relative tolerance in [0, 1)')
    for collection in study.collections:
        validate_identifier(collection.id, 'Collection ID')
    names = {item.id for item in study.collections}
    if len(names) != len(study.collections):
        raise CalibrationError('Collection IDs must be unique')
    cases = set()
    for case in study.cases:
        validate_identifier(case.case_id, 'Case ID')
        if case.case_id in cases or case.reference_collection_id not in names:
            raise CalibrationError('Case IDs must be unique and reference a declared collection')
        cases.add(case.case_id)
        axes = set()
        for refinement in case.refinements:
            levels = refinement.collection_ids
            if (refinement.axis not in REFINEMENT_AXES or refinement.axis in axes or not levels
                    or any(level not in names for level in levels) or len(set(levels)) != len(levels)
                    or levels[-1] != case.reference_collection_id):
                raise CalibrationError('Each refinement needs a unique supported axis and distinct declared '
                                       'collections ending at the reference')
            axes.add(refinement.axis)


def _qualify_case(spec: CalibrationQualificationCaseStudy, measurements: Dict[str, QualificationMeasurement],
                  tolerance: CalibrationQualificationTolerance) -> CalibrationQualificationCaseResult:
    reference = measurements[spec.reference_collection_id]
    result = CalibrationQualificationCaseResult(case_id=spec.case_id, pattern=reference.pattern,
                                                technology=reference.run.preparation.technology,
                                                units=reference.run.preparation.units)
    diagnostics, errors = _physical(reference, tolerance)
    result.reference_diagnostics.extend(diagnostics)
    result.diagnostics.extend(errors)
    if reference.record.status == CalibrationCaseResult.COLLECTED:
        matrix = reference.record.measured_matrix
        result.reference_matrix.CopyFrom(matrix)
        values = charge_rows(matrix)
        for i, charge in enumerate(matrix.conductor_ids):
            for j, excitation in enumerate(matrix.conductor_ids):
                if abs(values[i, j]) <= tolerance.absolute_floor_f:
                    result.unresolved_entries.add(charge_conductor_id=charge, excitation_conductor_id=excitation)
    for study in spec.refinements:
        result.refinements.append(_refinement(study, reference, measurements, tolerance))
    missing = [Axis.Name(axis) for axis in REFINEMENT_AXES if all(item.axis != axis for item in result.refinements)]
    if missing:
        result.diagnostics.append('Missing refinement evidence: ' + ', '.join(missing))
    if (errors and reference.record.status != CalibrationCaseResult.INCOMPLETE
            or any(item.status == Status.REJECTED for item in result.refinements)):
        result.status = Status.REJECTED
    elif errors or missing or any(item.status != Status.STABILIZED for item in result.refinements):
        result.status = Status.INCOMPLETE
    else:
        result.status = Status.STABILIZED
    return result


def evaluate_qualification(path: Path) -> QualificationEvaluation:
    """Recompute qualification and expose the verified reference measurements."""
    path = path.absolute()
    study_hash = sha256_file(path)
    study = read_message(path, CalibrationQualificationStudy())
    _validated_study(study)
    paths = verify_artifacts(path.parent, [item.collection for item in study.collections])
    runs = {item.id: read_collection(collection_path, item.collection.sha256)
            for item, collection_path in zip(study.collections, paths)}
    report = CalibrationQualificationReport(schema_version=1, qualification_method_version=METHOD_VERSION,
                                            kpex_version=__version__, study_sha256=study_hash, study=study)
    references = {}
    for case in study.cases:
        names = dict.fromkeys([case.reference_collection_id,
                               *(name for group in case.refinements for name in group.collection_ids)])
        measurements = {name: read_measurement(runs[name], case.case_id) for name in names}
        report.cases.append(_qualify_case(case, measurements, study.tolerance))
        references[case.case_id] = measurements[case.reference_collection_id]
    if sha256_file(path) != study_hash or any(sha256_file(file) != item.collection.sha256
                                              for item, file in zip(study.collections, paths)):
        raise CalibrationError('Study or collection changed during qualification')
    return QualificationEvaluation(report, references)


def qualify_study(path: Path, output_dir: Path) -> QualificationOutput:
    validate_output_directory(output_dir)
    report = evaluate_qualification(path).report
    created = False
    try:
        output_dir.mkdir()
        created = True
        report_path = write_message(output_dir / 'qualification.pb.json', report)
    except (OSError, CalibrationError) as exc:
        if created:
            try:
                output_dir.rmdir()
            except OSError:
                pass
        if isinstance(exc, CalibrationError):
            raise
        raise CalibrationError(f"Cannot write qualification into '{output_dir}': {exc}") from exc
    return QualificationOutput(report_path, report)
