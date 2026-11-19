#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/klayout-pex).
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

"""Recollect immutable raw evidence, including interrupted campaigns."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

from .artifacts import (artifact_path, copy_artifact, read_message, sha256_file,
                        validate_output_directory, verify_artifacts, write_message)
from .validation import CalibrationError
from klayout_pex_protobuf.kpex.calibration.preparation_pb2 import CalibrationManifest, CapacitanceMeasurement
from klayout_pex_protobuf.kpex.calibration.solving_pb2 import (
    CalibrationRunManifest, CalibrationRunCheckpoint, CalibrationRunCompletion,
    CalibrationCollection, CalibrationCaseResult,
)
from klayout_pex_protobuf.kpex.result.solver_execution_pb2 import SolverExecution


@dataclass(frozen=True)
class CalibrationCollectionResult:
    manifest_path: Path
    written_paths: Tuple[Path, ...]
    successful_cases: int
    failed_cases: int


def _native_statistics(log: Path) -> Dict[str, Optional[int]]:
    """Read only the final matrix's statistics block; missing or ambiguous counts stay unknown."""
    fields = {
        'input_panels': ('Number of input panels to solver engine:', r'Number of input panels to solver engine: (\d+)'),
        'refined_panels': ('Number of panels after refinement:', r'Number of panels after refinement: (\d+)'),
        'potential_estimates': ('Number of potential estimates:', r'Number of potential estimates: (\d+)'),
        'links': ('Number of links:', r'Number of links: (\d+)(?: \(.*\))?'),
    }
    unknown = {name: None for name in fields}
    lines = log.read_text(encoding='utf-8', errors='replace').splitlines()
    matrices = [index for index, line in enumerate(lines) if line.strip() == 'Capacitance matrix is:']
    if not matrices:
        return unknown
    tail = lines[matrices[-1] + 1:]
    # A later unfinished adaptive iteration must not contribute statistics to an earlier matrix.
    for index, line in enumerate(tail):
        if line.startswith('Iteration number #'):
            tail = tail[:index]
            break
    blocks = [index for index, line in enumerate(tail) if line.strip() == 'Solve statistics:']
    if len(blocks) != 1:
        return unknown
    block = tail[blocks[0] + 1:]
    for name, (prefix, pattern) in fields.items():
        candidates = [line.strip() for line in block if line.strip().startswith(prefix)]
        if len(candidates) == 1:
            match = re.fullmatch(pattern, candidates[0])
            if match:
                try:
                    unknown[name] = int(match.group(1))
                except ValueError:
                    pass  # Oversized or malformed native counts are unknown, not fabricated
    return unknown


def _validate_checkpoint(checkpoint: CalibrationRunCheckpoint, case_id: str):
    if checkpoint.schema_version != 1 or checkpoint.case_id != case_id:
        raise CalibrationError(f"Checkpoint for '{case_id}' has an incompatible identity or version")
    execution = checkpoint.execution
    if execution.status not in (SolverExecution.NOT_STARTED, SolverExecution.RUNNING,
                                SolverExecution.SUCCEEDED, SolverExecution.FAILED,
                                SolverExecution.TIMED_OUT, SolverExecution.CANCELLED):
        raise CalibrationError(f"Checkpoint for '{case_id}' has an unknown execution status")
    if not math.isfinite(execution.duration_seconds) or execution.duration_seconds < 0:
        raise CalibrationError(f"Checkpoint for '{case_id}' has an invalid duration")
    if execution.status == SolverExecution.SUCCEEDED and (
            not execution.HasField('return_code') or execution.return_code != 0 or not checkpoint.HasField('log')):
        raise CalibrationError(f"Successful checkpoint for '{case_id}' needs exit code zero and a hashed log")


