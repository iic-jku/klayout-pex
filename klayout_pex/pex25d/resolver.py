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

"""Resolution of a ``PEX25DFile`` into a ``PEX25DScene``."""

from __future__ import annotations

from typing import *

from .diagnostics import DiagnosticsReport


def resolve(pex25d_file: Any,
            report: Optional[DiagnosticsReport] = None,
            strict: bool = False) -> Any:
    """
    Resolve a ``kpex.pex25d.PEX25DFile`` into a ``kpex.pex25d.PEX25DScene``.

    Derives absolute z extents, resolves ``CONNECTS`` / ``BETWEEN`` / ``WRAPS``,
    flattens the wrap chain to a depth number and computes terminal
    intersections.

    :param strict: additionally run the geometric tier — ring simplicity, hole
        containment, same-depth overlap.
    """
    raise NotImplementedError("PEX25D resolver")
