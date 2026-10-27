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
import unittest

import allure

from klayout_pex.netlist.expression.ngspice import NGSPICE_SYNTAX
from klayout_pex.netlist.expression.nodes import Expression
from klayout_pex.netlist.expression.parser import ExpressionParser
from klayout_pex.netlist.spice_netlist import (
    SpiceElement,
    SpiceNetlist,
    SpiceSource,
    SpiceSourceFunction,
    SpiceSubcircuit,
)
from klayout_pex.netlist.spice_reader import SpiceReader, SpiceReaderError


def parse(text: str) -> SpiceNetlist:
    return SpiceReader().parse(text)


def expression(text: str) -> Expression:
    return ExpressionParser(NGSPICE_SYNTAX).parse(text)


def parse_error(text: str) -> str:
    try:
        parse(text)
    except SpiceReaderError as e:
        return str(e)
    raise AssertionError('no error')


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "SPICE")
class SpiceReaderTest(unittest.TestCase):
    # ------------------------------------------------------------ lines

    def test_extracted_netlist(self):
        netlist = parse('* NGSPICE file created by KLayout-PEX\n'
                        '\n'
                        '.SUBCKT cell A sky130_gnd\n'
                        'Cext_1 A sky130_gnd 223.458a\n'
                        'Rext_1 A A|B|C 426.666666667\n'
                        'XM1 A|B|C A sky130_gnd sky130_gnd sky130_fd_pr__nfet_01v8 l=0.15 w=1\n'
                        '+ as=0.29 ad=0.29\n'
                        '.ENDS cell\n')
        self.assertEqual(SpiceNetlist(subcircuits=[SpiceSubcircuit(name='cell', ports=['A', 'sky130_gnd'], elements=[
            SpiceElement('Cext_1', ['A', 'sky130_gnd'], value=223.458e-18),
            SpiceElement('Rext_1', ['A', 'A|B|C'], value=426.666666667),
            SpiceElement('XM1', ['A|B|C', 'A', 'sky130_gnd', 'sky130_gnd'], model='sky130_fd_pr__nfet_01v8',
                         parameters={'l': 0.15, 'w': 1.0, 'as': 0.29, 'ad': 0.29}),
        ])]), netlist)

    def test_comments(self):
        # NOTE: as ngspice, $ starts a comment at the start of a word (KLayout writes the net $1 as \$1),
        #       ; anywhere
        netlist = parse('* comment\n'
                        '  * indented comment\n'
                        'R1 a \\$1 1k $ comment\n'
                        'R2 a b 2k $b comment\n'
                        'R3 a c 3k; comment\n'
                        'R4 a d 4k // comment\n'
                        'R5 a e$f 5k\n')
        self.assertEqual([('R1', ['a', '\\$1'], 1e3), ('R2', ['a', 'b'], 2e3), ('R3', ['a', 'c'], 3e3),
                          ('R4', ['a', 'd'], 4e3), ('R5', ['a', 'e$f'], 5e3)],
                         [(e.name, e.nodes, e.value) for e in netlist.elements])

    def test_continuation_lines_and_spaces_around_equals(self):
        netlist = parse('X1 a b\n'
                        '* a comment between\n'
                        '+ sub w = 1u\n'
                        '+ l= 2u m\n'
                        '+ =2\n')
        self.assertEqual([SpiceElement('X1', ['a', 'b'], model='sub', parameters={'w': 1e-6, 'l': 2e-6, 'm': 2.0})],
                         netlist.elements)

    def test_title_line_of_a_deck(self):
        # NOTE: the first line of a deck, a file with .end, is its title
        netlist = parse('R1 is the title\n'
                        'R2 a b 1k\n'
                        '.end\n'
                        'R3 a b 1k\n')
        self.assertEqual(['R2'], [e.name for e in netlist.elements])

    # ------------------------------------------------------------ case

    def test_node_is_written_as_first_in_its_subcircuit(self):
        # NOTE: SPICE is case-insensitive, VACASK isn't
        netlist = parse('.subckt cell VDD out\n'
                        'R1 vdd Out 1k\n'
                        'R2 OUT x 1k\n'
                        'R3 X Vdd 1k\n'
                        '.ends\n'
                        '.subckt other vdd\n'
                        'R1 VDD 0 1k\n'
                        '.ends\n')
        self.assertEqual([['VDD', 'out'], ['out', 'x'], ['x', 'VDD']],
                         [e.nodes for e in netlist.subcircuits[0].elements])
        self.assertEqual([['vdd', '0']], [e.nodes for e in netlist.subcircuits[1].elements])

    def test_global_nodes(self):
        netlist = parse('.global VDD\n'
                        '.subckt cell a\n'
                        'R1 a vdd 1k\n'
                        '.ends\n')
        self.assertEqual(['VDD'], netlist.global_nodes)
        self.assertEqual(['a', 'VDD'], netlist.subcircuits[0].elements[0].nodes)

    def test_gnd_is_ground(self):
        # NOTE: ngspice takes gnd as ground, also a port (which then connects to nothing in the subcircuit)
        netlist = parse('.subckt cell a GND\n'
                        'R1 a gnd 1k\n'
                        '.ends\n'
                        'V1 in Gnd 1\n')
        self.assertEqual(['a', 'GND'], netlist.subcircuits[0].ports)
        self.assertEqual(['a', '0'], netlist.subcircuits[0].elements[0].nodes)
        self.assertEqual(['in', '0'], netlist.elements[0].nodes)

    def test_subcircuit_call_has_the_name_of_the_definition(self):
        netlist = parse('.subckt Inv a b\n'
                        '.ends\n'
                        'X1 a b INV\n'
                        'X2 a b sg13_LV_nmos\n')
        self.assertEqual(['Inv', 'sg13_LV_nmos'], [e.model for e in netlist.elements])

    def test_element_twice_is_an_error(self):
        self.assertEqual('line 2: the element r1 of the top level is there already (line 1)',
                         parse_error('R1 a b 1k\n'
                                     'r1 a c 1k\n'))

    # ------------------------------------------------------------ cards

    def test_passives(self):
        netlist = parse('R1 a b r=1k\n'
                        'R2 a b 2k rpoly w=1u l=2u m=2\n'
                        'R3 a b rpoly w=1u\n'
                        'C1 a b 1p m=3\n'
                        'L1 a b 1n\n'
                        'L2 c d l=4n\n'
                        'K1 l1 L2 0.9\n')
        self.assertEqual([SpiceElement('R1', ['a', 'b'], value=1e3),
                          SpiceElement('R2', ['a', 'b'], model='rpoly', value=2e3,
                                       parameters={'w': 1e-6, 'l': 2e-6, 'm': 2.0}),
                          SpiceElement('R3', ['a', 'b'], model='rpoly', parameters={'w': 1e-6}),
                          SpiceElement('C1', ['a', 'b'], value=1e-12, parameters={'m': 3.0}),
                          SpiceElement('L1', ['a', 'b'], value=1e-9),
                          SpiceElement('L2', ['c', 'd'], value=4e-9),
                          SpiceElement('K1', references=['L1', 'L2'], value=0.9)],
                         netlist.elements)

    def test_devices_of_models(self):
        netlist = parse('D1 a k dmod 2 m=2\n'
                        'D2 a k dmod area=3p\n'
                        'M1 d g s b nmos w=1u l=0.13u\n')
        self.assertEqual([SpiceElement('D1', ['a', 'k'], model='dmod', parameters={'area': 2.0, 'm': 2.0}),
                          SpiceElement('D2', ['a', 'k'], model='dmod', parameters={'area': 3e-12}),
                          SpiceElement('M1', ['d', 'g', 's', 'b'], model='nmos', parameters={'w': 1e-6, 'l': 1.3e-7})],
                         netlist.elements)

    def test_subcircuit_with_parameters(self):
        netlist = parse('.subckt res a b params: W=1u L=2u\n'
                        '.ends\n'
                        'X1 a b res params: w=2u\n')
        self.assertEqual(SpiceSubcircuit(name='res', ports=['a', 'b'], parameters={'w': 1e-6, 'l': 2e-6}),
                         netlist.subcircuits[0])
        self.assertEqual(SpiceElement('X1', ['a', 'b'], model='res', parameters={'w': 2e-6}), netlist.elements[0])

    def test_sources(self):
        netlist = parse('V1 vdd 0 1.8\n'
                        'V2 in 0 DC 0.6 AC 1\n'
                        'V3 in 0 AC 1 90\n'
                        'V4 clk 0 PULSE(0 1.2 1n 100p 100p 5n 10n)\n'
                        'V5 x 0 dc 0 sin (0 0.1 1meg)\n'
                        'I1 y 0 PWL(0 0, 1n 1m)\n'
                        'V6 z 0\n')
        self.assertEqual([SpiceSource(dc=1.8),
                          SpiceSource(dc=0.6, ac_magnitude=1.0),
                          SpiceSource(ac_magnitude=1.0, ac_phase=90.0),
                          SpiceSource(function=SpiceSourceFunction('pulse', [0, 1.2, 1e-9, 1e-10, 1e-10, 5e-9, 1e-8])),
                          SpiceSource(dc=0.0, function=SpiceSourceFunction('sin', [0, 0.1, 1e6])),
                          SpiceSource(function=SpiceSourceFunction('pwl', [0, 0, 1e-9, 1e-3])),
                          SpiceSource()],
                         [e.source for e in netlist.elements])

    def test_controlled_sources(self):
        netlist = parse('E1 o 0 a b 2\n'
                        'G1 o 0 a b 1m\n'
                        'F1 o 0 vsense 10\n'
                        'H1 o 0 VSENSE 50\n'
                        'Vsense a b 0\n')
        self.assertEqual([SpiceElement('E1', ['o', '0', 'a', 'b'], value=2.0),
                          SpiceElement('G1', ['o', '0', 'a', 'b'], value=1e-3),
                          SpiceElement('F1', ['o', '0'], references=['Vsense'], value=10.0),
                          SpiceElement('H1', ['o', '0'], references=['Vsense'], value=50.0)],
                         netlist.elements[:4])

    # ------------------------------------------------------------ parameters and expressions

    def test_parameters_of_param_lines(self):
        netlist = parse('.param vdd=1.8 w = {2*l}\n'
                        '.subckt cell a b\n'
                        '.param r0=\'w*1k\'\n'
                        'R1 a b {r0}\n'
                        '.ends\n')
        self.assertEqual({'vdd': 1.8, 'w': expression('2*l')}, netlist.parameters)
        self.assertEqual({'r0': expression('w*1k')}, netlist.subcircuits[0].local_parameters)
        self.assertEqual(SpiceElement('R1', ['a', 'b'], value=expression('r0')), netlist.subcircuits[0].elements[0])

    def test_expressions_in_braces_quotes_or_without_them(self):
        # NOTE: e.g. as xschem writes the MOS of sky130A, and BAG its subcircuits
        netlist = parse('.subckt nmos4 D G S B w=150n l=130n nf=4\n'
                        'MM1 D G S B nmos w=w*nf l=l ng=nf ad = { w / 2 }\n'
                        '+ as=\'int((nf+1)/2) * w/nf * 0.29\' m={1u}\n'
                        '.ends\n')
        self.assertEqual({'w': 150e-9, 'l': 130e-9, 'nf': 4.0}, netlist.subcircuits[0].parameters)
        self.assertEqual(SpiceElement('MM1', ['D', 'G', 'S', 'B'], model='nmos',
                                      parameters={'w': expression('w*nf'), 'l': expression('l'),
                                                  'ng': expression('nf'), 'ad': expression('w / 2'),
                                                  'as': expression('int((nf+1)/2) * w/nf * 0.29'),
                                                  'm': 1e-6}),
                         netlist.subcircuits[0].elements[0])

    def test_values_of_elements_as_expressions(self):
        netlist = parse('R1 a b {r0*2}\n'
                        'R2 a b \'r0\' rpoly\n'
                        'R3 a b rpoly r=r0\n'
                        'C1 a b c=2*c0\n'
                        'L1 a b 1n\n'
                        'K1 L1 L2 {k0}\n'
                        'D1 a k dmod {a0}\n'
                        'E1 o 0 a b gain\n')
        self.assertEqual([expression('r0*2'), expression('r0'), expression('r0'), expression('2*c0'), 1e-9,
                          expression('k0'), None, expression('gain')],
                         [e.value for e in netlist.elements])
        self.assertEqual('rpoly', netlist.elements[1].model)
        self.assertEqual({'area': expression('a0')}, netlist.elements[6].parameters)

    def test_errors_of_parameters_and_expressions_name_the_line(self):
        self.assertEqual("line 2: the parameter w is no expression (w*: ends early)",
                         parse_error('R1 a b 1k\nX1 a b sub w={w*}\n'))
        self.assertEqual("line 1: the value of R1 is no expression (2*: ends early)",
                         parse_error("R1 a b '2*'\n"))
        self.assertEqual("line 1: { has no counterpart (expressions are written {...} or '...')",
                         parse_error('X1 a b sub w={2*l\n'))
        self.assertEqual("line 1: ' has no counterpart (expressions are written {...} or '...')",
                         parse_error("X1 a b sub w='2*l\n"))
        self.assertEqual("line 1: the parameter w= has no value",
                         parse_error('.param w=\n'))
        self.assertEqual("line 1: the source V1 has the expression {vdd}, which is not supported",
                         parse_error('V1 a 0 {vdd}\n'))

    # ------------------------------------------------------------ not supported

    def test_unsupported_cards_are_errors_naming_the_line(self):
        self.assertEqual('line 2: .lib is not supported',
                         parse_error('R1 a b 1k\n.lib models.lib tt\n'))
        self.assertEqual('line 1: .include is not supported',
                         parse_error('.include "models.lib"\n'))
        self.assertEqual("line 1: the element Q1 is not supported (supported are "
                         "R, C, L, K, D, M, V, I, E, F, G, H and X)",
                         parse_error('Q1 c b e npn\n'))

    def test_subcircuit_structure_errors(self):
        self.assertEqual('the subcircuit cell has no .ends', parse_error('.subckt cell a\nR1 a 0 1\n'))
        self.assertEqual('line 2: nested subcircuit definitions are not supported (in subcircuit a)',
                         parse_error('.subckt a x\n.subckt b y\n.ends\n.ends\n'))
        self.assertEqual('line 1: the port 0 (ground) of subcircuit a is not supported',
                         parse_error('.subckt a x 0\n.ends\n'))

    def test_read_names_the_file(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'bad.spice')
            with open(path, 'w') as f:
                f.write('B1 a 0 v=1\n')
            with self.assertRaises(SpiceReaderError) as ctx:
                SpiceReader().read(path)
            self.assertTrue(str(ctx.exception).startswith(f"{path}: line 1: the element B1 is not supported"))
