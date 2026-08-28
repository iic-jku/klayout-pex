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

import allure
from fractions import Fraction
import unittest

from klayout_pex.pex25d.writer import (
    CONTINUATION, WRAP_COLUMN, WriteError, format_exact, write_pex25d_text,
)

from .pex25d_fixtures import MINIMAL, read, read_codes, replacing


@allure.parent_suite("Unit Tests")
@allure.tag("PEX25D", "Writer")
class Pex25DWriterTest(unittest.TestCase):
    # ------------------------------------------------------- exact rendering

    def test_format_exact(self):
        cases = {
            Fraction(0): '0.0',
            Fraction(1): '1.0',
            Fraction(-1): '-1.0',
            Fraction(1, 2): '0.5',
            Fraction(1, 8): '0.125',
            Fraction(1, 10000): '0.0001',
            Fraction(3262, 10000): '0.3262',
            Fraction(-43, 100): '-0.43',
            Fraction(5, 4): '1.25',
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                assert format_exact(value) == expected

    def test_format_exact_refuses_what_it_cannot_render(self):
        # A denominator with a factor other than 2 or 5 has no finite decimal
        # form, and rounding one silently would move geometry off the grid.
        for value in (Fraction(1, 3), Fraction(2, 7)):
            with self.subTest(value=value):
                with self.assertRaises(WriteError):
                    format_exact(value)

    def test_lengths_are_rendered_exactly(self):
        text = write_pex25d_text(read(MINIMAL)).decode()
        assert 'METAL met1 Z_OFFSETS 1.0 1.4' in text
        assert 'GROUND_PLANE subs Z_OFFSETS -0.4 -0.1' in text

    # ------------------------------------------------------------------ wrap

    def test_long_records_wrap_and_read_back_identically(self):
        ring = ' '.join(f"{x / 10} {x % 7}" for x in range(40))
        text = replacing(
            'POLYGON CONDUCTOR B LAYER met1 OUTER 2.0 0.0 3.0 0.0 3.0 1.0 2.0 1.0',
            f'POLYGON CONDUCTOR B LAYER met1 OUTER {ring}')
        written = write_pex25d_text(read(text)).decode()

        wrapped = [line for line in written.splitlines()
                   if line.endswith(CONTINUATION)]
        assert wrapped, "the long polygon should have wrapped"
        for line in written.splitlines():
            assert len(line) <= WRAP_COLUMN

        assert write_pex25d_text(read(written)) == written.encode()

    def test_a_wrap_never_splits_a_coordinate_pair(self):
        ring = ' '.join(f"{x / 10} {x % 7}" for x in range(40))
        text = replacing(
            'POLYGON CONDUCTOR B LAYER met1 OUTER 2.0 0.0 3.0 0.0 3.0 1.0 2.0 1.0',
            f'POLYGON CONDUCTOR B LAYER met1 OUTER {ring}')
        def is_number(token: str) -> bool:
            return token.lstrip('-').replace('.', '', 1).isdigit()

        checked = 0
        for line in write_pex25d_text(read(text)).decode().splitlines():
            tokens = line.rstrip(CONTINUATION).split()
            if not tokens or not all(is_number(token) for token in tokens):
                continue
            checked += 1
            assert len(tokens) % 2 == 0, f"odd number of coordinates in {line!r}"
        assert checked >= 3, "expected several pure-coordinate continuation lines"

    # ------------------------------------------------------------ round trip

    def test_round_trip_is_byte_identical(self):
        once = write_pex25d_text(read(MINIMAL))
        twice = write_pex25d_text(read(once.decode()))
        assert once == twice

    def test_round_trip_preserves_the_message(self):
        original = read(MINIMAL)
        again = read(write_pex25d_text(original).decode())
        assert original.SerializeToString(deterministic=True) == \
            again.SerializeToString(deterministic=True)

    def test_comments_change_nothing_but_the_comments(self):
        plain = write_pex25d_text(read(MINIMAL), comments=False).decode()
        annotated = write_pex25d_text(read(MINIMAL), comments=True).decode()
        assert len(annotated) > len(plain)
        assert read_codes(annotated) == []

        def records(text: str) -> list:
            return [line for line in text.splitlines()
                    if line and not line.lstrip().startswith('#')]

        assert records(annotated) == records(plain)
