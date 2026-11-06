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
The peak memory of a run, as resident set size, in bytes on each platform
"""

from __future__ import annotations

import logging
import sys
from unittest import mock

import allure
import pytest

from klayout_pex.util.peak_memory import PeakMemory, format_bytes, log_peak_memory
from tests.common.cli_runner import run_python_script

MIB = 1 << 20


@allure.parent_suite("Unit Tests")
@allure.tag("Logging", "Util")
def test_peak_memory_is_in_bytes():
    # NOTE: in a fresh process, whose subprocess takes 128 MiB, and then itself, as ru_maxrss is in bytes on macOS,
    #       in KiB on Linux, which also carries it over to a subprocess, e.g. from this test runner (see PeakMemory)
    script = ("import subprocess, sys\n"
              "from klayout_pex.util.peak_memory import peak_memory\n"
              "subprocess.run([sys.executable, '-c', \"data = b'x' * (128 << 20)\"], check=True)\n"
              "data = b'x' * (128 << 20)\n"
              "memory = peak_memory()\n"
              "print(memory.process, memory.largest_subprocess)\n")
    result = run_python_script(script)
    assert result.returncode == 0, result.stderr
    process, largest_subprocess = result.stdout.split()
    assert 128 * MIB <= int(process) < 256 * MIB, result.stdout
    if sys.platform == 'win32':
        assert largest_subprocess == 'None'  # NOTE: Windows doesn't tell
    else:
        assert 128 * MIB <= int(largest_subprocess) < 256 * MIB, result.stdout


@allure.parent_suite("Unit Tests")
@allure.tag("Logging", "Util")
@pytest.mark.parametrize('memory, logged', [
    (PeakMemory(process=200 * MIB, largest_subprocess=300 * MIB),
     "Peak memory (resident set size) after LVS: 200.0 MiB, largest subprocess 300.0 MiB"),
    # NOTE: on Linux, it may be the size of this process when it started the subprocess
    (PeakMemory(process=200 * MIB, largest_subprocess=100 * MIB),
     "Peak memory (resident set size) after LVS: 200.0 MiB"),
    (PeakMemory(process=200 * MIB, largest_subprocess=None),
     "Peak memory (resident set size) after LVS: 200.0 MiB"),
], ids=['larger subprocess', 'smaller subprocess', 'Windows'])
def test_log_names_the_largest_subprocess_only_if_larger(memory: PeakMemory, logged: str,
                                                         caplog: pytest.LogCaptureFixture):
    with mock.patch('klayout_pex.util.peak_memory.peak_memory', return_value=memory):
        log_peak_memory('LVS')
    assert ('__kpex__', logging.INFO, logged) in caplog.record_tuples


@allure.parent_suite("Unit Tests")
@allure.tag("Logging", "Util")
@pytest.mark.parametrize('size, text', [
    (512, '512 B'),
    (1536, '1.5 KiB'),
    (int(245.3 * MIB), '245.3 MiB'),
    (int(5.7 * 1024 * MIB), '5.7 GiB'),
])
def test_format_bytes(size: int, text: str):
    assert format_bytes(size) == text
