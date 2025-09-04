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
import json
from typing import *

import klayout.db as kdb

from ..log import (
    info
)

# see https://yosyshq.readthedocs.io/projects/yosys/en/latest/cmd/write_json.html


class NetlistJSONWriter:
    def __init__(self):
        self.next_id = 0
        self.id_for_net: Dict[str, int] = {}

    def _get_or_create_id(self, net: kdb.Net) -> int:
        net_name = net.expanded_name() or net.name
        i = self.id_for_net.get(net_name, None)
        if i is None:
            i = self.next_id
            self.next_id += 1
            self.id_for_net[net_name] = i
        return i

    def dict_for_ports(self, circuit: kdb.Circuit) -> Dict[str, Any]:
        port_dict = {}
        for pin in circuit.each_pin():
            pin: kdb.Pin
            name = pin.name()
            net = circuit.net_for_pin(pin)
            bit = self._get_or_create_id(net)
            port_dict[name] = {
                'direction': 'input',
                'bits': [bit]
            }

        return port_dict

    def dict_for_cells(self, circuit: kdb.Circuit) -> Dict[str, Any]:
        gnd_nodes: Dict[str, List[int]] = {}
        vdd_nodes: Dict[str, List[int]] = {}
        vss_nodes: Dict[str, List[int]] = {}
        gnd_aliases = ('GND', 'DGND', 'AGND', 'VGND', 'GND1', 'GND2', 'VSUBS')
        vdd_aliases = ('VDD', 'VCC', 'VPWR')
        vss_aliases = ('VSS', 'VEE')

        cells_dict = {}

        for sc in circuit.each_subcircuit():
            subcircuit: kdb.Circuit = sc.circuit_ref()

            port_directions = {}
            connections = {}

            for pin in subcircuit.each_pin():
                pin: kdb.Pin
                net = sc.net_for_pin(pin.id())
                pin_name = net.expanded_name()
                pin_text = f"{pin.id()}={pin_name}"
                port_directions[pin_text] = 'input'
                connections[pin_text] = [self._get_or_create_id(net)]

            cells_dict[f"{subcircuit.name}{subcircuit.cell_index}"] = {
                'hide_name': 1,
                'type': f"${subcircuit.name}",
                'port_directions': port_directions,
                'connections': connections,
                'attributes': {
                }
            }

        for d in circuit.each_device():
            d: kdb.Device
            # https://www.klayout.de/doc-qt5/code/class_Device.html
            dc = d.device_class()
            dn = d.expanded_name() or d.name
            param_defs = dc.parameter_definitions()
            params = {p.name: d.parameter(p.id()) for p in param_defs}
            if isinstance(dc, kdb.DeviceClassCapacitor):
                net1: kdb.Net = d.net_for_terminal('A')
                net2: kdb.Net = d.net_for_terminal('B')
                cap = params['C']
                cap_femto = round(cap * 1e15, 3)
                cells_dict[f"C{dn}"] = {
                    'type': 'c_v',
                    'connections': {
                        'A': [self._get_or_create_id(net1)],
                        'B': [self._get_or_create_id(net2)],
                    },
                    'attributes': {
                        'value': f"{cap_femto}f"
                    }
                }
            elif isinstance(dc, kdb.DeviceClassResistor):
                net1: kdb.Net = d.net_for_terminal('A')
                net2: kdb.Net = d.net_for_terminal('B')
                ohm = params['R']
                cells_dict[f"R{dn}"] = {
                    'type': 'r_v',
                    'connections': {
                        'A': [self._get_or_create_id(net1)],
                        'B': [self._get_or_create_id(net2)],
                    },
                    'attributes': {
                        'value': f"{round(ohm, 3)}"
                    }
                }
            else:
                raise NotImplementedError(f"Not yet implemented: {dc}")

        gnd_counter = 0
        for gnd_name in ('VSUBS', 'GND'):
            gnd_id = self.id_for_net.get(gnd_name, None)
            if gnd_id is None:
                continue
            device_name = f"gnd{'' if gnd_counter == 0 else gnd_counter}"
            gnd_counter += 1
            cells_dict[device_name] = {
                'type': 'gnd',
                'port_directions': {
                    'A': 'input'
                },
                'connections': {
                    'A': [gnd_id],
                },
                'attributes': {
                    'value': gnd_name
                }
            }

        return cells_dict

    def netlist_json_dict(self,
                          netlist: kdb.Netlist,
                          top_circuit: kdb.Circuit) -> Dict[str, Any]:
        json_dict = {
            'modules': {
                top_circuit.name: {
                    'ports': self.dict_for_ports(top_circuit),
                    'cells': self.dict_for_cells(top_circuit)
                }
            }
        }
        return json_dict

    def write_json(self,
                   netlist: kdb.Netlist,
                   top_circuit: kdb.Circuit,
                   output_path: str):
        with open(output_path, 'w', encoding='utf-8') as f:
            d = self.netlist_json_dict(netlist=netlist, top_circuit=top_circuit)
            json.dump(d, f, indent=4)
