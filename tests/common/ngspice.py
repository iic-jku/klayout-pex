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
Simulations with ngspice in tests, which are skipped where ngspice isn't installed (ngspice on PATH)
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import *

import numpy as np

from tests.common.port_admittance_bench import port_admittance_bench, port_admittance_from_currents


def ngspice_executable() -> Optional[str]:
    return shutil.which('ngspice')


def run_ngspice(deck_path: str):
    """
    Runs the deck in batch mode in its directory (where ngspice reads .spiceinit)
    """
    result = subprocess.run([ngspice_executable(), '-b', os.path.basename(deck_path)],
                            cwd=os.path.dirname(deck_path), capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, f"ngspice failed on {deck_path}:\n{result.stdout}\n{result.stderr}"


def read_wrdata(path: str) -> List[List[float]]:
    """
    The rows of a file of ngspice's wrdata (with set wr_singlescale and wr_vecnames):
    the scale, then the vectors, a complex one as its real and imaginary part
    """
    with open(path) as f:
        lines = f.read().splitlines()
    return [[float(v) for v in line.split()] for line in lines[1:]]


def ngspice_port_admittance(netlist_path: str,
                            subcircuit: str,
                            ports: Sequence[str],
                            decades: Tuple[int, int],
                            work_dir: str) -> Tuple[np.ndarray, np.ndarray]:
    """
    Y(f) of the subcircuit's ports, by an AC analysis of the bench of port_admittance_bench

    :param ports: all ports of the subcircuit, in the order of its .SUBCKT line
    :param decades: frequencies 10**decades[0] … 10**decades[1] Hz, one point per decade
    :return: the frequencies (F) and Y (F × P × P)
    """
    count = len(ports)
    name = os.path.splitext(os.path.basename(netlist_path))[0]
    bench_path = os.path.join(work_dir, f"{name}_ac.cir")
    data_path = os.path.join(work_dir, f"{name}_ac.txt")
    lines, sources = port_admittance_bench(os.path.abspath(netlist_path), subcircuit, count)
    lines += [".control",
              "set wr_singlescale",
              f"ac dec 1 1e{decades[0]} 1e{decades[1]}",
              f"wrdata {data_path} {' '.join(f'{source}#branch' for source in sources)}",
              ".endc",
              ".end"]
    with open(bench_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    run_ngspice(bench_path)
    assert os.path.exists(data_path), f"ngspice wrote no {data_path}"

    data = np.loadtxt(data_path, ndmin=2)
    frequencies = data[:, 0]
    # NOTE: with wr_singlescale, the columns are the frequency, then real and imaginary part of each vector
    currents = data[:, 1::2] + 1j * data[:, 2::2]
    return frequencies, port_admittance_from_currents(currents, count)
