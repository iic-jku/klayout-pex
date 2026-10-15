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

from klayout_pex.util.unit_formatter import format_spice_number, format_spice_resistance, parse_spice_number


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
        self.assertEqual(format_spice_number(5e-18), '0.005f')

    def test_boundary_cases(self):
        self.assertEqual(format_spice_number(1e-12), '1p')
        self.assertEqual(format_spice_number(1e-15), '1f')
        self.assertEqual(format_spice_number(1e-18), '0.001f')
        self.assertEqual(format_spice_number(1e-9), '1n')  # 1000p → 1n
        self.assertEqual(format_spice_number(1e-12), '1p')  # exactly 1p

    def test_neither_atto_nor_mil_is_chosen(self):
        # NOTE: Xyce reads the a of 223.458a as a unit, and mil is no SI prefix
        self.assertEqual(format_spice_number(223.458e-18), '0.223458f')
        self.assertEqual(format_spice_number(1e-25), '1e-10f')
        self.assertEqual(format_spice_number(3e-3), '3m')
        self.assertEqual(format_spice_number(2.54e-5), '25.4u')
        self.assertEqual(format_spice_number(5e-5), '50u')

    def test_written_numbers_have_neither_atto_nor_mil_and_read_back(self):
        for exponent in range(-27, 15):
            for mantissa in (1.0, 2.54, 4.7, 9.99999):
                value = mantissa * 10.0 ** exponent
                with self.subTest(value=value):
                    text = format_spice_number(value)
                    self.assertFalse(text.endswith(('a', 'mil')), text)
                    self.assertEqual(parse_spice_number(text), float(f"{value:.6g}"))

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

    def test_resistance_has_12_significant_digits_without_scale_factor(self):
        self.assertEqual(format_spice_resistance(1280 / 3), '426.666666667')
        self.assertEqual(format_spice_resistance(0.001), '0.001')
        self.assertEqual(format_spice_resistance(185.0), '185')
        self.assertEqual(format_spice_resistance(1e12), '1e+12')

    def test_parse_scale_factors(self):
        cases = {
            '1.5': 1.5, '-2': -2.0, '.5': 0.5, '2e-15': 2e-15, '1E+3': 1e3,
            '1T': 1e12, '1g': 1e9, '1Meg': 1e6, '1MEG': 1e6, '1k': 1e3, '1K': 1e3,
            '1m': 1e-3, '1M': 1e-3, '1u': 1e-6, '4.7n': 4.7e-9, '0.1p': 1e-13, '1f': 1e-15, '223.458a': 223.458e-18,
            '1mil': 25.4e-6, '1e-07a': 1e-25, '-2.': -2.0, '1.5E+3k': 1.5e6,
        }
        for text, value in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_spice_number(text), value)

    def test_parse_ignores_letters_after_the_scale_factor(self):
        self.assertEqual(parse_spice_number('1pF'), 1e-12)
        self.assertEqual(parse_spice_number('10kOhm'), 10e3)
        self.assertEqual(parse_spice_number('10V'), 10.0)
        self.assertEqual(parse_spice_number('1F'), 1e-15)  # 'F' is femto, not farad

    def test_parse_reads_what_format_writes(self):
        for value in (1.2e-15, 3.4e-12, 4.7e-9, 2.2e-6, 5e-18, 1.23456e-16, 9.87654e3, 1e-25):
            with self.subTest(value=value):
                self.assertEqual(parse_spice_number(format_spice_number(value)), float(f"{value:.6g}"))
                self.assertEqual(parse_spice_number(format_spice_resistance(value)), float(f"{value:.12g}"))

    def test_parse_rejects_what_is_no_number(self):
        for text in ('', 'abc', '{2*c0}', '1.2.3', 'nan', 'inf', 'k1', '1k5', 'w=1'):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "Not a SPICE number: .*examples of valid numbers"):
                    parse_spice_number(text)


if __name__ == '__main__':
    unittest.main()
