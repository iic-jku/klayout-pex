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

"""Schematic names for devices whose correspondence is unambiguous (#243).

Comparison uses temporary circuits before RC splitting. Only device names in the
exported circuit change: IDs, terminals, parameters and the port order stay intact.
Parallel MOS fingers are compared by their total width, then named in device-ID
order. That order is repeatable for an LVS database, not a cross-version identity.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import math
from typing import Dict, List, Mapping, Optional, Set, Tuple

import klayout.db as kdb

from ..device_models import DeviceModels
from ..klayout.parasitic_device_classes import PARASITIC_CAPACITOR_CLASS_NAME, PARASITIC_RESISTOR_CLASS_NAME
from ..netlist.spice_hierarchy import SpiceEvaluationError, SpiceHierarchy
from ..netlist.spice_netlist import SpiceNetlist
from ..schematic_devices import schematic_devices
from .netlist_checks import DEVICE_TOTAL_TOLERANCE


_COUNT = '__kpex_naming_count'


class SchematicDeviceNameError(Exception):
    """A failure of the comparison used to transfer device names."""


class _CannotName(Exception):
    pass


@dataclass
class _Group:
    class_name: str
    nodes: Dict[str, str]
    parameters: Dict[str, float]
    ids: List[int] = field(default_factory=list)
    names: List[str] = field(default_factory=list)


def _swappable_terminals(device_class: kdb.DeviceClass) -> Optional[Tuple[str, str]]:
    # Only native, documented symmetries are used. Unknown custom terminal
    # permutations stay strict in the temporary comparison circuits.
    pairs = ((kdb.DeviceClassMOS3Transistor, ('D', 'S')),
             (kdb.DeviceClassResistor, ('A', 'B')),
             (kdb.DeviceClassCapacitor, ('A', 'B')),
             (kdb.DeviceClassInductor, ('A', 'B')))
    if not device_class.strict:
        for native_class, terminals in pairs:
            if isinstance(device_class, native_class):
                return terminals
    return None


def _canonical_nodes(device_class: kdb.DeviceClass, nodes: Dict[str, str]) -> Dict[str, str]:
    terminals = _swappable_terminals(device_class)
    if terminals is not None and all(name in nodes for name in terminals):
        nodes = dict(nodes)
        nodes[terminals[0]], nodes[terminals[1]] = sorted(nodes[name] for name in terminals)
    return nodes


def _groups(devices: List[_Group], classes: Mapping[str, kdb.DeviceClass]) -> List[_Group]:
    grouped: Dict[Tuple, _Group] = {}
    for device in devices:
        mos = isinstance(classes[device.class_name], kdb.DeviceClassMOS3Transistor)
        parameters = tuple(sorted((name, value) for name, value in device.parameters.items()
                                  if not (mos and name == 'W')))
        key = device.class_name, tuple(sorted(device.nodes.items())), parameters
        group = grouped.get(key)
        if group is None:
            grouped[key] = device
        else:
            group.ids += device.ids
            group.names += device.names
            if mos:
                group.parameters['W'] += device.parameters['W']
                if not math.isfinite(group.parameters['W']):
                    raise _CannotName('the combined width of parallel MOS devices is not finite')
    return list(grouped.values())


def _proxy(groups: List[_Group], classes: Mapping[str, kdb.DeviceClass],
           parameter_names: Mapping[str, List[str]]) -> Tuple[kdb.Netlist, kdb.Circuit, Dict[str, kdb.Net]]:
    netlist = kdb.Netlist()
    circuit = kdb.Circuit()
    circuit.name = 'TOP'
    netlist.add(circuit)
    nodes: Dict[str, kdb.Net] = {}
    for class_name in sorted({group.class_name for group in groups}):
        device_class = classes[class_name].dup()
        device_class.strict = _swappable_terminals(device_class) is None
        device_class.equal_parameters = None
        compared = parameter_names.get(class_name, [])
        for parameter in device_class.parameter_definitions():
            device_class.enable_parameter(parameter.id(), parameter.name in compared)
        tolerance = None
        for name in compared:
            item = kdb.EqualDeviceParameters(device_class.parameter_id(name), 0.0, DEVICE_TOTAL_TOLERANCE)
            tolerance = item if tolerance is None else tolerance + item
        device_class.equal_parameters = tolerance
        if not isinstance(device_class, kdb.DeviceClassMOS3Transistor):
            if device_class.has_parameter(_COUNT):
                raise _CannotName(f'the device class {class_name} already uses the comparison parameter {_COUNT}')
            device_class.add_parameter(kdb.DeviceParameterDefinition(_COUNT))
        netlist.add(device_class)
    for index, group in enumerate(groups):
        device_class = netlist.device_class_by_name(group.class_name)
        device = circuit.create_device(device_class, str(index))
        for name, value in group.parameters.items():
            device.set_parameter(name, value)
        if not isinstance(device_class, kdb.DeviceClassMOS3Transistor):
            device.set_parameter(_COUNT, len(group.ids) or len(group.names))
        for terminal, name in group.nodes.items():
            if name not in nodes:
                nodes[name] = circuit.create_net(name)
            device.connect_terminal(terminal, nodes[name])
    return netlist, circuit, nodes


class _Matches(kdb.GenericNetlistCompareLogger):
    def __init__(self):
        super().__init__()
        self.pairs: List[Tuple[int, int]] = []
        self.nodes: Dict[str, str] = {}
        self.ambiguous = False

    def match_nets(self, left: kdb.Net, right: kdb.Net):
        self.nodes[left.name] = right.name

    def match_devices(self, left: kdb.Device, right: kdb.Device):
        self.pairs.append((int(left.name), int(right.name)))

    def match_ambiguous_nets(self, left: kdb.Net, right: kdb.Net, message: str):
        self.ambiguous = True


def _indistinguishable_devices(left_groups: List[_Group], right_groups: List[_Group], matches: _Matches,
                               classes: Mapping[str, kdb.DeviceClass],
                               parameter_names: Mapping[str, List[str]]) -> Set[int]:
    # The comparer reports ambiguous nets, but can arbitrarily pair parallel
    # devices whose parameters are equal within tolerance. Check those alternatives
    # with its own parameter rules, after anchoring the already matched nets.
    candidates: Dict[Tuple, List[_Group]] = defaultdict(list)
    for group in right_groups:
        candidates[group.class_name, tuple(sorted(group.nodes.items()))].append(group)
    ambiguous: Set[int] = set()
    for index, group in enumerate(left_groups):
        mapped_nodes = _canonical_nodes(classes[group.class_name],
                                        {terminal: matches.nodes[name] for terminal, name in group.nodes.items()})
        alternatives = candidates[group.class_name, tuple(sorted(mapped_nodes.items()))]
        if len(alternatives) < 2:
            continue
        left, _, left_nodes = _proxy([group], classes, parameter_names)
        matched = 0
        for alternative in alternatives:
            right, _, right_nodes = _proxy([alternative], classes, parameter_names)
            comparer = kdb.NetlistComparer()
            comparer.dont_consider_net_names = True
            for name, net in left_nodes.items():
                comparer.same_nets(net, right_nodes[matches.nodes[name]])
            if comparer.compare(left, right):
                matched += 1
                if matched > 1:
                    ambiguous.add(index)
                    break
    return ambiguous


def _matched_names(lvs_netlist: kdb.Netlist, schematic: SpiceNetlist,
                   device_models: DeviceModels, top_cell_name: str,
                   label_ports: Mapping[str, List[str]]) -> Tuple[Dict[int, str], List[str]]:
    top = SpiceHierarchy(schematic).subcircuit(top_cell_name)
    if top is None:
        raise _CannotName(f'the schematic has no subcircuit {top_cell_name}')
    circuit = lvs_netlist.circuit_by_name(top_cell_name)
    if circuit is None:
        raise _CannotName(f'the LVS netlist has no circuit {top_cell_name}')
    if any(circuit.each_subcircuit()):
        raise _CannotName('the LVS circuit is not flat')
    nets = list(circuit.each_net())
    if any(net.cluster_id == 0 for net in nets) or len({net.cluster_id for net in nets}) != len(nets):
        raise _CannotName('the LVS nets have no unique cluster IDs')
    reference = schematic_devices(schematic, device_models, top_cell_name, resolve_nodes=True)
    if reference.device_names_by_unknown_model:
        raise _CannotName('the schematic has models without a device mapping: ' +
                          ', '.join(sorted(reference.device_names_by_unknown_model)))
    if reference.device_names_without_model:
        raise _CannotName('the schematic has devices without a model mapping: ' +
                          ', '.join(reference.device_names_without_model))
    classes = {device_class.name: device_class for device_class in lvs_netlist.each_device_class()}
    parameter_names: Dict[str, List[str]] = {}
    reference_devices: List[_Group] = []
    for class_name, devices in reference.devices_by_class_name.items():
        if class_name not in classes:
            raise _CannotName(f'the LVS netlist has no device class {class_name}')
        device_class = classes[class_name]
        mapping = device_models.mapping_by_lvs_device_class_name[class_name]
        multiplier = device_models.multiplier_lvs_parameter_name(mapping)
        mos = isinstance(device_class, kdb.DeviceClassMOS3Transistor)
        for device in devices:
            if len(device.nodes) != len(mapping.terminal_names):
                raise _CannotName(f'{device.name} has {len(device.nodes)} terminals, expected {len(mapping.terminal_names)}')
            if not math.isfinite(device.m) or device.m <= 0:
                raise _CannotName(f'{device.name} has a non-positive or non-finite multiplier')
            if multiplier:
                device.lvs_parameters.setdefault(multiplier, device.m)
            if mos:
                if not {'W', 'L'} <= device.lvs_parameters.keys():
                    raise _CannotName(f'{device.name} needs width and length for finger matching')
                if device.lvs_parameters['W'] <= 0 or device.lvs_parameters['L'] <= 0:
                    raise _CannotName(f'{device.name} has non-positive MOS geometry')
                device.lvs_parameters['W'] *= device.lvs_parameters.get(multiplier, device.m)
                if multiplier:
                    device.lvs_parameters[multiplier] = 1.0
            elif device.m != 1.0 and not multiplier:
                raise _CannotName(f'{device.name} has a multiplier without an LVS parameter mapping')
        common = set.intersection(*(set(device.lvs_parameters) for device in devices))
        parameter_names[class_name] = sorted(common)
        for device in devices:
            values = {name: device.lvs_parameters[name] for name in common}
            if not all(math.isfinite(value) for value in values.values()):
                raise _CannotName(f'{device.name} has non-finite geometry')
            nodes = dict(zip(mapping.terminal_names, (name.casefold() for name in device.nodes)))
            reference_devices.append(_Group(class_name, _canonical_nodes(device_class, nodes), values,
                                            names=[device.name]))
    layout_devices: List[_Group] = []
    for device in circuit.each_device():
        device_class = device.device_class()
        class_name = device_class.name
        mapping = device_models.mapping_by_lvs_device_class_name.get(class_name)
        if mapping is None:
            raise _CannotName(f'the device class {class_name} has no model mapping')
        nodes: Dict[str, str] = {}
        for terminal in mapping.terminal_names:
            net = device.net_for_terminal(terminal)
            if net is None:
                raise _CannotName(f'{device.expanded_name()} has an unconnected terminal {terminal}')
            nodes[terminal] = str(net.cluster_id)
        values = {name: device.parameter(name) for name in parameter_names.get(class_name, [])}
        if isinstance(device_class, kdb.DeviceClassMOS3Transistor):
            if not {'W', 'L'} <= values.keys():
                raise _CannotName(f'the schematic has no geometry for {class_name}')
            multiplier = device_models.multiplier_lvs_parameter_name(mapping)
            if multiplier:
                values['W'] *= values[multiplier]
                values[multiplier] = 1.0
        if not all(math.isfinite(value) for value in values.values()):
            raise _CannotName(f'{device.expanded_name()} has non-finite geometry')
        layout_devices.append(_Group(class_name, _canonical_nodes(device_class, nodes), values, ids=[device.id()]))
    left_groups = _groups(layout_devices, classes)
    right_groups = _groups(reference_devices, classes)
    left, _, left_nodes = _proxy(left_groups, classes, parameter_names)
    right, _, right_nodes = _proxy(right_groups, classes, parameter_names)
    matches = _Matches()
    comparer = kdb.NetlistComparer(matches)
    comparer.dont_consider_net_names = True
    # Pin names anchor the correspondence, but never reorder the exported pins.
    pins: Dict[str, List[str]] = {}
    for pin in circuit.each_pin():
        net = circuit.net_for_pin(pin.id())
        if net is not None:
            for name in {pin.name(), *label_ports.get(net.expanded_name(), [])}:
                pins.setdefault(name.casefold(), []).append(str(net.cluster_id))
    for port in top.ports:
        key = port.casefold()
        if key not in pins:
            continue  # e.g. a substrate terminal without a named layout pin
        if len(set(pins[key])) != 1:
            raise _CannotName(f'the schematic port {port} has no unique layout pin')
        if key in right_nodes and pins[key][0] in left_nodes:
            comparer.same_nets(left_nodes[pins[key][0]], right_nodes[key])
    if not comparer.compare(left, right):
        raise _CannotName('topology or known device parameters do not match')
    if matches.ambiguous:
        raise _CannotName('the circuit has ambiguous net correspondence')
    ambiguous_devices = _indistinguishable_devices(left_groups, right_groups, matches, classes, parameter_names)
    names: Dict[int, str] = {}
    warnings: List[str] = []
    for left_index, right_index in matches.pairs:
        layout_group, reference_group = left_groups[left_index], right_groups[right_index]
        if len(reference_group.names) != 1 or left_index in ambiguous_devices:
            warnings.append('indistinguishable parallel schematic instances: ' + ', '.join(reference_group.names))
            continue
        stem = reference_group.names[0][1:]
        if not stem:
            warnings.append('the schematic instance has no name after its SPICE designator')
            continue
        ids = sorted(layout_group.ids)
        names.update({device_id: stem if len(ids) == 1 else f'{stem}_{index}'
                      for index, device_id in enumerate(ids)})
    return names, warnings


def use_schematic_device_names(lvs_netlist: kdb.Netlist, rc_netlist: kdb.Netlist,
                               schematic: SpiceNetlist, device_models: DeviceModels,
                               top_cell_name: str,
                               label_ports: Optional[Mapping[str, List[str]]] = None) -> List[str]:
    """Rename uniquely matched exported devices and return reasons for retained layout names.

    A failed or ambiguous comparison leaves extraction usable. The model mapping
    still supplies the required SPICE designator, including for native devices
    represented by model wrappers. Name collisions reject the whole assignment.
    """
    try:
        names, warnings = _matched_names(lvs_netlist, schematic, device_models, top_cell_name, label_ports or {})
    except (_CannotName, SpiceEvaluationError) as exc:
        return [f'Schematic device names retained from layout: {exc}']
    except RuntimeError as exc:
        raise SchematicDeviceNameError(f'KLayout could not compare devices for schematic naming: {exc}') from exc
    devices = list(rc_netlist.circuit_by_name(top_cell_name).each_device())
    original_classes = {device.id(): device.device_class().name
                        for device in lvs_netlist.circuit_by_name(top_cell_name).each_device()}
    # Removed white-box devices may leave IDs subsequently reused by parasitics.
    names = {device.id(): names[device.id()] for device in devices
             if device.id() in names and device.device_class().name == original_classes[device.id()]}
    output_names: List[str] = []
    for device in devices:
        class_name = device.device_class().name
        prefix = {PARASITIC_CAPACITOR_CLASS_NAME: 'C', PARASITIC_RESISTOR_CLASS_NAME: 'R'}.get(class_name)
        if prefix is None:
            prefix = device_models.mapping_by_lvs_device_class_name[class_name].spice_prefix
        output_names.append((prefix + names.get(device.id(), device.expanded_name())).casefold())
    duplicates = [name for name, count in Counter(output_names).items() if count > 1]
    if duplicates:
        return ['Schematic device names retained from layout: output names would collide: ' + ', '.join(sorted(duplicates))]
    for device in devices:
        if device.id() in names:
            device.name = names[device.id()]
    return [f'Schematic device names retained from layout: {message}' for message in warnings]
