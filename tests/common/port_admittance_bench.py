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
A SPICE bench for the port admittance Y(f) of a subcircuit, for the AC analyses of ngspice and Xyce:
one instance per port, that port driven by an AC voltage of 1 V, the others at 0 V;
the currents into the ports are the columns of Y
"""

from __future__ import annotations

from typing import *

import numpy as np


def port_admittance_bench(netlist_path: str,
                          subcircuit: str,
                          port_count: int) -> Tuple[List[str], List[str]]:
    """
    :return: the lines of the bench (title, include, instances and sources, no analysis),
             and the names of the sources, in the order of port_admittance_from_currents
    """
    lines = [f"* port admittance of {subcircuit}", f".include {netlist_path}"]
    sources = []
    for driven in range(port_count):
        nodes = [f"p{driven}_{port}" for port in range(port_count)]
        lines.append(f"Xdut{driven} {' '.join(nodes)} {subcircuit}")
        for port, node in enumerate(nodes):
            source = f"v{driven}_{port}"
            lines.append(f"{source} {node} 0 DC 0 AC {1 if port == driven else 0}")
            sources.append(source)
    return lines, sources


def port_admittance_from_currents(currents: np.ndarray, port_count: int) -> np.ndarray:
    """
    :param currents: the branch currents of the sources (F × P·P), in the order of port_admittance_bench
    :return: Y (F × P × P)
    """
    y = np.zeros((currents.shape[0], port_count, port_count), dtype=complex)
    for driven in range(port_count):
        for port in range(port_count):
            # NOTE: a source's branch current flows from its + node through it, i.e. out of the port
            y[:, port, driven] = -currents[:, driven * port_count + port]
    return y
