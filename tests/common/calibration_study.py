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
"""Shared calibration studies and deterministic solver evidence for tests."""

from dataclasses import replace
import json
import math
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Tuple

import pytest
import numpy as np

from kpex.calibration.artifacts import read_message, sha256_file, write_message
from kpex.calibration.patterns import read_patterns
from kpex.calibration.prepare import prepare_calibration
from kpex.calibration.solve import SolveOptions, solve_calibration
from kpex.fastercap.fastercap_runner import FasterCapRunResult
from kpex.tech_info import TechInfo
from kpex_protobuf.kpex.calibration.qualification_pb2 import (
    CalibrationQualificationStudy, CalibrationRefinementAxis as Axis,
)
from kpex_protobuf.kpex.calibration.patterns_pb2 import PatternSetSpecification, TRAINING, VALIDATION
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


def wire_patterns_and_coupling() -> Tuple[List[Dict[str, Any]], Callable[[str, str], List[List[float]]]]:
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


def overlap_patterns_and_coupling(holdout_offset_f: float = 0
                                 ) -> Tuple[PatternSetSpecification, Callable[[str, str], List[List[float]]]]:
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

    return specification, matrix_for_case


def assert_circuit_coupling(root: Path, simulator: Callable, coupling_f: float, prediction_f: float):
    """Compare a fit with an independently specified passive capacitor network."""
    circuit = root / 'holdout.spice'
    circuit.write_text(f'.subckt dut A B\nCa A 0 3f\nCb B 0 2f\nCab A B {coupling_f:.17g}\n.ends\n',
                       encoding='utf-8')
    frequencies, actual = simulator(str(circuit), 'dut', ['A', 'B'], (3, 9), str(root))
    predicted_y = -1j * math.tau * frequencies * prediction_f
    np.testing.assert_allclose(actual[:, 0, 1], predicted_y, rtol=5e-6, atol=1e-20)
    np.testing.assert_allclose(actual[:, 1, 0], predicted_y, rtol=5e-6, atol=1e-20)
