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
Reads a SPICE netlist (e.g. an extracted netlist, or a simple testbench) as ngspice reads it.

Reads:
    - the elements R, C, L, K, D, M, V, I, E, F, G, H and X, the subcircuits (.subckt, .ends),
      .global, .param and .end
    - the lines as ngspice reads them (see spice_syntax): continuation lines, also across comment lines,
      comments, the title of a deck
    - numbers with SI suffix: T, G, MEG, K, M (milli), MIL (25.4 µ), U, N, P, F, A,
      letters after them are ignored (e.g. 10pF)
    - expressions of parameters as ngspice reads them (see expression/ngspice.py), in {...} or '...',
      or without them in a parameter (e.g. w=w*nf, as BAG writes it): the values of .param, of the parameters
      of subcircuits and their calls and of elements, which the netlist keeps as expressions
      (spice_hierarchy evaluates them in the subcircuit calls)

SPICE is case-insensitive:
    - a node is written as it is first written in its subcircuit (or in .global),
      a node named gnd is ground (as ngspice has it), also a port named so
    - a subcircuit call has the name of the subcircuit's definition (if in the netlist)
    - the parameter names are lowercase

Doesn't read (an error naming the line): .model, .include, .lib, .func, .option, analyses, .control,
expressions in sources, the elements B, Q, J, ...

NOTE: imports neither KLayout nor generated protobuf code, so that format-only paths can use it
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
from typing import *

from ..log import warning
from ..util.unit_formatter import parse_spice_number
from .expression.ngspice import NGSPICE_SYNTAX
from .expression.nodes import Number, NumberOrExpression
from .expression.parser import ExpressionParser, ExpressionSyntaxError
from .spice_syntax import GROUND_NODE_NAMES, SpiceSyntaxError, spice_lines
from .spice_netlist import (
    SpiceElement,
    SpiceNetlist,
    SpiceSource,
    SpiceSourceFunction,
    SpiceSubcircuit,
)


class SpiceReaderError(Exception):
    """
    The netlist is no SPICE netlist the reader reads (e.g. it has .include)
    """
    pass


GROUND = '0'

_SOURCE_FUNCTIONS = ('pulse', 'sin', 'exp', 'pwl', 'sffm', 'am', 'trnoise', 'trrandom')

# NOTE: a statement is split into words of these pieces, the last one catches an unbalanced { } or '
_WORD_PIECE = re.compile(r"\s*(\{[^{}]*\}|'[^']*'|=|[^\s{}'=]+|.)")


def _optional_number(text: str) -> Optional[float]:
    """The SPICE number (see parse_spice_number), None if the text is no number"""
    try:
        return parse_spice_number(text)
    except ValueError:
        return None


@dataclass
class _Line:
    number: int  # of the first line, if continued
    tokens: List[str]


class _Scope:
    """
    The names of a subcircuit (or of the top level), case-insensitive as in SPICE
    """

    def __init__(self, description: str, global_nodes: Dict[str, str]):
        self.description = description
        self.global_nodes = global_nodes
        self.node_by_key: Dict[str, str] = {}
        self.element_line_by_key: Dict[str, int] = {}
        self.element_by_key: Dict[str, str] = {}

    def node(self, name: str) -> str:
        key = name.casefold()
        if key in GROUND_NODE_NAMES:  # NOTE: ngspice takes gnd as ground
            return GROUND
        return self.global_nodes.get(key) or self.node_by_key.setdefault(key, name)

    def port(self, name: str) -> str:
        if name == GROUND:
            # NOTE: VACASK takes a port 0 as a node of the subcircuit, not as ground
            raise SpiceReaderError(f"the port 0 (ground) of {self.description} is not supported")
        if name.casefold() in GROUND_NODE_NAMES:
            # NOTE: ngspice ties the node to ground, the port connects to nothing inside the subcircuit
            warning(f"The port {name} of {self.description} is ground inside the subcircuit, as in ngspice")
            return name
        return self.node(name)

    def add_element(self, name: str, line_number: int):
        key = name.casefold()
        other = self.element_line_by_key.setdefault(key, line_number)
        if other != line_number:
            raise SpiceReaderError(f"the element {name} of {self.description} is there already (line {other})")
        self.element_by_key[key] = name


