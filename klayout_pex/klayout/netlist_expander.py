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
from ..common.capacitance_matrix import CapacitanceMatrix
from ..device_models import DeviceModels
from klayout_pex.klayout.capacitance_matrix_interpreter import CapacitanceMatrixInterpreter
from .parasitic_device_classes import PARASITIC_CAPACITOR_CLASS_NAME
from ..util.unit_formatter import format_spice_number


class NetlistExpander:
    @staticmethod
    def expand(extracted_netlist: kdb.Netlist,
               top_cell_name: str,
               cap_matrix: CapacitanceMatrix,
               cap_matrix_interpreter: CapacitanceMatrixInterpreter,
               blackbox_devices: bool,
               device_models: DeviceModels,
               substrate_net_name: str) -> kdb.Netlist:
        """
        :param device_models: the device models of the tech info, whose metal capacitors white-box mode removes
        :param substrate_net_name: the conductor of the substrate (see FasterCapInputBuilder),
                                   created if the netlist has no such net, and a port if it has no pin
        """
        expanded_netlist: kdb.Netlist = extracted_netlist.dup()
        top_circuit: kdb.Circuit = expanded_netlist.circuit_by_name(top_cell_name)

        if not blackbox_devices:
            # NOTE: only the metal capacitors (e.g. MIM and MOM caps), whose capacitance is extracted
            #       from their plates and fingers (see RCX25NetlistExpander.is_whiteboxed), not e.g. the transistors
            metal_capacitor_class_names = device_models.metal_capacitor_class_names
            # NOTE: Store devices before modifying container
            devices_to_remove: List[kdb.Device] = [d for d in top_circuit.each_device()
                                                   if d.device_class().name in metal_capacitor_class_names]
            for d in devices_to_remove:
                name = d.name or d.expanded_name()
                info(f"Removing whiteboxed device {name}")
                top_circuit.remove_device(d)

        # create capacitor class
        cap = kdb.DeviceClassCapacitor()
        cap.name = PARASITIC_CAPACITOR_CLASS_NAME
        cap.description = "Extracted by kpex/FasterCap PEX"
        expanded_netlist.add(cap)

        nets: List[kdb.Net] = []

        # build table: name -> net
        name2net: Dict[str, kdb.Net] = {n.expanded_name(): n for n in top_circuit.each_net()}

        signal_names = [cap_matrix_interpreter.signal_name_from_conductor_name(nc)
                        for nc in cap_matrix.conductor_names]

        # NOTE: the substrate conductor is the substrate net, or a net of its own (e.g. a metal test pattern),
        #       and the substrate net is a port, also if the LVS netlist has it without pin
        #       (e.g. IHP's global net sub! in a metal test pattern without taps)
        if substrate_net_name in signal_names:
            substrate_net = name2net.get(substrate_net_name)
            if substrate_net is None:
                substrate_net = top_circuit.create_net(substrate_net_name)
                name2net[substrate_net_name] = substrate_net
            if substrate_net.pin_count() == 0:
                top_circuit.connect_pin(top_circuit.create_pin(substrate_net_name), substrate_net)

        # find nets for the matrix axes
        for nn in signal_names:
            n = name2net.get(nn)
            if n is None:
                raise Exception(f"No net found with name {nn}, net names are: {list(name2net.keys())}")
            nets.append(n)

        cap_threshold = 0.0

        def add_parasitic_cap(i: int,
                              j: int,
                              net1: kdb.Net,
                              net2: kdb.Net,
                              cap_value: float):
            if cap_value > cap_threshold:
                c: kdb.Device = top_circuit.create_device(cap, f"Cext_{i}_{j}")
                c.connect_terminal('A', net1)
                c.connect_terminal('B', net2)
                c.set_parameter('C', cap_value)  # Farad
                if net1 == net2:
                    raise Exception(f"Invalid attempt to create cap {c.name} between "
                                    f"same net {net1} with value format_capacitance(cap_value)")
            else:
                warning(f"Ignoring capacitance matrix cell [{i},{j}], "
                        f"{format_spice_number(cap_value)} is below threshold {format_spice_number(cap_threshold)}")

        # -------------------------------------------------------------
        # Example capacitance matrix:
        #     [C11+C12+C13           -C12            -C13]
        #     [-C21           C21+C22+C23            -C23]
        #     [-C31                  -C32     C31+C32+C33]
        # -------------------------------------------------------------
        #
        # - Diagonal elements m[i][i] contain the capacitance over GND (Cii),
        #   but in a sum including all the other values of the row
        #
        # https://www.fastfieldsolvers.com/Papers/The_Maxwell_Capacitance_Matrix_WP110301_R03.pdf
        #
        ground_index = signal_names.index(substrate_net_name) if substrate_net_name in signal_names else 0

        for i in range(0, cap_matrix.dimension):
            row = cap_matrix[i]
            cap_ii = row[i]
            for j in range(0, cap_matrix.dimension):
                if i == j:
                    continue
                cap_value = -row[j]  # off-diagonals are always stored as negative values
                cap_ii -= cap_value  # subtract summands to filter out Cii
                if j > i:
                    add_parasitic_cap(i=i, j=j,
                                      net1=nets[i], net2=nets[j],
                                      cap_value=cap_value)
            # NOTE: the rest of the diagonal element (the capacitance to infinity) goes to the substrate
            if i != ground_index:
                add_parasitic_cap(i=i, j=i,
                                  net1=nets[i], net2=nets[ground_index],
                                  cap_value=cap_ii)

        return expanded_netlist
