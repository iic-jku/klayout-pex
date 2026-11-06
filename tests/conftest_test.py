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

import json
from pathlib import Path
from typing import *

import allure

from tests.common.cli_runner import run_cli_process

parent_suite = "Unit Tests"
tags = ("Allure",)

TESTS = """
import logging

def test_passes():
    print('console copy of the log')
    logging.getLogger('__kpex__').warning('logged')

def test_fails():
    print('console copy of the log')
    logging.getLogger('__kpex__').warning('logged')
    assert False
"""


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_allure_report_attaches_stdout_of_failing_tests_only(tmp_path: Path):
    # NOTE: the hook in the conftest of a subdirectory, which pytest registers while collecting,
    #       after the Allure plugin (as tests/conftest.py when pytest runs without arguments)
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'conftest.py').write_text('from tests.conftest import pytest_runtest_makereport\n',
                                                  encoding='utf-8')
    (tmp_path / 'sub' / 'inner_test.py').write_text(TESTS, encoding='utf-8')
    (tmp_path / 'pytest.ini').write_text('[pytest]\n', encoding='utf-8')
    results_dir = tmp_path / 'allure-results'

    result = run_cli_process('pytest', ['-p', 'no:cacheprovider', '-c', str(tmp_path / 'pytest.ini'),
                                        '--alluredir', str(results_dir), str(tmp_path)])
    assert result.returncode == 1, result.stdout + result.stderr

    attachments: Dict[str, List[str]] = {}
    for path in results_dir.glob('*-result.json'):
        test_result = json.loads(path.read_text(encoding='utf-8'))
        attachments[test_result['name']] = sorted(a['name'] for a in test_result.get('attachments', []))
    assert attachments == {'test_passes': ['log'], 'test_fails': ['log', 'stdout']}, result.stdout + result.stderr
