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

"""Prepare inspectable finite 3D calibration cases; no reference solve or fit is implied."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple, TYPE_CHECKING

from google.protobuf.json_format import MessageToJson
from google.protobuf.message import Message

from .patterns import CalibrationError, CalibrationPatternCase, CalibrationPatternSpec
from .targets import validate_target_rows
from ..klayout.native_coordinates import is_supported_native_coordinate
from ..klayout.pex25d_stack import BuilderOptions, build_pex25d_stack
from ..pex25d.artifact import ArtifactFormat, ArtifactKind, derive_path
from ..pex25d.diagnostics import DiagnosticsReport
from ..pex25d.protobuf import pex25d_file_pb2
from ..pex25d.resolver import ResolveError, resolve
from ..pex25d.validator import validate
from ..pex25d.writer import format_exact, write_pex25d_text
from ..tech_identity import message_sha256
from ..version import __version__
from kpex_protobuf.kpex.calibration.patterns_pb2 import CalibrationPatternFamily
from kpex_protobuf.kpex.calibration.preparation_pb2 import (
    CapacitanceMeasurement, CalibrationManifest, CalibratedTechnology,
)
from kpex_protobuf.kpex.pex25d.pex25d_units_pb2 import Units


if TYPE_CHECKING:
    from ..tech_info import TechInfo


@dataclass(frozen=True)
class CalibrationPreparationResult:
    manifest_path: Path
    written_paths: Tuple[Path, ...]


def _json_bytes(message: Message) -> bytes:
    return (MessageToJson(message, preserving_proto_field_name=True, sort_keys=True,
                          ensure_ascii=False, always_print_fields_with_no_presence=True) + '\n').encode('utf-8')


def _stack(tech_info: TechInfo, spec: CalibrationPatternSpec) -> Any:
    profiles = {layer.name: layer for layer in tech_info.process_metal_layers}
    names = set(profiles)
    for case in spec.patterns:
        for name in case.layers:
            if name not in names:
                raise CalibrationError(f"Pattern '{case.case_id}' names unknown metal profile '{name}'; "
                                       f"valid profiles: {', '.join(sorted(names))}")
            if profiles[name].metal_layer.physical_geometry_unavailable:
                raise CalibrationError(f"Pattern '{case.case_id}' has no supported physical geometry for '{name}'")
    selection = getattr(tech_info, 'selection', None)
    if selection is not None:
        selection.require_physical_stack(tech_info.tech.process_stack)
    stack = build_pex25d_stack(tech_info, BuilderOptions(
        grid_um=format_exact(spec.grid), include_resistance=False,
        process_corner=selection.scenario_id if selection is not None else None))
    # A calibration scene with a silently dropped film would fit the wrong physical stack.
    expected = {layer.name for layer in tech_info.filterable_dielectric_layers}
    expected.add(tech_info.field_oxide_layer.name)
    represented = {layer.name for layer in stack.dielectrics} | {stack.background.name}
    omitted = sorted(expected - represented)
    if omitted:
        raise CalibrationError('Calibration needs the complete physical stack; omitted dielectrics: '
                               + ', '.join(omitted))
    stack.domain_margin.x = stack.domain_margin.y = stack.domain_margin.z = spec.domain_margin
    return stack


def _case_file(stack: Any, case: CalibrationPatternCase) -> Any:
    file = pex25d_file_pb2().PEX25DFile()
    file.CopyFrom(stack)
    metals = {layer.name: layer for layer in file.metals}
    if case.family == CalibrationPatternFamily.PARALLEL_PLATES:
        below, above = (metals[name] for name in case.layers)
        if below.zhigh >= above.zlow:
            raise CalibrationError(f"Pattern '{case.case_id}' needs lower_layer strictly below upper_layer "
                                   'with a nonzero dielectric gap')
    if case.family == CalibrationPatternFamily.DIRECTIONAL_FRINGE:
        edge, receiver = (metals[name] for name in case.layers)
        if not (edge.zhigh < receiver.zlow or receiver.zhigh < edge.zlow):
            raise CalibrationError(f"Pattern '{case.case_id}' needs distinct vertical profiles with a nonzero dielectric gap")
    for index, (conductor, layer) in enumerate(zip(('A', 'B'), case.layers)):
        file.conductors.add(name=conductor, net=conductor)
        shape = file.shapes.add(conductor=conductor, layer=layer,
                                kind=pex25d_file_pb2().ShapeRecord.SHAPE_KIND_BOX)
        match case.family:
            case CalibrationPatternFamily.PARALLEL_WIRES:
                xlow = index * (case.width + case.gap)
            case CalibrationPatternFamily.PARALLEL_PLATES | CalibrationPatternFamily.SUBSTRATE:
                xlow = 0
            case CalibrationPatternFamily.DIRECTIONAL_FRINGE:
                xlow = 0 if index == 0 else case.width + case.lateral_offset
            case _:
                raise NotImplementedError(f'Calibration geometry for pattern family {case.family} is not implemented')
        width = case.receiver_width if case.family == CalibrationPatternFamily.DIRECTIONAL_FRINGE and index == 1 else case.width
        shape.box.lower_left.x, shape.box.lower_left.y = xlow, 0
        shape.box.upper_right.x, shape.box.upper_right.y = xlow + width, case.length
    return file


def _resolve_case(file: Any, case: CalibrationPatternCase) -> Tuple[Any, DiagnosticsReport]:
    report = DiagnosticsReport()
    try:
        scene = resolve(file, report=report)
    except ResolveError as exc:
        detail = '\n'.join(d.message for d in report.diagnostics)
        exc.add_note(f"Pattern '{case.case_id}': {detail}")
        raise
    # The protobuf uses int64, but strict geometric validation and downstream exporters use KLayout XY.
    box = scene.domain.box
    if any(not is_supported_native_coordinate(value) for value in
           (box.lower_left.x, box.lower_left.y, box.upper_right.x, box.upper_right.y)):
        raise CalibrationError(f"Pattern '{case.case_id}' with coatings and margin exceeds "
                               'the supported native XY coordinate range')
    validate(file, scene=scene, report=report, strict=True)
    if report.num_errors:
        detail = '\n'.join(d.message for d in report.diagnostics)
        raise CalibrationError(f"Invalid calibration pattern '{case.case_id}': {detail}")
    return scene, report


def validate_output_directory(output_dir: Path):
    """Refuse existing outputs before expensive preparation or technology loading."""
    if output_dir.exists() or output_dir.is_symlink():
        raise CalibrationError(f"Output path '{output_dir}' already exists; choose a new directory")
    if not output_dir.parent.is_dir():
        raise CalibrationError(f"Output parent '{output_dir.parent}' must be an existing directory")


def prepare_calibration(tech_info: TechInfo, spec: CalibrationPatternSpec, output_dir: Path) -> CalibrationPreparationResult:
    """Validate all cases, then create a new directory and write its manifest last.

    Existing paths are never reused, including empty directories and broken symlinks.
    Returned paths are exactly those written by this invocation.
    """
    validate_output_directory(output_dir)
    validate_target_rows(tech_info, spec.targets)
    halo = tech_info.tech.process_parasitics.side_halo
    if not math.isfinite(halo) or halo <= 0:
        raise CalibrationError('The selected technology side_halo must be positive and finite')
    stack = _stack(tech_info, spec)
    outputs: Dict[str, bytes] = {
        'patterns.json': spec.source,
        'technology.pb.json': _json_bytes(tech_info.tech),
    }
    manifest = CalibrationManifest(
        schema_version=1, pattern_generator_version=1, stage=CalibrationManifest.PREPARED,
        kpex_version=__version__,
        technology=CalibratedTechnology(name=tech_info.tech.name,
                                      resolved_technology_sha256=message_sha256(tech_info.tech),
                                      physical_stack_sha256=message_sha256(tech_info.tech.process_stack)),
        source_specification_sha256=spec.source_sha256,
        units=Units(length=Units.LENGTH_UNIT_UM, grid_numerator=spec.grid.numerator,
                    grid_denominator=spec.grid.denominator),
        domain_margin_grid=spec.domain_margin,
        targets=[target.definition for target in spec.targets],
        technology_side_halo_um=halo, fringe_scale_mode=spec.fringe_scale_mode)
    for case in spec.patterns:
        file = _case_file(stack, case)
        scene, report = _resolve_case(file, case)
        stem = 'case_' + case.case_id
        file_path = stem + '.pex25d'
        scene_path = derive_path(file_path, ArtifactKind.SCENE, ArtifactFormat.PB)
        outputs[file_path] = write_pex25d_text(file)
        outputs[scene_path] = scene.SerializeToString(deterministic=True)
        record = manifest.cases.add(id=case.case_id, family=case.family, role=case.role,
                                    layers=case.layers, file=file_path, scene=scene_path, target_ids=case.target_ids)
        record.dimensions_grid.width = case.width
        record.dimensions_grid.length = case.length
        record.dimensions_grid.gap = case.gap
        record.dimensions_grid.receiver_width = case.receiver_width
        record.dimensions_grid.lateral_offset = case.lateral_offset
        record.measurement.kind = CapacitanceMeasurement.MAXWELL_CAPACITANCE_MATRIX
        record.measurement.conductor_order.extend(conductor.name for conductor in file.conductors)
        record.measurement.reference.profile = file.ground_plane.name
        record.measurement.reference.potential_v = 0
        record.measurement.capacitance_unit = CapacitanceMeasurement.FARAD
        record.measurement.convention = CapacitanceMeasurement.MAXWELL_GROUNDED_UNEXCITED
        record.measurement.exterior_boundary_condition = CapacitanceMeasurement.EXTERIOR_UNSPECIFIED
        record.diagnostics.extend(diagnostic.to_proto() for diagnostic in report.diagnostics)
    for name, data in outputs.items():
        manifest.artifacts.add(path=name, sha256=hashlib.sha256(data).hexdigest())
    selection = getattr(tech_info, 'selection', None)
    if selection is not None:
        manifest.technology.selection.CopyFrom(selection.to_proto())
    outputs['manifest.json'] = _json_bytes(manifest)
    written: List[Path] = []
    created = False
    try:
        output_dir.mkdir()
        created = True
        for name, data in outputs.items():
            path = output_dir / name
            with path.open('xb') as stream:
                written.append(path)
                stream.write(data)
    except OSError as exc:
        # Remove only our exact files. Concurrent unrelated work prevents rmdir and is preserved.
        for path in reversed(written):
            try:
                path.unlink()
            except OSError:
                pass
        if created:
            try:
                output_dir.rmdir()
            except OSError:
                pass
        raise CalibrationError(f"Cannot write prepared calibration '{output_dir}': {exc}") from exc
    return CalibrationPreparationResult(output_dir / 'manifest.json', tuple(written))
