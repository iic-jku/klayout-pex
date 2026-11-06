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

"""
The multiple choice patterns, e.g. of the dielectrics (kpex --diel)
"""

from __future__ import annotations

from typing import *

import allure
import pytest

from klayout_pex.util.multiple_choice import MultipleChoicePattern

CHOICES = ['ild1', 'ild2', 'Pass']


@allure.parent_suite("Unit Tests")
@allure.tag("Util")
@pytest.mark.parametrize('pattern, included', [
    ('all', ['ild1', 'ild2', 'Pass']),
    ('none', []),
    ('all,-ild1', ['ild2', 'Pass']),
    ('-ild1', ['ild2', 'Pass']),
    ('none,+ild1', ['ild1']),
    ('+ild1', ['ild1']),
    (' -ILD1 , - pass ', ['ild2']),
])
def test_pattern_includes_the_choices(pattern: str, included: List[str]):
    # NOTE: -ild1 and +ild1 included no choice, though filter returned those of +ild1 (#451)
    multiple_choice = MultipleChoicePattern(pattern)
    assert multiple_choice.filter(CHOICES) == included
    assert [c for c in CHOICES if multiple_choice.is_included(c)] == included


@allure.parent_suite("Unit Tests")
@allure.tag("Util")
@pytest.mark.parametrize('pattern, message', [
    ('al', "Multiple choice pattern can only have the subpatterns all, none, +name and -name, not 'al'"),
    ('all,,+', "Multiple choice pattern can only have the subpatterns all, none, +name and -name, not '', '+'"),
    ('-ild1,+ild2', "Multiple choice pattern can't have both inclusive (+) and exclusive (-) subpatterns"),
    ('all,+ild2', "Multiple choice pattern based on all can only have exclusive (-) subpatterns"),
    ('all,none', "Multiple choice pattern can't have both subpatterns all and none"),
])
def test_invalid_pattern_is_an_error(pattern: str, message: str):
    with pytest.raises(ValueError) as e:
        MultipleChoicePattern(pattern)
    assert str(e.value) == message


@allure.parent_suite("Unit Tests")
@allure.tag("Util")
@pytest.mark.parametrize('pattern, unknown_choices', [
    ('all', []),
    ('-ILD1,-pass', []),
    ('+ild1,+ild3,+ILD3', ['ild3']),
])
def test_unknown_choices_are_the_names_of_no_choice(pattern: str, unknown_choices: List[str]):
    assert MultipleChoicePattern(pattern).unknown_choices(CHOICES) == unknown_choices



@allure.parent_suite('Unit Tests')
@allure.tag('Util', 'Dielectric Filter')
class TestMultipleChoicePattern:
    @pytest.mark.parametrize('pattern, expected', [
        ('all', ['ild', 'nit', 'air', 'ild']),
        ('none', []),
        ('all,-nit', ['ild', 'air', 'ild']),
        ('none,+air,+ild', ['ild', 'air', 'ild']),
        (' ALL , -NIT ', ['ild', 'air', 'ild']),
        ('none,+missing', []),
        ('all,-missing', ['ild', 'nit', 'air', 'ild']),
    ])
    def test_filter_and_membership_agree_and_preserve_input_order(self, pattern: str, expected: List[str]):
        choices = ['ild', 'nit', 'air', 'ild']
        selector = MultipleChoicePattern(pattern)
        assert selector.filter(choices) == expected
        assert [choice for choice in choices if selector.is_included(choice)] == expected
        assert choices == ['ild', 'nit', 'air', 'ild']
        assert selector.filter([]) == []

    @pytest.mark.parametrize('pattern', ['all,none', 'none,-ild', 'all,+ild'])
    def test_conflicting_selectors_are_rejected(self, pattern: str):
        with pytest.raises(ValueError, match='Multiple choice pattern'):
            MultipleChoicePattern(pattern)
