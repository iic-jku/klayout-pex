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

from __future__ import annotations
from enum import StrEnum


class NetlistFormat(StrEnum):
    """
    The formats of the netlists KPEX writes
    """
    SPICE = 'spice'
    VACASK = 'vacask'  # an include file of the VACASK simulator (https://codeberg.org/arpadbuermen/VACASK)

    @property
    def file_extension(self) -> str:
        match self:
            case NetlistFormat.SPICE:
                return '.spice'
            case NetlistFormat.VACASK:
                return '.inc'  # NOTE: as the include files of the VACASK views of PDKs
