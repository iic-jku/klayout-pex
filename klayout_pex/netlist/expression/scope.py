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
The scope of parameters, e.g. of a subcircuit call: their definitions, numbers or expressions,
evaluated when first asked for, in that scope. A definition that refers to its own name (e.g. w=w*2)
refers to the parameter of that name in the parent scope.

How the scopes of a netlist nest (e.g. a subcircuit call in the scope of its caller) is up to its flavour.

NOTE: imports neither KLayout nor generated protobuf code, so that format-only paths can use it
"""

from __future__ import annotations
from typing import *

from .nodes import Expression, ExpressionError, NumberOrExpression, Scope


class ParameterScope:
    def __init__(self,
                 definitions: Mapping[str, NumberOrExpression],
                 parent: Optional[Scope] = None):
        """
        :param definitions: the parameters by name, as the expressions name them
                            (e.g. lowercase for a flavour that ignores case), in any order
        :param parent: the scope of the parameters these definitions don't define
        """
        self.definitions = definitions
        self.parent = parent
        self._values: Dict[str, float] = {}
        self._evaluating: List[str] = []

    def value(self, name: str) -> float:
        """
        :raises ExpressionError: if the parameter is not defined, or its definition has no value
                                 (e.g. it depends on itself)
        """
        value = self._values.get(name)
        if value is not None:
            return value
        if name not in self.definitions or self._evaluating[-1:] == [name]:
            if self.parent is None:
                raise ExpressionError(f"the parameter {name} is not defined")
            return self.parent.value(name)
        if name in self._evaluating:
            cycle = self._evaluating[self._evaluating.index(name):] + [name]
            raise ExpressionError(f"the parameter {name} depends on itself ({' → '.join(cycle)})")
        self._evaluating.append(name)
        try:
            value = self.evaluate(self.definitions[name])
        finally:
            self._evaluating.pop()
        self._values[name] = value
        return value

    def evaluate(self, value: NumberOrExpression) -> float:
        """
        The value of a number or expression in this scope

        :raises ExpressionError: if the expression has no value in this scope
        """
        if isinstance(value, Expression):
            return value.evaluate(self)
        return float(value)
