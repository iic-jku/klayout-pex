#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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
from __future__ import annotations

import re
from typing import *

import klayout.db as kdb

from ..log import (
    info,
    warning,
)
from .extraction_results import ExtractionResults
from ..device_models import DeviceModels
from ..klayout.parasitic_device_classes import PARASITIC_CAPACITOR_CLASS_NAME, PARASITIC_RESISTOR_CLASS_NAME


# the net of the capacitances to the substrate in the extraction results (TechInfo.internal_substrate_layer_name)
SUBSTRATE = 'VSUBS'


class RCX25NetlistExpander:
    @staticmethod
    def is_whiteboxed(device_class: kdb.DeviceClass, device_models: DeviceModels) -> bool:
        """
        :return: whether white-box mode (--blackbox n) removes the devices of the class,
                 as their capacitances are extracted from their plates and fingers (e.g. MIM and MOM caps)

        NOTE: the kind of their device model tells, not the LVS device class:
              e.g. sky130A reads VPP caps with 4 terminals as MOS4,
              while the MOS capacitors and varactors are capacitor classes,
              whose capacitance (of the gate oxide) the extraction doesn't have
        """
        return device_class.name in device_models.metal_capacitor_class_names

    @staticmethod
    def expand(extracted_netlist: kdb.Netlist,
               top_cell_name: str,
               extraction_results: ExtractionResults,
               blackbox_devices: bool,
               device_models: DeviceModels,
               substrate_net_name: Optional[str] = None) -> kdb.Netlist:
        """
        :param device_models: the device models of the tech info, which tell the whiteboxed devices
        :param substrate_net_name: the net the capacitances to the substrate go to (VSUBS if not given),
                                   created if the netlist has none, and a port if it has no pin
        """
        expanded_netlist: kdb.Netlist = extracted_netlist.dup()
        top_circuit: kdb.Circuit = expanded_netlist.circuit_by_name(top_cell_name)

        if not blackbox_devices:
            # NOTE: removing a device ends the iteration over the circuit's devices,
            #       so iterate over a list of them
            for d in list(top_circuit.each_device()):
                if RCX25NetlistExpander.is_whiteboxed(d.device_class(), device_models):
                    info(f"Removing whiteboxed device {d.name or d.expanded_name()}")
                    top_circuit.remove_device(d)

        # create capacitor device class
        cap = kdb.DeviceClassCapacitor()
        # cap.name = 'KPEX_CAP'
        cap.name = PARASITIC_CAPACITOR_CLASS_NAME
        cap.description = "Extracted by KPEX/2.5D"
        expanded_netlist.add(cap)

        # create resistor device class
        res = kdb.DeviceClassResistor()
        # res.name = 'KPEX_RES'
        res.name = PARASITIC_RESISTOR_CLASS_NAME
        res.description = "Extracted by KPEX/2.5D"
        expanded_netlist.add(res)

        fc_gnd_net = top_circuit.create_net('FC_GND')  # create GROUND net

        summary = extraction_results.summarize()
        cap_items = sorted(summary.capacitances.items())
        res_items = sorted(summary.resistances.items())

        # build table: name -> net
        name2net: Dict[str, kdb.Net] = {n.expanded_name(): n for n in top_circuit.each_net()}

        def add_net_if_needed(net_name: str):
            if net_name in name2net:
                return
            name2net[net_name] = top_circuit.create_net(net_name)

        # NOTE: the capacitances to the substrate are on VSUBS (TechInfo.internal_substrate_layer_name),
        #       they go to the substrate net, rather than to a net that connects to nothing,
        #       and the substrate net is a port, also if the LVS netlist has it without pin
        #       (e.g. IHP's global net sub! in a metal test pattern without taps)
        if any(SUBSTRATE in (key.net1, key.net2) for key, _ in cap_items):
            substrate_net_name = substrate_net_name or SUBSTRATE
            substrate_net = name2net.get(substrate_net_name)
            if substrate_net is None:
                substrate_net = top_circuit.create_net(substrate_net_name)
                name2net[substrate_net_name] = substrate_net
            if substrate_net.pin_count() == 0:
                top_circuit.connect_pin(top_circuit.create_pin(substrate_net_name), substrate_net)
            name2net[SUBSTRATE] = substrate_net

        # add additional nets for new nodes (e.g. created during R extraction of vias)
        for key, _ in cap_items:
            add_net_if_needed(key.net1)
            add_net_if_needed(key.net2)
        for key, _ in res_items:
            add_net_if_needed(key.net1)
            add_net_if_needed(key.net2)

        # connect each device terminal to its node of the resistor network (#211 §6),
        # a terminal without one stays on its net, which a node of the resistor network carries
        for key, node_name in sorted(summary.device_terminal_nodes.items()):
            device = top_circuit.device_by_id(key.device_id)
            if device is None:  # e.g. removed, as whiteboxed
                continue
            add_net_if_needed(node_name)
            device.connect_terminal(key.terminal_id, name2net[node_name])

        # the pin of a net of several labels (e.g. A,B) becomes a port per label, in its place (#211 §11)
        if summary.label_ports:
            ports: List[Tuple[str, Optional[kdb.Net]]] = []
            for pin in top_circuit.each_pin():
                net = top_circuit.net_for_pin(pin.id())
                port_names = summary.label_ports.get(net.expanded_name(), None) if net else None
                if port_names is None:
                    ports.append((pin.name(), net))
                    continue
                for port_name in port_names:
                    add_net_if_needed(port_name)
                    ports.append((port_name, name2net[port_name]))
            for pin in list(top_circuit.each_pin()):
                top_circuit.remove_pin(pin.id())
            for port_name, net in ports:
                pin = top_circuit.create_pin(port_name)
                if net is not None:
                    top_circuit.connect_pin(pin, net)

        for idx, (key, cap_value_femto) in enumerate(cap_items):
            net1 = name2net[key.net1]
            net2 = name2net[key.net2]
            if net1 == net2 and SUBSTRATE in (key.net1, key.net2):
                continue  # e.g. the metal of the substrate net itself (VSS), shorted

            cap_value_farad = cap_value_femto / 1e15

            c: kdb.Device = top_circuit.create_device(cap, f"ext_{idx+1}")
            c.connect_terminal('A', net1)
            c.connect_terminal('B', net2)
            c.set_parameter('C', cap_value_farad)
            if net1 == net2:
                warning(f"Invalid attempt to create cap {c.name} between "
                        f"same net {net1} with value {'%.12g' % cap_value_femto} fF")

        for idx, (key, res_value) in enumerate(res_items):
            net1 = name2net[key.net1]
            net2 = name2net[key.net2]

            r: kdb.Device = top_circuit.create_device(res, f"ext_{idx+1}")
            r.connect_terminal('A', net1)
            r.connect_terminal('B', net2)
            r.set_parameter('R', res_value)
            if net1 == net2:
                warning(f"Invalid attempt to create resistor {r.name} between "
                        f"same net {net1} with value {'%.12g' % res_value}")

        return expanded_netlist
