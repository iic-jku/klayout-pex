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

"""Nominal device references from mapped tech parameters or an explicit reference file."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from ...device_models import DeviceModelError
from ...netlist.expression.ngspice import NGSPICE_SYNTAX
from ...netlist.expression.nodes import ExpressionError
from ...netlist.expression.parser import ExpressionParser
from ...netlist.expression.scope import ParameterScope
from ...util.unit_formatter import parse_spice_number

if TYPE_CHECKING:
    from ...klayout.lvsdb_extractor import KLayoutExtractionContext


class DeviceCapacitanceCheckError(Exception):
    """A requested device-capacitance comparison cannot be evaluated."""


def _number(value: Any, what: str, allow_suffix: bool = False) -> float:
    if allow_suffix and isinstance(value, str):
        value = parse_spice_number(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{what} must be a finite number')
    return float(value)


@dataclass(frozen=True)
class DeviceCapacitanceReference:
    device: str
    device_class: str
    terminals: Tuple[str, str]
    capacitance_f: float
    min_ratio: Optional[float] = None
    max_ratio: Optional[float] = None
    source: Optional[str] = None
    description: Optional[str] = None

    def __post_init__(self):
        if _number(self.capacitance_f, 'capacitance') <= 0:
            raise ValueError('capacitance must be greater than zero')
        for name, bound in (('min_ratio', self.min_ratio), ('max_ratio', self.max_ratio)):
            if bound is not None and _number(bound, name) < 0:
                raise ValueError(f'{name} must be nonnegative')
        if self.min_ratio is not None and self.max_ratio is not None and self.min_ratio > self.max_ratio:
            raise ValueError('ratio bounds must have min_ratio <= max_ratio')


def read_device_capacitance_references(path: str) -> List[DeviceCapacitanceReference]:
    """Read version 1 references; numeric capacitances are in F, strings accept SPICE suffixes."""
    def unique_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate JSON key {key!r}')
            result[key] = value
        return result

    def fields(value: Any, required: Set[str], optional: Set[str], where: str):
        if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
            raise ValueError(f'{where} needs {", ".join(sorted(required))}; '
                             f'optional fields: {", ".join(sorted(optional)) or "none"}')

    try:
        with open(path, encoding='utf-8') as stream:
            document = json.load(stream, object_pairs_hook=unique_object)
        fields(document, {'format_version', 'references'}, set(), 'reference file')
        if type(document['format_version']) is not int or document['format_version'] != 1:
            raise ValueError('format_version must be 1')
        if not isinstance(document['references'], list) or not document['references']:
            raise ValueError('references must be a nonempty list')
        references = []
        seen = set()
        for index, item in enumerate(document['references']):
            where = f'reference {index + 1}'
            fields(item, {'device', 'device_class', 'terminals', 'capacitance'},
                   {'min_ratio', 'max_ratio'}, where)
            for name in ('device', 'device_class'):
                if not isinstance(item[name], str) or not item[name].strip():
                    raise ValueError(f'{where}: {name} must be a nonempty string')
            terminals = item['terminals']
            if not isinstance(terminals, list) or len(terminals) != 2 or \
                    any(not isinstance(name, str) or not name.strip() for name in terminals) or \
                    terminals[0] == terminals[1]:
                raise ValueError(f'{where}: terminals must name two different terminals')
            capacitance = _number(item['capacitance'], f'{where}: capacitance', allow_suffix=True)
            low = _number(item['min_ratio'], f'{where}: min_ratio') if 'min_ratio' in item else None
            high = _number(item['max_ratio'], f'{where}: max_ratio') if 'max_ratio' in item else None
            key = item['device'], frozenset(terminals)
            if key in seen:
                raise ValueError(f'{where}: duplicate device and terminal pair')
            seen.add(key)
            references.append(DeviceCapacitanceReference(item['device'], item['device_class'],
                                                          tuple(terminals), capacitance, low, high))
        return references
    except (OSError, UnicodeError, ValueError, OverflowError) as exc:
        raise DeviceCapacitanceCheckError(f'Invalid device-capacitance reference file {path}: {exc}') from exc


def tech_device_capacitance_references(context: KLayoutExtractionContext) -> Tuple[
        List[DeviceCapacitanceReference], List[str]]:
    """Evaluate tech references and name metal capacitors without one; never use LVS C placeholders."""
    models = context.tech.device_models
    references: List[DeviceCapacitanceReference] = []
    unchecked: List[str] = []
    parser = ExpressionParser(NGSPICE_SYNTAX)
    for device in context.top_circuit.each_device():
        name = device.expanded_name()
        dc = device.device_class()
        if dc.name not in models.metal_capacitor_class_names:
            continue
        mapping = models.mapping_by_lvs_device_class_name[dc.name]
        if not mapping.capacitance_references:
            unchecked.append(f'{name} ({dc.name})')
            continue
        try:
            names = [p.name.lower() for p in mapping.parameters]
            if len(names) != len(set(names)):
                raise ValueError('duplicate model parameter names')
            values = {key.lower(): _number(value, key) for key, value in
                      models.model_parameter_values(mapping, device).items()}
            terminals = {terminal.name for terminal in dc.terminal_definitions()}
            pairs = set()
            for spec in mapping.capacitance_references:
                pair = frozenset(spec.terminal_names)
                if len(spec.terminal_names) != 2 or len(pair) != 2 or not pair <= terminals:
                    raise ValueError('reference needs two distinct LVS terminals; valid terminals: '
                                     + ', '.join(sorted(terminals)))
                if pair in pairs:
                    raise ValueError('duplicate reference terminal pair')
                pairs.add(pair)
                if not spec.source.strip() or not spec.description.strip():
                    raise ValueError('reference needs source and nominal assumptions in description')
                local_names = [key.lower() for key in spec.parameters]
                if len(local_names) != len(set(local_names)) or set(local_names) & values.keys():
                    raise ValueError('local parameter names must be unique and must not shadow model parameters')
                scope = ParameterScope({key.lower(): parser.parse(value) for key, value in spec.parameters.items()},
                                       parent=ParameterScope(values))
                # Validate all definitions, including ones an inactive conditional would not evaluate.
                for key in local_names:
                    scope.value(key)
                if spec.valid_when and not scope.evaluate(parser.parse(spec.valid_when)):
                    raise ValueError(f'outside reference domain: {spec.valid_when}')
                capacitance = scope.evaluate(parser.parse(spec.capacitance))
                references.append(DeviceCapacitanceReference(
                    name, dc.name, tuple(spec.terminal_names), capacitance,
                    source=spec.source, description=spec.description))
        except (ExpressionError, DeviceModelError, ValueError, RuntimeError) as exc:
            raise DeviceCapacitanceCheckError(
                f'Tech-info capacitance reference for {name} ({dc.name}): {exc}') from exc
    if not references:
        raise DeviceCapacitanceCheckError('No tech-info capacitance references for this layout. '
                                          'Supply --check-device-caps JSON with explicit device references. '
                                          'Unchecked metal capacitors: ' + (', '.join(unchecked) or 'none'))
    return references, unchecked
