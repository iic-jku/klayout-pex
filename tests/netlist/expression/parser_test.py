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

from dataclasses import replace
import unittest

import allure

from klayout_pex.netlist.expression.ngspice import NGSPICE_SYNTAX
from klayout_pex.netlist.expression.nodes import (
    BinaryOperation,
    BinaryOperator,
    Number,
    Parameter,
)
from klayout_pex.netlist.expression.parser import ExpressionParser, ExpressionSyntaxError
from klayout_pex.netlist.expression.scope import ParameterScope
from klayout_pex.netlist.expression.syntax import Associativity, BinaryOperatorSyntax


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "SPICE")
class ExpressionParserTest(unittest.TestCase):
    def test_tree_of_the_operations(self):
        expression = ExpressionParser(NGSPICE_SYNTAX).parse('W*nf + 1')
        self.assertEqual('W*nf + 1', expression.text)
        self.assertEqual(BinaryOperation(BinaryOperator.ADD,
                                         BinaryOperation(BinaryOperator.MULTIPLY, Parameter('w'), Parameter('nf')),
                                         Number(1.0)),
                         expression.root)

    def test_the_syntax_decides_the_associativity(self):
        # NOTE: e.g. of a flavour whose ** binds from the right
        syntax = replace(NGSPICE_SYNTAX, binary_operators={
            **NGSPICE_SYNTAX.binary_operators,
            '**': BinaryOperatorSyntax(BinaryOperator.POWER, 8, Associativity.RIGHT),
        })
        self.assertEqual(512.0, ExpressionParser(syntax).parse('2**3**2').evaluate(ParameterScope({})))
        self.assertEqual(64.0, ExpressionParser(syntax).parse('2^3^2').evaluate(ParameterScope({})))

    def test_the_syntax_decides_whether_case_matters(self):
        syntax = replace(NGSPICE_SYNTAX, ignores_case=False)
        self.assertEqual(Parameter('W'), ExpressionParser(syntax).parse('W').root)
        with self.assertRaises(ExpressionSyntaxError) as ctx:
            ExpressionParser(syntax).parse('SQRT(4)')
        self.assertTrue(str(ctx.exception).startswith('SQRT(4): unknown function SQRT'))
