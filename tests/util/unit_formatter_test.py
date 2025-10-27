#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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

import allure
import unittest

from klayout_pex.util.unit_formatter import format_spice_number


@allure.parent_suite("Unit Tests")
@allure.tag("Enum", "Help", "Util")
class UnitFormatterTest(unittest.TestCase):
    def test_auto_prefix(self):
        self.assertEqual(format_spice_number(1.2e-15), '1.2f')
        self.assertEqual(format_spice_number(3.4e-12), '3.4p')
        self.assertEqual(format_spice_number(4.7e-9), '4.7n')
        self.assertEqual(format_spice_number(1e-6), '1u')
        self.assertEqual(format_spice_number(2.2e-6), '2.2u')
        self.assertEqual(format_spice_number(0.0), '0')
        self.assertEqual(format_spice_number(-3.3e-12), '-3.3p')
        self.assertEqual(format_spice_number(5e-18), '5a')

    def test_boundary_cases(self):
        self.assertEqual(format_spice_number(1e-12), '1p')
        self.assertEqual(format_spice_number(1e-15), '1f')
        self.assertEqual(format_spice_number(1e-18), '1a')
        self.assertEqual(format_spice_number(1e-9), '1n')  # 1000p → 1n
        self.assertEqual(format_spice_number(1e-12), '1p')  # exactly 1p

    def test_forced_prefix(self):
        self.assertEqual(format_spice_number(1e-9, 'f'), '1000000f')
        self.assertEqual(format_spice_number(1e-9, 'p'), '1000p')  # pF
        self.assertEqual(format_spice_number(1e-9, 'n'), '1n')  # nF
        self.assertEqual(format_spice_number(2.2e-6, 'n'), '2200n')
        self.assertEqual(format_spice_number(4.7e-9, 'u'), '0.0047u')
        self.assertEqual(format_spice_number(1.0, 'K'), '0.001K')
        self.assertEqual(format_spice_number(5e-18, 'a'), '5a')

    def test_invalid_prefix(self):
        with self.assertRaises(ValueError):
            format_spice_number(1e-6, 'x')  # invalid prefix


if __name__ == '__main__':
    unittest.main()
