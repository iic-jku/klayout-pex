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

"""Prepare inspectable finite 3D calibration cases; no reference solve or fit is implied."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple, TYPE_CHECKING

from google.protobuf.json_format import MessageToDict

from .patterns import CalibrationError, MAX_COORDINATE, PatternCase, PatternSpec
from ..klayout.pex25d_stack import BuilderOptions, build_pex25d_stack
from ..pex25d.artifact import ArtifactFormat, ArtifactKind, derive_path
from ..pex25d.diagnostics import DiagnosticsReport
from ..pex25d.protobuf import pex25d_file_pb2
from ..pex25d.resolver import ResolveError, resolve
from ..pex25d.validator import validate
from ..pex25d.writer import format_exact, write_pex25d_text
from ..tech_identity import message_sha256
from ..version import __version__

if TYPE_CHECKING:
    from ..tech_info import TechInfo


@dataclass(frozen=True)
class PreparedCalibration:
    manifest_path: Path
    written_paths: Tuple[Path, ...]


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def _stack(tech_info: TechInfo, spec: PatternSpec) -> Any:
    names = {layer.name for layer in tech_info.process_metal_layers}
    for case in spec.cases:
        for name in case.layers:
            if name not in names:
                raise CalibrationError(f"Pattern '{case.case_id}' names unknown metal profile '{name}'; "
                                       f"valid profiles: {', '.join(sorted(names))}")
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


def _case_file(stack: Any, case: PatternCase) -> Any:
    file = pex25d_file_pb2().PEX25DFile()
    file.CopyFrom(stack)
    metals = {layer.name: layer for layer in file.metals}
    if case.family == 'parallel_plates':
        below, above = (metals[name] for name in case.layers)
        if below.zhigh >= above.zlow:
            raise CalibrationError(f"Pattern '{case.case_id}' needs lower_layer strictly below upper_layer "
                                   'with a nonzero dielectric gap')
    for index, (conductor, layer) in enumerate(zip(('A', 'B'), case.layers)):
        file.conductors.add(name=conductor, net=conductor)
        shape = file.shapes.add(conductor=conductor, layer=layer,
                                kind=pex25d_file_pb2().ShapeRecord.SHAPE_KIND_BOX)
        xlow = index * (case.width + case.gap) if case.family == 'parallel_wires' else 0
        shape.box.lower_left.x, shape.box.lower_left.y = xlow, 0
        shape.box.upper_right.x, shape.box.upper_right.y = xlow + case.width, case.length
    return file


def _resolve_case(file: Any, case: PatternCase) -> Tuple[Any, DiagnosticsReport]:
    report = DiagnosticsReport()
    try:
        scene = resolve(file, report=report)
    except ResolveError as exc:
        detail = '\n'.join(d.message for d in report.diagnostics)
        exc.add_note(f"Pattern '{case.case_id}': {detail}")
        raise
    # The protobuf uses int64, but strict geometric validation and downstream exporters use KLayout XY.
    box = scene.domain.box
    if any(abs(value) > MAX_COORDINATE for value in
           (box.lower_left.x, box.lower_left.y, box.upper_right.x, box.upper_right.y)):
        raise CalibrationError(f"Pattern '{case.case_id}' with coatings and margin exceeds "
                               f'{MAX_COORDINATE} XY grid units')
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


def prepare_calibration(tech_info: TechInfo, spec: PatternSpec, output_dir: Path) -> PreparedCalibration:
    """Validate all cases, then create a new directory and write its manifest last.

    Existing paths are never reused, including empty directories and broken symlinks.
    Returned paths are exactly those written by this invocation.
    """
    validate_output_directory(output_dir)
    stack = _stack(tech_info, spec)
    outputs: Dict[str, bytes] = {
        'patterns.json': spec.source,
        'technology.pb.json': _json_bytes(MessageToDict(tech_info.tech, preserving_proto_field_name=True)),
    }
    records: List[Dict[str, Any]] = []
    for case in spec.cases:
        file = _case_file(stack, case)
        scene, report = _resolve_case(file, case)
        stem = 'case_' + case.case_id
        file_path = stem + '.pex25d'
        scene_path = derive_path(file_path, ArtifactKind.SCENE, ArtifactFormat.PB)
        outputs[file_path] = write_pex25d_text(file)
        outputs[scene_path] = scene.SerializeToString(deterministic=True)
        records.append({
            'id': case.case_id,
            'family': case.family,
            'role': case.role,
            'layers': list(case.layers),
            'dimensions_grid': {'width': case.width, 'length': case.length, 'gap': case.gap},
            'file': file_path,
            'scene': scene_path,
            'measurement': {
                'kind': 'maxwell_capacitance_matrix',
                'conductor_order': ['A', 'B'],
                'reference': {'kind': 'ground_plane', 'profile': file.ground_plane.name, 'potential_V': 0},
                'floating_conductors': [],
                'capacitance_unit': 'F',
                'convention': 'Q_i = sum_j C_ij V_j; unexcited conductors held at 0 V',
                'exterior_boundary_condition': 'unspecified',
            },
            'diagnostics': [diagnostic.as_json_dict() for diagnostic in report.diagnostics],
        })
    manifest = {
        'schema_version': 1,
        'pattern_generator_version': 1,
        'stage': 'prepared',
        'reference_solutions': [],
        'fitted_coefficients': None,
        'kpex_version': __version__,
        'technology': {
            'name': tech_info.tech.name,
            'resolved_technology_sha256': message_sha256(tech_info.tech),
            'physical_stack_sha256': message_sha256(tech_info.tech.process_stack),
        },
        'source_specification_sha256': spec.source_sha256,
        'units': {'length': 'um', 'grid_numerator': spec.grid.numerator,
                  'grid_denominator': spec.grid.denominator},
        'domain_margin_grid': spec.domain_margin,
        'cases': records,
        'artifacts': [{'path': name, 'sha256': hashlib.sha256(data).hexdigest()}
                      for name, data in outputs.items()],
    }
    selection = getattr(tech_info, 'selection', None)
    if selection is not None:
        manifest['technology']['selection'] = selection.to_json()
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
    return PreparedCalibration(output_dir / 'manifest.json', tuple(written))
