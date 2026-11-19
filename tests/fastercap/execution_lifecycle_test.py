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

"""Timeouts, cancellation and failure evidence use real child processes."""

import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any, Callable

import allure
import pytest

from klayout_pex.fastercap.fastercap_runner import run_fastercap, fastercap_parse_capacitance_matrix
from klayout_pex.fastercap.fastercap_error import (FasterCapError, FasterCapExecutionError,
                                                 FasterCapTimeoutError, FasterCapCancelledError)

pytestmark = allure.parent_suite('Unit Tests')


@pytest.fixture
def child_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable:
    popen = subprocess.Popen
    script = tmp_path / 'child.py'
    def start(source: str, **options: Any):
        script.write_text(source, encoding='utf-8')
        # Use Python as a portable stand-in executable; exercise the real process,
        # pipes, deadline and environment rather than mock its lifecycle.
        def launch(args: Any, **kwargs: Any) -> subprocess.Popen:
            if args[0] == 'taskkill':
                return popen(args, **kwargs)
            return popen([sys.executable, str(script), *args[1:]], **kwargs)
        monkeypatch.setattr('klayout_pex.fastercap.fastercap_runner.subprocess.Popen', launch)
        return run_fastercap(sys.executable, 'input.lst', str(tmp_path / 'solver.log'),
                             0.05, 0.5, 0, True, False, False, **options)
    return start


def test_success_records_command_and_environment(child_runner: Callable, tmp_path: Path):
    original = dict(os.environ)
    env = os.environ.copy()
    env['OMP_NUM_THREADS'] = '2'
    result = child_runner("import os; print(os.environ['OMP_NUM_THREADS'])", env=env, timeout_seconds=5)
    assert result.returncode == 0
    assert '-a0.05' in result.arguments
    assert (tmp_path / 'solver.log').read_text(encoding='utf-8').strip() == '2'
    assert dict(os.environ) == original


def test_nonzero_exit_keeps_log(child_runner: Callable, tmp_path: Path):
    with pytest.raises(FasterCapExecutionError) as caught:
        child_runner("import sys; print('evidence', flush=True); sys.exit(75)", timeout_seconds=5)
    assert caught.value.result.returncode == 75
    assert 'evidence' in (tmp_path / 'solver.log').read_text(encoding='utf-8')


def test_deadline_reaps_silent_process(child_runner: Callable, tmp_path: Path):
    with pytest.raises(FasterCapTimeoutError) as caught:
        child_runner("import time; print('started', flush=True); time.sleep(60)", timeout_seconds=0.5)
    assert caught.value.result.returncode is not None
    assert caught.value.result.duration_seconds < 8
    assert 'started' in (tmp_path / 'solver.log').read_text(encoding='utf-8')


def test_cancellation_reaps_silent_process(child_runner: Callable):
    event = threading.Event()
    timer = threading.Timer(0.5, event.set)
    timer.start()
    try:
        with pytest.raises(FasterCapCancelledError):
            child_runner('import time; time.sleep(60)', cancel_event=event, timeout_seconds=10)
    finally:
        timer.cancel()
        timer.join()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX process group lifecycle')
def test_deadline_stops_descendant_holding_stdout(child_runner: Callable):
    source = "import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])"
    with pytest.raises(FasterCapTimeoutError) as caught:
        child_runner(source, timeout_seconds=0.5)
    assert caught.value.result.duration_seconds < 8


@pytest.mark.parametrize('tail', [
    'Dimension 0 x 0\n', 'Dimension 1 x 2\ng1_A 1 2\n',
    'Dimension 2 x 2\ng1_A 1 2\n',
    'Dimension 1 x 1\ng1_A 1e-320\n',
    'Dimension 1 x 1\ng1_A nan\n', 'Dimension 1 x 1\ng1_A inf\n',
    'Dimension 2 x 2\ng1_A 1 2\ng1_A 3 4\n',
    'Dimension 1 x 1\ng1_A 1\nIteration number #2\n',
])
def test_malformed_final_matrix_is_not_replaced_by_earlier_one(tmp_path: Path, tail: str):
    path = tmp_path / 'solver.log'
    path.write_text('Capacitance matrix is:\nDimension 1 x 1\ng1_A 1\n'
                    'Capacitance matrix is:\n' + tail, encoding='utf-8')
    with pytest.raises(FasterCapError):
        fastercap_parse_capacitance_matrix(str(path))
