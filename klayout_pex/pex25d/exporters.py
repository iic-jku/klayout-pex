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
Generation of solver-native input files from a ``PEX25DScene``.

The specification calls these solver *adapters*; this module is named after the
operation the CLI exposes, ``pex25d export``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import *


class SolverTarget(StrEnum):
    """Engines a PEX25D scene can be written out for."""

    FASTERCAP = 'fastercap'
    FASTCAP2 = 'fastcap2'

    DEFAULT = 'fastercap'


def export(scene: Any,
           target: SolverTarget,
           output_dir_path: str,
           prefix: str = '') -> List[str]:
    """
    Export ``scene`` as native input for ``target`` into ``output_dir_path``.

    Does not run the engine.

    :return: the paths written, most significant first — for FasterCap the
        ``.lst`` file, followed by the per-surface files it references.
    """
    raise NotImplementedError(f"PEX25D → {target.value} input generation")
