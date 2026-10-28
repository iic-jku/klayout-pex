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

"""Reading the RC elements of SPICE netlists into networks, and writing them back"""

from __future__ import annotations

import textwrap
from typing import *

import allure
import pytest

from klayout_pex.netlist.rc_reduction import ReductionOptions, reduce_network
from klayout_pex.netlist.spice_rc_netlist import NetlistReadError, SpiceRCNetlist
from tests.common.rc_networks import (
    approx,
    protected_names,
    scope_named,
    value_of,
)

parent_suite = "Unit Tests"
tags = ("Netlist", "Reduction", "SPICE")


# NOTE: as KPEX writes it (2.5D, RC mode), see e.g. the RC extraction of sky130A's nfet_li1 test pattern
KPEX_NETLIST = textwrap.dedent("""\
    *********************************************************
    *** NGSPICE file created by KLayout-PEX 0.6.8
    *********************************************************

    .SUBCKT nfet_li1 D G S sky130_gnd
    X$1 D.P0.nsdm G.P0.poly S.P0.nsdm
    + sky130_gnd sky130_fd_pr__nfet_01v8 l=0.15 w=0.65
    Cext_1 D G.$0.li1 0.0123059f
    Cext_2 D.$0.li1 sky130_gnd 0.0167878f
    Cext_3 G.$0.li1 sky130_gnd 0.012871f
    Rext_1 D D.$0.li1 30.4941176471
    Rext_2 D.$0.li1 D.P0.nsdm 185
    Rext_3 G G.$0.li1 6.4
    Rext_4 G.$0.li1 G.P0.poly 152
    .ENDS nfet_li1
    """)


# ----------------------------------------------------------------------------------------- reading

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_reads_scopes_ports_and_elements():
    netlist = SpiceRCNetlist.parse(KPEX_NETLIST)
    assert [s.title for s in netlist.scopes] == ['.SUBCKT nfet_li1', 'top level']
    scope = scope_named(netlist, 'nfet_li1')
    assert scope.ports == ['D', 'G', 'S', 'sky130_gnd']
    assert (scope.resistors_read, scope.capacitors_read) == (4, 3)
    assert value_of(scope.network, 'D', 'G.$0.li1') == (0.0, 12.3059e-18)
    assert value_of(scope.network, 'D.$0.li1', 'D.P0.nsdm') == approx((1 / 185, 0.0))
    assert scope_named(netlist, None).network.nodes() == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_ports_device_terminals_on_continuation_lines_and_ground_are_protected():
    scope = scope_named(SpiceRCNetlist.parse(KPEX_NETLIST), 'nfet_li1')
    # NOTE: S has no R or C, so it is no node of the network
    assert protected_names(scope.network) == ['D', 'D.P0.nsdm', 'G', 'G.P0.poly', 'sky130_gnd']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('ground', ['0', 'gnd', 'GND'])
