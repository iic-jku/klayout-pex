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
Simulations with VACASK (https://codeberg.org/arpadbuermen/VACASK) in tests,
which are skipped where VACASK isn't installed (vacask on PATH)
"""

import os
import shutil
import subprocess
from typing import *

import pytest


VACASK_EXE = shutil.which('vacask')

requires_vacask = pytest.mark.skipif(VACASK_EXE is None, reason='vacask is not on PATH')


def run_vacask(deck_path: str):
    """
    Runs the deck in its directory, where the analyses write their results (e.g. op1.raw)
    """
    result = subprocess.run([VACASK_EXE, os.path.basename(deck_path)], cwd=os.path.dirname(deck_path),
                            capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, f"vacask failed on {deck_path}:\n{result.stdout}\n{result.stderr}"


def read_ascii_raw(path: str) -> Dict[str, List[complex]]:
    """
    The vectors of a raw file of VACASK (options rawfile="ascii"), by name (e.g. x1:out)
    """
    with open(path) as f:
        lines = f.read().splitlines()
    names: List[str] = []
    values: List[complex] = []
    section = None
    for line in lines:
        if line.startswith('Variables:'):
            section = 'variables'
        elif line.startswith('Values:'):
            section = 'values'
        elif section == 'variables':
            names.append(line.split('\t')[2])
        elif section == 'values' and line.strip():
            text = line.split('\t')[-1]
            real, _, imag = text.partition(',')
            values.append(complex(float(real), float(imag or 0.0)))
    point_count = len(values) // len(names)
    return {name: [values[point * len(names) + i] for point in range(point_count)]
            for i, name in enumerate(names)}
