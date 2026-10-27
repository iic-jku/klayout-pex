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
"""
Consistency checks of the RC netlist against the LVS netlist it's made of (#215),
and of the LVS netlist against the schematic (#345)

NOTE: the defects of #211 gave RC netlists that simulate to plausible, but wrong numbers,
      so these checks compare the RC netlist with the LVS netlist by identity
      (the devices by ID, the nets by cluster ID), not by the names of the nodes
"""

from __future__ import annotations

from collections import Counter, defaultdict
import math
from typing import *

import klayout.db as kdb

from ..device_models import DeviceModels
from ..device_totals import DeviceTotalParameters
from ..log import info, warning
from ..schematic_devices import SchematicDevices
from .extraction_results import ExtractionSummary
from .netlist_expander import RCX25NetlistExpander, SUBSTRATE
from ..types import NetName
from ..klayout.parasitic_device_classes import (
    PARASITIC_CAPACITOR_CLASS_NAME,
    PARASITIC_DEVICE_CLASS_NAMES,
    PARASITIC_RESISTOR_CLASS_NAME,
)


NET_ID_PROPERTY = 'kpex_check_net_id'


class RCNetlistCheckError(Exception):
    """
    The RC netlist is inconsistent with the LVS netlist (see check_rc_netlist)
    """
    pass

# NOTE: relative, the capacitances of the summary and the netlist differ by rounding only
CAPACITANCE_TOLERANCE = 1e-9

# NOTE: relative, the device totals of a schematic and its layout differ by rounding only (e.g. of µm in m and back)
DEVICE_TOTAL_TOLERANCE = 1e-6


def first_names(names: List[str]) -> str:
    """
    :return: the first three names, e.g. 'a, b, c and 2 more'
    """
    return f"{', '.join(names[:3])}{'' if len(names) <= 3 else f' and {len(names) - 3} more'}"