def test_ground_is_protected_without_being_a_port(ground: str):
    scope = scope_named(SpiceRCNetlist.parse(f"R1 a {ground} 1k\nC1 a b 1f\n"), None)
    assert protected_names(scope.network) == [ground]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_global_nodes_and_nodes_of_control_statements_are_protected():
    netlist = SpiceRCNetlist.parse(textwrap.dedent("""\
        a deck, its first line is the title
        .global vdd
        .subckt cell a
        R1 a vdd 1k
        R2 a mid 1k
        R3 mid probe 1k
        R4 probe far 1k
        .ends cell
        R5 x y 1k
        R6 y z 1k
        .control
        plot v(y)
        .endc
        .end
        """))
    assert protected_names(scope_named(netlist, 'cell').network) == ['a', 'vdd']
    assert protected_names(scope_named(netlist, None).network) == ['y']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_elements_with_other_values_are_kept_as_they_are_and_protect_their_nodes():
    text = textwrap.dedent("""\
        .subckt cell a b
        Rplain a n1 1k
        Rtc n1 n2 1k tc1=0.01
        Rexpr n2 n3 {rval}
        Rzero n3 n4 0
        Cneg n4 n5 -1f
        Rmodel n5 n6 rpoly l=1u
        Cplain n6 b 1f
        .ends cell
        """)
    netlist = SpiceRCNetlist.parse(text)
    scope = scope_named(netlist, 'cell')
    assert (scope.resistors_read, scope.capacitors_read) == (1, 1)
    assert protected_names(scope.network) == ['a', 'b', 'n1', 'n6']
    assert scope.other_element_names == {'rtc', 'rexpr', 'rzero', 'cneg', 'rmodel'}
    formatted = netlist.format()
    for line in text.splitlines()[2:7]:
        assert line in formatted.splitlines()


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_node_names_are_case_insensitive():
    scope = scope_named(SpiceRCNetlist.parse(".subckt cell OUT\nR1 out mid 1k\nC1 MID Out 1f\n.ends\n"), 'cell')
    assert sorted(scope.network.name(n) for n in scope.network.nodes()) == ['mid', 'out']
    assert protected_names(scope.network) == ['out']
    assert value_of(scope.network, 'OUT', 'mid') == approx((1e-3, 1e-15))


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_ports_on_continuation_lines_and_parameters():
    scope = scope_named(SpiceRCNetlist.parse(".subckt cell a\n+ b c params: w=1\nR1 a b 1k\nR2 c d 1k\n.ends\n"),
                        'cell')
    assert scope.ports == ['a', 'b', 'c']
    assert protected_names(scope.network) == ['a', 'b', 'c']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_device_terminals_on_continuation_lines_are_protected():
    # NOTE: mid is a node of the continuation line only, and no port
    scope = scope_named(SpiceRCNetlist.parse(".subckt cell a\nX1 a\n+ mid model\nR1 a mid 1k\nR2 mid far 1k\n"
                                             "C1 far 0 1f\n.ends\n"), 'cell')
    assert protected_names(scope.network) == ['0', 'a', 'mid']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_device_terminals_on_continuation_lines_after_comment_lines_are_protected():
    # NOTE: ngspice continues a line across comment and blank lines; the + line used to continue the comment,
    #       so that mid wasn't protected, and the reduction left X1 on a node without elements
    netlist = SpiceRCNetlist.parse(".subckt cell a far\nX1 a\n* a comment\n+ mid model\n"
                                   "R1 a mid 1k\nR2 mid far 1k\nC1 mid 0 1f\n.ends\n")
    scope = scope_named(netlist, 'cell')
    assert protected_names(scope.network) == ['0', 'a', 'far', 'mid']
    reduce_network(scope.network, ReductionOptions(ticer_tau=1e-9))
    assert netlist.format() == (".subckt cell a far\nX1 a\n* a comment\n+ mid model\n"
                                "Cred_1 0 mid 1f\nRred_1 a mid 1000\nRred_2 far mid 1000\n.ends\n")


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_end_of_line_comments_are_no_part_of_the_elements():
    # NOTE: R1 is a plain resistor, and the comment of X1 names no node
    netlist = SpiceRCNetlist.parse(".subckt cell a\nX1 a model $ mid\nR1 a mid 1k $ wire\nR2 mid far 1k\n"
                                   "C1 far 0 1f\n.ends\n")
    scope = scope_named(netlist, 'cell')
    assert scope.resistors_read == 2
    assert protected_names(scope.network) == ['0', 'a']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_title_of_a_deck_is_no_element():
    netlist = SpiceRCNetlist.parse("R1 a b 1k\nR2 a b 2k\n.end\n")
    scope = scope_named(netlist, None)
    assert (scope.resistors_read, value_of(scope.network, 'a', 'b')) == (1, (0.5e-3, 0.0))
    assert netlist.format() == "R1 a b 1k\nRred_1 a b 2000\n.end\n"


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_elements_on_continuation_lines_are_read_and_replaced():
    netlist = SpiceRCNetlist.parse(".subckt cell a b\nR1 a\n+ b 1k\nC1 a\n+ b\n+ 1f\n.ends\n")
    scope = scope_named(netlist, 'cell')
    assert (scope.resistors_read, scope.capacitors_read) == (1, 1)
    assert netlist.format() == ".subckt cell a b\nCred_1 a b 1f\nRred_1 a b 1000\n.ends\n"


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_nested_subcircuits_are_scopes_of_their_own():
    netlist = SpiceRCNetlist.parse(textwrap.dedent("""\
        .subckt outer a
        .subckt inner x
        R1 x y 1k
        .ends inner
        R2 a y 1k
        .ends outer
        """))
    assert [s.title for s in netlist.scopes] == ['.SUBCKT inner', '.SUBCKT outer', 'top level']
    assert protected_names(scope_named(netlist, 'inner').network) == ['x']
    assert protected_names(scope_named(netlist, 'outer').network) == ['a']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('text, message', [
    ("R1 a b 1k\n.ends\n", r"<text>:2: \.ENDS without \.SUBCKT"),
    (".subckt cell a\nR1 a b 1k\n", r"<text>: \.SUBCKT cell without \.ENDS"),
    (".subckt\n", r"<text>:1: \.SUBCKT without name"),
    ("* comment\n+ a b 1k\n", r"<text>:2: continuation line without a line to continue"),
])
def test_unreadable_netlists_are_errors(text: str, message: str):
    with pytest.raises(NetlistReadError, match=message):
        SpiceRCNetlist.parse(text)


