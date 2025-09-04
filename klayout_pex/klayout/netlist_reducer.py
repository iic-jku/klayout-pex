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
from typing import *

import klayout.db as kdb

from ..log import (
    info,
)


class NetlistReducer:
    @staticmethod
    def reduce(netlist: kdb.Netlist,
               top_cell_name: str,
               cap_threshold: float = 0.05e-15) -> kdb.Netlist:
        reduced_netlist: kdb.Netlist = netlist.dup()
        reduced_netlist.combine_devices()  # merge C/R

        top_circuit: kdb.Circuit = reduced_netlist.circuit_by_name(top_cell_name)

        devices_to_remove: List[kdb.Device] = []

        for d in top_circuit.each_device():
            d: kdb.Device
            dc = d.device_class()
            if isinstance(dc, kdb.DeviceClassCapacitor):
                # net_a = d.net_for_terminal('A')
                # net_b = d.net_for_terminal('B')
                c_value = d.parameter('C')
                if c_value < cap_threshold:
                    devices_to_remove.append(d)

            elif isinstance(dc, kdb.DeviceClassResistor):
                # TODO
                pass

        for d in devices_to_remove:
            info(f"Removed device {d.name} {d.parameter('C')}")
            top_circuit.remove_device(d)

        return reduced_netlist
