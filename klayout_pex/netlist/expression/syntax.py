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
How a netlist flavour writes expressions (e.g. ngspice, see ngspice.py): the spelling and precedence
of its operators, its functions, its numbers, and whether it ignores the case of names.

The parser (see parser.py) reads the expressions of any flavour with its syntax.

NOTE: imports neither KLayout nor generated protobuf code, so that format-only paths can use it
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import *

from .nodes import BinaryOperator, ExpressionFunction, UnaryOperator


class Associativity(Enum):
    LEFT = 'left'  # a - b - c is (a - b) - c
    RIGHT = 'right'  # a ** b ** c is a ** (b ** c)


@dataclass(frozen=True)
class BinaryOperatorSyntax:
    operator: BinaryOperator
    precedence: int  # the higher, the stronger it binds
    associativity: Associativity = Associativity.LEFT


@dataclass(frozen=True)
class ExpressionSyntax:
    binary_operators: Mapping[str, BinaryOperatorSyntax]
    """by spelling, e.g. '**'"""

    unary_operators: Mapping[str, UnaryOperator]
    """by spelling, e.g. '-'"""

    unary_precedence: int
    """compared with the binary operators, e.g. -2^2 is -(2^2), if ^ has a higher one"""

    functions: Mapping[str, ExpressionFunction]
    """by name, in lowercase if the flavour ignores the case of names"""

    number_pattern: str
    """the regular expression of a number, e.g. of 1.5k"""

    parse_number: Callable[[str], float]
    """the value of a number (a match of number_pattern)"""

    ignores_case: bool
    """whether e.g. W and w are the same parameter"""

    def name_key(self, name: str) -> str:
        """
        The name of a parameter or function, as its syntax compares it
        """
        return name.lower() if self.ignores_case else name
