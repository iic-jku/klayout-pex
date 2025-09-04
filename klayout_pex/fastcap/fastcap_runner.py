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
import re
import time
from typing import *

import os
import subprocess

from ..log import (
    debug,
    info,
    warning,
    error,
    rule,
    subproc,
)
from ..common.capacitance_matrix import CapacitanceMatrix


def run_fastcap(exe_path: str,
                lst_file_path: str,
                log_path: str,
                expansion_order: float = 2,
                partitioning_depth: str = 'auto',
                permittivity_factor: float = 1.0,
                iterative_tolerance: float = 0.01):
    work_dir = os.path.dirname(lst_file_path)

    # we have to chdir into the directory containing the lst file,
    # so make all paths absolute, and the lst_file relative
    log_path = os.path.abspath(log_path)
    lst_file_path = os.path.basename(lst_file_path)

    info(f"Chdir to {work_dir}")
    os.chdir(work_dir)
    args = [
        exe_path,
        f"-o{expansion_order}",
    ]

    if partitioning_depth != 'auto':
        args += [
            f"-d{partitioning_depth}",
        ]

    args += [
        f"-p{permittivity_factor}",
        f"-t{iterative_tolerance}",
        f"-l{lst_file_path}",
    ]

    info(f"Calling FastCap2")
    subproc(f"{' '.join(args)}, output file: {log_path}")

    rule('FastCap Output')
    start = time.time()

    proc = subprocess.Popen(args,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            universal_newlines=True,
                            text=True)
    with open(log_path, 'w', encoding='utf-8') as f:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            subproc(line[:-1])  # remove newline
            f.writelines([line])
    proc.wait()

    duration = time.time() - start

    rule()

    if proc.returncode == 0:
        info(f"FastCap2 succeeded after {'%.4g' % duration}s")
    else:
        raise Exception(f"FastCap2 failed with status code {proc.returncode} after {'%.4g' % duration}s, "
                        f"see log file: {log_path}")


# CAPACITANCE MATRIX, picofarads
#                     1          2          3          4
# $1%GROUP2 1       7850      -7277      -2115      54.97
# $1%GROUP2 2      -7277  3.778e+05      130.9 -3.682e+05
# $2%GROUP3 3      -2115      130.9       6792      -5388
# $2%GROUP3 4      54.97 -3.682e+05      -5388  3.753e+05
def fastcap_parse_capacitance_matrix(log_path: str) -> CapacitanceMatrix:
    with open(log_path, 'r') as f:
        rlines = f.readlines()
        rlines.reverse()

        # multiple iterations possible, find the last matrix
        for idx, line in enumerate(rlines):
            if line.startswith('CAPACITANCE MATRIX, '):
                section_m = re.match(r'CAPACITANCE MATRIX, (\w+)', line)
                if not section_m:
                    raise Exception(f"Could not parse capacitor unit")
                unit_str = section_m.group(1)

                dimension_line = rlines[idx-1].strip()
                dimensions = dimension_line.split()  # remove whitespace
                dim = len(dimensions)
                conductor_names: List[str] = []
                rows: List[List[float]] = []
                for i in reversed(range(idx-1-dim, idx-1)):
                    line = rlines[i].strip()
                    cells = [cell.strip() for cell in line.split(' ')]
                    if cells[1] != str(i):
                        warning(f"Expected capacitor matrix row to have index {i}, but obtained {cells[1]}")
                    cells.pop(1)
                    cells = list(filter(lambda c: len(c) >= 1, cells))
                    conductor_names.append(cells[0])
                    row = [float(cell)/1e6 for cell in cells[1:]]
                    rows.append(row)
                cm = CapacitanceMatrix(conductor_names=conductor_names, rows=rows)
                return cm

        raise Exception(f"Could not extract capacitance matrix from FasterCap log file {log_path}")
