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
from typing import *
import unittest

import allure

from klayout_pex.netlist.spice_netlist import (
    SpiceElement,
    SpiceNetlist,
    SpiceSource,
    SpiceSourceFunction,
    SpiceSubcircuit,
)
from klayout_pex.netlist.spice_reader import SpiceReader
from klayout_pex.netlist.vacask_writer import (
    VacaskWriter,
    VacaskWriterError,
    vacask_identifier,
    vacask_number,
)


def cell(*elements: SpiceElement, ports: Sequence[str] = ('a', 'b')) -> SpiceNetlist:
    return SpiceNetlist(subcircuits=[SpiceSubcircuit(name='cell', ports=list(ports), elements=list(elements))])


def instance_lines(netlist: SpiceNetlist, subcircuits_with_m: Collection[str] = frozenset()) -> List[str]:
    """
    The instance lines of the netlist (not load, model, subckt, ends), without indentation
    """
    text = VacaskWriter(subcircuits_with_m=subcircuits_with_m).text(netlist)
    keywords = ('load', 'model', 'subckt', 'ends', 'global', 'parameters', '//')
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith(keywords)]


def source(element_name: str, src: SpiceSource) -> List[str]:
    return instance_lines(SpiceNetlist(elements=[SpiceElement(element_name, ['p', '0'], source=src)]))


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "VACASK")
class VacaskWriterTest(unittest.TestCase):
    # ------------------------------------------------------------ cards

    def test_rc_netlist(self):
        netlist = cell(SpiceElement('Rext_1', ['a', 'n1'], value=1280 / 3),
                       SpiceElement('Cext_1', ['n1', 'b'], value=2.23458e-16))
        self.assertEqual(
            '// extracted by test\n'
            '//\n'
            '// tech: none\n'
            '\n'
            'load "capacitor.osdi"\n'
            'load "resistor.osdi"\n'
            '\n'
            'subckt cell (a b)\n'
            '  model capacitor capacitor\n'
            '  model resistor resistor\n'
            '  Rext_1 (a n1) resistor r=426.666666667\n'
            '  Cext_1 (n1 b) capacitor c=2.23458e-16\n'
            'ends\n',
            VacaskWriter(header=['extracted by test', '', 'tech: none']).text(netlist))

    def test_only_the_devices_used_are_loaded(self):
        text = VacaskWriter().text(cell(SpiceElement('C1', ['a', 'b'], value=1e-15)))
        self.assertIn('load "capacitor.osdi"', text)
        self.assertNotIn('resistor', text)

    def test_device_subcircuit_call_has_lowercase_parameter_names(self):
        # NOTE: VACASK is case-sensitive, the PDK's VACASK subcircuits have lowercase parameters (e.g. nx)
        netlist = cell(SpiceElement('X$1', ['a', 'b', 'b', 'b'], model='sg13_hv_svaricap',
                                    parameters={'w': 3.74e-06, 'l': 3e-07, 'Nx': 2.0}))
        self.assertEqual(['X$1 (a b b b) sg13_hv_svaricap w=3.74e-06 l=3e-07 nx=2'],
                         instance_lines(netlist))

    def test_device_of_a_model_takes_m_as_mfactor(self):
        netlist = cell(SpiceElement('D1', ['a', 'b'], model='diode_nd2ps_03v3',
                                    parameters={'area': 1e-12, 'm': 2.0}),
                       SpiceElement('Rm1', ['a', 'b'], model='res_generic_m1', value=10,
                                    parameters={'w': 1e-6}),
                       SpiceElement('R2', ['a', 'b'], value=10, parameters={'m': 4.0}))
        self.assertEqual(['D1 (a b) diode_nd2ps_03v3 area=1e-12 $mfactor=2',
                          'Rm1 (a b) res_generic_m1 r=10 w=1e-06',
                          'R2 (a b) resistor r=10 $mfactor=4'],
                         instance_lines(netlist))

    def test_passive_without_model_takes_no_other_parameters(self):
        with self.assertRaises(VacaskWriterError) as ctx:
            instance_lines(cell(SpiceElement('C1', ['a', 'b'], value=1e-15, parameters={'ic': 0.5})))
        self.assertEqual("The element 'C1' of subcircuit 'cell' has parameters "
                         "VACASK's capacitor doesn't take: ic", str(ctx.exception))

    def test_inductors_and_their_coupling(self):
        netlist = cell(SpiceElement('L1', ['a', '0'], value=1e-9),
                       SpiceElement('L.2', ['b', '0'], value=4e-9),
                       SpiceElement('K1', references=['L1', 'L.2'], value=0.9))
        text = VacaskWriter().text(netlist)
        self.assertIn('load "inductor.osdi"', text)
        self.assertIn('  model mutual mutual', text)
        self.assertEqual(['L1 (a 0) inductor l=1e-09',
                          "'L.2' (b 0) inductor l=4e-09",
                          'K1 () mutual k=0.9 ind1="L1" ind2="L.2"'],
                         instance_lines(netlist))

    def test_coupling_of_no_inductor_is_an_error(self):
        with self.assertRaises(VacaskWriterError) as ctx:
            instance_lines(cell(SpiceElement('L1', ['a', '0'], value=1e-9),
                                SpiceElement('K1', references=['L1', 'L2'], value=0.9)))
        self.assertEqual("The element 'K1' of subcircuit 'cell' refers to 'L2', which is no element L there",
                         str(ctx.exception))

    def test_controlled_sources(self):
        netlist = SpiceNetlist(elements=[
            SpiceElement('Vsense', ['a', 'b'], source=SpiceSource(dc=0.0)),
            SpiceElement('E1', ['o1', '0', 'a', '0'], value=2.0),
            SpiceElement('G1', ['o2', '0', 'a', '0'], value=1e-3),
            SpiceElement('F1', ['o3', '0'], references=['Vsense'], value=10.0),
            SpiceElement('H1', ['o4', '0'], references=['Vsense'], value=50.0),
        ])
        self.assertEqual(['Vsense (a b) vsource dc=0',
                          'E1 (o1 0 a 0) vcvs gain=2',
                          'G1 (o2 0 a 0) vccs gain=0.001',
                          'F1 (o3 0) cccs gain=10 ctlinst="Vsense"',
                          'H1 (o4 0) ccvs gain=50 ctlinst="Vsense"'],
                         instance_lines(netlist))

    def test_top_level_elements_have_their_models_at_the_top_level(self):
        netlist = SpiceNetlist(subcircuits=cell(SpiceElement('R1', ['a', 'b'], value=1.0)).subcircuits,
                               elements=[SpiceElement('V1', ['in', '0'], source=SpiceSource(dc=1.2)),
                                         SpiceElement('X1', ['in', '0'], model='cell')])
        text = VacaskWriter().text(netlist)
        self.assertTrue(text.endswith('ends\n'
                                      '\n'
                                      'model vsource vsource\n'
                                      'V1 (in 0) vsource dc=1.2\n'
                                      'X1 (in 0) cell\n'), text)

    def test_subcircuit_parameters_and_global_nodes(self):
        netlist = SpiceNetlist(subcircuits=[SpiceSubcircuit(name='res', ports=['a', 'b'],
                                                            parameters={'W': 1e-06},
                                                            elements=[SpiceElement('R1', ['a', 'vdd'], value=1.0)])],
                               global_nodes=['vdd'])
        self.assertEqual('load "resistor.osdi"\n'
                         '\n'
                         'global vdd\n'
                         '\n'
                         'subckt res (a b)\n'
                         '  parameters w=1e-06\n'
                         '  model resistor resistor\n'
                         '  R1 (a vdd) resistor r=1\n'
                         'ends\n',
                         VacaskWriter().text(netlist))

    # ------------------------------------------------------------ sources

    def test_dc_and_ac_source(self):
        self.assertEqual(['V1 (p 0) vsource dc=1.8 mag=1 phase=90'],
                         source('V1', SpiceSource(dc=1.8, ac_magnitude=1.0, ac_phase=90.0)))
        self.assertEqual(['I1 (p 0) isource dc=0'], source('I1', SpiceSource()))

    def test_pulse_source(self):
        pulse = SpiceSourceFunction('pulse', [0.0, 1.2, 1e-9, 1e-10, 2e-10, 5e-9, 1e-8])
        self.assertEqual(['V1 (p 0) vsource type="pulse" val0=0 val1=1.2 delay=1e-09 rise=1e-10 fall=2e-10 '
                          'width=5e-09 period=1e-08'],
                         source('V1', SpiceSource(function=pulse)))

    def test_pulse_without_fall_time_is_an_error(self):
        # NOTE: SPICE takes the time step for TF = 0, VACASK doesn't fall
        pulse = SpiceSourceFunction('pulse', [0.0, 1.2, 0.0, 1e-10, 0.0, 5e-9])
        with self.assertRaises(VacaskWriterError) as ctx:
            source('V1', SpiceSource(function=pulse))
        self.assertIn("PULSE needs TR > 0 and TF > 0", str(ctx.exception))

    def test_sine_exp_and_pwl_sources(self):
        self.assertEqual(['V1 (p 0) vsource type="sine" sinedc=0.6 ampl=0.1 freq=1000000 tdphase=90'],
                         source('V1', SpiceSource(function=SpiceSourceFunction('sin', [0.6, 0.1, 1e6, 0, 0, 90]))))
        self.assertEqual(['V1 (p 0) vsource type="exp" val0=0 val1=1 delay=1e-09 tau1=1e-10 td2=4e-09 '
                          'tau2=2e-10'],
                         source('V1', SpiceSource(function=SpiceSourceFunction(
                             'exp', [0.0, 1.0, 1e-9, 1e-10, 5e-9, 2e-10]))))
        self.assertEqual(['I1 (p 0) isource type="pwl" wave=[0, 0, 1e-09, 0.001]'],
                         source('I1', SpiceSource(function=SpiceSourceFunction('pwl', [0.0, 0.0, 1e-9, 1e-3]))))

    def test_dc_value_other_than_the_initial_value_of_the_function_is_an_error(self):
        # NOTE: SPICE takes the DC value for the operating point, VACASK the value of the function at time 0
        pulse = SpiceSourceFunction('pulse', [0.0, 1.2, 0.0, 1e-10, 1e-10, 5e-9])
        self.assertEqual(['V1 (p 0) vsource type="pulse" val0=0 val1=1.2 delay=0 rise=1e-10 fall=1e-10 '
                          'width=5e-09'],
                         source('V1', SpiceSource(dc=0.0, function=pulse)))
        with self.assertRaises(VacaskWriterError) as ctx:
            source('V1', SpiceSource(dc=0.6, function=pulse))
        self.assertEqual("The source 'V1' of the top level: its DC value 0.6 differs from its value 0 at time 0, "
                         "which VACASK takes for the operating point", str(ctx.exception))

    # ------------------------------------------------------------ m

    def test_m_of_subcircuit_that_declares_it_is_kept(self):
        netlist = cell(SpiceElement('XM1', ['a', 'b', 'b', 'b'], model='sg13_lv_nmos',
                                    parameters={'w': 1e-6, 'm': 4.0, 'l': 1.3e-7}),
                       SpiceElement('XM2', ['a', 'b', 'b', 'b'], model='sg13_lv_nmos',
                                    parameters={'w': 1e-6, 'm': 1.0}))
        self.assertEqual(['XM1 (a b b b) sg13_lv_nmos w=1e-06 m=4 l=1.3e-07',
                          'XM2 (a b b b) sg13_lv_nmos w=1e-06 m=1'],
                         instance_lines(netlist, subcircuits_with_m={'sg13_lv_nmos'}))

    def test_m_of_subcircuit_that_doesnt_declare_it_is_written_as_copies(self):
        # NOTE: VACASK rejects a parameter a subcircuit doesn't declare (e.g. the PNP of the IHP PDKs),
        #       m = N is N calls, as in SPICE
        netlist = cell(SpiceElement('XQ1', ['a', 'b', 'b'], model='pnpMPA',
                                    parameters={'a': 2e-12, 'm': 3.0}),
                       SpiceElement('XQ2', ['a', 'b', 'b'], model='pnpMPA',
                                    parameters={'a': 2e-12, 'm': 1.0}))
        self.assertEqual(['XQ1_1 (a b b) pnpMPA a=2e-12',
                          'XQ1_2 (a b b) pnpMPA a=2e-12',
                          'XQ1_3 (a b b) pnpMPA a=2e-12',
                          'XQ2 (a b b) pnpMPA a=2e-12'],
                         instance_lines(netlist, subcircuits_with_m={'sg13_lv_nmos'}))

    def test_m_of_element_of_subcircuit_that_declares_it_is_kept(self):
        # NOTE: e.g. KLayout's SPICE writer writes the MOS of the IHP PDKs as M lines, and their VACASK models
        #       are subcircuits, which reject $mfactor
        netlist = cell(SpiceElement('M1', ['a', 'b', 'b', 'b'], model='sg13_lv_nmos',
                                    parameters={'w': 1e-6, 'm': 2.0}))
        self.assertEqual(['M1 (a b b b) sg13_lv_nmos w=1e-06 m=2'],
                         instance_lines(netlist, subcircuits_with_m={'sg13_lv_nmos'}))

    def test_m_of_1_of_element_of_model_is_left_out(self):
        # NOTE: a diode of the IHP PDKs, whose VACASK model is a subcircuit without m
        netlist = cell(SpiceElement('D1', ['a', 'b'], model='dantenna',
                                    parameters={'w': 6.3e-7, 'm': 1.0, 'l': 8.4e-7}))
        self.assertEqual(['D1 (a b) dantenna w=6.3e-07 l=8.4e-07'], instance_lines(netlist))

    def test_fractional_m_of_subcircuit_that_doesnt_declare_it_is_an_error(self):
        netlist = cell(SpiceElement('XQ1', ['a', 'b', 'b'], model='pnpMPA', parameters={'m': 1.5}))
        with self.assertRaises(VacaskWriterError) as ctx:
            instance_lines(netlist)
        self.assertEqual("The subcircuit call 'XQ1' of subcircuit 'cell' has m=1.5, which VACASK's pnpMPA "
                         "doesn't declare and which is no number of copies", str(ctx.exception))

    def test_copy_with_the_name_of_another_instance_is_an_error(self):
        netlist = cell(SpiceElement('XQ1', ['a', 'b', 'b'], model='pnpMPA', parameters={'m': 2.0}),
                       SpiceElement('XQ1_2', ['a', 'b', 'b'], model='pnpMPA'))
        with self.assertRaises(VacaskWriterError) as ctx:
            instance_lines(netlist)
        self.assertEqual("The instances 'XQ1_2' (copy 2 of XQ1, m=2) and 'XQ1_2' of subcircuit 'cell' "
                         "would both be the instance XQ1_2 in VACASK", str(ctx.exception))

    # ------------------------------------------------------------ names

    def test_names_that_are_no_identifiers_are_quoted(self):
        netlist = cell(SpiceElement('R1', ['A,B,C', 'sub!'], value=1.0),
                       SpiceElement('R2', ['cnt_o[7]', "n'q"], value=1.0),
                       SpiceElement('R3', ['x1.n3', 'a$b'], value=1.0),
                       SpiceElement('control', ['1n', '0'], value=1e-15),  # NOTE: a capacitor, as in SPICE
                       SpiceElement('R5', ['12', '007'], value=1.0),
                       ports=['A,B,C', 'ä'])
        text = VacaskWriter().text(netlist)
        self.assertIn("subckt cell ('A,B,C' 'ä')", text)
        self.assertEqual(["R1 ('A,B,C' 'sub!') resistor r=1",
                          "R2 ('cnt_o[7]' 'n''q') resistor r=1",
                          "R3 ('x1.n3' a$b) resistor r=1",
                          "'control' ('1n' 0) capacitor c=1e-15",
                          "R5 (12 '007') resistor r=1"],
                         instance_lines(netlist))

    def test_identifiers(self):
        self.assertEqual('vdd', vacask_identifier('vdd'))
        self.assertEqual('$1', vacask_identifier('$1'))
        self.assertEqual("'1'", vacask_identifier('1'))  # an instance or subcircuit
        self.assertEqual('1', vacask_identifier('1', is_node=True))
        self.assertEqual("'a\\x20b'", vacask_identifier('a b'))
        self.assertEqual("'a\\x09b'", vacask_identifier('a\tb'))
        self.assertEqual("'include'", vacask_identifier('include'))

    def test_nets_with_the_same_vacask_name_are_an_error(self):
        # NOTE: whitespace, which no VACASK name can have, is written as \x20 (as KLayout does),
        #       a net of that name would be shorted to it
        netlist = cell(SpiceElement('R1', ['a b', 'a\\x20b'], value=1.0))
        with self.assertRaises(VacaskWriterError) as ctx:
            instance_lines(netlist)
        self.assertEqual("The nets 'a b' and 'a\\\\x20b' of subcircuit 'cell' would both be "
                         "the net 'a\\x20b' in VACASK, which shorts them", str(ctx.exception))

    def test_names_keep_their_case(self):
        # NOTE: VACASK is case-sensitive, these are 2 nets
        self.assertEqual(['R1 (VDD vdd) resistor r=1'],
                         instance_lines(cell(SpiceElement('R1', ['VDD', 'vdd'], value=1.0))))

    def test_port_twice_is_an_error(self):
        with self.assertRaises(VacaskWriterError) as ctx:
            instance_lines(cell(ports=['a', 'a']))
        self.assertEqual("The port 'a' of subcircuit 'cell' is there twice", str(ctx.exception))

    def test_parameters_and_expressions_are_errors(self):
        # NOTE: VACASK has them too, but the writer writes numbers only
        errors = {
            '.subckt cell a b\nR1 a b {r0*2}\n.ends\n':
                "The value of the element 'R1' of subcircuit 'cell' is the expression r0*2",
            '.subckt cell a b w=2*l\n.ends\n':
                "The parameter w of subcircuit 'cell' is the expression 2*l",
            '.subckt cell a b\n.ends\nX1 a b cell w={l}\n':
                "The parameter w of the element 'X1' of the top level is the expression l",
            '.subckt cell a b\n.param r0=1k\nR1 a b 1k\n.ends\n':
                "Subcircuit 'cell' has .param lines (r0)",
            '.param vdd=1.8 vss=0\nR1 a 0 1k\n':
                "The top level has .param lines (vdd, vss)",
        }
        for text, message in errors.items():
            with self.subTest(text):
                with self.assertRaises(VacaskWriterError) as ctx:
                    VacaskWriter().text(SpiceReader().parse(text))
                self.assertEqual(f"{message}, the VACASK writer writes numbers only", str(ctx.exception))

    def test_subcircuit_with_the_name_of_a_device_model_is_an_error(self):
        netlist = SpiceNetlist(subcircuits=[SpiceSubcircuit(name='resistor', ports=['a', 'b'])])
        with self.assertRaises(VacaskWriterError) as ctx:
            VacaskWriter().text(netlist)
        self.assertIn("The subcircuit 'resistor' has the name of a model the VACASK netlist defines",
                      str(ctx.exception))

    # ------------------------------------------------------------ numbers

    def test_numbers_have_12_significant_digits_and_no_si_prefix(self):
        # NOTE: VACASK reads the SI prefix M as mega, SPICE as milli
        self.assertEqual('0.001', vacask_number(1e-3))
        self.assertEqual('1e-15', vacask_number(1e-15))
        self.assertEqual('1e22', vacask_number(1e22))
        self.assertEqual('2', vacask_number(2.0))
        self.assertEqual('426.666666667', vacask_number(1280 / 3))
        self.assertEqual('7.8e-07', vacask_number(0.78 * 1e-6))  # NOTE: not 7.799999999999999e-07
        for value in (2.23458e-16, 6.02214076e23, -4.5e-12):
            self.assertEqual(value, float(vacask_number(value)))
