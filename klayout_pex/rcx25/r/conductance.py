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

from __future__ import annotations
from typing import *


class Conductance:
    """
    An object describing a resistor in terms of conductance
    """

    def __init__(self, cond: float = 0.0):
        self.cond = cond

    def __str__(self) -> str:
        return "%.6g" % self.cond

    def res(self) -> str:
        return "%.6g" % (1.0 / self.cond)

    def copy(self) -> Conductance:
        return Conductance(self.cond)

    def add_parallel(self, other: Conductance) -> Conductance:
        self.cond += other.cond
        return self

    def parallel(self, other: Conductance) -> Conductance:
        return self.copy().add_parallel(other)

    def add_serial(self, other: Conductance) -> Conductance:
        if abs(self.cond) < 1e-10 or abs(other.cond) < 1e-10:
            self.cond = 0.0
        else:
            self.cond = 1.0 / (1.0 / self.cond + 1.0 / other.cond)
        return self

    def serial(self, other: Conductance) -> Conductance:
        return self.copy().add_serial(other)
