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

from __future__ import annotations

import math
import tempfile
from typing import *
import unittest

import allure

from klayout_pex.netlist.spice_hierarchy import SpiceEvaluationError, SpiceHierarchy
from klayout_pex.netlist.spice_netlist import SpiceElement
from klayout_pex.netlist.spice_reader import SpiceReader
from tests.common.ngspice import ngspice_operating_point, requires_ngspice


# NOTE: the scopes of parameters of ngspice-46, in the resistances
SCOPES = """\
.param g=3 w=100
.subckt top a b w=7 k=2
.param loc={k+1}
R1 a b {loc*g}
X1 a b sub w='w*2' nf=4 ad='w/nf'
X2 a b sub ad='w/nf'
.ends
.subckt sub a b w=1 nf=2 ad=0
R1 a b {ad*1000 + w + g}
X3 a b leaf
.ends
.subckt leaf a b
R1 a b {w + 1000}
.ends
X0 a 0 top
X4 a 0 top w=10 k=0
R5 a 0 {g*1000}
Va a 0 1
"""

RESISTANCES = {
    'X0.R1': 9.0,  # loc of the .param line of top, from its default k
    'X0.X1.R1': 3517.0,  # the call's w='w*2' is its caller's w*2, its ad='w/nf' refers to the call's w and nf
    'X0.X1.X3.R1': 1014.0,  # w of the call of the calling subcircuit
    'X0.X2.R1': 504.0,  # ad='w/nf' of the call refers to the defaults of sub
    'X0.X2.X3.R1': 1001.0,
    'X4.R1': 3.0,
    'X4.X1.R1': 5023.0,
    'X4.X1.X3.R1': 1020.0,
    'X4.X2.R1': 504.0,
    'X4.X2.X3.R1': 1001.0,
    'R5': 3000.0,
}


# NOTE: the same raw width is used for geometry and a resistance inside the wrapper.
GEOMETRY = """\
.param width=2
.subckt wrapper d g w=1 l=1
Mwrapped d g 0 0 n w={w*2} l={l} as={w*l} ad={w*l/2} ps={w+l} pd={2*(w+l)} m=3
Rraw d 0 {w}
.ends
X1 d g wrapper w={width} l=0.5
Mtop d g 0 0 n w=2 l=1 as=3 ad=4 ps=5 pd=6 m=2
Msuffixed d g 0 0 n w=2u l=1u
Rgeometry d 0 1k w=4 l=3
Cgeometry d 0 2p w=6 l=5
Rparam d 0 {width}
Vd d 0 1.8
Vg g 0 1
"""


def flat_elements(text: str, subcircuit_name: Optional[str] = None) -> Dict[str, SpiceElement]:
    hierarchy = SpiceHierarchy(SpiceReader().parse(text))
    subcircuit = hierarchy.subcircuit(subcircuit_name) if subcircuit_name else None
    return {e.path: e.element for e in hierarchy.flat_elements(subcircuit)}


