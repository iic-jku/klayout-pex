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

import os
import time
from typing import *

import subprocess

from ..log import (
    info,
    # warning,
    rule,
    subproc,
)


SKIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'analog_skin.svg')
"""The analog skin of netlistsvg (its lib/analog.svg), shipped as package data"""


class NetlistSVGError(Exception):
    pass


def run_netlistsvg(exe_path: str,
                   skin_path: str,
                   yosys_json_netlist_path: str,
                   output_svg_path: str,
                   layout_elk_path: Optional[str]):
    """
    :raises NetlistSVGError: if netlistsvg can't be started or fails
    """
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
    subproc(' '.join(args))

    rule('netlistsvg Output')

    start = time.time()

    try:
        proc = subprocess.Popen(args,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True,
                                encoding='utf-8',
                                errors='replace')
    except OSError as e:
        raise NetlistSVGError(f"Can't run netlistsvg {exe_path}: {e}") from e
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        subproc(line[:-1])  # remove newline
    proc.wait()

    duration = time.time() - start

    rule()

    if proc.returncode == 0:
        info(f"netlistsvg succeeded after {'%.4g' % duration}s")
    else:
        raise NetlistSVGError(f"netlistsvg failed with status code {proc.returncode} "
                              f"after {'%.4g' % duration}s, see its output above")
