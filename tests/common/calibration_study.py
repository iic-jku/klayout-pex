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

"""Shared calibration studies and deterministic solver evidence for tests."""

from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Tuple

import pytest

from kpex.calibration.artifacts import read_message, sha256_file, write_message
from kpex.calibration.patterns import read_patterns
from kpex.calibration.prepare import prepare_calibration
from kpex.calibration.solve import SolveOptions, solve_calibration
from kpex.fastercap.fastercap_runner import FasterCapRunResult
from kpex.tech_info import TechInfo
from kpex_protobuf.kpex.calibration.qualification_pb2 import (
    CalibrationQualificationStudy, CalibrationRefinementAxis as Axis,
)
from kpex_protobuf.kpex.calibration.solving_pb2 import CalibrationCollection
from kpex_protobuf.kpex.result.solver_execution_pb2 import SolverIdentity
from tests.common.fastercap_report import numerical_report


def make_study(root: Path, tech_info: TechInfo, pattern_data: Dict[str, Any],
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
        assert result.successful_cases == case_count, [
            (case.case_id, list(case.diagnostics))
            for case in read_message(result.collection_path, CalibrationCollection()).cases
            if case.status != case.COLLECTED
        ]
        entry = study.collections.add(id=name).collection
        entry.path = result.collection_path.relative_to(root).as_posix()
        entry.sha256 = sha256_file(result.collection_path)
    for pattern in patterns:
        case = study.cases.add(case_id=pattern['id'], reference_collection_id='reference')
        case.refinements.add(axis=Axis.LINEAR_SOLVER_TOLERANCE, collection_ids=['solver-coarse', 'solver-medium', 'reference'])
        case.refinements.add(axis=Axis.INITIAL_MESH_MAX_AREA, collection_ids=['mesh-coarse', 'mesh-medium', 'reference'])
        case.refinements.add(axis=Axis.DOMAIN_MARGIN, collection_ids=['domain-small', 'domain-medium', 'reference'])
        if adaptive:
            case.refinements.add(axis=Axis.ADAPTIVE_MESH_REFINEMENT,
                                 collection_ids=['adaptive-coarse', 'adaptive-medium', 'reference'])
    return study, write_message(root / 'study.pb.json', study)


def mock_solver(monkeypatch: pytest.MonkeyPatch, matrix_for_case: Callable[[str, str], List[List[float]]],
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
