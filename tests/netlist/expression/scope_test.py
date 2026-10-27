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

import unittest

import allure

from klayout_pex.netlist.expression.ngspice import NGSPICE_SYNTAX
from klayout_pex.netlist.expression.nodes import ExpressionError
from klayout_pex.netlist.expression.parser import ExpressionParser
from klayout_pex.netlist.expression.scope import ParameterScope

PARSER = ExpressionParser(NGSPICE_SYNTAX)


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "SPICE")
class ParameterScopeTest(unittest.TestCase):
    def test_definitions_refer_to_each_other_in_any_order(self):
        scope = ParameterScope({'a': PARSER.parse('b*2'), 'b': 3.0})
        self.assertEqual(6.0, scope.value('a'))
        self.assertEqual(7.0, scope.evaluate(PARSER.parse('a+1')))
        self.assertEqual(2.0, scope.evaluate(2.0))

    def test_parameters_not_defined_are_those_of_the_parent(self):
        top = ParameterScope({'w': 1.0, 'l': 2.0})
        call = ParameterScope({'w': PARSER.parse('l*5')}, parent=top)
        self.assertEqual(10.0, call.value('w'))
        self.assertEqual(1.0, top.value('w'))

    def test_definition_that_refers_to_its_own_name_refers_to_the_parent(self):
        top = ParameterScope({'w': 7.0})
        call = ParameterScope({'w': PARSER.parse('w*2'), 'ad': PARSER.parse('w/2')}, parent=top)
        self.assertEqual(14.0, call.value('w'))
        self.assertEqual(7.0, call.value('ad'))

    def test_errors(self):
        with self.assertRaises(ExpressionError) as ctx:
            ParameterScope({'w': PARSER.parse('w*2')}).value('w')
        self.assertEqual('the parameter w is not defined', str(ctx.exception))
        with self.assertRaises(ExpressionError) as ctx:
            ParameterScope({'a': PARSER.parse('b'), 'b': PARSER.parse('c+1'), 'c': PARSER.parse('a')}).value('a')
        self.assertEqual('the parameter a depends on itself (a → b → c → a)', str(ctx.exception))
