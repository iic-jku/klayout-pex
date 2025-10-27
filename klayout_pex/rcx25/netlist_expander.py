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


class RCX25NetlistExpander:
    @staticmethod
    def expand(extracted_netlist: kdb.Netlist,
               top_cell_name: str,
               extraction_results: ExtractionResults,
               blackbox_devices: bool) -> kdb.Netlist:
        expanded_netlist: kdb.Netlist = extracted_netlist.dup()
        top_circuit: kdb.Circuit = expanded_netlist.circuit_by_name(top_cell_name)

        if not blackbox_devices:
            # TODO: we'll need additional information about the available devices
            #       because we only want to replace resistor / capacitor devices
            #       and for example not transitors

            for d in top_circuit.each_device():
                name = d.name or d.expanded_name()
                match d.device_class().__class__:
                    case kdb.DeviceClassResistor | kdb.DeviceClassResistorWithBulk:
                        pass

                    case kdb.DeviceClassCapacitor | kdb.DeviceClassCapacitorWithBulk:
                        info(f"Removing whiteboxed device {name}")
                        top_circuit.remove_device(d)

                    case kdb.DeviceClassInductor:
                        pass

                    case kdb.DeviceClassBJT3Transistor | kdb.DeviceClassBJT4Transistor | kdb.DeviceClassDiode | \
                         kdb.DeviceClassMOS3Transistor | kdb.DeviceClassMOS4Transistor:
                        pass

        # create capacitor device class
        cap = kdb.DeviceClassCapacitor()
        # cap.name = 'KPEX_CAP'
        cap.name = 'C'
        cap.description = "Extracted by KPEX/2.5D"
        expanded_netlist.add(cap)

        # create resistor device class
        res = kdb.DeviceClassResistor()
        # res.name = 'KPEX_RES'
        res.name = 'R'
        res.description = "Extracted by KPEX/2.5D"
        expanded_netlist.add(res)

        fc_gnd_net = top_circuit.create_net('FC_GND')  # create GROUND net
        vsubs_net = top_circuit.create_net("VSUBS")

        summary = extraction_results.summarize()
        cap_items = sorted(summary.capacitances.items())
        res_items = sorted(summary.resistances.items())

        # build table: name -> net
        name2net: Dict[str, kdb.Net] = {n.expanded_name(): n for n in top_circuit.each_net()}

        def add_net_if_needed(net_name: str):
            if net_name in name2net:
                return
            name2net[net_name] = top_circuit.create_net(net_name)

        # add additional nets for new nodes (e.g. created during R extraction of vias)
        for key, _ in cap_items:
            add_net_if_needed(key.net1)
            add_net_if_needed(key.net2)
        for key, _ in res_items:
            add_net_if_needed(key.net1)
            add_net_if_needed(key.net2)

        for idx, (key, cap_value_femto) in enumerate(cap_items):
            net1 = name2net[key.net1]
            net2 = name2net[key.net2]

            cap_value_farad = cap_value_femto / 1e15

            c: kdb.Device = top_circuit.create_device(cap, f"ext_{idx+1}")
            c.connect_terminal('A', net1)
            c.connect_terminal('B', net2)
            c.set_parameter('C', cap_value_farad)
            if net1 == net2:
                warning(f"Invalid attempt to create cap {c.name} between "
                        f"same net {net1} with value {'%.12g' % cap_value}")

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
