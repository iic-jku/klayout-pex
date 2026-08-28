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

"""The reference PEX25D validator."""

from __future__ import annotations

from typing import *

from .diagnostics import DiagnosticsReport


def validate(message: Any,
             report: DiagnosticsReport,
             strict: bool = False) -> None:
    """
    Validate a ``PEX25DFile`` or ``PEX25DScene``, appending findings to ``report``.

    An invalid file is reported through the diagnostics, not through an
    exception; only an input that cannot be read at all raises.

    :param strict: additionally run the geometric tier.
    """
    raise NotImplementedError("PEX25D reference validator")
