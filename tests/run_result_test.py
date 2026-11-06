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
The result file of a kpex run, written when the run ends, with the exit code the process ends with
"""

from __future__ import annotations

from contextlib import nullcontext
import json
from typing import *

import allure
import pytest

from klayout_pex.log import error, warning
from klayout_pex.pex25d.diagnostics import ExitCode
from klayout_pex.run_result import RESULT_FILE_NAME, RunResult, Stage


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Result File")
@pytest.mark.parametrize('end, exit_code, stage, errors', [
    (None, 0, 'done', []),
    (SystemExit(None), 0, 'done', []),
    (SystemExit(ExitCode.USAGE), 2, 'lvs', []),
    (SystemExit("message"), 1, 'lvs', []),  # NOTE: Python prints the message and exits with 1
    (ValueError("unexpected"), 1, 'lvs', ["ValueError: unexpected"]),  # NOTE: and the traceback
], ids=['return', 'exit', 'exit code', 'exit message', 'exception'])
def test_result_file_has_the_exit_code_of_the_process(end: Optional[BaseException], exit_code: int, stage: str,
                                                      errors: List[str], tmp_path):
    result = RunResult(run_dir=str(tmp_path))
    with pytest.raises(type(end)) if end is not None else nullcontext():
        with result.recording():
            result.stage = Stage.LVS
            warning("a warning")
            if end is not None:
                raise end
    error("an error after the run")
    with open(tmp_path / RESULT_FILE_NAME, encoding='utf-8') as f:
        written = json.load(f)
    assert (written['exit_code'], written['stage'], written['warnings'], written['errors']) == \
           (exit_code, stage, ["a warning"], errors)
