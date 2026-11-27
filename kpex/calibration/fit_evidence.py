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
"""Qualification evidence shared by the capacitance fitters."""

import math
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from .artifacts import read_message, sha256_file
from .qualification import QualificationEvaluation, charge_rows, evaluate_qualification
from .validation import CalibrationError
from kpex_protobuf.kpex.calibration.qualification_pb2 import (
    CalibrationQualificationCaseResult, CalibrationQualificationReport, CalibrationQualificationStatus as Status,
    CalibrationRefinementResult,
)
from kpex_protobuf.kpex.result.capacitance_matrix_pb2 import MaxwellCapacitanceMatrix as Matrix


def qualified_couplings(case: CalibrationQualificationCaseResult) -> Tuple[float, float]:
    """Return the A/B and B/A coupling without changing the charge convention."""
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
    return -float(capacitance[a, b]), -float(capacitance[b, a])


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


def recent_couplings(refinement: CalibrationRefinementResult, reference_f: float) -> Dict[float, float]:
    couplings = {}
    value_f = reference_f
    for level, step in zip(reversed(refinement.levels[-3:-1]), reversed(refinement.changes[-2:])):
        # The qualification deltas are in charge-row convention. Coupling is
        # -C[A,B], so walking backward adds the signed change in C[A,B].
        value_f += next(entry.signed_delta_f for entry in step.entries
                        if (entry.entry.charge_conductor_id, entry.entry.excitation_conductor_id) == ('A', 'B'))
        couplings[level.parameter_value] = value_f
    return couplings


def read_verified_qualification(study_path: Path, qualification_path: Path
                                ) -> Tuple[str, QualificationEvaluation]:
    """Recompute qualification and verify its saved report against the evidence."""
    qualification_sha256 = sha256_file(qualification_path)
    saved = read_message(qualification_path, CalibrationQualificationReport())
    evaluation = evaluate_qualification(study_path)
    # A package version change alone does not invalidate evidence produced by the same method.
    evaluation.report.kpex_version = saved.kpex_version
    _ignore_eigensolver_roundoff(saved)
    _ignore_eigensolver_roundoff(evaluation.report)
    if not saved.kpex_version or saved != evaluation.report:
        raise CalibrationError('Qualification report differs from the recomputed study and solver evidence')

    return qualification_sha256, evaluation



def refinement_residual_violation(max_abs_training_residual_f: float, validation_residuals_f: Iterable[float],
                                  budget_f: float) -> Optional[str]:
    maximum_f = max(max_abs_training_residual_f, max(abs(value) for value in validation_residuals_f))
    if maximum_f > budget_f:
        return f'Maximum absolute residual {maximum_f:.6g} F exceeds the declared budget {budget_f:.6g} F'
    return None
