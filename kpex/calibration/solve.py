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

"""Bounded execution with durable checkpoints and protobuf provenance."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import math
import os
from pathlib import Path
import platform
import shutil
from tempfile import TemporaryDirectory
import threading
from typing import Any, List, Optional, Tuple

from .artifacts import (artifact_path, copy_artifact, read_message, sha256_file, validate_output_directory,
                        verify_artifacts, write_message)
from .validation import CalibrationError
from .prepared_input import PreparedInput, read_preparation, validated_scenes
from ..version import __version__
from ..util.number_range import DELAUNAY_B_MAX, RELATIVE_ERROR
from kpex_protobuf.kpex.calibration.solving_pb2 import (
    CalibrationRunManifest, CalibrationRunCase, CalibrationRunCheckpoint,
    CalibrationRunCompletion, CalibrationSolveOptions,
)
from kpex_protobuf.kpex.fastercap.calibration_pb2 import CalibrationControls
from ..fastercap.calibration_backend import controls_message
from kpex_protobuf.kpex.calibration.preparation_pb2 import CalibrationArtifactReference
from kpex_protobuf.kpex.result.solver_execution_pb2 import SolverExecution, SolverIdentity

MAX_JOBS = 32
MAX_THREADS_PER_JOB = 256
MAX_MESH_MIN_ANGLE_DEG = math.degrees(math.asin(DELAUNAY_B_MAX / 2))
THREAD_ENVIRONMENT_KEYS = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                           'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS')


def _number(value: Any, name: str, minimum: float, maximum: Optional[float] = None,
            inclusive: bool = False):
    try:
        valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                 and math.isfinite(value) and (value >= minimum if inclusive else value > minimum)
                 and (maximum is None or value <= maximum))
    except OverflowError:
        valid = False
    if not valid:
        relation = 'at least' if inclusive else 'greater than'
        bound = '' if maximum is None else f' and at most {maximum:g}'
        raise CalibrationError(f'{name} must be finite, {relation} {minimum:g}{bound}')


@dataclass(frozen=True)
class SolveOptions:
    jobs: int = 1
    solver_timeout_seconds: float = 600.0
    threads_per_job: int = 1
    automatic_tolerance: Optional[float] = None
    mesh_refinement: Optional[float] = None
    gmres_tolerance: Optional[float] = None
    mesh_max_area_um2: float = 0.0
    mesh_min_angle_deg: float = 30.0
    interaction_ratio: float = 0.5

    def __post_init__(self):
        for name, maximum in (('jobs', MAX_JOBS), ('threads_per_job', MAX_THREADS_PER_JOB)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise CalibrationError(f'{name} must be an integer from 1 to {maximum}')
        _number(self.solver_timeout_seconds, 'solver_timeout_seconds', 0, threading.TIMEOUT_MAX)
        _number(self.mesh_max_area_um2, 'mesh_max_area_um2', 0, inclusive=True)
        _number(self.mesh_min_angle_deg, 'mesh_min_angle_deg', 0, MAX_MESH_MIN_ANGLE_DEG, inclusive=True)
        _number(self.interaction_ratio, 'interaction_ratio', 0)
        manual = self.mesh_refinement is not None or self.gmres_tolerance is not None
        if manual and self.automatic_tolerance is not None:
            raise CalibrationError('Automatic tolerance cannot be combined with manual mesh/GMRES controls')
        if manual and (self.mesh_refinement is None or self.gmres_tolerance is None):
            raise CalibrationError('Manual refinement requires both mesh_refinement and gmres_tolerance')
        if manual:
            _number(self.mesh_refinement, 'mesh_refinement', 0)
        elif self.automatic_tolerance is None:
            object.__setattr__(self, 'automatic_tolerance', 0.05)
        for name in ('automatic_tolerance', 'gmres_tolerance'):
            value = getattr(self, name)
            if value is not None:
                _number(value, name, 0)
                if value not in RELATIVE_ERROR:
                    raise CalibrationError(f'{name} {RELATIVE_ERROR.error_message(str(value))}')


def options_message(options: SolveOptions) -> CalibrationSolveOptions:
    controls = CalibrationControls(interaction_ratio=options.interaction_ratio,
                                 mesh_max_area_um2=options.mesh_max_area_um2,
                                 mesh_min_angle_deg=options.mesh_min_angle_deg)
    if options.automatic_tolerance is not None:
        controls.automatic_tolerance = options.automatic_tolerance
    else:
        controls.mesh_refinement = options.mesh_refinement
        controls.gmres_tolerance = options.gmres_tolerance
    result = CalibrationSolveOptions(jobs=options.jobs, threads_per_job=options.threads_per_job,
                                   solver_timeout_seconds=options.solver_timeout_seconds)
    result.solver_controls.Pack(controls)
    return result


def validate_options_message(message: CalibrationSolveOptions) -> SolveOptions:
    controls = controls_message(message.solver_controls)
    if not controls.HasField('automatic_tolerance') and not controls.HasField('mesh_refinement'):
        raise CalibrationError('Saved solver options need an explicit refinement mode')
    return SolveOptions(jobs=message.jobs, threads_per_job=message.threads_per_job,
                        solver_timeout_seconds=message.solver_timeout_seconds,
                        automatic_tolerance=controls.automatic_tolerance if controls.HasField('automatic_tolerance') else None,
                        mesh_refinement=controls.mesh_refinement if controls.HasField('mesh_refinement') else None,
                        gmres_tolerance=controls.gmres_tolerance if controls.HasField('gmres_tolerance') else None,
                        interaction_ratio=controls.interaction_ratio,
                        mesh_max_area_um2=controls.mesh_max_area_um2, mesh_min_angle_deg=controls.mesh_min_angle_deg)


def reference(path: Path, root: Path) -> CalibrationArtifactReference:
    return CalibrationArtifactReference(path=path.relative_to(root).as_posix(), sha256=sha256_file(path))


@dataclass(frozen=True)
class CalibrationSolveResult:
    manifest_path: Path
    collection_path: Path
    written_paths: Tuple[Path, ...]
    successful_cases: int
    failed_cases: int


def _solver_identity(executable: str) -> SolverIdentity:
    from ..tool_version_constraints import Tool, effective_version_range
    resolved = shutil.which(executable)
    if resolved is None:
        raise CalibrationError(f"FasterCap executable '{executable}' was not found or is not executable")
    path = Path(resolved).resolve()
    before = sha256_file(path)
    version = Tool.FASTERCAP.detect_version(str(path))
    supported = effective_version_range(Tool.FASTERCAP)
    if version is None or version not in supported:
        raise CalibrationError(f"Calibration requires FasterCap {supported}; '{path}' reported {version or 'unknown'}")
    if sha256_file(path) != before:
        raise CalibrationError('FasterCap executable changed during version detection')
    return SolverIdentity(name='fastercap', version=str(version), executable_path=str(path),
                          executable_sha256=before, operating_system=platform.system(),
                          architecture=platform.machine(), operating_system_release=platform.release())


def snapshot_preparation(prepared: PreparedInput, target: Path) -> List[Path]:
    paths = []
    for item in prepared.manifest.artifacts:
        paths.append(copy_artifact(artifact_path(prepared.path.parent, item.path), target / item.path, item.sha256))
    paths.append(copy_artifact(prepared.path, target / 'manifest.json', prepared.sha256))
    return paths

def _export(scene: Any, directory: Path, options: SolveOptions) -> List[Path]:
    from ..fastercap.pex25d_exporter import FasterCapSceneExporter

    # KLayout geometry/export runs serially. A private staging directory contains partial exports.
    with TemporaryDirectory(prefix='kpex-calibration-export-') as temporary:
        staging = Path(temporary)
        # Preserve the existing b limit even if the degree conversion rounds upward.
        quality = min(DELAUNAY_B_MAX, 2 * math.sin(math.radians(options.mesh_min_angle_deg)))
        written = FasterCapSceneExporter().export(
            scene, output_dir_path=str(staging), prefix='geometry',
            options={'delaunay_amax': options.mesh_max_area_um2, 'delaunay_b': quality})
        if not written:
            raise CalibrationError('FasterCap exporter returned no solver input')
        sources = []
        seen = set()
        for returned in written:
            candidate = Path(returned)
            try:
                name = candidate.relative_to(staging).as_posix()
            except ValueError as exc:
                raise CalibrationError(f"FasterCap exporter returned an outside path '{candidate}'") from exc
            source = artifact_path(staging, name)
            if name.casefold() in seen:
                raise CalibrationError(f"FasterCap exporter repeated path '{name}'")
            seen.add(name.casefold())
            sources.append((source, directory / name))
        if sum(source.suffix == '.lst' for source, _ in sources) != 1:
            raise CalibrationError('FasterCap export must contain exactly one primary .lst file')
        paths = []
        try:
            for source, destination in sources:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.open('rb') as src, destination.open('xb') as dst:
                    paths.append(destination)
                    shutil.copyfileobj(src, dst)
        except OSError:
            for path in reversed(paths):
                try:
                    path.unlink()
                except OSError:
                    pass
            raise
        return paths


def _execute(case: CalibrationRunCase, manifest: CalibrationRunManifest, output: Path,
             options: SolveOptions, cancelled: threading.Event):
    from ..fastercap.fastercap_error import (FasterCapExecutionError, FasterCapTimeoutError,
                                            FasterCapCancelledError)
    from ..fastercap.fastercap_runner import run_fastercap

    checkpoint = CalibrationRunCheckpoint(schema_version=1, case_id=case.case_id)
    checkpoint.execution.status = SolverExecution.RUNNING
    path = output / case.checkpoint_path
    env = os.environ.copy()
    env.update({key: str(options.threads_per_job) for key in THREAD_ENVIRONMENT_KEYS})
    checkpoint.execution.controlled_environment.update({key: env[key] for key in THREAD_ENVIRONMENT_KEYS})
    if cancelled.is_set():
        checkpoint.execution.status = SolverExecution.CANCELLED
        write_message(path, checkpoint, replace=True)
        return
    write_message(path, checkpoint, replace=True)
    result = None
    log = output / case.log_path
    numerical_report = output / case.numerical_report_path if case.numerical_report_path else None
    try:
        verify_artifacts(output, case.inputs)
        if sha256_file(Path(manifest.solver.executable_path)) != manifest.solver.executable_sha256:
            raise CalibrationError('FasterCap executable changed before execution')
        primary = artifact_path(output, case.primary_input_path)
        result = run_fastercap(
            manifest.solver.executable_path, str(primary), str(log), options.automatic_tolerance,
            options.interaction_ratio, 0, True, False, False, timeout_seconds=options.solver_timeout_seconds,
            cwd=str(primary.parent), env=env, mesh_refinement=options.mesh_refinement,
            gmres_tolerance=options.gmres_tolerance, cancel_event=cancelled,
            report_path=str(numerical_report) if numerical_report is not None else None)
        verify_artifacts(output, case.inputs)
        if sha256_file(Path(manifest.solver.executable_path)) != manifest.solver.executable_sha256:
            raise CalibrationError('FasterCap executable changed during execution')
        checkpoint.execution.status = SolverExecution.SUCCEEDED
    except Exception as exc:
        if isinstance(exc, FasterCapExecutionError):
            result = exc.result
        checkpoint.execution.status = (SolverExecution.TIMED_OUT if isinstance(exc, FasterCapTimeoutError)
                                       else SolverExecution.CANCELLED if isinstance(exc, FasterCapCancelledError)
                                       else SolverExecution.FAILED)
        checkpoint.execution.diagnostic = f"FasterCap case '{case.case_id}': {exc}"
    if result is not None:
        checkpoint.execution.arguments.extend(result.arguments)
        if result.returncode is not None:
            checkpoint.execution.return_code = result.returncode
        checkpoint.execution.duration_seconds = result.duration_seconds
    if log.is_file():
        checkpoint.log.CopyFrom(reference(log, output))
    if numerical_report is not None and numerical_report.is_file():
        checkpoint.numerical_report.CopyFrom(reference(numerical_report, output))
    write_message(path, checkpoint, replace=True)


def solve_calibration(prepared_path: Path, output_dir: Path, *, executable: str = 'FasterCap',
                      options: Optional[SolveOptions] = None,
                      cancel_event: Optional[threading.Event] = None) -> CalibrationSolveResult:
    """Run and collect raw results. Existing outputs are never reused or overwritten."""
    from .collect import collect_calibration

    options = SolveOptions() if options is None else options
    if not isinstance(options, SolveOptions):
        raise CalibrationError('options must be SolveOptions')
    if not isinstance(executable, str) or not executable.strip():
        raise CalibrationError('executable must be a nonempty FasterCap program name or path')
    validate_output_directory(output_dir)
    prepared = read_preparation(prepared_path)
    scenes = validated_scenes(prepared)
    solver = _solver_identity(executable)
    from ..tool_version_constraints import FASTERCAP_NUMERICAL_REPORT
    from packaging.version import Version
    numerical_reports = FASTERCAP_NUMERICAL_REPORT.is_satisfied_by(Version(solver.version))
    output = output_dir.absolute()
    cancelled = threading.Event() if cancel_event is None else cancel_event
    try:
        output.mkdir()
        written = snapshot_preparation(prepared, output / 'preparation')
        manifest = CalibrationRunManifest(schema_version=2, kpex_version=__version__, solver=solver,
                                          options=options_message(options),
                                          preparation=reference(output / 'preparation/manifest.json', output))
        jobs = []
        for record, scene in zip(prepared.manifest.cases, scenes):
            directory = output / 'cases' / record.id
            directory.mkdir(parents=True)
            case = manifest.cases.add(case_id=record.id,
                                      checkpoint_path=f'cases/{record.id}/checkpoint.pb.json',
                                      log_path=f'cases/{record.id}/solver.log',
                                      numerical_report_path=(f'cases/{record.id}/numerical-report.json'
                                                             if numerical_reports else ''))
            checkpoint = CalibrationRunCheckpoint(schema_version=1, case_id=record.id)
            checkpoint.execution.status = SolverExecution.NOT_STARTED
            try:
                inputs = _export(scene, directory / 'inputs', options)
                case.inputs.extend(reference(path, output) for path in inputs)
                written.extend(inputs)
                case.primary_input_path = next(path for path in case.inputs if path.path.endswith('.lst')).path
                jobs.append(case)
            except Exception as exc:
                checkpoint.execution.status = SolverExecution.FAILED
                checkpoint.execution.diagnostic = f"Export of case '{record.id}' failed: {exc}"
            written.append(write_message(output / case.checkpoint_path, checkpoint))
        manifest_path = write_message(output / 'manifest.json', manifest)
        written.append(manifest_path)
        pool = ThreadPoolExecutor(max_workers=options.jobs)
        interrupted = False
        try:
            futures = [pool.submit(_execute, case, manifest, output, options, cancelled) for case in jobs]
            for future in as_completed(futures):
                future.result()
        except KeyboardInterrupt:
            interrupted = True
            cancelled.set()
        finally:
            # Let queued jobs write CANCELLED checkpoints and reap all running children.
            pool.shutdown(wait=True)
        if interrupted or cancelled.is_set():
            raise CalibrationError(f'Calibration interrupted; saved runs can be collected from {manifest_path}')
        completion = CalibrationRunCompletion(schema_version=1, manifest=reference(manifest_path, output))
        completion.checkpoints.extend(reference(output / case.checkpoint_path, output) for case in manifest.cases)
        written.append(write_message(output / 'completed.pb.json', completion))
        for case in manifest.cases:
            checkpoint = read_message(output / case.checkpoint_path, CalibrationRunCheckpoint())
            if checkpoint.HasField('log'):
                written.append(output / checkpoint.log.path)
            if checkpoint.HasField('numerical_report'):
                written.append(output / checkpoint.numerical_report.path)
        collected = collect_calibration(manifest_path, output / 'collection')
        written.extend(collected.written_paths)
        return CalibrationSolveResult(manifest_path, collected.manifest_path, tuple(written),
                                      collected.successful_cases, collected.failed_cases)
    except CalibrationError:
        raise
    except OSError as exc:
        raise CalibrationError(f"Cannot write calibration solve '{output}'; evidence was retained: {exc}") from exc
