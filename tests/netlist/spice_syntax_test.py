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

"""The lines of SPICE netlists as ngspice reads them: continuation lines, comments, the title of a deck"""

from __future__ import annotations

from typing import *

import allure
import pytest

from klayout_pex.netlist.spice_syntax import (
    SpiceLine,
    SpiceSyntaxError,
    element_terminals,
    read_subcircuit_ports,
    spice_lines,
    strip_comment,
)

parent_suite = "Unit Tests"
tags = ("Netlist", "SPICE")


def texts(text: str) -> List[Optional[str]]:
    return [line.text for line in spice_lines(text)]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('statement, terminals', [
    ('Vbias ref 0 DC 0', ['ref', '0']),
    ('Iload (ref, 0) PULSE(0 1 2n)', ['ref', '0']),
    ('R1 a b rmodel w = 1u', ['a', 'b']),
    ('C1 a b {capacitance}', ['a', 'b']),
    ('L1 a b 1u $SUB = substrate $[lmodel]', ['a', 'b', 'substrate']),
    ('D1 a k diode 2', ['a', 'k']),
    ('D1 a k diode OFF', ['a', 'k']),
    ('D1 a k sub diode thermal', ['a', 'k', 'sub']),
    ('Q1 c b e bjt', ['c', 'b', 'e']),
    ('Q1 c b e bjt 2 off', ['c', 'b', 'e']),
    ('Q1 c b e 20 bjt 2', ['c', 'b', 'e', '20']),
    ('Q1 c b e s tj bjt area=2', ['c', 'b', 'e', 's', 'tj']),
    ('M1 d g s b mos W=1u L=1u', ['d', 'g', 's', 'b']),
    ('M1 d g s b soi body tj mos off', ['d', 'g', 's', 'b', 'soi', 'body', 'tj']),
    ('J1 d g s jfet area=2', ['d', 'g', 's']),
    ('Z1 d g s mesfet', ['d', 'g', 's']),
    ('S1 a b ctrlp ctrln switch', ['a', 'b', 'ctrlp', 'ctrln']),
    ('W1 a b Vsense switch', ['a', 'b']),
    ('T1 a b c d Z0=50 TD=1n', ['a', 'b', 'c', 'd']),
    ('O1 a b c d line', ['a', 'b', 'c', 'd']),
    ('U1 a b reference line L=1', ['a', 'b', 'reference']),
    ('F1 a b Vsense 2', ['a', 'b']),
    ('H1 a b POLY(1) Vsense 0 2', ['a', 'b']),
    ('E1 a b ctrlp ctrln 2', ['a', 'b', 'ctrlp', 'ctrln']),
    ('G1 a b POLY(2) c d e f 0 1 2', ['a', 'b', 'c', 'd', 'e', 'f']),
    ('E1 a b VALUE={V(c,d)}', ['a', 'b', 'c', 'd']),
    ('G1 a b TABLE {V(c)} = (0, 0) (1, 1)', ['a', 'b', 'c']),
    ('B1 a b I=V(c,d)+V(e)+I(Vsense)', ['a', 'b', 'c', 'd', 'e']),
    ('X1 a b wrapper', ['a', 'b']),
    ('X1 (a b) wrapper PARAMS: gain = {2 * multiplier}', ['a', 'b']),
    ('X1 a b wrapper gain = {2 * multiplier}', ['a', 'b']),
    ('X1 wrapper params: p=1', []),
    ('K1 L1 L2 0.8', []),
    ('Aopaque [a b] opaque_model', []),
    ('.param ref=value', []),
    ('', []),
    ('Vbias', []),
    ('M1 d g s', []),
])
def test_known_element_terminals_exclude_models_values_and_parameters(statement: str, terminals: List[str]):
    # Optional terminals and spaced assignments are the boundaries where a model,
    # scalar value or controlling element name can be mistaken for a node.
    assert element_terminals(statement) == terminals


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_statement_continues_on_lines_starting_with_plus():
    assert spice_lines("X1 a\n  + b\n+c model w=1\nR1 a b 1k\n") == [
        SpiceLine(number=1, physical_lines=['X1 a', '  + b', '+c model w=1'], text='X1 a b c model w=1'),
        SpiceLine(number=4, physical_lines=['R1 a b 1k'], text='R1 a b 1k'),
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_statement_continues_across_comment_and_blank_lines():
    # NOTE: as ngspice, which drops the comment and blank lines before it joins the continuation lines
    lines = spice_lines("X1 a\n* a comment\n\n+ mid model\n* after\n")
    assert lines == [
        SpiceLine(number=1, physical_lines=['X1 a', '* a comment', '', '+ mid model'], text='X1 a mid model'),
        SpiceLine(number=5, physical_lines=['* after'], text=None),
    ]
    assert lines[0].verbatim == "X1 a\n* a comment\n\n+ mid model"


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_comment_and_blank_lines_are_lines_without_text():
    assert spice_lines("* comment\n   * indented\n\n  \nR1 a b 1k\n") == [
        SpiceLine(number=1, physical_lines=['* comment'], text=None),
        SpiceLine(number=2, physical_lines=['   * indented'], text=None),
        SpiceLine(number=3, physical_lines=[''], text=None),
        SpiceLine(number=4, physical_lines=['  '], text=None),
        SpiceLine(number=5, physical_lines=['R1 a b 1k'], text='R1 a b 1k'),
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('line, stripped', [
    ('R1 a b 1k $ comment', 'R1 a b 1k'),
    ('R1 a b 1k $comment', 'R1 a b 1k'),           # NOTE: $ at the start of a word
    ('R1 a b 1k // comment', 'R1 a b 1k'),
    ('R1 a b 1k; comment', 'R1 a b 1k'),           # NOTE: ; anywhere
    ('$ comment', ''),
    ('  $[comment] with brackets', ''),
    ('$SUB=body in a comment line', ''),
    ('R1 a \\$1 1k', 'R1 a \\$1 1k'),             # NOTE: KLayout writes the net $1 as \\$1
    ('R1 a$b c 1k', 'R1 a$b c 1k'),
    ('R1 a//b c 1k', 'R1 a//b c 1k'),
    ('  * comment $ more', ''),
])
def test_end_of_line_comments(line: str, stripped: str):
    assert strip_comment(line) == stripped


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_statements_are_read_without_their_end_of_line_comments():
    assert texts("X1 a $ one\n+ b ; two\n+ model // three\n") == ['X1 a b model']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('annotation', ['$SUB=VSS $[rpoly]', '$[rpoly] $sub = VSS'])
def test_cdl_annotations_are_not_comments(annotation: str):
    line = f'R1 a b 1k {annotation} w=1u l=2u'
    assert strip_comment(line + ' $ comment') == line
    assert texts(f'R1 a b 1k\n+ {annotation} w=1u l=2u $ comment\n') == [line]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('end', ['.end', '.END', '  .end  '])
def test_first_line_of_a_deck_is_its_title(end: str):
    # NOTE: ngspice reads the first line of a deck (a netlist with .end) as its title, whatever it is
    assert texts(f"R1 a b 1k\nR2 b c 2k\n{end}\n") == [None, 'R2 b c 2k', end.strip()]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_netlist_without_end_has_no_title():
    # NOTE: e.g. an include file, or a netlist KPEX writes
    assert texts("R1 a b 1k\n.endc\n.ends\n") == ['R1 a b 1k', '.endc', '.ends']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('text, line_number', [
    ("+ a b\n", 1),
    ("* comment\n\n+ a b\n", 3),
    ("title\n+ a b\n.end\n", 2),  # NOTE: the title is no statement to continue
])
def test_continuation_without_a_line_to_continue_is_an_error(text: str, line_number: int):
    with pytest.raises(SpiceSyntaxError) as exception_info:
        spice_lines(text)
    assert exception_info.value.line_number == line_number
    assert str(exception_info.value) == f"line {line_number}: continuation line without a line to continue"


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('text, ports', [
    (".SUBCKT inv A Y\nM1 Y A 0 0 nmos\n.ENDS inv\n", ['A', 'Y']),
    # NOTE: after another subcircuit, regardless of case, across a comment line, up to the parameters
    (".subckt other A\n.ends other\n.subckt INV A $ in\n* out\n+ Y PARAMS: w=1\nM1 Y A 0 0 nmos\n.ends INV\n",
     ['A', 'Y']),
    (".SUBCKT other A Y\n.ENDS other\n", None),
], ids=['one line', 'continued', 'missing'])
def test_ports_of_a_subcircuit_are_read_from_its_subckt_statement(text: str, ports: Optional[List[str]], tmp_path):
    path = tmp_path / 'netlist.spice'
    path.write_text(text, encoding='utf-8')
    assert read_subcircuit_ports(str(path), 'inv') == ports