# ----------------------------------------------------------------------------------------- writing

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_unreduced_netlist_is_written_back_in_kpex_precision():
    formatted = SpiceRCNetlist.parse(KPEX_NETLIST).format()
    assert formatted == KPEX_NETLIST.replace('Cext_', 'Cred_').replace('Rext_', 'Rred_')


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_elements_are_written_sorted_in_place_of_the_first_one_with_free_names():
    netlist = SpiceRCNetlist.parse(textwrap.dedent("""\
        * title
        .subckt cell b a
        Rred_1 a b 1k tc1=0.1
        R9 b x 2k
        C9 x b 2f
        Xinst a b sub
        C1 x a 1f
        C2 a x 1f
        R1 x a 1k
        .ends cell
        """))
    assert netlist.format() == textwrap.dedent("""\
        * title
        .subckt cell b a
        Rred_1 a b 1k tc1=0.1
        Cred_1 a x 2f
        Cred_2 b x 2f
        Rred_2 a x 1000
        Rred_3 b x 2000
        Xinst a b sub
        .ends cell
        """)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_comment_lines_go_above_the_elements():
    netlist = SpiceRCNetlist.parse(".subckt cell a\nR1 a b 1k\n.ends\n")
    scope_named(netlist, 'cell').comment_lines.append('* reduced')
    assert netlist.format() == ".subckt cell a\n* reduced\nRred_1 a b 1000\n.ends\n"


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_write_returns_the_path(tmp_path):
    path = str(tmp_path / 'out.spice')
    assert SpiceRCNetlist.parse(KPEX_NETLIST).write(path) == path
    with open(path, encoding='utf-8') as f:
        assert SpiceRCNetlist.parse(f.read()).format() == SpiceRCNetlist.parse(KPEX_NETLIST).format()


