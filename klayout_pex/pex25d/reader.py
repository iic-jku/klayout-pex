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

"""PEX25D text format reader."""

from __future__ import annotations

from typing import *

from .diagnostics import DiagnosticsReport


def read_pex25d_text(data: bytes,
                     source_name: Optional[str] = None,
                     report: Optional[DiagnosticsReport] = None) -> Any:
    """
    Parse the PEX25D text format into a ``kpex.pex25d.PEX25DFile``.

    :param data: raw UTF-8 bytes of the top-level file. ``INCLUDE`` is textual,
        so the result covers the whole include tree, flattened.
    :param source_name: path used for ``SourceRef.file`` and for resolving
        relative includes; for ``-`` they resolve against the current directory.
    :param report: collects syntax- and semantic-tier diagnostics. A malformed
        file yields diagnostics; only an unreadable one raises.
    """
    raise NotImplementedError("PEX25D text reader")