def check_rc_netlist(lvs_netlist: kdb.Netlist,
                     rc_netlist: kdb.Netlist,
                     top_cell_name: str,
                     summary: ExtractionSummary,
                     blackbox_devices: bool,
                     device_models: DeviceModels,
                     substrate_net_name: Optional[str] = None) -> List[str]:
    """
    :param blackbox_devices: whether the RC netlist keeps the devices, rather than the whiteboxed ones
                             removed (see RCX25NetlistExpander)
    :param device_models: the device models of the tech info, which tell the whiteboxed devices
    :param substrate_net_name: the net of the capacitances to the substrate (see RCX25NetlistExpander)
    :return: the problems of the RC netlist, e.g. a device terminal that is not on
             the resistor network of its net, so that the resistances don't reach it
    """
    lvs_circuit: kdb.Circuit = lvs_netlist.circuit_by_name(top_cell_name)

    # NOTE: the nets of an extracted netlist have unique cluster IDs, which the copies keep
    cluster_ids = [net.cluster_id for net in lvs_circuit.each_net()]
    if 0 in cluster_ids or len(set(cluster_ids)) != len(cluster_ids):
        return ["the nets of the LVS netlist have no unique cluster IDs, to find them in the RC netlist"]

    # NOTE: KLayout's net objects are no Python identities, so the nets get an ID (on a copy)
    rc_device_ids = [(device.id(), device.expanded_name())
                     for device in rc_netlist.circuit_by_name(top_cell_name).each_device()]
    rc_netlist = rc_netlist.dup()
    rc_circuit: kdb.Circuit = rc_netlist.circuit_by_name(top_cell_name)

    nets = list(rc_circuit.each_net())
    for net_id, net in enumerate(nets):
        net.set_property(NET_ID_PROPERTY, net_id)

    def id_of(net: kdb.Net) -> int:
        return net.property(NET_ID_PROPERTY)

    # NOTE: the copy numbers its devices anew (in their order), which closes the gaps of the removed ones
    #       (e.g. whiteboxed), so that a device would have the ID of another one of the LVS netlist,
    #       hence the devices go by the IDs and names of the RC netlist, which are the ones of the LVS netlist
    devices: Dict[int, Tuple[str, kdb.Device]] = {
        device_id: (device_name, device)
        for (device_id, device_name), device in zip(rc_device_ids, rc_circuit.each_device())
    }

    problems: List[str] = []

    # the pieces of the netlist, DC-connected by the parasitic resistors (union-find by net ID)
    parent = list(range(len(nets)))

    def piece_of(net_id: int) -> int:
        while parent[net_id] != net_id:
            parent[net_id] = parent[parent[net_id]]
            net_id = parent[net_id]
        return net_id

    has_resistor: Set[int] = set()
    for device in rc_circuit.each_device():
        if device.device_class().name != PARASITIC_RESISTOR_CLASS_NAME:
            continue
        net_a, net_b = device.net_for_terminal('A'), device.net_for_terminal('B')
        has_resistor.update((id_of(net_a), id_of(net_b)))
        parent[piece_of(id_of(net_a))] = piece_of(id_of(net_b))

    # NOTE: each LVS net keeps its net in the RC netlist, which its resistor network hangs off
    lvs_net_by_piece: Dict[int, NetName] = {}
    for lvs_net in lvs_circuit.each_net():
        rc_net = rc_circuit.net_by_cluster_id(lvs_net.cluster_id)
        if rc_net is None:
            problems.append(f"net {lvs_net.expanded_name()} is missing")
            continue
        piece = piece_of(id_of(rc_net))
        other = lvs_net_by_piece.setdefault(piece, lvs_net.expanded_name())
        if other != lvs_net.expanded_name():
            problems.append(f"resistors join the nets {other} and {lvs_net.expanded_name()}")

    def lvs_net_name(rc_net: kdb.Net) -> NetName:
        # NOTE: a net of no LVS net, e.g. the substrate of the capacitances
        return lvs_net_by_piece.get(piece_of(id_of(rc_net)), rc_net.expanded_name())

    floating_pieces = {piece_of(net_id) for net_id in has_resistor} - set(lvs_net_by_piece)
    names_by_floating_piece: Dict[int, List[NetName]] = defaultdict(list)
    for net_id, net in enumerate(nets):
        if piece_of(net_id) in floating_pieces:
            names_by_floating_piece[piece_of(net_id)].append(net.expanded_name())
    for names in sorted(sorted(names) for names in names_by_floating_piece.values()):
        problems.append(f"resistors of the nodes {first_names(names)} touch no net")

    # the RC netlist has the devices of the LVS netlist, but the whiteboxed ones,
    # whose capacitances are extracted from their plates and fingers instead, so they'd count twice
    device_counts: Counter[str] = Counter()
    missing_devices: Dict[str, List[str]] = defaultdict(list)
    kept_whiteboxed_devices: Dict[str, List[str]] = defaultdict(list)
    for lvs_device in lvs_circuit.each_device():
        class_name = lvs_device.device_class().name
        device_counts[class_name] += 1
        _, device = devices.get(lvs_device.id(), (None, None))
        # NOTE: the ID of a removed device may be given to a parasitic one
        in_rc_netlist = device is not None and device.device_class().name == class_name
        if blackbox_devices or not RCX25NetlistExpander.is_whiteboxed(lvs_device.device_class(), device_models):
            if not in_rc_netlist:
                missing_devices[class_name].append(lvs_device.expanded_name())
        elif in_rc_netlist:
            kept_whiteboxed_devices[class_name].append(lvs_device.expanded_name())
    for class_name, names in sorted(missing_devices.items()):
        problems.append(f"the RC netlist lacks {len(names)} of the {device_counts[class_name]} devices "
                        f"of class {class_name}: {first_names(names)}")
    for class_name, names in sorted(kept_whiteboxed_devices.items()):
        problems.append(f"the RC netlist keeps {len(names)} of the {device_counts[class_name]} whiteboxed devices "
                        f"of class {class_name}, which counts their capacitances twice: {first_names(names)}")

    # every device terminal is on the resistor network of its net
    for device_id, (device_name, device) in devices.items():
        if device.device_class().name in PARASITIC_DEVICE_CLASS_NAMES:
            continue
        lvs_device = lvs_circuit.device_by_id(device_id)
        if lvs_device is None:
            problems.append(f"device {device_name} is not in the LVS netlist")
            continue
        for terminal in device.device_class().terminal_definitions():
            lvs_net = lvs_device.net_for_terminal(terminal.id())
            rc_net = device.net_for_terminal(terminal.id())
            if lvs_net is None:
                continue
            if rc_net is None or lvs_net_name(rc_net) != lvs_net.expanded_name():
                problems.append(f"terminal {terminal.name} of device {device_name} "
                                f"is not on the resistor network of its net {lvs_net.expanded_name()}")

    # every device terminal with a port is on the node of its port (#211 §6)
    for key, node_name in sorted(summary.device_terminal_nodes.items()):
        device_name, device = devices.get(key.device_id, (None, None))
        # NOTE: e.g. removed, as whiteboxed, and its ID given to a parasitic device
        if device is None or device.device_class().name in PARASITIC_DEVICE_CLASS_NAMES:
            continue
        rc_net = device.net_for_terminal(key.terminal_id)
        if rc_net is None or rc_net.expanded_name() != node_name:
            terminal_name = device.device_class().terminal_definitions()[key.terminal_id].name
            problems.append(f"terminal {terminal_name} of device {device_name} "
                            f"is not on the node {node_name} of its port")

    # every port touches something, and every net with a pin in the LVS netlist keeps a port
    ported_lvs_nets: Set[NetName] = set()
    for pin in rc_circuit.each_pin():
        rc_net = rc_circuit.net_for_pin(pin.id())
        if rc_net is None or rc_net.terminal_count() == 0:
            # NOTE: but for a net that touches nothing in the LVS netlist either (e.g. a wire of one pin, R mode)
            lvs_net = lvs_circuit.net_by_name(lvs_net_name(rc_net)) if rc_net is not None else None
            if lvs_net is None or lvs_net.terminal_count() + lvs_net.subcircuit_pin_count() > 0:
                problems.append(f"port {pin.name()} touches nothing")
        if rc_net is not None:
            ported_lvs_nets.add(lvs_net_name(rc_net))
    for pin in lvs_circuit.each_pin():
        lvs_net = lvs_circuit.net_for_pin(pin.id())
        if lvs_net is not None and lvs_net.expanded_name() not in ported_lvs_nets:
            problems.append(f"net {lvs_net.expanded_name()} has no port")

    # the capacitances between each pair of nets are the ones of the summary
    # NOTE: the summary names the nodes, which must be unique for that,
    #       also regardless of case, as SPICE reads names (ngspice joins the nets d and D)
    names_by_key: Dict[str, List[NetName]] = defaultdict(list)
    for net in nets:
        names_by_key[net.expanded_name().casefold()].append(net.expanded_name())
    duplicate_names = sorted(name for names in names_by_key.values() if len(names) > 1 for name in set(names))
    if duplicate_names:
        problems.append(f"nets have the same name: {', '.join(duplicate_names)}")
    rc_net_by_name = {net.expanded_name(): net for net in nets}

    def net_pair(net_a: NetName, net_b: NetName) -> Tuple[NetName, NetName]:
        return (net_a, net_b) if net_a <= net_b else (net_b, net_a)

    netlist_capacitances: Dict[Tuple[NetName, NetName], float] = defaultdict(float)
    for device in rc_circuit.each_device():
        if device.device_class().name != PARASITIC_CAPACITOR_CLASS_NAME:
            continue
        pair = net_pair(lvs_net_name(device.net_for_terminal('A')), lvs_net_name(device.net_for_terminal('B')))
        netlist_capacitances[pair] += device.parameter('C') * 1e15  # fF

    def rc_net(node_name: NetName) -> Optional[kdb.Net]:
        if node_name == SUBSTRATE:
            node_name = substrate_net_name or SUBSTRATE
        return rc_net_by_name.get(node_name)

    summary_capacitances: Dict[Tuple[NetName, NetName], float] = defaultdict(float)
    for key, capacitance in summary.capacitances.items():
        net1, net2 = rc_net(key.net1), rc_net(key.net2)
        if net1 is None or net2 is None:
            problems.append(f"the capacitance between {key.net1} and {key.net2} has no nodes")
            continue
        if id_of(net1) == id_of(net2) and SUBSTRATE in (key.net1, key.net2):
            continue  # e.g. the metal of the substrate net itself (VSS), shorted
        summary_capacitances[net_pair(lvs_net_name(net1), lvs_net_name(net2))] += capacitance

    for pair in sorted(set(netlist_capacitances) | set(summary_capacitances)):
        expected, obtained = summary_capacitances.get(pair, 0.0), netlist_capacitances.get(pair, 0.0)
        if abs(obtained - expected) > CAPACITANCE_TOLERANCE * max(abs(expected), abs(obtained)):
            problems.append(f"the capacitance between {pair[0]} and {pair[1]} is {'%.12g' % obtained} fF, "
                            f"but {'%.12g' % expected} fF in the summary")

    return problems


