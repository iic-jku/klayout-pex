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
      or from ';' (KLayout writes the net $1 as \\$1)
    - the first line of a deck (a netlist with .end) is its title
    - ground: the nodes '0' and 'gnd'

NOTE: imports neither KLayout nor generated protobuf code, so that format-only paths can use it
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import *


GROUND_NODE_NAMES = ('0', 'gnd')
"""Ground in SPICE: '0', and 'gnd', which ngspice reads as '0'"""

_END = re.compile(r'\s*\.end\s*$', re.IGNORECASE)
_END_OF_LINE_COMMENT = re.compile(r'(^|\s)(\$|//)|;')


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
    if line.lstrip().startswith('*'):
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
