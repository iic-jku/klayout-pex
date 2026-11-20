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
    FASTERCAP_NUMERICAL_REPORT,
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

    def test_a_prerelease_banner_keeps_its_suffix(self):
        assert Tool.FASTERCAP.parse_version('FasterCap version 6.3.0rc1') == Version('6.3.0rc1')
        assert Tool.FASTERCAP.parse_version('FasterCap version 6.3.0.dev1') == Version('6.3.0.dev1')
        assert Tool.FASTERCAP.parse_version('FasterCap version 6.3.0') == Version('6.3.0')

    def test_a_prerelease_cannot_satisfy_a_stable_version_constraint(self):
        constraint = ToolVersionConstraint(
            id='TEST_PRERELEASE', tool=Tool.FASTERCAP, specifier='>= 6.3.0',
            reason="a hypothetical calibration requirement")
        assert not constraint.is_satisfied_by(Version('6.3.0rc1'))
        assert not constraint.is_satisfied_by(Version('6.3.0.dev1'))
        assert constraint.is_satisfied_by(Version('6.3.0'))

    def test_a_fastercap_prerelease_fails_numerical_report_calibration(self):
        assert not FASTERCAP_NUMERICAL_REPORT.is_satisfied_by(Version('6.3.0rc1'))
        assert not FASTERCAP_NUMERICAL_REPORT.is_satisfied_by(Version('6.3.0.dev1'))
        assert FASTERCAP_NUMERICAL_REPORT.is_satisfied_by(Version('6.3.0'))

    def test_a_fastercap_prerelease_warns_at_the_stable_version_boundary(self):
        with mock.patch('klayout_pex.tool_version_constraints.warning') as warning, \
                mock.patch.object(Tool, 'detect_version', return_value=Version('6.3.0rc1')):
            assert check_tool_versions({Tool.FASTERCAP: '/FasterCap'})
        assert any('Upgrading is recommended' in call.args[0]
                   for call in warning.call_args_list)

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


@pytest.mark.parametrize('version', [
    '6.3.0-rc1', '6.3.0_rc_1', '6.3.0rc', '6.3.0preview1', '6.3.0c1',
    '6.3.0.dev', '6.3.0.post1.dev1', '6.3.0rc1.post2.dev3', '6.3.0+local.1',
])
def test_fastercap_keeps_complete_version_token(version: str):
    # PEP 440 allows separators, aliases, implicit zeroes and combined suffixes.
    # Keeping only the first suffix can change ordering and solver provenance.
    assert Tool.FASTERCAP.parse_version(f'FasterCap version {version}') == Version(version)


@pytest.mark.parametrize('version', ['6.3.0-rc1', '6.3.0rc', '6.3.0.dev'])
def test_calibration_rejects_banners_below_stable_minimum(version: str):
    import subprocess
    import sys
    from klayout_pex.calibration.solve import _solver_identity
    from klayout_pex.calibration.validation import CalibrationError

    # Exercise detection and the actual calibration gate, not a pre-parsed mock.
    # FasterCap may report its version while returning an unsupported-option code.
    response = subprocess.CompletedProcess([], 64, f'FasterCap version {version}', '')
    with mock.patch('klayout_pex.tool_version_constraints.subprocess.run', return_value=response):
        with pytest.raises(CalibrationError, match='Calibration requires FasterCap'):
            _solver_identity(sys.executable)


@pytest.mark.parametrize('version,accepted', [
    ('6.3.0.post1.dev1', False), ('6.3.0.post1', True), ('6.3.0.post2', True),
])
def test_development_suffix_keeps_postrelease_boundary(version: str, accepted: bool):
    # post1.dev1 is newer than 6.3.0, but must not pass a post1 minimum.
    constraint = ToolVersionConstraint(
        id='TEST_POSTRELEASE', tool=Tool.FASTERCAP, specifier='>= 6.3.0.post1',
        reason='a hypothetical fix first available in a postrelease')
    detected = Tool.FASTERCAP.parse_version(f'FasterCap version {version}')
    assert detected is not None
    assert constraint.is_satisfied_by(detected) == accepted


@pytest.mark.parametrize('version', ['6.3.0rcgarbage', '6.3.0.post1.devgarbage'])
def test_invalid_fastercap_suffix_is_not_silently_truncated(version: str):
    assert Tool.FASTERCAP.parse_version(f'FasterCap version {version}') is None


@pytest.mark.parametrize('version,upgrade', [
    ('6.3.0', True), ('6.3.99', True), ('6.4.0.dev1', True), ('6.4.0rc1', True),
    ('6.4.0', False), ('6.4.1', False),
])
@pytest.mark.parametrize('mode', [VersionCheckMode.ON, VersionCheckMode.WARN])
def test_fastercap_corrected_solver_is_recommended_without_blocking_extraction(
        version: str, upgrade: bool, mode: VersionCheckMode):
    # Report support starts earlier than the corrected numerical baseline. Keep
    # ordinary extraction available, but never present a prerelease as final 6.4.
    parsed = Tool.FASTERCAP.parse_version(f'FasterCap version {version}')
    assert parsed == Version(version)
    with mock.patch.object(Tool, 'detect_version', return_value=parsed), \
            mock.patch('klayout_pex.tool_version_constraints.warning') as warn, \
            mock.patch('klayout_pex.tool_version_constraints.error') as error:
        assert check_tool_versions({Tool.FASTERCAP: '/fastercap'}, mode=mode)
    error.assert_not_called()
    assert warn.call_count == int(upgrade)
    if upgrade:
        message = warn.call_args.args[0]
        assert '6.4.0' in message and 'Upgrading is recommended' in message


def test_fastercap_report_contract_remains_independent_of_recommended_solver():
    # Saved 6.3 reports remain evidence at their original version and precision.
    assert FASTERCAP_NUMERICAL_REPORT.is_satisfied_by(Version('6.3.0'))
    assert not FASTERCAP_NUMERICAL_REPORT.is_satisfied_by(Version('6.2.99'))
    supported = effective_version_range(Tool.FASTERCAP)
    assert Version('6.3.99') not in supported
    assert Version('6.4.0') in supported
