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
The lines of a SPICE netlist as ngspice reads them, for the netlist tools:
    - a statement continues on the lines starting with '+', also across comment and blank lines
    - comments: lines starting with '*', and end-of-line comments from '$' or '//' at the start of a word,
      or from ';' (KLayout writes the net $1 as \\$1), except the CDL annotations `$[model]` and `$SUB=net`
    - the first line of a deck (a netlist with .end) is its title
    - ground: the nodes '0' and 'gnd'

NOTE: imports neither KLayout nor generated protobuf code, so that format-only paths can use it
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import *

from ..util.unit_formatter import parse_spice_number


GROUND_NODE_NAMES = ('0', 'gnd')
"""Ground in SPICE: '0', and 'gnd', which ngspice reads as '0'"""

_END = re.compile(r'\s*\.end\s*$', re.IGNORECASE)
_END_OF_LINE_COMMENT = re.compile(r'(^|\s)(\$(?!\[|SUB\s*=)|//)|;', re.IGNORECASE)
_PARAMETER_START = re.compile(r'\s+(?:params:|[^\s=]+\s*=)', re.IGNORECASE)
_VOLTAGE_NODES = re.compile(r'\bv\s*\(\s*([^\s(),]+)\s*(?:,\s*([^\s(),]+)\s*)?\)', re.IGNORECASE)


class SpiceSyntaxError(Exception):
    """A netlist whose lines ngspice can't read, e.g. a continuation line without a line to continue"""

    def __init__(self, line_number: int, message: str):
        super().__init__(f"line {line_number}: {message}")
        self.line_number = line_number
        self.message = message


@dataclass
class SpiceLine:
    """
    A statement with its continuation lines, or a comment line, a blank line or the title
    """

    number: int
    """the number of its first physical line, counted from 1"""
    physical_lines: List[str]
    """as written: the statement, its continuation lines and the comment and blank lines between them"""
    text: Optional[str]
    """the statement in one line, without comments and the '+' of its continuation lines,
    None for a comment line, a blank line or the title"""

    @property
    def verbatim(self) -> str:
        return '\n'.join(self.physical_lines)


def strip_comment(line: str) -> str:
    """
    :return: the physical line without its comment, '' for a comment line
    """
    if line.lstrip().startswith(('*', '$')):
        return ''
    match = _END_OF_LINE_COMMENT.search(line)
    return line if match is None else line[:match.start()]


def spice_lines(text: str) -> List[SpiceLine]:
    """
    The lines of the netlist, in their order (see the module docs)

    :raises SpiceSyntaxError: for a continuation line without a statement to continue
    """
    physical_lines = text.splitlines()
    has_title = any(_END.match(line) for line in physical_lines)

    lines: List[SpiceLine] = []
    statement: Optional[SpiceLine] = None
    between: List[SpiceLine] = []  # NOTE: comment and blank lines after the statement, a continuation may follow

    for number, line in enumerate(physical_lines, start=1):
        if number == 1 and has_title:
            lines.append(SpiceLine(number=number, physical_lines=[line], text=None))
            continue
        stripped = strip_comment(line).strip()
        if not stripped:
            between.append(SpiceLine(number=number, physical_lines=[line], text=None))
        elif stripped.startswith('+'):
            if statement is None:
                raise SpiceSyntaxError(number, "continuation line without a line to continue")
            for other in between:
                statement.physical_lines.extend(other.physical_lines)
            between = []
            statement.physical_lines.append(line)
            statement.text += ' ' + stripped[1:].strip()
        else:
            lines.extend(between)
            between = []
            statement = SpiceLine(number=number, physical_lines=[line], text=stripped)
            lines.append(statement)
    lines.extend(between)
    return lines


def subcircuit_ports(tokens: Sequence[str]) -> List[str]:
    """
    :param tokens: of a .SUBCKT statement (see SpiceLine.text), e.g. ['.SUBCKT', 'inv', 'A', 'Y', 'PARAMS:', 'w=1']
    :return: its ports, in their order, without its name and parameters, e.g. ['A', 'Y']
    """
    ports: List[str] = []
    for token in tokens[2:]:
        if '=' in token or token.lower() == 'params:':
            break
        ports.append(token)
    return ports


def element_terminals(statement: str) -> List[str]:
    """Known terminals of a retained element, without evaluating its values.

    The caller supplies one uncommented logical statement, outside control blocks.
    Unknown element syntax stays opaque. In particular, its arbitrary words must
    not become new nodes merely because reduction conservatively protects them.
    """
    positional = _PARAMETER_START.split(statement, maxsplit=1)[0]
    words = [word for word in re.split(r'[\s(),]+', positional) if word]
    if not words:
        return []
    kind = words[0][0].upper()
    if kind == 'X':
        # The final positional word is the called subcircuit, even when parameter
        # assignments contain spaces around '=' or expressions containing spaces.
        return words[1:-1]
    count = {'R': 2, 'C': 2, 'L': 2, 'V': 2, 'I': 2, 'B': 2, 'F': 2, 'H': 2,
             'W': 2, 'D': 2, 'Q': 3, 'J': 3, 'Z': 3, 'M': 4, 'S': 4,
             'T': 4, 'O': 4, 'U': 3, 'E': 2, 'G': 2}.get(kind)
    if count is None or len(words) < count + 1:
        return []
    if kind in ('D', 'Q', 'M'):
        # Optional substrate/thermal nodes precede the model. An area, parameter
        # or flag after the model is not another terminal (nor is the model).
        end = next((index for index in range(count + 1, len(words))
                    if words[index].casefold() in ('off', 'on', 'thermal')
                    or words[index].startswith(('{', "'"))), len(words))
        while end > count + 1:
            try:
                parse_spice_number(words[end - 1])
            except ValueError:
                break
            end -= 1
        count = max(count, min(end - 2, {'D': 3, 'Q': 5, 'M': 7}[kind]))
    terminals = words[1:count + 1]
    if kind in ('R', 'C', 'L'):
        substrate = re.search(r'\$sub\s*=\s*([^\s(),=]+)', statement, re.IGNORECASE)
        if substrate:
            terminals.append(substrate.group(1))
    if kind in ('E', 'G') and len(words) >= 6:
        if words[3].casefold() == 'poly':
            try:
                pairs = int(words[4])
            except ValueError:
                pairs = 0
            if 0 < pairs <= (len(words) - 6) // 2:
                terminals.extend(words[5:5 + 2 * pairs])
        elif words[3].casefold() not in ('value', 'table', 'vol', 'cur', 'laplace'):
            terminals.extend(words[3:5])
    if kind in ('B', 'E', 'G'):
        for match in _VOLTAGE_NODES.finditer(statement):
            terminals.extend(name for name in match.groups() if name is not None)
    return terminals


def read_subcircuit_ports(path: str, subcircuit_name: str) -> Optional[List[str]]:
    """
    Reads the netlist up to the end of the .SUBCKT statement of the subcircuit only, so also a large one

    :param subcircuit_name: regardless of case, as SPICE reads names
    :return: its ports as written (see subcircuit_ports), None if the netlist has no such subcircuit
    """
    statement: List[str] = []  # NOTE: its physical lines
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if not statement:
                tokens = line.split()
                if len(tokens) >= 2 and tokens[0].lower() == '.subckt' \
                        and tokens[1].casefold() == subcircuit_name.casefold():
                    statement.append(line)
                continue
            stripped = strip_comment(line).strip()
            if stripped and not stripped.startswith('+'):
                break
            statement.append(line)
    if not statement:
        return None
    return subcircuit_ports(spice_lines(''.join(statement))[0].text.split())
