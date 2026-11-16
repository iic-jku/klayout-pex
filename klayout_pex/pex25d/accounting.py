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

"""Electrical identity and result accounting for a resolved physical scene."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional
import json

from ..common.capacitance_matrix import CapacitanceMatrix, aggregate_capacitance_matrix
from .electrical import BodyKind, ElectricalBody, conductor_body, ground_body, solver_body_names
from .protobuf import pex25d_capacitance_accounting_pb2


@dataclass(frozen=True)
class AccountingPart:
    body: ElectricalBody
    regions: FrozenSet[str] = frozenset()
    layer: Optional[str] = None
    is_reference: bool = False


class SceneCapacitanceMap:
    """Map solver charge groups back to bodies without losing exclusion scope."""

    def __init__(self, scene: Any):
        from .capability_validation import validate_required_capabilities
        from .accounting_validation import validate_capacitance_accounting
        from .diagnostics import DiagnosticsReport
        report = DiagnosticsReport()
        if not validate_required_capabilities(scene, report) or not validate_capacitance_accounting(scene, report):
            raise ValueError('Invalid scene accounting: ' + '; '.join(d.message for d in report.diagnostics))
        self.scene = scene
        self.body_names = solver_body_names(scene)
        self.policy = scene.capacitance_accounting
        self.active = scene.HasField('capacitance_accounting')
        self.parts: Dict[str, AccountingPart] = {}
        self.names: Dict[AccountingPart, str] = {}
        self.region_names: Dict[str, str] = {}
        self.region_indexes = {r.name: i for i, r in enumerate(self.policy.regions)}
        kinds = pex25d_capacitance_accounting_pb2().CapacitanceExclusion
        self.layer_sensitive_regions = {rule.region for rule in self.policy.exclusions
                                        if rule.kind == kinds.KIND_LAYER_PAIR}
        for conductor in scene.conductors:
            body = conductor_body(conductor)
            for region in conductor.regions:
                memberships = frozenset(region.accounting_regions)
                layer = region.layer if memberships & self.layer_sensitive_regions else None
                part = AccountingPart(body, memberships, layer)
                name = self.name_of(part)
                if region.accounting_part_id:
                    self.region_names[region.accounting_part_id] = name
        self.reference_name: Optional[str] = None
        if scene.HasField('ground_plane'):
            self.reference_name = self.name_of(AccountingPart(ground_body(scene), is_reference=self.active))

    def name_of(self, part: AccountingPart) -> str:
        if part in self.names:
            return self.names[part]
        base = self.body_names[part.body]
        if part.is_reference:
            candidate = base + '#substrate'
        elif part.regions:
            candidate = base + '#x' + '_'.join(str(self.region_indexes[r]) for r in sorted(part.regions))
            if part.layer is not None:
                # Profile names are identifiers; output filenames must not gain path separators.
                from urllib.parse import quote
                candidate += '_' + quote(part.layer, safe='._-$[]')
        else:
            candidate = base
        plain = not part.regions and not part.is_reference
        while candidate in self.parts or (not plain and candidate in self.body_names.values()):
            candidate += '#'
        self.parts[candidate] = part
        self.names[part] = candidate
        return candidate

    def conductor_name(self, conductor: Any, region: Any) -> str:
        if region.accounting_part_id:
            return self.region_names[region.accounting_part_id]
        return self.names[AccountingPart(conductor_body(conductor))]

    def leaves_out_reference(self, part: AccountingPart) -> bool:
        if part.is_reference:
            return False
        if part.body.kind == BodyKind.NET and part.body.name in self.policy.excluded_substrate_nets:
            return True
        ground_layer = self.scene.ground_plane.name
        return any(self.applies(rule, part.layer, ground_layer)
                   for rule in self.policy.exclusions if rule.region in part.regions)

    @staticmethod
    def applies(rule: Any, first: Optional[str], second: Optional[str]) -> bool:
        kinds = pex25d_capacitance_accounting_pb2().CapacitanceExclusion
        match rule.kind:
            case kinds.KIND_ALL_LAYER_PAIRS:
                return True
            case kinds.KIND_LAYER_PAIR:
                return {first, second} == {rule.layer_a, rule.layer_b}
            case _:
                raise NotImplementedError(f'Capacitance exclusion kind {rule.kind} is not implemented')

    def leaves_out_pair(self, first: AccountingPart, second: AccountingPart) -> bool:
        if first.is_reference or second.is_reference:
            return self.leaves_out_reference(second if first.is_reference else first)
        shared = first.regions & second.regions
        return any(self.applies(rule, first.layer, second.layer)
                   for rule in self.policy.exclusions if rule.region in shared)

    def matrix_of_bodies(self, matrix: CapacitanceMatrix, labels: List[str],
                         net_name: Optional[Callable[[str], str]] = None) -> CapacitanceMatrix:
        """Aggregate/filter Maxwell coefficients, preserving the reference row sum."""
        missing = set(labels) - self.parts.keys()
        if missing:
            raise ValueError(f'Solver result contains unknown scene conductors: {sorted(missing)}')
        if len(set(labels)) != len(labels):
            raise ValueError('Solver result repeats a scene conductor')
        parts = [self.parts[name] for name in labels]
        nets = [self.body_names[p.body] for p in parts]
        if net_name is not None:
            nets = [net_name(name) for name in nets]
        return aggregate_capacitance_matrix(matrix, nets,
                                            lambda i: self.leaves_out_reference(parts[i]),
                                            lambda i, j: self.leaves_out_pair(parts[i], parts[j]))

    def write(self, path: Path) -> str:
        """Record the exact electrical and accounting map alongside a solver deck."""
        rows = [dict(solver_name=name, body_kind=part.body.kind.value, body_name=part.body.name,
                     regions=sorted(part.regions), layer=part.layer, is_reference=part.is_reference)
                for name, part in self.parts.items()]
        path.write_text(json.dumps(dict(schema_version=1, parts=rows), indent=2) + '\n', encoding='utf-8')
        return str(path)
