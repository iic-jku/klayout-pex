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
import unittest

import allure

from klayout_pex.netlist.expression.ngspice import NGSPICE_SYNTAX
from klayout_pex.netlist.expression.nodes import ExpressionError
from klayout_pex.netlist.expression.parser import ExpressionParser, ExpressionSyntaxError
from klayout_pex.netlist.expression.scope import ParameterScope
from tests.common.ngspice import ngspice_operating_point, requires_ngspice


PARAMETERS = {'g': 3.0, 'nf': 2.0}

# NOTE: the values of ngspice-46
VALUES = {
    '2 + 3 * 4 ^ 2': 50.0,
    '-2^2': -4.0,
    '2^3^2': 64.0,
    '2**3': 8.0,
    '2^-1': 0.5,
    '2*-3': -6.0,
    '3 - -2': 5.0,
    '7/2*2': 7.0,
    '2-3-4': -5.0,
    '7%3': 1.0,
    '-3 % 2': -1.0,
    '!1 + 1': 1.0,
    '1 < 2 == 1': 1.0,
    '2 >= 2 && 1 > 2': 0.0,
    '0 || 1 != 1': 0.0,
    '1 ? 2 : 0 ? 3 : 4': 2.0,
    '0 ? 2 : 0 ? 3 : 4': 4.0,
    '2u*1meg': 2.0,
    '10pF*1e12': 10.0,
    'G*NF + g': 9.0,
    'int((nf+1)/2) * g/nf * 0.29': 0.435,
    'log(100)': math.log(100),
    'ln(2)': math.log(2),
    'log10(1000)': 3.0,
    'pwr(-2,3)': 8.0,
    'pow(-2,3)': -8.0,
    'nint(2.5)': 2.0,
    'nint(-2.5)': -2.0,
    'nint(3.5)': 4.0,
    'int(-2.7)': -2.0,
    'floor(-2.5)': -3.0,
    'ceil(2.5)': 3.0,
    'sgn(-3)': -1.0,
    'SQRT(4)': 2.0,
    'max(1,5)': 5.0,
    'ternary_fcn(0,2,3)': 3.0,
    'arctan(1)': math.pi / 4,
}


def evaluate(text: str) -> float:
    return ExpressionParser(NGSPICE_SYNTAX).parse(text).evaluate(ParameterScope(PARAMETERS))


def error(text: str) -> str:
    try:
        evaluate(text)
    except ExpressionError as e:
        return f"{type(e).__name__}: {e}"
    raise AssertionError('no error')


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "SPICE")
class NgspiceExpressionTest(unittest.TestCase):
    def test_values(self):
        for text, value in VALUES.items():
            with self.subTest(text):
                self.assertAlmostEqual(value, evaluate(text), places=12)

    @requires_ngspice
    def test_values_are_those_of_ngspice(self):
        netlist = ''.join(f".param {n}={v:g}\n" for n, v in PARAMETERS.items())
        netlist += ''.join(f"V{i} n{i} 0 {{{text}}}\n" for i, text in enumerate(VALUES))
        with tempfile.TemporaryDirectory() as work_dir:
            values = ngspice_operating_point(netlist, [f"v(n{i})" for i in range(len(VALUES))], work_dir)
        for i, (text, value) in enumerate(VALUES.items()):
            with self.subTest(text):
                self.assertTrue(math.isclose(value, values[f"v(n{i})"], rel_tol=1e-6, abs_tol=1e-12),
                                f"{text}: {value} here, {values[f'v(n{i})']} in ngspice")

    def test_operands_not_taken_are_not_evaluated(self):
        self.assertEqual(2.0, evaluate('1 ? 2 : 1/0'))
        self.assertEqual(0.0, evaluate('0 && 1/0'))
        self.assertEqual(1.0, evaluate('1 || undefined'))

    def test_errors_of_values(self):
        self.assertEqual('ExpressionError: division by zero', error('1/(nf-2)'))
        self.assertEqual('ExpressionError: sqrt(-1) has no finite value', error('sqrt(-g/3)'))
        self.assertEqual('ExpressionError: power(-2, 0.5) has no finite value', error('(-2)^0.5'))
        self.assertEqual('ExpressionError: exp(1000) has no finite value', error('exp(1000)'))
        self.assertEqual('ExpressionError: the parameter w is not defined', error('W*nf'))

    def test_syntax_errors(self):
        self.assertEqual('ExpressionSyntaxError: foo(1): unknown function foo (known are abs, acos, acosh, arctan, '
                         'asin, asinh, atan, atanh, ceil, cos, cosh, exp, floor, int, ln, log, log10, max, min, '
                         'nint, pow, pwr, sgn, sin, sinh, sqrt, tan, tanh, ternary_fcn)',
                         error('foo(1)'))
        self.assertEqual('ExpressionSyntaxError: pow(1): pow takes 2 arguments, not 1', error('pow(1)'))
        self.assertEqual('ExpressionSyntaxError: 2 +: ends early', error('2 +'))
        self.assertEqual("ExpressionSyntaxError: (1: ends early, ')' expected", error('(1'))
        self.assertEqual("ExpressionSyntaxError: 1 ? 2: ends early, ':' expected", error('1 ? 2'))
        self.assertEqual("ExpressionSyntaxError: g $ 2: unexpected '$' at column 3", error('g $ 2'))
        self.assertEqual("ExpressionSyntaxError: g 2: unexpected '2' at column 3", error('g 2'))
        self.assertEqual("ExpressionSyntaxError: : ends early", error(''))
        self.assertTrue(issubclass(ExpressionSyntaxError, ExpressionError))
