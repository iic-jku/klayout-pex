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

import klayout.db as kdb

from klayout_pex.log import (
    info,
)


class NetlistCSVWriter:
    @staticmethod
    def write_csv(netlist: kdb.Netlist,
                  top_cell_name: str,
                  output_path: str):
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('Device;Net1;Net2;Capacitance [fF]\n')

            top_circuit: kdb.Circuit = netlist.circuit_by_name(top_cell_name)

            # NOTE: only caps for now
            for d in top_circuit.each_device():
                # https://www.klayout.de/doc-qt5/code/class_Device.html
                dc = d.device_class()
                if isinstance(dc, kdb.DeviceClassCapacitor):
                    dn = d.expanded_name() or d.name
                    if dc.name != 'PEX_CAP':
                        info(f"Ignoring device {dn}")
                        continue
                    param_defs = dc.parameter_definitions()
                    params = {p.name: d.parameter(p.id()) for p in param_defs}
                    d: kdb.Device
                    net1 = d.net_for_terminal('A')
                    net2 = d.net_for_terminal('B')
                    cap = params['C']
                    cap_femto = round(cap * 1e15, 2)
                    f.write(f"{dn};{net1.name};{net2.name};{cap_femto}\n")