def collect_calibration(run_manifest: Path, output_dir: Path) -> CalibrationCollectionResult:
    # No geometry imports or executable discovery: saved evidence is portable.
    from .solve import reference, validate_options_message
    from .prepared_input import read_preparation
    from ..fastercap.result_collection import collect_fastercap_matrix
    from ..fastercap.fastercap_error import FasterCapError

    validate_output_directory(output_dir)
    root = run_manifest.parent
    manifest_hash = sha256_file(run_manifest)
    manifest = read_message(run_manifest, CalibrationRunManifest())
    if manifest.schema_version != 1 or not manifest.kpex_version or manifest.solver.name != 'fastercap':
        raise CalibrationError('Unsupported calibration run schema, version or solver')
    validate_options_message(manifest.options)
    if (not manifest.solver.version or not manifest.solver.operating_system or not manifest.solver.architecture
            or re.fullmatch(r'[0-9a-f]{64}', manifest.solver.executable_sha256) is None):
        raise CalibrationError('Solver identity is incomplete')
    files: Dict[str, str] = {run_manifest.name: manifest_hash}

    def remember(path: Path, digest: Optional[str] = None):
        name = path.relative_to(root).as_posix()
        value = sha256_file(path) if digest is None else digest
        if name in files and files[name] != value:
            raise CalibrationError(f"Artifact '{name}' changed during collection")
        files[name] = value

    verify_artifacts(root, [manifest.preparation])
    preparation_path = artifact_path(root, manifest.preparation.path)
    remember(preparation_path, manifest.preparation.sha256)
    prepared = read_preparation(preparation_path).manifest
    if (prepared.schema_version != 1 or prepared.stage != CalibrationManifest.PREPARED
            or not prepared.cases or len(prepared.cases) != len(manifest.cases)):
        raise CalibrationError('Run preparation has an unsupported stage or case set')
    for item, path in zip(prepared.artifacts, verify_artifacts(preparation_path.parent, prepared.artifacts)):
        remember(path, item.sha256)
    completion_path = root / 'completed.pb.json'
    complete = completion_path.exists() or completion_path.is_symlink()
    if complete:
        completion = read_message(completion_path, CalibrationRunCompletion())
        if completion.schema_version != 1 or completion.manifest != reference(run_manifest, root):
            raise CalibrationError('Completion record does not identify this run')
        verify_artifacts(root, completion.checkpoints)
        if [ref.path for ref in completion.checkpoints] != [case.checkpoint_path for case in manifest.cases]:
            raise CalibrationError('Completion record does not identify every case checkpoint')
        remember(completion_path)
    checkpoints = []
    identities = set()
    declared_paths = set(files)
    for case, preparation in zip(manifest.cases, prepared.cases):
        if case.case_id != preparation.id or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', case.case_id):
            raise CalibrationError('Run cases differ from the prepared cases')
        if case.case_id.casefold() in identities:
            raise CalibrationError('Run case IDs must be unique ignoring case')
        identities.add(case.case_id.casefold())
        if (case.checkpoint_path != f'cases/{case.case_id}/checkpoint.pb.json'
                or case.log_path != f'cases/{case.case_id}/solver.log'):
            raise CalibrationError('Run case paths do not match their case identity')
        signals = list(preparation.measurement.conductor_order)
        measurement = preparation.measurement
        if (measurement.kind != CapacitanceMeasurement.MAXWELL_CAPACITANCE_MATRIX
                or measurement.convention != CapacitanceMeasurement.MAXWELL_GROUNDED_UNEXCITED
                or measurement.capacitance_unit != CapacitanceMeasurement.FARAD
                or measurement.floating_conductors or measurement.reference.potential_v != 0
                or not signals or any(not name for name in signals) or len(set(signals)) != len(signals)
                or not measurement.reference.profile or measurement.reference.profile in signals):
            raise CalibrationError('Unsupported prepared measurement contract')
        for item, path in zip(case.inputs, verify_artifacts(root, case.inputs)):
            if not item.path.startswith(f'cases/{case.case_id}/inputs/') or item.path.casefold() in declared_paths:
                raise CalibrationError('Solver input paths must be unique and owned by their case')
            declared_paths.add(item.path.casefold())
            remember(path, item.sha256)
        if case.inputs and (case.primary_input_path not in [item.path for item in case.inputs]
                            or not case.primary_input_path.endswith('.lst')):
            raise CalibrationError('Primary solver input is absent from the declared inputs')
        checkpoint_path = artifact_path(root, case.checkpoint_path, required=False)
        if checkpoint_path.exists():
            checkpoint = read_message(checkpoint_path, CalibrationRunCheckpoint())
            _validate_checkpoint(checkpoint, case.case_id)
            remember(checkpoint_path)
        else:
            checkpoint = CalibrationRunCheckpoint(schema_version=1, case_id=case.case_id)
            checkpoint.execution.status = SolverExecution.NOT_STARTED
        if complete and checkpoint.execution.status in (SolverExecution.RUNNING, SolverExecution.NOT_STARTED):
            raise CalibrationError('Completion record contains unfinished execution')
        if checkpoint.execution.status == SolverExecution.SUCCEEDED and not case.inputs:
            raise CalibrationError('Successful execution is missing solver inputs')
        if checkpoint.HasField('log'):
            if checkpoint.log.path != case.log_path:
                raise CalibrationError('Checkpoint log does not belong to this case')
            verify_artifacts(root, [checkpoint.log])
            remember(root / case.log_path, checkpoint.log.sha256)
        elif checkpoint.execution.status in (SolverExecution.RUNNING, SolverExecution.NOT_STARTED):
            log = artifact_path(root, case.log_path, required=False)
            if log.is_file():
                remember(log)  # Snapshot partial output, but never promote it to a successful result.
        checkpoints.append(checkpoint)
    if sha256_file(run_manifest) != manifest_hash:
        raise CalibrationError('Run manifest changed during collection')
    output = output_dir.absolute()
    try:
        output.mkdir()
        written = [copy_artifact(artifact_path(root, name), output / 'runs' / name, digest)
                   for name, digest in files.items()]
        collection = CalibrationCollection(schema_version=1, execution_complete=complete,
                                            run_manifest=reference(output / 'runs' / run_manifest.name, output))
        for case, preparation, checkpoint in zip(manifest.cases, prepared.cases, checkpoints):
            record = collection.cases.add(case_id=case.case_id, execution=checkpoint.execution)
            status = checkpoint.execution.status
            if status in (SolverExecution.NOT_STARTED, SolverExecution.RUNNING):
                record.status = CalibrationCaseResult.INCOMPLETE
            elif status in (SolverExecution.FAILED, SolverExecution.TIMED_OUT, SolverExecution.CANCELLED):
                record.status = CalibrationCaseResult.EXECUTION_FAILED
                record.diagnostics.append(checkpoint.execution.diagnostic)
            elif status == SolverExecution.SUCCEEDED:
                log = output / 'runs' / case.log_path
                try:
                    native, measured = collect_fastercap_matrix(
                        log, list(preparation.measurement.conductor_order), preparation.measurement.reference.profile)
                    record.native_matrix.CopyFrom(native)
                    record.measured_matrix.CopyFrom(measured)
                    record.status = CalibrationCaseResult.COLLECTED
                except FasterCapError as exc:
                    record.status = CalibrationCaseResult.INVALID_RESULT
                    record.diagnostics.append(str(exc))
                for name, value in _native_statistics(log).items():
                    if value is not None and value <= 2**64 - 1:
                        setattr(record, name, value)
                for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
                    if re.match(r'^\s*(Warning|Error):', line, flags=re.IGNORECASE):
                        record.diagnostics.append(line)
            else:
                raise NotImplementedError(f'Collect execution status {status}')
        collection.artifacts.extend(reference(path, output) for path in written)
        path = write_message(output / 'collection.pb.json', collection)
        written.append(path)
        success = sum(case.status == CalibrationCaseResult.COLLECTED for case in collection.cases)
        return CalibrationCollectionResult(path, tuple(written), success, len(collection.cases) - success)
    except OSError as exc:
        raise CalibrationError(f"Cannot collect into '{output}'; evidence was retained: {exc}") from exc
