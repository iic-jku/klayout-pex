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
Expressions of netlist parameters (e.g. w*nf), as trees of their operations, and their evaluation.

The tree doesn't depend on how a netlist flavour writes the expression (see syntax.py), and its operators
compute as in C: e.g. % is the remainder with the sign of the dividend, a comparison is 1 or 0.

NOTE: imports neither KLayout nor generated protobuf code, so that format-only paths can use it
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import math
import operator
from typing import *


class ExpressionError(Exception):
    """
    An expression without value, e.g. of a parameter that is not defined, or with a division by zero
    """
    pass


class Scope(Protocol):
    """
    The values of the parameters an expression refers to
    """

    def value(self, name: str) -> float:
        """
        :raises ExpressionError: if the scope has no parameter of that name, or it has no value
        """
        ...


def _checked(name: str, function: Callable[..., float], *arguments: float) -> float:
    """
    :raises ExpressionError: if the function has no finite value for the arguments, e.g. sqrt(-1)
    """
    try:
        result = function(*arguments)
    except ZeroDivisionError:
        raise ExpressionError("division by zero") from None
    except (ArithmeticError, ValueError):
        result = math.nan
    if not math.isfinite(result):
        raise ExpressionError(f"{name}({', '.join(f'{a:g}' for a in arguments)}) has no finite value")
    return float(result)


class UnaryOperator(Enum):
    NEGATIVE = 'negative'
    POSITIVE = 'positive'
    NOT = 'not'


class BinaryOperator(Enum):
    OR = 'or'
    AND = 'and'
    EQUAL = 'equal'
    NOT_EQUAL = 'not equal'
    LESS = 'less'
    LESS_EQUAL = 'less or equal'
    GREATER = 'greater'
    GREATER_EQUAL = 'greater or equal'
    ADD = 'add'
    SUBTRACT = 'subtract'
    MULTIPLY = 'multiply'
    DIVIDE = 'divide'
    REMAINDER = 'remainder'
    POWER = 'power'


_UNARY_FUNCTIONS: Dict[UnaryOperator, Callable[[float], float]] = {
    UnaryOperator.NEGATIVE: operator.neg,
    UnaryOperator.POSITIVE: operator.pos,
    UnaryOperator.NOT: lambda x: float(not x),
}

# NOTE: but AND and OR, which evaluate their right operand only if needed
_BINARY_FUNCTIONS: Dict[BinaryOperator, Callable[[float, float], float]] = {
    BinaryOperator.EQUAL: lambda a, b: float(a == b),
    BinaryOperator.NOT_EQUAL: lambda a, b: float(a != b),
    BinaryOperator.LESS: lambda a, b: float(a < b),
    BinaryOperator.LESS_EQUAL: lambda a, b: float(a <= b),
    BinaryOperator.GREATER: lambda a, b: float(a > b),
    BinaryOperator.GREATER_EQUAL: lambda a, b: float(a >= b),
    BinaryOperator.ADD: operator.add,
    BinaryOperator.SUBTRACT: operator.sub,
    BinaryOperator.MULTIPLY: operator.mul,
    BinaryOperator.DIVIDE: operator.truediv,
    BinaryOperator.REMAINDER: math.fmod,
    BinaryOperator.POWER: math.pow,
}


@dataclass(frozen=True)
class ExpressionFunction:
    """
    A function that expressions call, e.g. sqrt
    """
    name: str
    arity: int
    implementation: Callable[..., float]

    def __call__(self, *arguments: float) -> float:
        """
        :raises ExpressionError: if the function has no finite value for the arguments, e.g. sqrt(-1)
        """
        return _checked(self.name, self.implementation, *arguments)


class Node(ABC):
    """
    An operation of an expression, or a number, or a parameter
    """

    @abstractmethod
    def evaluate(self, scope: Scope) -> float:
        """
        :raises ExpressionError: if the expression has no value in the scope
        """
        ...


@dataclass(frozen=True)
class Number(Node):
    value: float

    def evaluate(self, scope: Scope) -> float:
        return self.value


@dataclass(frozen=True)
class Parameter(Node):
    name: str  # as the scope names it (e.g. lowercase for a flavour that ignores case)

    def evaluate(self, scope: Scope) -> float:
        return scope.value(self.name)


@dataclass(frozen=True)
class UnaryOperation(Node):
    operator: UnaryOperator
    operand: Node

    def evaluate(self, scope: Scope) -> float:
        return _UNARY_FUNCTIONS[self.operator](self.operand.evaluate(scope))


@dataclass(frozen=True)
class BinaryOperation(Node):
    operator: BinaryOperator
    left: Node
    right: Node

    def evaluate(self, scope: Scope) -> float:
        left = self.left.evaluate(scope)
        match self.operator:
            case BinaryOperator.AND:
                return float(bool(left) and bool(self.right.evaluate(scope)))
            case BinaryOperator.OR:
                return float(bool(left) or bool(self.right.evaluate(scope)))
        return _checked(self.operator.value, _BINARY_FUNCTIONS[self.operator], left, self.right.evaluate(scope))


@dataclass(frozen=True)
class Conditional(Node):
    """
    condition ? if_true : if_false, which evaluates only the operand it takes
    """
    condition: Node
    if_true: Node
    if_false: Node

    def evaluate(self, scope: Scope) -> float:
        return (self.if_true if self.condition.evaluate(scope) else self.if_false).evaluate(scope)


@dataclass(frozen=True)
class FunctionCall(Node):
    function: ExpressionFunction
    arguments: Tuple[Node, ...]

    def evaluate(self, scope: Scope) -> float:
        return self.function(*(a.evaluate(scope) for a in self.arguments))


@dataclass(frozen=True)
class Expression:
    """
    An expression as a netlist writes it (text) and as tree of its operations (root)
    """
    text: str
    root: Node

    def evaluate(self, scope: Scope) -> float:
        """
        :raises ExpressionError: if the expression has no value in the scope
        """
        return self.root.evaluate(scope)

    def __str__(self) -> str:
        return self.text


NumberOrExpression = Union[float, Expression]
"""A value of a netlist, e.g. of a parameter"""
