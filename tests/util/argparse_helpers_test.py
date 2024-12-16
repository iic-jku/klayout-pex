#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/martinjankoehler/klayout-pex).
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
from enum import StrEnum, IntEnum
from typing import *
import unittest

from klayout_pex.util.argparse_helpers import render_enum_help


@allure.parent_suite("Unit Tests")
@allure.tag("Enum", "Help", "Util")
class Test(unittest.TestCase):
    def test_render_enum_help__nodefault__intenum(self):
        class IntEnum1(IntEnum):
            CASE1 = 1
            CASE2 = 2

        expected_string = "--arg ∈ {'case1', 'case2'}"
        obtained_string = render_enum_help(enum_cls=IntEnum1, topic="--arg", print_default=False)
        assert obtained_string == expected_string

    def test_render_enum_help__default__intenum(self):
        class IntEnum2(IntEnum):
            CASE1 = 1
            CASE2 = 2
            DEFAULT = CASE1

        expected_string = "--arg ∈ {'case1', 'case2', 'default'}.\nDefaults to 'case1'"
        obtained_string = render_enum_help(enum_cls=IntEnum2, topic="--arg", print_default=True)
        assert obtained_string == expected_string

    def test_render_enum_help__default__strenum(self):
        class StrEnum1(StrEnum):
            CASE1 = "Case1"
            CASE2 = "Case2"
            DEFAULT = CASE1

        expected_string = "--arg ∈ {'Case1', 'Case2', 'default'}.\nDefaults to 'Case1'"
        obtained_string = render_enum_help(enum_cls=StrEnum1, topic="--arg", print_default=True)
        assert obtained_string == expected_string

    def test_render_enum_help__default__strenum__lowercased(self):
        class StrEnum1(StrEnum):
            CASE1 = "Case1"
            CASE2 = "Case2"
            DEFAULT = CASE1

        expected_string = "--arg ∈ {'case1', 'case2', 'default'}.\nDefaults to 'case1'"
        obtained_string = render_enum_help(enum_cls=StrEnum1, topic="--arg",
                                           print_default=True,
                                           lowercase_strenum=True)
        assert obtained_string == expected_string