class SpiceReader:
    # NOTE: a reader of another SPICE flavour (e.g. HSPICE) reads the expressions with its own syntax
    expression_parser = ExpressionParser(NGSPICE_SYNTAX)

    def read(self, path: str | Path) -> SpiceNetlist:
        """
        :raises SpiceReaderError: if the netlist has a line the reader doesn't read (the message names the line)
        """
        with open(path, 'r', encoding='utf-8', errors='surrogateescape') as f:
            text = f.read()
        try:
            return self.parse(text)
        except SpiceReaderError as e:
            raise SpiceReaderError(f"{path}: {e}") from None

    def parse(self, text: str) -> SpiceNetlist:
        netlist = SpiceNetlist()
        global_nodes: Dict[str, str] = {}
        top_scope = _Scope('the top level', global_nodes)
        scope = top_scope
        subcircuit: Optional[SpiceSubcircuit] = None
        subcircuit_scopes: List[Tuple[SpiceSubcircuit, _Scope]] = []

        for line in self._logical_lines(text):
            card = line.tokens[0].lower()
            try:
                if card.startswith('.'):
                    match card:
                        case '.subckt':
                            if subcircuit is not None:
                                raise SpiceReaderError(f"nested subcircuit definitions are not supported "
                                                       f"(in subcircuit {subcircuit.name})")
                            subcircuit, scope = self._subcircuit(line, global_nodes)
                            netlist.subcircuits.append(subcircuit)
                            subcircuit_scopes.append((subcircuit, scope))
                        case '.ends':
                            if subcircuit is None:
                                raise SpiceReaderError(".ends without .subckt")
                            subcircuit, scope = None, top_scope
                        case '.param':
                            parameters = netlist.parameters if subcircuit is None else subcircuit.local_parameters
                            for token in line.tokens[1:]:
                                name, value = self._parameter(token)
                                parameters[name] = value
                        case '.global':
                            for name in line.tokens[1:]:
                                if name.casefold() not in global_nodes:
                                    global_nodes[name.casefold()] = name
                                    netlist.global_nodes.append(name)
                        case '.end':
                            break
                        case _:
                            raise SpiceReaderError(f"{line.tokens[0]} is not supported")
                else:
                    element = self._element(line, scope)
                    scope.add_element(element.name, line.number)
                    if subcircuit is None:
                        netlist.elements.append(element)
                    else:
                        subcircuit.elements.append(element)
            except SpiceReaderError as e:
                raise SpiceReaderError(f"line {line.number}: {e}") from None

        if subcircuit is not None:
            raise SpiceReaderError(f"the subcircuit {subcircuit.name} has no .ends")

        subcircuit_by_key = {s.name.casefold(): s.name for s in netlist.subcircuits}
        for elements, scope in [(s.elements, sc) for s, sc in subcircuit_scopes] + [(netlist.elements, top_scope)]:
            for element in elements:
                if element.kind == 'X':
                    element.model = subcircuit_by_key.get(element.model.casefold(), element.model)
                element.references = [scope.element_by_key.get(r.casefold(), r) for r in element.references]
        return netlist

    # --------------------------------------------------------------------------------

    @staticmethod
    def _logical_lines(text: str) -> Iterator[_Line]:
        try:
            lines = spice_lines(text)
        except SpiceSyntaxError as e:
            raise SpiceReaderError(str(e)) from None
        for line in lines:
            if line.text is None:  # NOTE: a comment line, a blank line or the title
                continue
            try:
                tokens = SpiceReader._tokens(line.text)
            except SpiceReaderError as e:
                raise SpiceReaderError(f"line {line.number}: {e}") from None
            yield _Line(number=line.number, tokens=tokens)

    @staticmethod
    def _tokens(text: str) -> List[str]:
        """
        The words of a statement: an expression in {...} or '...' is one word, also with spaces in it,
        and so is a parameter with spaces around its = (e.g. w = {a + b})
        """
        tokens: List[str] = []
        after_equals = False
        for match in _WORD_PIECE.finditer(text):
            piece = match.group(1)
            if piece in ('{', '}', "'"):
                raise SpiceReaderError(f"{piece} has no counterpart (expressions are written {{...}} or '...')")
            if piece == '=':
                if not tokens:
                    raise SpiceReaderError("= without parameter name")
                tokens[-1] += piece
                after_equals = True
            elif tokens and (after_equals or match.start(1) == match.start(0)):
                tokens[-1] += piece
                after_equals = False
            else:
                tokens.append(piece)
        return tokens

    def _parameter(self, token: str) -> Tuple[str, NumberOrExpression]:
        name, _, text = token.partition('=')
        if not name or not text:
            raise SpiceReaderError(f"the parameter {token} has no {'value' if name else 'name'}")
        return name.lower(), self._value(text, f"parameter {name}")

    def _value(self, text: str, what: str) -> NumberOrExpression:
        """
        A number, or an expression: in {...} or '...', or without them (e.g. w*nf)
        """
        if text[:1] in ('{', "'"):
            text = text[1:-1]
        else:
            number = _optional_number(text)
            if number is not None:
                return number
        try:
            expression = self.expression_parser.parse(text.strip())
        except ExpressionSyntaxError as e:
            raise SpiceReaderError(f"the {what} is no expression ({e})") from None
        if isinstance(expression.root, Number):  # NOTE: e.g. {1u}
            return expression.root.value
        return expression

    def _subcircuit(self,
                    line: _Line,
                    global_nodes: Dict[str, str]) -> Tuple[SpiceSubcircuit, _Scope]:
        if len(line.tokens) < 2:
            raise SpiceReaderError(".subckt without name")
        name = line.tokens[1]
        scope = _Scope(f"subcircuit {name}", global_nodes)
        ports: List[str] = []
        parameters: Dict[str, NumberOrExpression] = {}
        for token in line.tokens[2:]:
            if token.lower() == 'params:':
                continue
            if '=' in token:
                parameter, value = self._parameter(token)
                parameters[parameter] = value
            elif parameters:
                raise SpiceReaderError(f"the port {token} of subcircuit {name} follows its parameters")
            else:
                ports.append(scope.port(token))
        return SpiceSubcircuit(name=name, ports=ports, parameters=parameters), scope

    def _element(self, line: _Line, scope: _Scope) -> SpiceElement:
        tokens = line.tokens
        name = tokens[0]
        kind = name[0].upper()

        def nodes(count: int) -> List[str]:
            if len(tokens) < 1 + count:
                raise SpiceReaderError(f"the element {name} needs {count} nodes")
            return [scope.node(n) for n in tokens[1:1 + count]]

        def parameters(rest: List[str]) -> Dict[str, NumberOrExpression]:
            result: Dict[str, NumberOrExpression] = {}
            for token in rest:
                if '=' not in token:
                    raise SpiceReaderError(f"the element {name} has {token} where a parameter is expected")
                parameter, value = self._parameter(token)
                result[parameter] = value
            return result

        match kind:
            case 'R' | 'C' | 'L':
                element = SpiceElement(name=name, nodes=nodes(2))
                rest = tokens[3:]
                while rest and '=' not in rest[0]:
                    is_value = rest[0][:1] in ('{', "'") or _optional_number(rest[0]) is not None
                    if is_value and element.value is None and element.model is None:
                        element.value = self._value(rest[0], f"value of {name}")
                    elif element.model is None:
                        element.model = rest[0]
                    else:
                        raise SpiceReaderError(f"the element {name} has {rest[0]} where a parameter is expected")
                    rest = rest[1:]
                element.parameters = parameters(rest)
                value_parameter = kind.lower()
                if value_parameter in element.parameters:
                    if element.value is not None:
                        raise SpiceReaderError(f"the element {name} has two values")
                    element.value = element.parameters.pop(value_parameter)
                return element
            case 'K':
                if len(tokens) != 4:
                    raise SpiceReaderError(f"the coupling {name} needs two inductors and a coupling factor")
                return SpiceElement(name=name, references=tokens[1:3],
                                    value=self._value(tokens[3], f"coupling factor of {name}"))
            case 'D' | 'M':
                count = 2 if kind == 'D' else 4
                element = SpiceElement(name=name, nodes=nodes(count))
                if len(tokens) < 2 + count:
                    raise SpiceReaderError(f"the element {name} has no model")
                element.model = tokens[1 + count]
                rest = tokens[2 + count:]
                if kind == 'D' and rest and '=' not in rest[0]:  # the area
                    element.parameters['area'] = self._value(rest[0], f"area of {name}")
                    rest = rest[1:]
                element.parameters.update(parameters(rest))
                return element
            case 'X':
                rest = [t for t in tokens[1:] if t.lower() != 'params:']
                count = next((i for i, t in enumerate(rest) if '=' in t), len(rest)) - 1
                if count < 0:
                    raise SpiceReaderError(f"the subcircuit call {name} has no subcircuit")
                return SpiceElement(name=name, nodes=[scope.node(n) for n in rest[:count]],
                                    model=rest[count], parameters=parameters(rest[count + 1:]))
            case 'V' | 'I':
                element_nodes = nodes(2)
                expression = next((t for t in tokens[3:] if t[:1] in ('{', "'")), None)
                if expression is not None:
                    raise SpiceReaderError(f"the source {name} has the expression {expression}, "
                                           f"which is not supported")
                rest = ' '.join(tokens[3:]).replace('(', ' ').replace(')', ' ').replace(',', ' ').split()
                return SpiceElement(name=name, nodes=element_nodes, source=self._source(name, rest))
            case 'E' | 'G':
                if len(tokens) != 6:
                    raise SpiceReaderError(f"the controlled source {name} needs 4 nodes and a gain "
                                           f"(VALUE, POLY and TABLE are not supported)")
                return SpiceElement(name=name, nodes=nodes(4), value=self._value(tokens[5], f"gain of {name}"))
            case 'F' | 'H':
                if len(tokens) != 5:
                    raise SpiceReaderError(f"the controlled source {name} needs 2 nodes, a voltage source "
                                           f"and a gain (POLY is not supported)")
                return SpiceElement(name=name, nodes=nodes(2), references=[tokens[3]],
                                    value=self._value(tokens[4], f"gain of {name}"))
            case _:
                raise SpiceReaderError(f"the element {name} is not supported (supported are "
                                       f"R, C, L, K, D, M, V, I, E, F, G, H and X)")

    def _source(self, name: str, tokens: List[str]) -> SpiceSource:
        source = SpiceSource()
        i = 0

        def numbers_from(start: int, max_count: int) -> List[float]:
            result = []
            while start + len(result) < len(tokens) and len(result) < max_count:
                value = _optional_number(tokens[start + len(result)])
                if value is None:
                    break
                result.append(value)
            return result

        while i < len(tokens):
            token = tokens[i].lower()
            if token == 'dc':
                values = numbers_from(i + 1, 1)
                if not values:
                    raise SpiceReaderError(f"the source {name} has DC without value")
                source.dc = values[0]
                i += 2
            elif token == 'ac':
                values = numbers_from(i + 1, 2)
                source.ac_magnitude = values[0] if values else 1.0
                source.ac_phase = values[1] if len(values) > 1 else None
                i += 1 + len(values)
            elif token in _SOURCE_FUNCTIONS:
                if source.function is not None:
                    raise SpiceReaderError(f"the source {name} has two functions")
                values = numbers_from(i + 1, len(tokens))
                source.function = SpiceSourceFunction(name=token, arguments=values)
                i += 1 + len(values)
            elif i == 0 and (value := _optional_number(token)) is not None:
                source.dc = value
                i += 1
            else:
                raise SpiceReaderError(f"the source {name} has {tokens[i]}, which is not supported")
        return source
