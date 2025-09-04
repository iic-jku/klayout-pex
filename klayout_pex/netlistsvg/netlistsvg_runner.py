#! /usr/bin/env python3
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

import time
from typing import *

import subprocess

from ..log import (
    info,
    # warning,
    rule,
    subproc,
)


def run_netlistsvg(exe_path: str,
                   skin_path: str,
                   yosys_json_netlist_path: str,
                   output_svg_path: str,
                   layout_elk_path: Optional[str],
                   log_path: str):
    args = [
        exe_path,
        '-o', output_svg_path,
        '--skin', skin_path,
    ]
    if layout_elk_path is not None:
        args += [
            '--layout', layout_elk_path
        ]
    args += [
        yosys_json_netlist_path,
    ]

    info('Calling netlistsvg')
    subproc(f"{' '.join(args)}, output file: {log_path}")

    rule('netlistsvg Output')

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
        info(f"netlistsvg succeeded after {'%.4g' % duration}s")
    else:
        raise Exception(f"netlistsvg failed with status code {proc.returncode} after {'%.4g' % duration}s, "
                        f"see log file: {log_path}")

