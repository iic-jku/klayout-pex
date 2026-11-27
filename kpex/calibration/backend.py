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

"""Internal calibration backend selection and refinement evidence contract."""

from dataclasses import dataclass
from typing import List, Protocol, Sequence, Tuple, TYPE_CHECKING

from .validation import CalibrationError

if TYPE_CHECKING:
    from pathlib import Path
    from google.protobuf.any_pb2 import Any
    from kpex_protobuf.kpex.calibration.preparation_pb2 import CalibrationCase
    from kpex_protobuf.kpex.calibration.qualification_pb2 import CalibrationRefinementLevel
    from kpex_protobuf.kpex.calibration.solving_pb2 import (
        CalibrationCaseResult, CalibrationRunCase, CalibrationRunCheckpoint,
        CalibrationRunManifest, CalibrationSolveOptions,
    )
    from kpex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene
    from .qualification_evidence import QualificationMeasurement


@dataclass(frozen=True)
class RefinementControls:
    parameter_value: float
    fixed: 'CalibrationSolveOptions'
    scene: 'PEX25DScene'
    independently_controlled: bool


class CalibrationBackend(Protocol):
    """Backend semantics used by collection and numerical qualification."""

    def supported_refinement_axes(self) -> Tuple[int, ...]: ...
    def required_refinement_axes(self) -> Tuple[int, ...]: ...
    def validate_run(self, manifest: 'CalibrationRunManifest', *, qualification: bool): ...
    def collect_result(self, case: 'CalibrationRunCase', checkpoint: 'CalibrationRunCheckpoint',
                       pattern: 'CalibrationCase', root: 'Path', version: str,
                       record: 'CalibrationCaseResult'): ...
    def verify_result(self, log: 'Path', report: 'Path', pattern: 'CalibrationCase',
                      record: 'CalibrationCaseResult', version: str): ...
    def refinement_controls(self, measurement: 'QualificationMeasurement', axis: int) -> RefinementControls: ...
    def refinement_statistics(self, record: 'CalibrationCaseResult') -> 'Any': ...
    def requires_unchanged_inputs(self, axis: int) -> bool: ...
    def refinement_diagnostics(self, axis: int, levels: Sequence['CalibrationRefinementLevel']) -> List[str]: ...


def calibration_backend(name: str) -> CalibrationBackend:
    # This is the implemented calibration backend, not a new plugin discovery API.
    from ..fastercap.calibration_backend import FasterCapCalibrationBackend

    if name == FasterCapCalibrationBackend.solver_name():
        return FasterCapCalibrationBackend()
    raise CalibrationError(f"Unsupported calibration solver '{name}'; supported: fastercap")
