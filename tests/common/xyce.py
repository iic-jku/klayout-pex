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
Simulations with Xyce in tests, which are skipped where Xyce isn't installed (Xyce on PATH)
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import *

import numpy as np
import pytest

from tests.common.port_admittance_bench import port_admittance_bench, port_admittance_from_currents


def xyce_executable() -> Optional[str]:
    return shutil.which('Xyce')


requires_xyce = pytest.mark.skipif(xyce_executable() is None, reason='Xyce is not on PATH')


def run_xyce(deck_path: str):
    """
    Runs the deck in its directory, where its .print writes <deck>.prn
    """
    result = subprocess.run([xyce_executable(), os.path.basename(deck_path)],
                            cwd=os.path.dirname(deck_path), capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, f"Xyce failed on {deck_path}:\n{result.stdout}\n{result.stderr}"


def read_prn(path: str) -> Dict[str, List[float]]:
    """
    The columns of a .prn file of Xyce's .print, by name (e.g. I(V1)), without the closing line
    """
    with open(path) as f:
        lines = [line.split() for line in f.read().splitlines()]
    names = lines[0]
    rows = [row for row in lines[1:] if len(row) == len(names)]
    return {name: [float(row[i]) for row in rows] for i, name in enumerate(names)}


def xyce_port_admittance(netlist_path: str,
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
    lines, sources = port_admittance_bench(os.path.abspath(netlist_path), subcircuit, count)
    lines += [f".ac dec 1 1e{decades[0]} 1e{decades[1]}",
              ".print ac " + ' '.join(f"IR({source}) II({source})" for source in sources),
              ".end"]
    with open(bench_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    run_xyce(bench_path)
    columns = read_prn(f"{bench_path}.FD.prn")
    frequencies = np.array(columns['FREQ'])
    currents = np.array([[re + 1j * im for re, im in zip(columns[f"IR({source.upper()})"],
                                                            columns[f"II({source.upper()})"])]
                         for source in sources]).T
    return frequencies, port_admittance_from_currents(currents, count)
