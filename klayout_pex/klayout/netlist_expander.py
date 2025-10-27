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
from ..util.unit_formatter import format_spice_number


class NetlistExpander:
    @staticmethod
    def expand(extracted_netlist: kdb.Netlist,
               top_cell_name: str,
               cap_matrix: CapacitanceMatrix,
               blackbox_devices: bool) -> kdb.Netlist:
        expanded_netlist: kdb.Netlist = extracted_netlist.dup()
        top_circuit: kdb.Circuit = expanded_netlist.circuit_by_name(top_cell_name)

        if not blackbox_devices:
            for d in top_circuit.each_device():
                name = d.name or d.expanded_name()
                info(f"Removing whiteboxed device {name}")
                top_circuit.remove_device(d)

        # create capacitor class
        cap = kdb.DeviceClassCapacitor()
        cap.name = 'PEX_CAP'
        cap.description = "Extracted by kpex/FasterCap PEX"
        expanded_netlist.add(cap)

        fc_gnd_net = top_circuit.create_net('FC_GND')  # create GROUND net
        vsubs_net = top_circuit.create_net("VSUBS")
        nets: List[kdb.Net] = []

        # build table: name -> net
        name2net: Dict[str, kdb.Net] = {n.expanded_name(): n for n in top_circuit.each_net()}

        # find nets for the matrix axes
        pattern = re.compile(r'^g\d+_(.*)$')
        for idx, nn in enumerate(cap_matrix.conductor_names):
            m = pattern.match(nn)
            nn = m.group(1)
            if nn not in name2net:
                raise Exception(f"No net found with name {nn}, net names are: {list(name2net.keys())}")
            n = name2net[nn]
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
            if i > 0:
                add_parasitic_cap(i=i, j=i,
                                  net1=nets[i], net2=nets[0],
                                  cap_value=cap_ii)

        # Short VSUBS and FC_GND together
        #   VSUBS ... substrate block
        #   FC_GND ... FasterCap's GND, i.e. the diagonal Cii elements
        # create capacitor class

        res = kdb.DeviceClassResistor()
        res.name = 'PEX_RES'
        res.description = "Extracted by kpex/FasterCap PEX"
        expanded_netlist.add(res)

        gnd_net = name2net.get('GND', None)
        if not gnd_net:
            gnd_net = top_circuit.create_net('GND')  # create GROUND net

        c: kdb.Device = top_circuit.create_device(res, f"Rext_FC_GND_GND")
        c.connect_terminal('A', fc_gnd_net)
        c.connect_terminal('B', gnd_net)
        c.set_parameter('R', 0)

        c: kdb.Device = top_circuit.create_device(res, f"Rext_VSUBS_GND")
        c.connect_terminal('A', vsubs_net)
        c.connect_terminal('B', gnd_net)
        c.set_parameter('R', 0)

        return expanded_netlist
