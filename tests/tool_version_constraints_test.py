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
from unittest import mock
from typing import Optional, Tuple

import pytest

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
    check_tool_versions,
    VersionCheckMode,
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
        required = effective_version_range(Tool.KLAYOUT, severity=Severity.ERROR)
        assert required == SpecifierSet('>=0.30.1,>=0.30.2,>=0.30.3')
        assert required.contains(Version('0.30.4'))
        assert not required.contains(Version('0.30.2'))
        assert effective_version_range(Tool.KLAYOUT, severity=Severity.WARNING) == SpecifierSet('>=0.30.13')

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


@pytest.mark.parametrize('binary,module,expected_sources', [
    ('0.30.12', '0.30.13', ('KLayout executable',)),
    ('0.30.13', '0.30.12', ('KLayout Python module',)),
    ('0.30.12', '0.30.12', ('KLayout executable', 'KLayout Python module')),
    ('0.30.13', '0.30.13', ()),
    ('0.30.14', '0.31.0', ()),
    (None, '0.30.12', ('KLayout Python module',)),
    ('0.30.12', None, ('KLayout executable',)),
    (None, '0.30.13rc1', ('KLayout Python module',)),
])
def test_recommended_version_warns_without_rejecting_supported_installations(
        binary: Optional[str], module: Optional[str], expected_sources: Tuple[str, ...]):
    # Independently check both components: upgrading the wheel does not update
    # the executable, and an LVSDB-only run still uses the Python module.
    with mock.patch('klayout_pex.tool_version_constraints.warning') as warn, \
            mock.patch('klayout_pex.tool_version_constraints.error') as error, \
            mock.patch.object(Tool, 'detect_version', return_value=Version(binary) if binary else None):
        assert check_tool_versions({Tool.KLAYOUT: '/klayout'} if binary else {}, klayout_python_version=module)
    messages = [call.args[0] for call in warn.call_args_list]
    assert len(messages) == len(expected_sources)
    assert all(any(source in message and 'Upgrading is recommended' in message for message in messages)
               for source in expected_sources)
    error.assert_not_called()


@pytest.mark.parametrize('mode,accepted', [(VersionCheckMode.ON, False), (VersionCheckMode.WARN, True)])
def test_existing_hard_constraints_keep_their_severity(mode: VersionCheckMode, accepted: bool):
    with mock.patch('klayout_pex.tool_version_constraints.warning') as warn, \
            mock.patch('klayout_pex.tool_version_constraints.error') as error:
        assert check_tool_versions({}, mode=mode, klayout_python_version='0.30.2') == accepted
    assert bool(error.call_count) == (mode == VersionCheckMode.ON)
    assert any('KLAYOUT_03013_FIXES' in call.args[0] for call in warn.call_args_list)


@pytest.mark.parametrize('tool', [Tool.KLAYOUT, Tool.MAGIC])
def test_off_disables_tools_and_python_module_without_detecting_versions(tool: Tool):
    with mock.patch.object(Tool, 'detect_version', side_effect=AssertionError('must not detect')), \
            mock.patch('klayout_pex.tool_version_constraints.warning') as warn:
        assert check_tool_versions({tool: '/missing'}, mode=VersionCheckMode.OFF,
                                   klayout_python_version='unknown')
    warn.assert_not_called()


@pytest.mark.parametrize('tool,label', [(Tool.KLAYOUT, 'KLayout executable'), (Tool.MAGIC, 'MAGIC')])
def test_unknown_versions_are_reported_as_unchecked(tool: Tool, label: str):
    with mock.patch.object(Tool, 'detect_version', return_value=None), \
            mock.patch('klayout_pex.tool_version_constraints.warning') as warn:
        assert check_tool_versions({tool: '/tool'}, klayout_python_version='unknown')
    assert len(warn.call_args_list) == 2
    assert all('unchecked' in call.args[0] for call in warn.call_args_list)
    assert any(label in call.args[0] for call in warn.call_args_list)
    assert any('KLayout Python module' in call.args[0] for call in warn.call_args_list)


@pytest.mark.parametrize('version,supported', [
    ('8.3.679', False), ('8.3.692', False), ('8.3.693', True), ('8.3.694', True), ('8.4.0', True),
])
@pytest.mark.parametrize('mode', [VersionCheckMode.ON, VersionCheckMode.WARN])
def test_magic_requires_correct_sidewall_counting(version: str, supported: bool, mode: VersionCheckMode):
    # The old minimum still halved twice. Check the last affected revision,
    # the first fixed one, and newer revisions without imposing an upper bound.
    with mock.patch.object(Tool, 'detect_version', return_value=Version(version)), \
            mock.patch('klayout_pex.tool_version_constraints.warning') as warn, \
            mock.patch('klayout_pex.tool_version_constraints.error') as error:
        assert check_tool_versions({Tool.MAGIC: '/magic'}, mode=mode) == \
               (supported or mode == VersionCheckMode.WARN)
    assert error.call_count == int(not supported and mode == VersionCheckMode.ON)
    assert warn.call_count == int(not supported and mode == VersionCheckMode.WARN)
    messages = [call.args[0] for call in error.call_args_list + warn.call_args_list]
    assert all(f'MAGIC {version}' in message and '>= 8.3.693' in message and 'sidewall' in message
               for message in messages)


def test_report_separates_required_and_recommended_ranges():
    with mock.patch('klayout_pex.tool_version_constraints.subproc') as printed:
        assert check_tool_versions({}, klayout_python_version='0.30.13')
    header, row = [call.args[0] for call in printed.call_args_list]
    assert 'Required' in header and 'Recommended' in header
    assert '0.30.3' in row and '0.30.13' in row