def evaluation_error(text: str) -> str:
    try:
        flat_elements(text)
    except SpiceEvaluationError as e:
        return str(e)
    raise AssertionError('no error')


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "SPICE")
class SpiceHierarchyTest(unittest.TestCase):
    def test_scopes_of_parameters(self):
        elements = flat_elements(SCOPES)
        self.assertEqual(RESISTANCES, {p: e.value for p, e in elements.items() if e.kind == 'R'})

    @requires_ngspice
    def test_scopes_of_parameters_are_those_of_ngspice(self):
        def vector(path: str) -> str:
            return f"@{'r.' if '.' in path else ''}{path.lower()}[resistance]"

        with tempfile.TemporaryDirectory() as work_dir:
            values = ngspice_operating_point(SCOPES, [vector(p) for p in RESISTANCES], work_dir)
        for path, resistance in RESISTANCES.items():
            self.assertTrue(math.isclose(resistance, values[vector(path)], rel_tol=1e-6),
                            f"{path}: {resistance} here, {values[vector(path)]} in ngspice")

    def test_scale_applies_once_to_native_geometry_after_evaluating_expressions(self):
        sources = ['.option scale=1u\n' + GEOMETRY,
                   GEOMETRY + '.options scale=1e-6\n',
                   GEOMETRY.replace('.subckt wrapper d g w=1 l=1\n',
                                    '.subckt wrapper d g w=1 l=1\n.options scale=1.0U\n')]
        expected = {
            'Mtop': {'w': 2e-6, 'l': 1e-6, 'as': 3e-12, 'ad': 4e-12, 'ps': 5e-6, 'pd': 6e-6, 'm': 2.0},
            'Msuffixed': {'w': 2e-12, 'l': 1e-12},
            'X1.Mwrapped': {'w': 4e-6, 'l': 0.5e-6, 'as': 1e-12, 'ad': 0.5e-12,
                            'ps': 2.5e-6, 'pd': 5e-6, 'm': 3.0},
            'Rgeometry': {'w': 4e-6, 'l': 3e-6},
            'Cgeometry': {'w': 6e-6, 'l': 5e-6},
        }
        for source in sources:
            with self.subTest(source=source):
                elements = flat_elements(source)
                for path, parameters in expected.items():
                    self.assertEqual(parameters.keys(), elements[path].parameters.keys())
                    for name, value in parameters.items():
                        self.assertTrue(math.isclose(value, elements[path].parameters[name], rel_tol=1e-12),
                                        f'{path}.{name}: {elements[path].parameters[name]} != {value}')
                self.assertEqual(1e3, elements['Rgeometry'].value)
                self.assertEqual(2e-12, elements['Cgeometry'].value)
                self.assertEqual(2.0, elements['X1.Rraw'].value)
                self.assertEqual(2.0, elements['Rparam'].value)
                self.assertEqual(1.8, elements['Vd'].source.dc)

    def test_scale_preserves_representable_results_at_numeric_limits(self):
        # NOTE: forming `scale²` first can overflow/underflow even when the scaled area is representable.
        cases = [('1e-200', 'ad', '1e300', 1e-100),
                 ('1e200', 'ad', '1e-300', 1e100),
                 ('1e200', 'ad', '0', 0.0),
                 ('1e308', 'w', '1', 1e308)]
        for scale, parameter, value, expected in cases:
            with self.subTest(scale=scale, parameter=parameter, value=value):
                element = flat_elements(f'.options scale={scale}\nM1 d g s b n {parameter}={value}\n')['M1']
                self.assertTrue(math.isclose(expected, element.parameters[parameter], rel_tol=1e-12),
                                f'{element.parameters[parameter]} != {expected}')
        self.assertEqual('the scaled parameter w of M1 has no finite value',
                         evaluation_error('.options scale=1e308\nM1 d g s b n w=2\n'))

    def test_repeated_hierarchy_traversals_do_not_scale_the_input_again(self):
        # NOTE: schematic checks can traverse the same parsed netlist more than once.
        netlist = SpiceReader().parse('.option scale=1u\nM1 d g s b n w=2\n')
        hierarchy = SpiceHierarchy(netlist)
        for _ in range(2):
            self.assertEqual(2e-6, next(hierarchy.flat_elements()).element.parameters['w'])
        self.assertEqual(2.0, netlist.elements[0].parameters['w'])

    def test_scale_does_not_guess_units_of_external_subcircuit_arguments(self):
        elements = flat_elements('.option scale=1u\nX1 d g s b external w=2 l=1 as=3 m=4\n')
        self.assertEqual({'w': 2.0, 'l': 1.0, 'as': 3.0, 'm': 4.0}, elements['X1'].parameters)

    @requires_ngspice
    def test_scaled_geometry_matches_ngspice(self):
        source = GEOMETRY + '.option scale=1u\n'
        elements = flat_elements(source)
        expected = {'v(d)': 1.8, '@n[tox]': 10e-9, '@n[ld]': 20e-9}
        for path, element in elements.items():
            if element.kind not in ('M', 'R', 'C'):
                continue
            prefix = element.kind.lower() + '.' if '.' in path else ''
            instance = prefix + path.lower()
            expected.update({f'@{instance}[{name}]': value for name, value in element.parameters.items()})
            if element.kind in ('R', 'C'):
                value_name = 'resistance' if element.kind == 'R' else 'capacitance'
                expected[f'@{instance}[{value_name}]'] = element.value
        with tempfile.TemporaryDirectory() as work_dir:
            values = ngspice_operating_point(source + '.model n nmos level=1 vto=0.7 kp=50u tox=10n ld=20n\n',
                                             list(expected), work_dir)
        for vector, value in expected.items():
            self.assertTrue(math.isclose(value, values[vector], rel_tol=1e-6),
                            f'{vector}: {value} here, {values[vector]} in ngspice')

    def test_parameterized_subcircuits_as_bag_writes_them(self):
        elements = flat_elements("""\
.subckt inverter VDD I Q VSS
Xnmos Q I VSS VSS nmos4_lvt w=3.9u l=130n nf=4
Xdummy VSS VSS VSS VSS nmos4_lvt w=3.9u l=130n nf=2
.ends
.subckt nmos4_lvt D G S B w=150n l=130n nf=4
MM1 D G S B sg13_lv_nmos w=w*nf l=l ng=nf
.ends
""", 'inverter')
        self.assertEqual({'Xnmos.MM1': {'w': 15.6e-6, 'l': 130e-9, 'ng': 4.0},
                          'Xdummy.MM1': {'w': 7.8e-6, 'l': 130e-9, 'ng': 2.0}},
                         {p: e.parameters for p, e in elements.items()})
        self.assertEqual('sg13_lv_nmos', elements['Xnmos.MM1'].model)

    def test_parameters_of_a_call_of_a_subcircuit_not_in_the_netlist_refer_to_each_other(self):
        # NOTE: e.g. a MOS of sky130A as xschem writes it, whose subcircuit is in the models of the PDK
        elements = flat_elements("XM1 d g s b sky130_fd_pr__nfet_01v8 L=0.15 W=1 nf=2 "
                                 "ad='int((nf+1)/2) * W/nf * 0.29'\n")
        self.assertEqual({'l': 0.15, 'w': 1.0, 'nf': 2.0, 'ad': 0.145}, elements['XM1'].parameters)

    def test_uncalled_subcircuits(self):
        hierarchy = SpiceHierarchy(SpiceReader().parse(SCOPES))
        self.assertEqual([], [s.name for s in hierarchy.uncalled_subcircuits()])
        hierarchy = SpiceHierarchy(SpiceReader().parse('.subckt a x\nXb x b\n.ends\n.subckt b x\n.ends\n'))
        self.assertEqual(['a'], [s.name for s in hierarchy.uncalled_subcircuits()])

    def test_only_the_parameters_asked_for_are_evaluated(self):
        # NOTE: the others, and the value, may have no number, also those of a call that the elements don't refer to
        hierarchy = SpiceHierarchy(SpiceReader().parse(
            '.subckt sub a\nXC1 a a cap w=w0 feed=double\nR1 a 0 {rval}\n.ends\nX1 a sub w0=1u unused=none\n'))
        elements = {e.path: e.element for e in hierarchy.flat_elements(parameter_names=lambda element: ['w'])}
        self.assertEqual({'X1.XC1': {'w': 1e-6}, 'X1.R1': {}}, {p: e.parameters for p, e in elements.items()})
        self.assertIsNone(elements['X1.R1'].value)

    def test_errors_name_the_element_and_its_value(self):
        self.assertEqual('the parameter w = w0*2 of X1.M1: the parameter w0 is not defined',
                         evaluation_error('.subckt sub a\nM1 a a a a nmos w={w0*2}\n.ends\nX1 a sub\n'))
        self.assertEqual('the value 1/(k-1) of X1.R1: division by zero',
                         evaluation_error('.subckt sub a k=1\nR1 a 0 {1/(k-1)}\n.ends\nX1 a sub\n'))
        self.assertEqual('X1.X2 calls the subcircuit sub within itself',
                         evaluation_error('.subckt sub a\nX2 a sub\n.ends\nX1 a sub\n'))
