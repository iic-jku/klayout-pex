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
The port admittance matrix of a SPICE subcircuit, by an AC analysis in ngspice
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import *

import numpy as np


def ngspice_executable() -> Optional[str]:
    return shutil.which('ngspice')


def ngspice_port_admittance(netlist_path: str,
                            subcircuit: str,
                            ports: Sequence[str],
                            decades: Tuple[int, int],
                            work_dir: str) -> Tuple[np.ndarray, np.ndarray]:
    """
    Y(f) of the subcircuit's ports, by one instance per port: that port driven by an AC voltage of 1 V,
    the others at 0 V; the currents into the ports are the columns of Y.

    :param ports: all ports of the subcircuit, in the order of its .SUBCKT line
    :param decades: frequencies 10**decades[0] … 10**decades[1] Hz, one point per decade
    :return: the frequencies (F) and Y (F × P × P)
    """
    count = len(ports)
    name = os.path.splitext(os.path.basename(netlist_path))[0]
    bench_path = os.path.join(work_dir, f"{name}_ac.cir")
    data_path = os.path.join(work_dir, f"{name}_ac.txt")
    lines = [f"* port admittance of {subcircuit}", f".include {os.path.abspath(netlist_path)}"]
    sources = []
    for driven in range(count):
        nodes = [f"p{driven}_{port}" for port in range(count)]
        lines.append(f"Xdut{driven} {' '.join(nodes)} {subcircuit}")
        for port, node in enumerate(nodes):
            source = f"v{driven}_{port}"
            lines.append(f"{source} {node} 0 DC 0 AC {1 if port == driven else 0}")
            sources.append(f"{source}#branch")
    lines += [".control",
              "set wr_singlescale",
              f"ac dec 1 1e{decades[0]} 1e{decades[1]}",
              f"wrdata {data_path} {' '.join(sources)}",
              ".endc",
              ".end"]
    with open(bench_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    result = subprocess.run([ngspice_executable(), '-b', bench_path], capture_output=True, text=True, cwd=work_dir)
    assert result.returncode == 0 and os.path.exists(data_path), \
        f"ngspice failed on {bench_path}:\n{result.stdout}\n{result.stderr}"

    data = np.loadtxt(data_path, ndmin=2)
    frequencies = data[:, 0]
    # NOTE: with wr_singlescale, the columns are the frequency, then real and imaginary part of each vector
    currents = data[:, 1::2] + 1j * data[:, 2::2]
    y = np.zeros((len(frequencies), count, count), dtype=complex)
    for driven in range(count):
        for port in range(count):
            # NOTE: a source's branch current flows from its + node through it, i.e. out of the port
            y[:, port, driven] = -currents[:, driven * count + port]
    return frequencies, y
