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
Parses expressions with the syntax of a netlist flavour (see syntax.py).

Besides the operators of the syntax, it reads parentheses, function calls, and the conditional c ? a : b,
which binds weakest, from the right (as in C).

NOTE: imports neither KLayout nor generated protobuf code, so that format-only paths can use it
"""

from __future__ import annotations
from dataclasses import dataclass
import re
from typing import *

from .nodes import (
    BinaryOperation,
    Conditional,
    Expression,
    ExpressionError,
    FunctionCall,
    Node,
    Number,
    Parameter,
    UnaryOperation,
)
from .syntax import Associativity, ExpressionSyntax


class ExpressionSyntaxError(ExpressionError):
    """
    A text that is no expression of the syntax, e.g. with an unknown function
    """
    pass


_NAME = r'[A-Za-z_][A-Za-z0-9_]*'
_PUNCTUATION = ('(', ')', ',', '?', ':')


@dataclass(frozen=True)
class _Token:
    kind: str  # 'number', 'name', 'symbol' or 'end'
    text: str
    column: int  # counted from 1


class ExpressionParser:
    def __init__(self, syntax: ExpressionSyntax):
        self.syntax = syntax
        symbols = sorted({*syntax.binary_operators, *syntax.unary_operators, *_PUNCTUATION}, key=len, reverse=True)
        self._token_pattern = re.compile(rf"\s*(?:(?P<number>{syntax.number_pattern})"
                                         rf"|(?P<name>{_NAME})"
                                         rf"|(?P<symbol>{'|'.join(re.escape(s) for s in symbols)}))")

    def parse(self, text: str) -> Expression:
        """
        :raises ExpressionSyntaxError: if the text is no expression of the syntax
        """
        return Expression(text=text, root=_Parse(self.syntax, text, self._tokens(text)).expression())

    def _tokens(self, text: str) -> List[_Token]:
        tokens: List[_Token] = []
        position = 0
        while text[position:].strip():
            match = self._token_pattern.match(text, position)
            if match is None:
                column = len(text) - len(text[position:].lstrip()) + 1
                raise ExpressionSyntaxError(f"{text}: unexpected {text[column - 1]!r} at column {column}")
            kind = match.lastgroup
            tokens.append(_Token(kind=kind, text=match.group(kind), column=match.start(kind) + 1))
            position = match.end()
        tokens.append(_Token(kind='end', text='', column=len(text) + 1))
        return tokens


class _Parse:
    """
    One expression, parsed by precedence climbing
    """

    def __init__(self, syntax: ExpressionSyntax, text: str, tokens: List[_Token]):
        self.syntax = syntax
        self.text = text
        self.tokens = tokens
        self.index = 0

    def expression(self) -> Node:
        node = self.conditional()
        if self.peek().kind != 'end':
            raise self.unexpected()
        return node

    # --------------------------------------------------------------------------------

    def peek(self) -> _Token:
        return self.tokens[self.index]

    def next(self) -> _Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def accept(self, symbol: str) -> bool:
        token = self.peek()
        if token.kind == 'symbol' and token.text == symbol:
            self.index += 1
            return True
        return False

    def expect(self, symbol: str):
        if not self.accept(symbol):
            raise self.unexpected(f"{symbol!r} expected")

    def unexpected(self, expected: Optional[str] = None) -> ExpressionSyntaxError:
        token = self.peek()
        found = 'ends early' if token.kind == 'end' else f"unexpected {token.text!r} at column {token.column}"
        return ExpressionSyntaxError(f"{self.text}: {found}" + (f", {expected}" if expected else ''))

    # --------------------------------------------------------------------------------

    def conditional(self) -> Node:
        condition = self.binary(0)
        if not self.accept('?'):
            return condition
        if_true = self.conditional()
        self.expect(':')
        return Conditional(condition=condition, if_true=if_true, if_false=self.conditional())

    def binary(self, min_precedence: int) -> Node:
        node = self.unary()
        while True:
            token = self.peek()
            operator = self.syntax.binary_operators.get(token.text) if token.kind == 'symbol' else None
            if operator is None or operator.precedence < min_precedence:
                return node
            self.next()
            right_precedence = operator.precedence + (operator.associativity == Associativity.LEFT)
            node = BinaryOperation(operator=operator.operator, left=node, right=self.binary(right_precedence))

    def unary(self) -> Node:
        token = self.peek()
        operator = self.syntax.unary_operators.get(token.text) if token.kind == 'symbol' else None
        if operator is None:
            return self.primary()
        self.next()
        return UnaryOperation(operator=operator, operand=self.binary(self.syntax.unary_precedence))

    def primary(self) -> Node:
        token = self.next()
        if token.kind == 'number':
            return Number(self.syntax.parse_number(token.text))
        if token.kind == 'name':
            if self.accept('('):
                return self.function_call(token)
            return Parameter(self.syntax.name_key(token.text))
        if token.kind == 'symbol' and token.text == '(':
            node = self.conditional()
            self.expect(')')
            return node
        self.index -= 1
        raise self.unexpected()

    def function_call(self, name: _Token) -> Node:
        function = self.syntax.functions.get(self.syntax.name_key(name.text))
        if function is None:
            raise ExpressionSyntaxError(f"{self.text}: unknown function {name.text} "
                                        f"(known are {', '.join(sorted(self.syntax.functions))})")
        arguments: List[Node] = []
        if not self.accept(')'):
            arguments.append(self.conditional())
            while self.accept(','):
                arguments.append(self.conditional())
            self.expect(')')
        if len(arguments) != function.arity:
            raise ExpressionSyntaxError(f"{self.text}: {function.name} takes {function.arity} "
                                        f"argument{'s' if function.arity != 1 else ''}, not {len(arguments)}")
        return FunctionCall(function=function, arguments=tuple(arguments))
