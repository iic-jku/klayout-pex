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
            - +dielname: include choice named 'dielname' (based on none, which may be left out)
            - -dielname: exclude choice named 'dielname' (based on all, which may be left out)
        Names are compared regardless of case.
        Examples:
            - all,-nild5,-nild6 or -nild5,-nild6
               - include all dielectrics except nild5 and nild6
            - none,+nild5,+capild or +nild5,+capild
                - include only dielectrics named nild5 and capild

        :raises ValueError: for any other subpattern, or a combination of them that contradicts itself
        """
        self.pattern = pattern

        components = pattern.split(sep=',')
        components = [c.lower().strip() for c in components]
        invalid = [c for c in components
                   if c not in ('all', 'none') and not (c[:1] in ('+', '-') and c[1:].strip())]
        if invalid:
            raise ValueError(f"Multiple choice pattern can only have the subpatterns all, none, +name and -name, "
                             f"not {', '.join(repr(c) for c in invalid)}")
        self.has_all = 'all' in components
        self.has_none = 'none' in components
        self.included = [c[1:].strip() for c in components if c.startswith('+')]
        self.excluded = [c[1:].strip() for c in components if c.startswith('-')]
        if self.has_none and self.has_all:
            raise ValueError("Multiple choice pattern can't have both subpatterns all and none")
        if self.has_none and len(self.excluded) >= 1:
            raise ValueError("Multiple choice pattern based on none can only have inclusive (+) subpatterns")
        if self.has_all and len(self.included) >= 1:
            raise ValueError("Multiple choice pattern based on all can only have exclusive (-) subpatterns")
        if self.included and self.excluded:
            raise ValueError("Multiple choice pattern can't have both inclusive (+) and exclusive (-) subpatterns")
        if not (self.has_all or self.has_none):
            # NOTE: +name includes into none, -name excludes from all
            self.has_none = bool(self.included)
            self.has_all = not self.has_none

    def filter(self, choices: List[str]) -> List[str]:
        return [c for c in choices if self.is_included(c)]

    def is_included(self, choice: str) -> bool:
        if self.has_none:
            return choice.lower() in self.included
        return choice.lower() not in self.excluded

    def unknown_choices(self, choices: List[str]) -> List[str]:
        """
        :return: the names of the subpatterns that aren't among the choices (lowercase)
        """
        known_choices = {c.lower() for c in choices}
        return [name for name in dict.fromkeys(self.included + self.excluded) if name not in known_choices]
