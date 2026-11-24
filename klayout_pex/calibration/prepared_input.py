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

"""Validate the merged preparation contract before solver execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import List, TYPE_CHECKING

from .artifacts import artifact_path, read_message, sha256_file, verify_artifacts
from .validation import CalibrationError

if TYPE_CHECKING:
    from .patterns import CalibrationPatternSpec
    from klayout_pex_protobuf.kpex.calibration.preparation_pb2 import CalibrationManifest
    from klayout_pex_protobuf.kpex.tech.tech_pb2 import Technology
    from klayout_pex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene


@dataclass(frozen=True)
class PreparedInput:
    path: Path
    sha256: str
    manifest: CalibrationManifest
    specification: CalibrationPatternSpec
    technology: Technology


def read_preparation(path: Path) -> PreparedInput:
    from .patterns import read_patterns
    from ..tech_identity import message_sha256
    from klayout_pex_protobuf.kpex.calibration.preparation_pb2 import CalibrationManifest, CalibrationCase
    from klayout_pex_protobuf.kpex.calibration.preparation_pb2 import CapacitanceMeasurement as Measurement
    from klayout_pex_protobuf.kpex.calibration.patterns_pb2 import SUBSTRATE
    from klayout_pex_protobuf.kpex.pex25d.pex25d_units_pb2 import Units
    from klayout_pex_protobuf.kpex.tech.tech_pb2 import Technology

    digest = sha256_file(path)
    manifest = read_message(path, CalibrationManifest())
    if (manifest.schema_version != 1 or manifest.pattern_generator_version != 1
            or manifest.stage != CalibrationManifest.PREPARED or not manifest.kpex_version):
        raise CalibrationError('Unsupported preparation version or stage')
    verify_artifacts(path.parent, manifest.artifacts)
    spec = read_patterns(artifact_path(path.parent, 'patterns.json'))
    tech = read_message(artifact_path(path.parent, 'technology.pb.json'), Technology())
    if (manifest.source_specification_sha256 != spec.source_sha256
            or manifest.technology.name != tech.name
            or manifest.technology.resolved_technology_sha256 != message_sha256(tech)
            or manifest.technology.physical_stack_sha256 != message_sha256(tech.process_stack)):
        raise CalibrationError('Preparation source or technology identity differs from its snapshot')
    if manifest.technology.HasField('selection'):
        selection = manifest.technology.selection
        if (selection.technology_id != tech.name or not selection.scenario_id
                or selection.resolved_technology_sha256 != manifest.technology.resolved_technology_sha256
                or not selection.physical_stack_matches
                or re.fullmatch(r'[0-9a-f]{64}', selection.catalog_sha256) is None):
            raise CalibrationError('Preparation catalog selection differs from its resolved technology')
    if (manifest.units != Units(length=Units.LENGTH_UNIT_UM, grid_numerator=spec.grid.numerator,
                                grid_denominator=spec.grid.denominator)
            or manifest.domain_margin_grid != spec.domain_margin
            or list(manifest.targets) != [target.definition for target in spec.targets]
            or manifest.fringe_scale_mode != spec.fringe_scale_mode
            or manifest.technology_side_halo_um != tech.process_parasitics.side_halo):
        raise CalibrationError('Preparation units, targets, halo or fringe scale differ from its source')
    if len(manifest.cases) != len(spec.patterns):
        raise CalibrationError('Preparation case count differs from its source')
    expected_paths = {'patterns.json', 'technology.pb.json'}
    for case, pattern in zip(manifest.cases, spec.patterns):
        expected = CalibrationCase(id=pattern.case_id, family=pattern.family, role=pattern.role,
                                   layers=pattern.layers, target_ids=pattern.target_ids,
                                   file=f'case_{pattern.case_id}.pex25d',
                                   scene=f'case_{pattern.case_id}.pex25d.scene.pb')
        expected.dimensions_grid.CopyFrom(type(case.dimensions_grid)(
            width=pattern.width, length=pattern.length, gap=pattern.gap,
            receiver_width=pattern.receiver_width, lateral_offset=pattern.lateral_offset))
        expected.measurement.CopyFrom(Measurement(
            kind=Measurement.MAXWELL_CAPACITANCE_MATRIX,
            conductor_order=['A'] if pattern.family == SUBSTRATE else ['A', 'B'],
            capacitance_unit=Measurement.FARAD, convention=Measurement.MAXWELL_GROUNDED_UNEXCITED))
        reference = case.measurement.reference.profile
        if not reference or reference in expected.measurement.conductor_order:
            raise CalibrationError('Preparation needs a distinct finite reference conductor')
        expected.measurement.reference.profile = reference
        expected.diagnostics.extend(case.diagnostics)
        if case != expected:
            raise CalibrationError(f"Prepared case '{case.id}' differs from its specification")
        expected_paths.update((case.file, case.scene))
    if {record.path for record in manifest.artifacts} != expected_paths:
        raise CalibrationError('Preparation artifact set differs from its specification')
    if sha256_file(path) != digest:
        raise CalibrationError('Preparation changed while being read')
    return PreparedInput(path.resolve(), digest, manifest, spec, tech)


def validated_scenes(prepared: PreparedInput) -> List[PEX25DScene]:
    from .prepare import _case_file, _resolve_case, _stack
    from .. import pex25d
    from ..tech_info import TechInfo

    try:
        from .targets import validate_target_rows
        tech = TechInfo(prepared.technology, dielectric_filter=None)
        validate_target_rows(tech, prepared.specification.targets)
        stack = _stack(tech, prepared.specification)
        scenes = []
        for case, pattern in zip(prepared.manifest.cases, prepared.specification.patterns):
            file = pex25d.read(str(artifact_path(prepared.path.parent, case.file)))
            scene = pex25d.read(str(artifact_path(prepared.path.parent, case.scene)))
            expected, _ = _resolve_case(_case_file(stack, pattern), pattern)
            resolved, _ = _resolve_case(file, pattern)
            for message in (scene, expected, resolved):
                message.ClearField('metadata')
            if scene != expected or scene != resolved or scene.ground_plane.name != case.measurement.reference.profile:
                raise CalibrationError(f"Prepared case '{case.id}' geometry differs from its specification")
            scenes.append(scene)
        return scenes
    except CalibrationError:
        raise
    except Exception as exc:
        raise CalibrationError(f'Cannot validate prepared geometry: {exc}') from exc
