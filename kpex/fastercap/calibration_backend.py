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

"""FasterCap controls, result provenance and refinement semantics for calibration."""

from pathlib import Path
import re
from typing import Dict, List, Optional, Sequence, Tuple

from google.protobuf.any_pb2 import Any
from google.protobuf.message import DecodeError
from packaging.version import InvalidVersion, Version

from ..calibration.backend import RefinementControls
from ..calibration.validation import CalibrationError
from ..tool_version_constraints import Tool, effective_version_range
from .fastercap_error import FasterCapError
from .result_collection import collect_fastercap_matrix
from kpex_protobuf.kpex.calibration.preparation_pb2 import CalibrationCase
from kpex_protobuf.kpex.calibration.solving_pb2 import (
    CalibrationCaseResult, CalibrationRunCase, CalibrationRunCheckpoint, CalibrationRunManifest,
    CalibrationSolveOptions,
)
from kpex_protobuf.kpex.calibration.qualification_pb2 import (
    CalibrationRefinementAxis as Axis, CalibrationRefinementLevel,
)
from kpex_protobuf.kpex.fastercap.calibration_pb2 import CalibrationControls, CalibrationStatistics
from kpex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..calibration.qualification_evidence import QualificationMeasurement


def controls_message(payload: Any) -> CalibrationControls:
    message = CalibrationControls()
    try:
        if not payload.Unpack(message):
            raise CalibrationError('FasterCap run requires typed CalibrationControls')
    except DecodeError as exc:
        raise CalibrationError('Invalid FasterCap CalibrationControls payload') from exc
    return message


def statistics_message(payload: Any) -> CalibrationStatistics:
    message = CalibrationStatistics()
    if not payload.type_url and not payload.value:
        return message
    try:
        if not payload.Unpack(message):
            raise CalibrationError('FasterCap result requires typed CalibrationStatistics')
    except DecodeError as exc:
        raise CalibrationError('Invalid FasterCap CalibrationStatistics payload') from exc
    return message


def read_native_statistics(log: Path) -> Dict[str, Optional[int]]:
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


def _statistics(log: Path) -> CalibrationStatistics:
    result = CalibrationStatistics()
    for name, value in read_native_statistics(log).items():
        if value is not None and value <= 2**64 - 1:
            setattr(result, name, value)
    return result


