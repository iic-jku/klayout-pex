#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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

"""Bounded fixed-mesh field solves shared by geometry regression tests."""

from pathlib import Path
import shutil
import subprocess

from kpex.common.capacitance_matrix import CapacitanceMatrix
from kpex.fastercap.fastercap_runner import fastercap_parse_capacitance_matrix


def solve_fastercap(deck: str, log: Path, mesh: float) -> CapacitanceMatrix:
    # Automatic -a uses a global matrix criterion and may over-refine dominant
    # entries while weak coupling remains poorly resolved. Fix mesh and tighten
    # GMRES separately so tests can assess each matrix entry under refinement.
    args = [shutil.which('FasterCap'), '-b', '-v', f'-m{mesh}', '-t1e-7', '-d0.1', '-f0', '-ap', deck]
    with log.open('w', encoding='utf-8') as output:
        try:
            result = subprocess.run(args, stdout=output, stderr=subprocess.STDOUT, timeout=180)
        except subprocess.TimeoutExpired as exc:
            raise AssertionError(f'FasterCap timed out\n{log.read_text(encoding="utf-8", errors="replace")}') from exc
    assert result.returncode == 0, log.read_text(encoding='utf-8', errors='replace')
    return fastercap_parse_capacitance_matrix(str(log))