def check_schematic_device_classes(lvs_netlist: kdb.Netlist,
                                   schematic: SchematicDevices) -> List[str]:
    """
    :return: the problems: the device classes of the schematic that no device of the LVS netlist has,
             e.g. of a device the PEX-LVS doesn't recognize, which the extraction then misses
    """
    lvs_class_names = {device.device_class().name
                       for circuit in lvs_netlist.each_circuit() for device in circuit.each_device()}
    if lvs_class_names and not schematic.device_names_by_class_name:
        models = sorted(schematic.device_names_by_unknown_model)
        return [f"kpex reads no devices from the schematic, e.g. of models without device model mapping"
                f"{f' ({first_names(models)})' if models else ''}, so no device classes are compared"]
    return [f"the schematic has devices of class {class_name} ({first_names(device_names)}), the LVS netlist none"
            for class_name, device_names in sorted(schematic.device_names_by_class_name.items())
            if class_name not in lvs_class_names]


class _DeviceTotals:
    """
    The totals of the devices of a class, and the devices without value for a quantity
    """

    def __init__(self):
        self.sums: Dict[str, float] = defaultdict(float)
        self.devices_without_value: Dict[str, List[str]] = defaultdict(list)

    def add(self, device_name: str, quantities: Dict[str, Optional[float]], count: int = 1):
        for name, value in quantities.items():
            if value is None:
                self.devices_without_value[name].append(device_name)
            else:
                self.sums[name] += value * count


