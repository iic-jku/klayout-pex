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
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from klayout_pex.pdk_config import PDK
from klayout_pex.tool_version_constraints import (
    TOOL_VERSION_CONSTRAINTS,
    Severity,
    Tool,
    ToolVersionConstraint,
    applicable_constraints,
    effective_version_range,
)


@allure.parent_suite('Unit Tests')
@allure.tag('Tool Versions', 'Version Constraints')
class Test(unittest.TestCase):
    def test_magic_reports_its_patch_level_as_a_revision(self):
        # the banner every MAGIC run prints, and what 'magic --version' gives
        assert Tool.MAGIC.parse_version(
            'Magic 8.3 revision 681 - Compiled on Di. 11 Aug. 2026 15:53:45 CEST.'
        ) == Version('8.3.681')
        assert Tool.MAGIC.parse_version('8.3.681') == Version('8.3.681')
        assert Tool.MAGIC.parse_version('no version in here') is None

    def test_a_packaging_release_is_not_part_of_the_tool_version(self):
        assert Tool.KLAYOUT.parse_version('KLayout 0.30.4') == Version('0.30.4')
        assert Tool.KLAYOUT.parse_version('klayout_0.30.4-1_amd64') == Version('0.30.4')
        assert Tool.FASTERCAP.parse_version('FasterCap 6.0.9') == Version('6.0.9')

    def test_constraints_compile_to_one_effective_range(self):
        assert effective_version_range(Tool.KLAYOUT) == SpecifierSet('>=0.30.1,>=0.30.2,>=0.30.3')
        assert effective_version_range(Tool.KLAYOUT).contains(Version('0.30.4'))
        assert not effective_version_range(Tool.KLAYOUT).contains(Version('0.30.2'))

    def test_a_pdk_constraint_is_part_of_that_pdk_s_range(self):
        for_sky130a = effective_version_range(Tool.MAGIC, pdk=PDK.SKY130A)
        assert for_sky130a == effective_version_range(Tool.MAGIC)
        assert {c.tool for c in applicable_constraints(Tool.MAGIC, PDK.SKY130A)} == {Tool.MAGIC}

    def test_an_excluded_version_is_the_only_one_rejected(self):
        constraint = ToolVersionConstraint(
            id='TEST_EXCLUSION', tool=Tool.KLAYOUT, specifier='!= 0.30.5',
            reason="a hypothetical regression")
        assert constraint.is_satisfied_by(Version('0.30.4'))
        assert not constraint.is_satisfied_by(Version('0.30.5'))
        assert constraint.is_satisfied_by(Version('0.30.6'))

    def test_a_pdk_constraint_applies_only_to_that_pdk(self):
        constraint = ToolVersionConstraint(
            id='TEST_PDK_SCOPED', tool=Tool.MAGIC, specifier='>= 8.3.540',
            reason="a PDK-specific requirement", pdk=PDK.SKY130A)
        assert constraint.applies_to(PDK.SKY130A)
        assert not constraint.applies_to(PDK.IHP_SG13G2)
        assert not constraint.applies_to(None)

    def test_every_declared_constraint_is_well_formed(self):
        ids = [c.id for c in TOOL_VERSION_CONSTRAINTS]
        assert len(ids) == len(set(ids)), "constraint IDs have to be unique"
        for constraint in TOOL_VERSION_CONSTRAINTS:
            with self.subTest(constraint=constraint.id):
                assert constraint.id.isupper()
                assert constraint.reason, "a constraint has to say why it exists"
                assert constraint.severity in (Severity.ERROR, Severity.WARNING)
                assert str(constraint.specifier_set) != ''
