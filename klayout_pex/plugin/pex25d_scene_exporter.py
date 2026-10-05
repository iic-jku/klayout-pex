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

"""PEX25D scene exporter metadata and lazy registration helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from ..plugin_api.v1 import ExporterFactory


@dataclass(frozen=True)
class ExporterInfo:
    """Metadata available without importing the exporter implementation."""

    name: str
    distribution: str

    @property
    def qualified_name(self) -> str:
        """An explicit selector, e.g. ``klayout-pex:fastercap``.

        Distribution names follow PyPA normalization. Exporter names remain
        case-sensitive. This requires no external packaging dependency.
        """
        distribution = re.sub(r'[-_.]+', '-', self.distribution).lower()
        return f'{distribution}:{self.name}'


@dataclass(frozen=True)
class ExporterRegistration:
    """Associate metadata with a loader that defers importing its factory."""

    info: ExporterInfo
    load_factory: Callable[[], ExporterFactory]
    builtin: bool = False


__all__ = ['ExporterInfo', 'ExporterRegistration']
