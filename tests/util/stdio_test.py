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
The command line tools write UTF-8, also where the locale has another encoding,
e.g. cp1252 of a pipe on Windows (here set by PYTHONIOENCODING)
"""

from __future__ import annotations

from typing import *

import allure
import pytest

from klayout_pex.pex25d.diagnostics import ExitCode
from tests.common.cli_runner import run_cli_process

CP1252_PIPE = {'PYTHONIOENCODING': 'cp1252', 'COLUMNS': '300'}  # NOTE: no line breaks within the texts


@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
@pytest.mark.parametrize('module, argv, text', [
    ('klayout_pex', ['extract', '-h'], "log_level ∈ {"),
    ('klayout_pex.pex25d', ['-h'], "log_level ∈ {"),
    ('klayout_pex.netlist', ['reduce', '-h'], "an integer ≥ 1"),
], ids=['kpex', 'pex25d', 'netlist'])
def test_help_in_utf8(module: str, argv: List[str], text: str):
    result = run_cli_process(module, argv, env=CP1252_PIPE)
    assert result.returncode == 0, result.stderr
    assert text in result.stdout, result.stderr


@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
def test_messages_in_utf8(tmp_path):
    result = run_cli_process('klayout_pex.netlist', ['reduce', str(tmp_path / 'line.spice'), '--ticer_max_degree', 'x'],
                             env=CP1252_PIPE)
    assert result.returncode == ExitCode.USAGE, result.stderr
    assert "must be an integer ≥ 1, got 'x'" in result.stderr
