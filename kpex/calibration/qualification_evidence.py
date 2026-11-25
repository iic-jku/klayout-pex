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
"""Read qualification evidence from the saved collection and its hashed inputs."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, TYPE_CHECKING

from google.protobuf.message import DecodeError
from packaging.version import InvalidVersion, Version

from .artifacts import artifact_path, read_message, sha256_file, verify_artifacts
from .collect import read_native_statistics
from .prepared_input import read_preparation
from .solve import validate_options_message
from .validation import CalibrationError
from ..fastercap.fastercap_error import FasterCapError
from ..tool_version_constraints import Tool, effective_version_range

from kpex_protobuf.kpex.calibration.solving_pb2 import (
    CalibrationCaseResult, CalibrationCollection, CalibrationRunCheckpoint, CalibrationRunManifest,
)
from kpex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene, ResolvedDomain
from kpex_protobuf.kpex.result.solver_execution_pb2 import SolverExecution

if TYPE_CHECKING:
    from kpex_protobuf.kpex.calibration.preparation_pb2 import CalibrationCase, CalibrationManifest


@dataclass(frozen=True)
class QualificationRun:
    root: Path
    run_sha256: str
    collection: CalibrationCollection
    manifest: CalibrationRunManifest
    preparation: 'CalibrationManifest'
    artifacts: Dict[str, str]

    def artifact(self, path: Path) -> Path:
        name = path.relative_to(self.root).as_posix()
        if name not in self.artifacts:
            raise CalibrationError(f"'{path}' is outside the saved collection artifact set")
        verified = artifact_path(self.root, name)
        if sha256_file(verified) != self.artifacts[name]:
            raise CalibrationError(f"Collection artifact '{name}' has changed")
        return verified


@dataclass(frozen=True)
class QualificationMeasurement:
    run: QualificationRun
    pattern: 'CalibrationCase'
    record: CalibrationCaseResult
    scene: PEX25DScene
    solver_inputs: Tuple[Tuple[str, str], ...]


def read_collection(path: Path, expected_hash: str) -> QualificationRun:
    root = path.parent
    collection = read_message(path, CalibrationCollection())
    if sha256_file(path) != expected_hash or collection.schema_version != 1:
        raise CalibrationError(f"Collection '{path}' changed or has an unsupported schema")
    verify_artifacts(root, collection.artifacts)
    hashes = {item.path: item.sha256 for item in collection.artifacts}
    run_path = artifact_path(root, collection.run_manifest.path)
    if hashes.get(collection.run_manifest.path) != collection.run_manifest.sha256:
        raise CalibrationError('Run manifest is absent from the collection artifact set')
    run = read_message(run_path, CalibrationRunManifest())
    if (run.schema_version != 1 or not run.kpex_version or run.solver.name != 'fastercap'
            or not run.solver.version or not run.solver.executable_sha256
            or not run.solver.operating_system or not run.solver.architecture):
        raise CalibrationError('Unsupported calibration run schema or solver identity')
    try:
        version = Version(run.solver.version)
    except InvalidVersion as exc:
        raise CalibrationError(f"Invalid recorded FasterCap version '{run.solver.version}'") from exc
    supported = effective_version_range(Tool.FASTERCAP)
    if version not in supported:
        raise CalibrationError(f'Qualification requires FasterCap {supported}; the saved run used {version}')
    validate_options_message(run.options)

    prepared_path = artifact_path(run_path.parent, run.preparation.path)
    if hashes.get(prepared_path.relative_to(root).as_posix()) != run.preparation.sha256:
        raise CalibrationError('Preparation is absent from the collection artifact set')
    prepared = read_preparation(prepared_path)
    if prepared.sha256 != run.preparation.sha256:
        raise CalibrationError('Preparation changed during qualification')
    for artifact in prepared.manifest.artifacts:
        name = (prepared_path.parent.relative_to(root) / artifact.path).as_posix()
        if hashes.get(name) != artifact.sha256:
            raise CalibrationError(f"Prepared artifact '{name}' is absent from the collection")
    case_ids = [case.case_id for case in collection.cases]
    if (not case_ids or len({case_id.casefold() for case_id in case_ids}) != len(case_ids)
            or case_ids != [case.case_id for case in run.cases]
            or case_ids != [case.id for case in prepared.manifest.cases]):
        raise CalibrationError('Collection case IDs differ from the run or preparation')
    return QualificationRun(root, collection.run_manifest.sha256,
                            collection, run, prepared.manifest, hashes)


def read_measurement(run: QualificationRun, case_id: str) -> QualificationMeasurement:
    from ..fastercap.result_collection import collect_fastercap_matrix

    index = next((i for i, case in enumerate(run.collection.cases) if case.case_id == case_id), None)
    if index is None:
        raise CalibrationError(f"Referenced collection does not contain case '{case_id}'")
    pattern = run.preparation.cases[index]
    record = run.collection.cases[index]
    case = run.manifest.cases[index]
    run_root = (run.root / run.collection.run_manifest.path).parent
    prepared_root = artifact_path(run_root, run.manifest.preparation.path).parent
    scene_path = run.artifact(artifact_path(prepared_root, pattern.scene))
    try:
        scene = PEX25DScene.FromString(scene_path.read_bytes())
    except (DecodeError, OSError) as exc:
        raise CalibrationError(f"Invalid saved scene for '{case_id}': {exc}") from exc
    scene.ClearField('metadata')
    domain = scene.domain
    margin = run.preparation.domain_margin_grid
    box, bounds = domain.box, domain.geometry_bounds
    if (scene.units != run.preparation.units or scene.ground_plane.name != pattern.measurement.reference.profile
            or domain.origin != ResolvedDomain.ORIGIN_DOMAIN_MARGIN or not domain.HasField('geometry_bounds')
            or not domain.HasField('box') or not domain.HasField('applied_margin')
            or (domain.applied_margin.x, domain.applied_margin.y, domain.applied_margin.z) != (margin,) * 3
            or (box.lower_left.x, box.lower_left.y, box.lower_left.z,
                box.upper_right.x, box.upper_right.y, box.upper_right.z) != (
                    bounds.lower_left.x - margin, bounds.lower_left.y - margin, scene.ground_plane.zhigh,
                    bounds.upper_right.x + margin, bounds.upper_right.y + margin, bounds.upper_right.z + margin)):
        raise CalibrationError(f"Saved geometry or domain for '{case_id}' differs from the preparation")

    if record.status == CalibrationCaseResult.COLLECTED:
        checkpoint = read_message(run.artifact(artifact_path(run_root, case.checkpoint_path)), CalibrationRunCheckpoint())
        if (checkpoint.schema_version != 1 or checkpoint.case_id != case_id
                or checkpoint.execution != record.execution or record.execution.status != SolverExecution.SUCCEEDED
                or not record.execution.HasField('return_code') or record.execution.return_code != 0
                or not record.execution.arguments):
            raise CalibrationError(f"Collected case '{case_id}' does not identify a successful solver execution")
        if (not case.numerical_report_path or checkpoint.numerical_report.path != case.numerical_report_path
                or checkpoint.log.path != case.log_path):
            raise CalibrationError(f"Collected case '{case_id}' requires the full-precision FasterCap report")
        log = run.artifact(artifact_path(run_root, case.log_path))
        report = run.artifact(artifact_path(run_root, case.numerical_report_path))
        log_name = log.relative_to(run.root).as_posix()
        report_name = report.relative_to(run.root).as_posix()
        if (run.artifacts.get(log_name) != checkpoint.log.sha256
                or run.artifacts.get(report_name) != checkpoint.numerical_report.sha256):
            raise CalibrationError(f"Collected case '{case_id}' has inconsistent checkpoint hashes")
        actual_input = record.execution.arguments[-1].removeprefix('"').removesuffix('"')
        try:
            native, measured = collect_fastercap_matrix(
                log, list(pattern.measurement.conductor_order), pattern.measurement.reference.profile,
                numerical_report=report,
                expected_input=actual_input, expected_version=run.manifest.solver.version,
            )
        except FasterCapError as exc:
            raise CalibrationError(f"Cannot verify collected matrix for '{case_id}': {exc}") from exc
        panels = read_native_statistics(log)['refined_panels']
        if panels is not None and panels > 2**64 - 1:
            panels = None
        if (record.refined_panels if record.HasField('refined_panels') else None) != panels:
            raise CalibrationError(f"Collected panel count for '{case_id}' differs from the saved log")
        if record.native_matrix != native or record.measured_matrix != measured:
            raise CalibrationError(f"Collected matrix for '{case_id}' differs from the native report")
    elif record.status not in (CalibrationCaseResult.INCOMPLETE, CalibrationCaseResult.EXECUTION_FAILED,
                               CalibrationCaseResult.INVALID_RESULT):
        raise CalibrationError(f"Invalid collection status for '{case_id}'")
    inputs = []
    for item in case.inputs:
        path = run.artifact(artifact_path(run_root, item.path))
        if run.artifacts[path.relative_to(run.root).as_posix()] != item.sha256:
            raise CalibrationError(f"Solver input for '{case_id}' differs from the run manifest")
        inputs.append((item.path, item.sha256))
    return QualificationMeasurement(run, pattern, record, scene, tuple(sorted(inputs)))
