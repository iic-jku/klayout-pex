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

"""Typed calibration target declarations and their proven technology-table bindings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
import math
from typing import Iterable, List, Tuple, TYPE_CHECKING

from .validation import CalibrationError, validate_identifier
from klayout_pex_protobuf.kpex.calibration.patterns_pb2 import CalibrationPatternFamily
from klayout_pex_protobuf.kpex.calibration.targets_pb2 import (
    CalibrationTarget, LayerProfileBinding, SubstrateTarget, SidewallTarget,
)

if TYPE_CHECKING:
    from .patterns import CalibrationPatternCase
    from ..tech_info import TechInfo


class CalibrationTargetKind(Enum):
    SUBSTRATE = auto()
    OVERLAP = auto()
    SIDEWALL = auto()
    SIDEOVERLAP = auto()


@dataclass(frozen=True)
class CalibrationTargetSpec:
    definition: CalibrationTarget
    kind: CalibrationTargetKind
    bindings: Tuple[LayerProfileBinding, ...]

    @property
    def target_id(self) -> str:
        return self.definition.id

    @property
    def row_key(self) -> Tuple[CalibrationTargetKind, Tuple[str, ...]]:
        return self.kind, tuple(binding.canonical_layer for binding in self.bindings)


def read_targets(declarations: Iterable[CalibrationTarget]) -> Tuple[CalibrationTargetSpec, ...]:
    targets: List[CalibrationTargetSpec] = []
    identifiers = set()
    rows = set()
    for index, target in enumerate(declarations):
        where = f'targets[{index}]'
        validate_identifier(target.id, where + '.id')
        if target.id.casefold() in identifiers:
            raise CalibrationError(f"{where}.id repeats '{target.id}' ignoring case")
        identifiers.add(target.id.casefold())
        # Field-name reflection stays at the input boundary. Runtime dispatch is typed.
        if target.HasField('substrate'):
            kind = CalibrationTargetKind.SUBSTRATE
            bindings = (target.substrate.layer,)
            parameters = tuple(target.substrate.parameters)
            valid = (SubstrateTarget.AREA, SubstrateTarget.PERIMETER)
        elif target.HasField('overlap'):
            kind = CalibrationTargetKind.OVERLAP
            bindings = (target.overlap.top, target.overlap.bottom)
            parameters, valid = (), ()
        elif target.HasField('sidewall'):
            kind = CalibrationTargetKind.SIDEWALL
            bindings = (target.sidewall.layer,)
            parameters = tuple(target.sidewall.parameters)
            valid = (SidewallTarget.COEFFICIENT, SidewallTarget.OFFSET)
        elif target.HasField('sideoverlap'):
            kind = CalibrationTargetKind.SIDEOVERLAP
            bindings = (target.sideoverlap.edge, target.sideoverlap.receiver)
            parameters, valid = (), ()
        else:
            raise CalibrationError(f'{where} must select substrate, overlap, sidewall or sideoverlap')
        if valid and (not parameters or len(set(parameters)) != len(parameters)
                      or any(parameter not in valid for parameter in parameters)):
            options = 'AREA, PERIMETER' if kind == CalibrationTargetKind.SUBSTRATE else 'COEFFICIENT, OFFSET'
            raise CalibrationError(f'{where}.parameters must select unique values from {options}')
        if any(not binding.canonical_layer or not binding.process_profile for binding in bindings):
            raise CalibrationError(f'{where} needs nonempty canonical_layer and process_profile bindings')
        if len(bindings) == 2 and (bindings[0].canonical_layer == bindings[1].canonical_layer
                                  or bindings[0].process_profile == bindings[1].process_profile):
            raise CalibrationError(f'{where} needs two distinct canonical layers and process profiles')
        normalized = CalibrationTargetSpec(target, kind, bindings)
        if normalized.row_key in rows:
            raise CalibrationError(f'{where} duplicates a canonical table row; combine its selected parameters in one target')
        rows.add(normalized.row_key)
        targets.append(normalized)
    return tuple(targets)


def validate_case_targets(case: CalibrationPatternCase, targets: Tuple[CalibrationTargetSpec, ...]):
    by_id = {target.target_id: target for target in targets}
    if len(set(case.target_ids)) != len(case.target_ids):
        raise CalibrationError(f"Pattern '{case.case_id}' repeats a target ID")
    for target_id in case.target_ids:
        target = by_id.get(target_id)
        if target is None:
            raise CalibrationError(f"Pattern '{case.case_id}' names unknown target '{target_id}'; "
                                   f"valid targets: {', '.join(sorted(by_id)) or 'none'}")
        profiles = tuple(binding.process_profile for binding in target.bindings)
        match target.kind:
            case CalibrationTargetKind.SUBSTRATE:
                matches = profiles[0] in case.layers
            case CalibrationTargetKind.OVERLAP:
                matches = case.family in (CalibrationPatternFamily.PARALLEL_PLATES,
                                          CalibrationPatternFamily.DIRECTIONAL_FRINGE) and set(profiles) == set(case.layers)
            case CalibrationTargetKind.SIDEWALL:
                matches = case.family == CalibrationPatternFamily.PARALLEL_WIRES and profiles[0] == case.layers[0]
            case CalibrationTargetKind.SIDEOVERLAP:
                matches = ((case.family == CalibrationPatternFamily.DIRECTIONAL_FRINGE and profiles == case.layers)
                           or (case.family == CalibrationPatternFamily.PARALLEL_PLATES and set(profiles) == set(case.layers)))
            case _:
                raise NotImplementedError(f'Pattern binding for target kind {target.kind} is not implemented')
        if not matches:
            raise CalibrationError(f"Pattern '{case.case_id}' does not match target '{target_id}' profiles or direction")


def validate_target_rows(tech_info: TechInfo, targets: Tuple[CalibrationTargetSpec, ...]):
    if not targets:
        return
    # Reuse the technology's GDS-checked explicit mapping; equal spelling is not proof.
    process_by_lvs = tech_info.process_layer_name_by_lvs_layer_name
    valid_bindings = {(layer.original_layer_name, process_by_lvs[layer.layer_info.name])
                      for layer in tech_info.tech.lvs_computed_layers
                      if layer.layer_info.name in process_by_lvs}
    profiles = {layer.name: layer for layer in tech_info.process_metal_layers}
    canonical_layers = {layer.name for layer in tech_info.tech.layers}
    tables = tech_info.tech.process_parasitics.capacitance
    for target in targets:
        for binding in target.bindings:
            if (binding.canonical_layer not in canonical_layers
                    or (binding.canonical_layer, binding.process_profile) not in valid_bindings):
                raise CalibrationError(f"Target '{target.target_id}' has no explicit validated mapping from "
                                       f"canonical layer '{binding.canonical_layer}' to profile '{binding.process_profile}'")
            if binding.process_profile not in profiles:
                raise CalibrationError(f"Target '{target.target_id}' requires a supported metal profile '{binding.process_profile}'")
        names = tuple(binding.canonical_layer for binding in target.bindings)
        match target.kind:
            case CalibrationTargetKind.SUBSTRATE:
                rows = [row for row in tables.substrates if row.layer_name == names[0]]
                values = [value for row in rows for value in (row.area_capacitance, row.perimeter_capacitance)]
            case CalibrationTargetKind.OVERLAP:
                rows = [row for row in tables.overlaps if (row.top_layer_name, row.bottom_layer_name) == names]
                values = [row.capacitance for row in rows]
                top, bottom = (profiles[binding.process_profile].metal_layer for binding in target.bindings)
                if top.z <= bottom.z + bottom.thickness:
                    raise CalibrationError(f"Target '{target.target_id}' needs top strictly above bottom with a nonzero dielectric gap")
            case CalibrationTargetKind.SIDEWALL:
                rows = [row for row in tables.sidewalls if row.layer_name == names[0]]
                values = [row.capacitance for row in rows]
                if any(not math.isfinite(row.offset) for row in rows):
                    raise CalibrationError(f"Target '{target.target_id}' has a nonfinite sidewall offset")
            case CalibrationTargetKind.SIDEOVERLAP:
                rows = [row for row in tables.sideoverlaps if (row.in_layer_name, row.out_layer_name) == names]
                values = [row.capacitance for row in rows]
            case _:
                raise NotImplementedError(f'Technology row resolution for target kind {target.kind} is not implemented')
        if len(rows) != 1:
            raise CalibrationError(f"Target '{target.target_id}' must resolve exactly one actual capacitance table row; found {len(rows)}")
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise CalibrationError(f"Target '{target.target_id}' has invalid capacitance coefficients")
