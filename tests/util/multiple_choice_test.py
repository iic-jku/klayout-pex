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

import allure
import pytest

from klayout_pex.util.multiple_choice import MultipleChoicePattern


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
