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
Command line tools in tests: run in this process (with their exit code and output),
or in a fresh one, e.g. to check which modules they load
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import subprocess
import sys
from typing import *

REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_cli(main: Callable[[List[str]], None], argv: List[str]) -> Tuple[int, str]:
    """
    Runs the main function of a command line tool (e.g. NetlistCLI().main) in this process.

    :return: the exit code and the output: stdout and stderr, and the logged messages
             (as they are, the console wraps them)
    """
    output = io.StringIO()
    records: List[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger('__kpex__')
    logger.addHandler(handler)
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            main(argv)
        code = 0
    except SystemExit as e:
        code = e.code
    finally:
        logger.removeHandler(handler)
    return code, output.getvalue() + '\n'.join(r.getMessage() for r in records)


def run_cli_process(module: str,
                    argv: Sequence[str],
                    env: Mapping[str, str] = {}) -> subprocess.CompletedProcess:
    """
    Runs a command line tool (e.g. klayout_pex.netlist) in a fresh process, as its console script does

    :param env: variables to set besides those of this process
    :return: the result, with the output decoded as UTF-8, which the tools write
    """
    return subprocess.run([sys.executable, '-m', module, *argv], cwd=REPO_DIR, capture_output=True,
                          encoding='utf-8', env={**os.environ, **env})


def assert_netlist_cli_loads_neither_klayout_nor_protobuf(argv: Sequence[str]):
    """
    Runs the netlist tool in a fresh process (the tests have loaded both) and asserts that it succeeds
    without loading KLayout or the generated protobuf code, as format-only paths must (AGENTS.md)
    """
    script = ("import sys\n"
              "from klayout_pex.netlist.netlist_cli import NetlistCLI\n"
              "try:\n"
              f"    NetlistCLI().main({list(argv)!r})\n"
              "except SystemExit as exit:\n"
              "    assert exit.code == 0, exit.code\n"
              "loaded = sorted(m for m in sys.modules if m.split('.')[0] in ('klayout', 'klayout_pex_protobuf'))\n"
              "assert not loaded, loaded\n")
    result = subprocess.run([sys.executable, '-c', script], cwd=REPO_DIR, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
