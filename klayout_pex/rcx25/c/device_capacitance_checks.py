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

"""Observe marker-internal plate coupling without changing exported black-box suppression.

Device abstracts may contain only terminal pins. Recognition markers therefore
come from the original layout, with references supplied independently of extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple, TYPE_CHECKING, Union

import klayout.db as kdb

from ...klayout.lvsdb_extractor import DEVICE_CAPACITOR_PLATE_PROPERTY
from .device_capacitance_references import DeviceCapacitanceCheckError, DeviceCapacitanceReference

if TYPE_CHECKING:
    from ...klayout.lvsdb_extractor import KLayoutExtractionContext


CHECK_DEVICE_PROPERTY = 'device_capacitance_check'
Shape = Union[kdb.PolygonWithProperties, kdb.EdgeWithProperties]


@dataclass(frozen=True)
class _DeviceMarker:
    owner: int
    device: str
    region: kdb.Region


class DeviceCapacitanceChecks:
    def __init__(self, references: List[DeviceCapacitanceReference], markers: List[_DeviceMarker],
                 owners: List[int], net_pairs: List[FrozenSet[str]]):
        self.references = references
        self.markers = {marker.owner: marker for marker in markers}
        self.owners = owners
        self.net_pairs = net_pairs
        self.indexes: Dict[Tuple[int, FrozenSet[str]], List[int]] = {}
        for index, (owner, pair) in enumerate(zip(owners, net_pairs)):
            self.indexes.setdefault((owner, pair), []).append(index)
        self.values: List[Dict[str, float]] = [dict(overlap=0.0, sidewall=0.0, fringe=0.0) for _ in references]
        self.plate_nets: Dict[int, Set[str]] = {owner: set() for owner in owners}
        self.errors: Dict[int, str] = {}
        self.marker_shapes = kdb.Shapes()
        for marker in markers:
            for polygon in marker.region.each():
                self.marker_shapes.insert(kdb.PolygonWithProperties(polygon, {CHECK_DEVICE_PROPERTY: marker.owner}))

    @classmethod
    def prepare(cls, references: List[DeviceCapacitanceReference], context: KLayoutExtractionContext,
                source_top_cell: kdb.Cell) -> DeviceCapacitanceChecks:
        """Find exact, unique marker polygons using the selected devices' terminal geometry."""
        devices = {device.expanded_name(): device for device in context.top_circuit.each_device()}
        markers: Dict[str, _DeviceMarker] = {}
        owners = []
        net_pairs = []
        layout = source_top_cell.layout()
        transform = kdb.ICplxTrans(layout.dbu / context.dbu)
        masks: Dict[FrozenSet[Tuple[int, int]], List[kdb.Region]] = {}
        terminal_shapes: Dict[Tuple[int, int], kdb.Region] = {}

        def terminal_region(device: kdb.Device, terminal: int) -> kdb.Region:
            key = device.id(), terminal
            if key not in terminal_shapes:
                if device.device_abstract is None:
                    raise DeviceCapacitanceCheckError(f'{device.expanded_name()}: device has no layout abstract')
                region = kdb.Region()
                try:
                    for terminal_ref in context.terminal_refs[key]:
                        for part in context.shapes_of_terminal(device, terminal_ref).values():
                            region += part
                except RuntimeError as exc:
                    raise DeviceCapacitanceCheckError(
                        f'KLayout could not read terminal geometry of {device.expanded_name()}: {exc}') from exc
                terminal_shapes[key] = region
            return terminal_shapes[key]

        for reference in references:
            device = devices.get(reference.device)
            if device is None:
                raise DeviceCapacitanceCheckError(f'Unknown device {reference.device!r}; valid devices: '
                                                  + ', '.join(sorted(devices)))
            device_class = device.device_class()
            if device_class.name != reference.device_class:
                raise DeviceCapacitanceCheckError(f'{reference.device} is of class {device_class.name}, '
                                                  f'not {reference.device_class}')
            if device_class.name not in context.tech.device_models.metal_capacitor_class_names:
                raise DeviceCapacitanceCheckError(f'{reference.device} is not a mapped metal capacitor')
            terminals = {terminal.name: terminal.id() for terminal in device_class.terminal_definitions()}
            nets = []
            for name in reference.terminals:
                if name not in terminals:
                    raise DeviceCapacitanceCheckError(f'{reference.device}: unknown terminal {name!r}; '
                                                      f'valid terminals: {", ".join(sorted(terminals))}')
                terminal = terminals[name]
                net = device.net_for_terminal(terminal)
                if net is None:
                    raise DeviceCapacitanceCheckError(f'{reference.device}: terminal {name} is unconnected')
                nets.append(net.expanded_name())
            if nets[0] == nets[1]:
                raise DeviceCapacitanceCheckError(f'{reference.device}: the selected terminals share net {nets[0]}')
            shapes = []
            for name in reference.terminals:
                region = terminal_region(device, terminals[name])
                if region.is_empty():
                    raise DeviceCapacitanceCheckError(f'{reference.device}: terminal {name} has no layout geometry')
                shapes.append(region)
            gds_pairs = context.tech.device_gds_pairs(device_class.name)
            if not gds_pairs:
                raise DeviceCapacitanceCheckError(f'{device_class.name}: the tech info has no recognition layers')
            key = frozenset(gds_pairs)
            if key not in masks:
                region = kdb.Region()
                for pair in sorted(gds_pairs):
                    layer = layout.find_layer(*pair)
                    if layer is not None:
                        region += kdb.Region(source_top_cell.begin_shapes_rec(layer)).transformed(transform)
                masks[key] = [kdb.Region(polygon) for polygon in region.merged().each()]
            candidates = [mask for mask in masks[key]
                          if all(not mask.interacting(terminal).is_empty() for terminal in shapes)]
            if len(candidates) != 1:
                raise DeviceCapacitanceCheckError(f'{reference.device}: expected one recognition marker at its '
                                                  f'terminals, found {len(candidates)}')
            # Touching markers can merge into one polygon. It must not absorb a
            # second device even when that device was not selected for checking.
            for other in devices.values():
                other_class = other.device_class().name
                if other.id() == device.id() or other_class not in context.tech.device_models.metal_capacitor_class_names:
                    continue
                if not key.intersection(context.tech.device_gds_pairs(other_class) or ()):
                    continue
                other_shapes = [terminal_region(other, terminal.id())
                                for terminal in other.device_class().terminal_definitions()
                                if (net := other.net_for_terminal(terminal.id())) is not None
                                and net.expanded_name() != context.substrate_net_name]
                if len(other_shapes) >= 2 and all(not candidates[0].interacting(shape).is_empty()
                                                  for shape in other_shapes):
                    raise DeviceCapacitanceCheckError(f'{reference.device}: recognition marker also contains '
                                                      f'terminals of {other.expanded_name()}')
            marker = markers.get(reference.device)
            if marker is None:
                marker = _DeviceMarker(len(markers) + 1, reference.device, candidates[0])
                if any(not (marker.region & other.region).is_empty() for other in markers.values()):
                    raise DeviceCapacitanceCheckError(f'{reference.device}: recognition marker overlaps another '
                                                      'selected device marker')
                markers[reference.device] = marker
            elif not (marker.region ^ candidates[0]).is_empty():
                raise DeviceCapacitanceCheckError(f'{reference.device}: terminal pairs identify different markers')
            owners.append(marker.owner)
            net_pairs.append(frozenset(nets))
        return cls(references, list(markers.values()), owners, net_pairs)

    def marked_plates(self, region: kdb.Region) -> kdb.Region:
        """Attach marker ownership without cutting polygons or creating extraction edges."""
        marked = kdb.Region()
        marked.enable_properties()
        marked.merged_semantics = region.merged_semantics
        for polygon in region.each():
            properties = polygon.properties()
            if polygon.property(DEVICE_CAPACITOR_PLATE_PROPERTY):
                shape = kdb.Region(polygon.downcast())
                owners = {item.property(CHECK_DEVICE_PROPERTY)
                          for item in self.marker_shapes.each_touching(kdb.Shapes.SAll, polygon.bbox())}
                contained = []
                for owner in owners:
                    if not any(owner == candidate and polygon.property('net') in pair
                               for candidate, pair in zip(self.owners, self.net_pairs)):
                        continue
                    marker = self.markers[owner].region
                    if (shape & marker).is_empty():
                        continue
                    if (shape - marker).is_empty():
                        contained.append(owner)
                    else:
                        self.errors[owner] = 'plate geometry crosses its recognition marker boundary'
                if len(contained) == 1:
                    owner, = contained
                    properties[CHECK_DEVICE_PROPERTY] = owner
                    self.plate_nets[owner].add(polygon.property('net'))
            marked.insert(kdb.PolygonWithProperties(polygon.downcast(), properties))
        return marked

    def indexes_for(self, first: Shape, net1: str, second: Shape, net2: str) -> List[int]:
        owner = first.property(CHECK_DEVICE_PROPERTY)
        if owner is None or owner != second.property(CHECK_DEVICE_PROPERTY):
            return []
        return self.indexes.get((owner, frozenset((net1, net2))), [])

    def record(self, first: Shape, net1: str, second: Shape, net2: str, kind: str, capacitance_ff: float):
        for index in self.indexes_for(first, net1, second, net2):
            if not math.isfinite(capacitance_ff) or capacitance_ff < 0:
                self.errors[self.owners[index]] = 'the extracted capacitance is not finite and nonnegative'
            else:
                self.values[index][kind] += capacitance_ff

    def records(self) -> List[Dict[str, Any]]:
        records = []
        for index, reference in enumerate(self.references):
            owner = self.owners[index]
            error = self.errors.get(owner)
            if not self.net_pairs[index] <= self.plate_nets[owner]:
                error = 'both terminals need capacitor-plate geometry wholly inside the recognition marker'
            contributions = {kind + '_f': value * 1e-15 for kind, value in self.values[index].items()}
            extracted = math.fsum(contributions.values())
            ratio = extracted / reference.capacitance_f
            if not math.isfinite(extracted) or not math.isfinite(ratio):
                error = 'the extracted/reference ratio is not finite'
            elif any(value > 0 and contributions[kind + '_f'] == 0
                     for kind, value in self.values[index].items()) or (extracted > 0 and ratio == 0):
                error = 'the extracted capacitance or ratio underflows floating-point precision'
            status = 'informational'
            if error is not None:
                status = 'unevaluable'
                extracted = ratio = None
                contributions = {kind: None for kind in contributions}
            elif reference.min_ratio is not None or reference.max_ratio is not None:
                status = 'passed' if (reference.min_ratio is None or ratio >= reference.min_ratio) and \
                    (reference.max_ratio is None or ratio <= reference.max_ratio) else 'failed'
            records.append(dict(device=reference.device, device_class=reference.device_class,
                                terminals=list(reference.terminals), nets=sorted(self.net_pairs[index]),
                                extracted_capacitance_f=extracted, reference_capacitance_f=reference.capacitance_f,
                                ratio=ratio, min_ratio=reference.min_ratio, max_ratio=reference.max_ratio,
                                status=status, error=error, contributions=contributions,
                                reference_source=reference.source, reference_description=reference.description))
        return records


def describe_device_capacitance_check(record: Dict[str, Any]) -> str:
    context = f"{record['device']} ({record['device_class']}), {' / '.join(record['terminals'])}"
    if record['error'] is not None:
        return f"{context}: device capacitance could not be checked: {record['error']}"
    bounds = []
    if record['min_ratio'] is not None:
        bounds.append(f"min {record['min_ratio']:.6g}")
    if record['max_ratio'] is not None:
        bounds.append(f"max {record['max_ratio']:.6g}")
    limits = '; ' + ', '.join(bounds) if bounds else ''
    return (f"{context}: marker coupling {record['extracted_capacitance_f'] * 1e15:.6g} fF, "
            f"model reference {record['reference_capacitance_f'] * 1e15:.6g} fF, "
            f"ratio {record['ratio']:.6g} ({record['status']}{limits})")