def _circuit_counts(netlist: kdb.Netlist) -> Dict[str, int]:
    """
    :return: how often each circuit is in the top circuits, by name
    """
    counts: Dict[str, int] = {}

    def count(circuit: kdb.Circuit) -> int:
        if circuit.name not in counts:
            references = list(circuit.each_ref())
            counts[circuit.name] = sum(count(r.circuit()) for r in references) if references else 1
        return counts[circuit.name]

    for c in netlist.each_circuit():
        count(c)
    return counts


def check_schematic_device_totals(lvs_netlist: kdb.Netlist,
                                  schematic: SchematicDevices,
                                  device_models: DeviceModels) -> List[str]:
    """
    Compares the totals of the device classes of both (see device_totals), e.g. Σ W·L of a MOS,
    but those that a device has no value for, which it warns about,
    and logs the classes without totals, whose presence check_schematic_device_classes compares only

    :return: the problems: the totals that differ, e.g. of a device the PEX-LVS doesn't recognize
             in a class it recognizes otherwise
    """
    circuit_counts = _circuit_counts(lvs_netlist)
    parameters_by_class_name: Dict[str, DeviceTotalParameters] = {}
    lvs_totals_by_class_name: Dict[str, _DeviceTotals] = defaultdict(_DeviceTotals)
    for circuit in lvs_netlist.each_circuit():
        for device in circuit.each_device():
            device_class = device.device_class()
            mapping = device_models.mapping_by_lvs_device_class_name.get(device_class.name)
            if mapping is None or device_class.name not in schematic.devices_by_class_name:
                continue
            parameters = parameters_by_class_name.setdefault(device_class.name,
                                                             DeviceTotalParameters.of(device_class, mapping))
            values = {pd.name: device.parameter(pd.name) for pd in device_class.parameter_definitions()}
            lvs_totals_by_class_name[device_class.name].add(device.expanded_name(), parameters.quantities(values),
                                                            count=circuit_counts[circuit.name])

    problems: List[str] = []
    uncompared: List[str] = []
    for class_name, lvs_totals in sorted(lvs_totals_by_class_name.items()):
        parameters = parameters_by_class_name[class_name]
        totals = _DeviceTotals()
        for device in schematic.devices_by_class_name[class_name]:
            totals.add(device.name, parameters.quantities(device.lvs_parameters, device.m))
        for quantity in parameters.quantity_names:
            without_value = totals.devices_without_value[quantity] + lvs_totals.devices_without_value[quantity]
            if without_value:
                uncompared.append(f"Σ {quantity} of class {class_name}: no value of {first_names(without_value)}")
            elif not math.isclose(totals.sums[quantity], lvs_totals.sums[quantity], rel_tol=DEVICE_TOTAL_TOLERANCE):
                problems.append(f"the schematic has Σ {quantity} = {'%.9g' % totals.sums[quantity]} "
                                f"of class {class_name}, the LVS netlist {'%.9g' % lvs_totals.sums[quantity]}")
    if uncompared:
        warning("The device class check leaves out these totals, as devices have no value for them "
                "(e.g. of the schematic, which leaves a parameter to the model's default):\n" +
                '\n'.join(f"  - {u}" for u in uncompared))
    presence_only = sorted(c for c, p in parameters_by_class_name.items() if not p.quantity_names)
    if presence_only:
        info(f"The device class check compares only the presence of these classes, "
             f"as their device model mappings give no totals: {', '.join(presence_only)}")
    return problems