# --------------------------------------------------------------------------------- with reduction

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_port_on_continuation_line_survives_the_reduction():
    # NOTE: b is reached by capacitors only, through the plate p to ground, which is eliminated (#214)
    netlist = SpiceRCNetlist.parse(".subckt w a\n+ b\nC1 b p 1e-15\nC2 p 0 1e-15\n.ends\n")
    reduce_network(scope_named(netlist, 'w').network, ReductionOptions())
    assert netlist.format() == ".subckt w a\n+ b\nCred_1 0 b 0.5f\n.ends\n"


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_ties_are_read_as_ties_and_written_after_the_elements():
    # NOTE: an Rtie_ element that isn't between a node and ground is a resistor
    netlist = SpiceRCNetlist.parse(".subckt cell a\nRTIE_7 0 plate 1T\nC1 plate a 1f\nRtie_x a b 1k\n.ends\n")
    scope = scope_named(netlist, 'cell')
    network = scope.network
    assert [network.name(n) for n in network.tied_nodes()] == ['plate']
    assert network.find_node('0') is None
    assert (scope.resistors_read, scope.capacitors_read) == (1, 1)
    assert netlist.format() == ".subckt cell a\nCred_1 a plate 1f\nRred_1 a b 1000\nRtie_1 plate 0 1e+12\n.ends\n"


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_a_reduced_netlist_can_be_reduced_again():
    text = ".subckt cell n0 n1 n2 n3\n" + ''.join(f"C{i} plate n{i} {i + 1}f\n" for i in range(4)) + ".ends\n"

    def reduced(text: str, floating_max_degree: int) -> str:
        netlist = SpiceRCNetlist.parse(text)
        reduce_network(scope_named(netlist, 'cell').network, ReductionOptions(floating_max_degree=floating_max_degree))
        return netlist.format()

    once = reduced(text, floating_max_degree=3)
    assert 'Rtie_1 plate 0 1e+12' in once
    assert reduced(once, floating_max_degree=3) == once
    # NOTE: with a higher degree limit, the plate is eliminated, and its tie dropped
    assert 'plate' not in reduced(once, floating_max_degree=4)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_ground_tied_to_two_floating_islands_is_kept():
    # NOTE: #214: a pass had tied two floating islands to ground; ground, no port and no device terminal,
    #       then looked like an ordinary node with two neighbours to TICER, which eliminated it
    netlist = SpiceRCNetlist.parse(textwrap.dedent("""\
        .subckt cell A B
        Rtie1 island1 0 1T
        Cp1 island1 A 1f
        Rtie2 island2 0 1T
        Cp2 island2 B 1f
        .ends cell
        """))
    scope = scope_named(netlist, 'cell')
    # NOTE: with τ = 1 fF · 1 TΩ = 1 ms below the threshold, the islands are quick leaves,
    #       their capacitors move to their resistive neighbour, ground
    reduce_network(scope.network, ReductionOptions(ticer_tau=1.0, ticer_max_degree=1000, floating=False))
    assert sorted(scope.network.name(n) for n in scope.network.nodes()) == ['0', 'A', 'B']
    assert value_of(scope.network, 'A', '0') == approx((0.0, 1e-15))
    assert value_of(scope.network, 'B', '0') == approx((0.0, 1e-15))


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_bytes_that_are_no_utf8_are_written_back_as_they_were(tmp_path):
    content = '* netlist by M. K\xf6hler (latin-1)\n.subckt cell a\nRred_1 a b 1000\n.ends\n'.encode('latin-1')
    input_path = tmp_path / 'latin1.spice'
    input_path.write_bytes(content)
    output_path = str(tmp_path / 'out.spice')
    SpiceRCNetlist.read(str(input_path)).write(output_path)
    with open(output_path, 'rb') as f:
        assert f.read() == content


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('newline', ['\n', '\r\n'], ids=['LF', 'CRLF'])
def test_line_endings_are_written_back_as_they_were(newline: str, tmp_path):
    content = newline.join(['* netlist', '.subckt cell a', 'Rred_1 a b 1000', '.ends', ''])
    input_path = tmp_path / 'cell.spice'
    input_path.write_bytes(content.encode())
    output_path = str(tmp_path / 'out.spice')
    SpiceRCNetlist.read(str(input_path)).write(output_path)
    with open(output_path, 'rb') as f:
        assert f.read() == content.encode()