class FasterCapCalibrationBackend:
    @classmethod
    def solver_name(cls) -> str:
        return 'fastercap'

    @classmethod
    def required_refinement_axes(cls) -> Tuple[int, ...]:
        return (Axis.LINEAR_SOLVER_TOLERANCE, Axis.INITIAL_MESH_MAX_AREA, Axis.DOMAIN_MARGIN)

    def validate_run(self, manifest: CalibrationRunManifest, *, qualification: bool):
        from ..calibration.solve import validate_options_message

        if manifest.solver.name != self.solver_name():
            raise CalibrationError('FasterCap backend received a different solver identity')
        validate_options_message(manifest.options)
        if qualification:
            try:
                version = Version(manifest.solver.version)
            except InvalidVersion as exc:
                raise CalibrationError(f"Invalid recorded FasterCap version '{manifest.solver.version}'") from exc
            supported = effective_version_range(Tool.FASTERCAP)
            if version not in supported:
                raise CalibrationError(f'Qualification requires FasterCap {supported}; the saved run used {version}')

    def collect_result(self, case: CalibrationRunCase, checkpoint: CalibrationRunCheckpoint,
                       pattern: CalibrationCase, root: Path, version: str,
                       record: CalibrationCaseResult):
        log = root / case.log_path
        try:
            report, expected_input = None, None
            if case.numerical_report_path:
                if not checkpoint.HasField('numerical_report') or not checkpoint.execution.arguments:
                    raise FasterCapError('Requested numerical report or recorded solver arguments are missing')
                report = root / case.numerical_report_path
                expected_input = checkpoint.execution.arguments[-1].removeprefix('"').removesuffix('"')
            native, measured = collect_fastercap_matrix(
                log, list(pattern.measurement.conductor_order), pattern.measurement.reference.profile,
                numerical_report=report, expected_input=expected_input, expected_version=version)
            record.native_matrix.CopyFrom(native)
            record.measured_matrix.CopyFrom(measured)
            record.status = CalibrationCaseResult.COLLECTED
        except FasterCapError as exc:
            record.status = CalibrationCaseResult.INVALID_RESULT
            record.diagnostics.append(str(exc))
        statistics = _statistics(log)
        if statistics.ListFields():
            record.solver_statistics.Pack(statistics)
        for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
            if re.match(r'^\s*(Warning|Error):', line, flags=re.IGNORECASE):
                record.diagnostics.append(line)

    def verify_result(self, log: Path, report: Path, pattern: CalibrationCase,
                      record: CalibrationCaseResult, version: str):
        expected_input = record.execution.arguments[-1].removeprefix('"').removesuffix('"')
        try:
            native, measured = collect_fastercap_matrix(
                log, list(pattern.measurement.conductor_order), pattern.measurement.reference.profile,
                numerical_report=report, expected_input=expected_input, expected_version=version)
        except FasterCapError as exc:
            raise CalibrationError(f"Cannot verify collected matrix for '{record.case_id}': {exc}") from exc
        statistics = statistics_message(record.solver_statistics)
        actual = _statistics(log)
        for field in statistics.DESCRIPTOR.fields:
            if (statistics.HasField(field.name) != actual.HasField(field.name)
                    or getattr(statistics, field.name) != getattr(actual, field.name)):
                raise CalibrationError(f"Collected {field.name} for '{record.case_id}' differs from the saved log")
        if record.native_matrix != native or record.measured_matrix != measured:
            raise CalibrationError(f"Collected matrix for '{record.case_id}' differs from the native report")

    def refinement_controls(self, measurement: 'QualificationMeasurement', axis: int) -> RefinementControls:
        fixed = CalibrationSolveOptions()
        fixed.CopyFrom(measurement.run.manifest.options)
        fixed.ClearField('jobs')
        fixed.ClearField('solver_timeout_seconds')
        scene = PEX25DScene()
        scene.CopyFrom(measurement.scene)
        controls = controls_message(fixed.solver_controls)
        independent = not controls.HasField('automatic_tolerance')
        match axis:
            case Axis.LINEAR_SOLVER_TOLERANCE:
                value = controls.gmres_tolerance
                controls.ClearField('gmres_tolerance')
            case Axis.INITIAL_MESH_MAX_AREA:
                value = controls.mesh_max_area_um2
                controls.ClearField('mesh_max_area_um2')
            case Axis.ADAPTIVE_MESH_REFINEMENT:
                value = controls.mesh_refinement
                controls.ClearField('mesh_refinement')
            case Axis.DOMAIN_MARGIN:
                value = measurement.run.preparation.domain_margin_grid
                scene.domain.ClearField('box')
                scene.domain.ClearField('applied_margin')
            case _:
                raise NotImplementedError(f'FasterCap calibration refinement axis {axis}')
        fixed.solver_controls.Pack(controls)
        return RefinementControls(value, fixed, scene, independent)

    @classmethod
    def refinement_statistics(cls, record: CalibrationCaseResult) -> Any:
        # Report only the statistics used to qualify refinement. Preserve native
        # performance counters in the collection rather than duplicating them.
        statistics = statistics_message(record.solver_statistics)
        statistics.ClearField('potential_estimates')
        statistics.ClearField('links')
        payload = Any()
        if statistics.ListFields():
            payload.Pack(statistics)
        return payload

    @classmethod
    def requires_unchanged_inputs(cls, axis: int) -> bool:
        return axis in (Axis.LINEAR_SOLVER_TOLERANCE, Axis.ADAPTIVE_MESH_REFINEMENT)

    @classmethod
    def refinement_diagnostics(cls, axis: int, levels: Sequence[CalibrationRefinementLevel]) -> List[str]:
        messages = []
        values = [level.parameter_value for level in levels]
        increasing = axis == Axis.DOMAIN_MARGIN
        if any(value <= 0 for value in values) or any(
                not (left < right if increasing else left > right) for left, right in zip(values, values[1:])):
            messages.append('Refinement controls must be positive and strictly ordered from coarse to fine')
        if axis in (Axis.INITIAL_MESH_MAX_AREA, Axis.ADAPTIVE_MESH_REFINEMENT):
            initial = axis == Axis.INITIAL_MESH_MAX_AREA
            statistics = [statistics_message(level.solver_statistics) for level in levels]
            counts = [value.input_panels if initial else value.refined_panels for value in statistics]
            if not all(counts) or any(left >= right for left, right in zip(counts, counts[1:])):
                kind = 'input' if initial else 'adaptive'
                messages.append(f'Observed {kind} panel counts must be present and strictly increase')
        return messages
