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
"""Separate electrical identity from a solver's flat label namespace."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class BodyKind(Enum):
    NET = 'net'
    FLOATING_BODY = 'floating-body'


@dataclass(frozen=True)
class ElectricalBody:
    kind: BodyKind
    name: str


def ground_body(scene: Any) -> ElectricalBody:
    ground = scene.ground_plane
    return ElectricalBody(BodyKind.NET, ground.net or ground.name)


def conductor_body(conductor: Any) -> ElectricalBody:
    if conductor.floating:
        return ElectricalBody(BodyKind.FLOATING_BODY, conductor.name)
    return ElectricalBody(BodyKind.NET, conductor.net)


def solver_body_names(scene: Any) -> Dict[ElectricalBody, str]:
    """Keep net labels and allocate distinct labels for independent floating bodies."""
    bodies = {conductor_body(c) for c in scene.conductors}
    if scene.HasField('ground_plane'):
        bodies.add(ground_body(scene))
    result: Dict[ElectricalBody, str] = {}
    floating_bodies: List[ElectricalBody] = []
    for body in bodies:
        match body.kind:
            case BodyKind.NET:
                result[body] = body.name
            case BodyKind.FLOATING_BODY:
                floating_bodies.append(body)
            case _:
                raise NotImplementedError(f'Solver body naming for {body.kind!r} is not implemented')
    used = set(result.values())
    for body in sorted(floating_bodies, key=lambda b: b.name):
        label = body.name
        if label in used:
            base = f'FLOATING:{body.name}'
            label = base
            suffix = 2
            while label in used:
                label = f'{base}:{suffix}'
                suffix += 1
        result[body] = label
        used.add(label)
    return result


def write_solver_body_map(scene: Any, path: Path) -> Optional[str]:
    """Write the explicit mapping when output labels need disambiguation."""
    names = solver_body_names(scene)
    if all(body.name == label for body, label in names.items()):
        return None
    rows = [dict(kind=body.kind.value, name=body.name, solver_name=label)
            for body, label in sorted(names.items(), key=lambda item: (item[0].kind.value,
                                                                       item[0].name))]
    payload = dict(schema_version=1, bodies=rows)
    if scene.HasField('ground_plane'):
        payload['ground_net'] = ground_body(scene).name
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return str(path)
