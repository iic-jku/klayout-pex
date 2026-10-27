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
The expressions of ngspice (as of ngspice-46), e.g. of .param, {...} and '...':
    - operators, from the weakest: c ? a : b, ||, &&, == !=, < <= > >=, + -, * / %, the unary - + !, ^ **
      (e.g. -2^2 is -4, 2*-3 is -6)
    - ^ and ** bind from the left (2^3^2 is 64), % is the remainder with the sign of the dividend
    - numbers with SI suffix (e.g. 1.5u, 2meg), letters after it are ignored (10pF)
    - functions as in ngspice: e.g. log is the natural logarithm, pwr(x, y) is |x|^y,
      nint rounds half to even, int towards zero
    - names (of parameters and functions) in any case

NOTE: imports neither KLayout nor generated protobuf code, so that format-only paths can use it
"""

from __future__ import annotations
import math
from typing import *

from ...util.unit_formatter import parse_spice_number
from .nodes import BinaryOperator, ExpressionFunction, UnaryOperator
from .syntax import Associativity, BinaryOperatorSyntax, ExpressionSyntax


def _sign(x: float) -> float:
    return float((x > 0) - (x < 0))


_FUNCTIONS = [
    ExpressionFunction('abs', 1, abs),
    ExpressionFunction('sqrt', 1, math.sqrt),
    ExpressionFunction('exp', 1, math.exp),
    ExpressionFunction('ln', 1, math.log),
    ExpressionFunction('log', 1, math.log),
    ExpressionFunction('log10', 1, math.log10),
    ExpressionFunction('pow', 2, math.pow),
    ExpressionFunction('pwr', 2, lambda x, y: math.pow(abs(x), y)),
    ExpressionFunction('sgn', 1, _sign),
    ExpressionFunction('min', 2, min),
    ExpressionFunction('max', 2, max),
    ExpressionFunction('int', 1, lambda x: float(math.trunc(x))),
    ExpressionFunction('nint', 1, lambda x: float(round(x))),
    ExpressionFunction('floor', 1, lambda x: float(math.floor(x))),
    ExpressionFunction('ceil', 1, lambda x: float(math.ceil(x))),
    ExpressionFunction('sin', 1, math.sin),
    ExpressionFunction('cos', 1, math.cos),
    ExpressionFunction('tan', 1, math.tan),
    ExpressionFunction('asin', 1, math.asin),
    ExpressionFunction('acos', 1, math.acos),
    ExpressionFunction('atan', 1, math.atan),
    ExpressionFunction('arctan', 1, math.atan),
    ExpressionFunction('sinh', 1, math.sinh),
    ExpressionFunction('cosh', 1, math.cosh),
    ExpressionFunction('tanh', 1, math.tanh),
    ExpressionFunction('asinh', 1, math.asinh),
    ExpressionFunction('acosh', 1, math.acosh),
    ExpressionFunction('atanh', 1, math.atanh),
    ExpressionFunction('ternary_fcn', 3, lambda c, a, b: a if c else b),
]


def _operators(precedence: int,
               spellings: Dict[str, BinaryOperator],
               associativity: Associativity = Associativity.LEFT) -> Dict[str, BinaryOperatorSyntax]:
    return {s: BinaryOperatorSyntax(o, precedence, associativity) for s, o in spellings.items()}


NGSPICE_SYNTAX = ExpressionSyntax(
    binary_operators={
        **_operators(1, {'||': BinaryOperator.OR}),
        **_operators(2, {'&&': BinaryOperator.AND}),
        **_operators(3, {'==': BinaryOperator.EQUAL, '!=': BinaryOperator.NOT_EQUAL}),
        **_operators(4, {'<': BinaryOperator.LESS, '<=': BinaryOperator.LESS_EQUAL,
                         '>': BinaryOperator.GREATER, '>=': BinaryOperator.GREATER_EQUAL}),
        **_operators(5, {'+': BinaryOperator.ADD, '-': BinaryOperator.SUBTRACT}),
        **_operators(6, {'*': BinaryOperator.MULTIPLY, '/': BinaryOperator.DIVIDE, '%': BinaryOperator.REMAINDER}),
        **_operators(8, {'^': BinaryOperator.POWER, '**': BinaryOperator.POWER}),
    },
    unary_operators={'-': UnaryOperator.NEGATIVE, '+': UnaryOperator.POSITIVE, '!': UnaryOperator.NOT},
    unary_precedence=7,
    functions={f.name: f for f in _FUNCTIONS},
    number_pattern=r'(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[A-Za-z]*',
    parse_number=parse_spice_number,
    ignores_case=True,
)
