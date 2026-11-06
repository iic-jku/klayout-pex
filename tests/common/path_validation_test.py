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

from pathlib import Path
from unittest.mock import patch

import allure
import pytest

from klayout_pex.common.path_validation import validate_files


@allure.parent_suite('Unit Tests')
@allure.tag('File Validation')
class TestFileValidation:
    def test_mixed_paths_report_all_failures_and_keep_working_files(self, tmp_path: Path):
        first = tmp_path / 'first.bin'
        first.write_bytes(b'\x00\xff')
        empty = tmp_path / 'empty.bin'
        empty.touch()
        missing = tmp_path / 'missing.bin'
        result = validate_files([first, str(missing), tmp_path, str(empty)])
        # NOTE: the paths as Path, also those given as str
        assert result.working_files == [first, empty]
        assert [(failure.path, failure.reason) for failure in result.failures] == [
            (missing, 'File does not exist'), (tmp_path, 'Not a regular file')]

    @pytest.mark.parametrize('failure', [PermissionError('access denied'), OSError('read failed')])
    def test_unreadable_files_are_reported(self, tmp_path: Path, failure: OSError):
        path = tmp_path / 'unreadable'
        path.touch()
        # Simulate I/O failure independently of platform and test-user privileges.
        with patch('klayout_pex.common.path_validation.open', side_effect=failure):
            result = validate_files([path])
        assert result.working_files == []
        assert len(result.failures) == 1
        assert result.failures[0].path == path
        assert result.failures[0].reason == f'Unreadable: {failure}'

    def test_empty_input_has_no_failures(self):
        result = validate_files([])
        assert result.working_files == []
        assert result.failures == []
