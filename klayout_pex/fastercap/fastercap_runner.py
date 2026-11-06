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
import subprocess
import time
from typing import *

from ..log import (
    info,
    # warning,
    rule,
    subproc,
)
from ..common.capacitance_matrix import CapacitanceMatrix
from .fastercap_error import FasterCapError


# NOTE: the exit codes of FasterCap 6.2 (see the README of iic-jku/FasterCap), earlier versions exit 0 or 1.
#       75 fails the run too, as the matrix it prints, the one of the last iteration, misses the tolerance
FASTERCAP_EXIT_CODE_MEANINGS: Dict[int, str] = {
    1: "other error",
    64: "wrong command line",
    65: "the matrix has NaN or infinite entries",
    66: "the input file can't be opened",
    71: "out of memory",
    74: "the input can't be read",
    75: "GMRES didn't converge",
    97: "the run can't go out-of-core",
    98: "unexpected exception",
    125: "stopped, e.g. by Ctrl-C or SIGTERM",
}


def run_fastercap(exe_path: str,
                  lst_file_path: str,
                  log_path: str,
                  tolerance: float,
                  d_coeff: float,
                  ooc_condition: Optional[int],
                  auto_preconditioner: bool,
                  galerkin_scheme: bool,
                  jacobi_preconditioner: bool):
    args = [
        exe_path,
        '-b',                          # console mode, without GUI
        '-i',                          # Dump detailed time and memory information
        '-v',                          # Verbose output
        f"-a{tolerance}",              # stop when relative error lower than threshold
        f"-d{d_coeff}",                # Direct potential interaction coefficient to mesh refinement ratio
        # NOTE: no -m (mesh relative refinement value), the automatic refinement (-a) overrides it
    ]

    if ooc_condition is not None:
        args += [f"-f{ooc_condition}"]
    
    if auto_preconditioner:
        args += ['-ap']

    if galerkin_scheme:
        args += ['-g']

    if jacobi_preconditioner:
        args += ['-pj']

    args += [
        lst_file_path
    ]
    info(f"Calling FasterCap")
    subproc(f"{' '.join(args)}, output file: {log_path}")

    rule('FasterCap Output')
    start = time.time()

    proc = subprocess.Popen(args,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            universal_newlines=True,
                            text=True,
                            encoding='utf-8',
                            errors='replace')
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
        info(f"FasterCap succeeded after {'%.4g' % duration}s")
    else:
        meaning = FASTERCAP_EXIT_CODE_MEANINGS.get(proc.returncode, None)
        raise FasterCapError(f"FasterCap failed with exit code {proc.returncode}"
                             f"{f' ({meaning})' if meaning else ''} after {'%.4g' % duration}s, "
                             f"see log file: {log_path}")


def fastercap_parse_capacitance_matrix(log_path: str) -> CapacitanceMatrix:
    with open(log_path, 'r', encoding='utf-8') as f:
        rlines = f.readlines()
        rlines.reverse()

        # multiple iterations possible, find the last matrix
        for idx, line in enumerate(rlines):
            if line.strip() == "Capacitance matrix is:":
                m = re.match(r'^Dimension (\d+) x (\d+)$', rlines[idx-1])
                if not m:
                    raise FasterCapError(f"Could not parse capacitor matrix dimensions")
                dim = int(m.group(1))
                conductor_names: List[str] = []
                rows: List[List[float]] = []
                for i in reversed(range(idx-1-dim, idx-1)):
                    line = rlines[i].strip()
                    cells = [cell.strip() for cell in line.split(' ')]
                    cells = list(filter(lambda c: len(c) >= 1, cells))
                    conductor_names.append(cells[0])
                    row = [float(cell)/1e6 for cell in cells[1:]]
                    rows.append(row)
                cm = CapacitanceMatrix(conductor_names=conductor_names, rows=rows)
                return cm

        raise FasterCapError(f"Could not extract capacitance matrix from FasterCap log file {log_path}")
