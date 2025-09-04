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


class MultipleChoicePattern:
    def __init__(self, pattern: str):
        """
        Multiple Choice pattern, allows blacklisting and whitelisting.
        For example, given a list of dielectric, let the user decide which of them to include or exclude.
        Allowed patterns:
            - all (default): complete list of choices included
            - none: no choices included at all
            - +dielname: include choice named 'dielname'
            - -dielname: exclude choice named 'dielname'
        Examples:
            - all,-nild5,-nild6
               - include all dielectrics except nild5 and nild6
            - none,+nild5,+capild
                - include only dielectrics named nild5 and capild
        """
        self.pattern = pattern

        components = pattern.split(sep=',')
        components = [c.lower().strip() for c in components]
        self.has_all = 'all' in components
        self.has_none = 'none' in components
        self.included = [c[1:] for c in components if c.startswith('+')]
        self.excluded = [c[1:] for c in components if c.startswith('-')]
        if self.has_none and self.has_all:
            raise ValueError("Multiple choice pattern can't have both subpatterns all and none")
        if self.has_none and len(self.excluded) >= 1:
            raise ValueError("Multiple choice pattern based on none can only have inclusive (+) subpatterns")
        if self.has_all and len(self.included) >= 1:
            raise ValueError("Multiple choice pattern based on all can only have exclusive (-) subpatterns")

    def filter(self, choices: List[str]) -> List[str]:
        if self.has_all:
            return [c for c in choices if c not in self.excluded]
        return [c for c in choices if c in self.included]

    def is_included(self, choice: str) -> bool:
        if self.has_none:
            return choice in self.included
        if self.has_all:
            return choice not in self.excluded
        return False
