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
The kpex command line tool, run more than once in a process (e.g. by tests or by a script)
"""

from __future__ import annotations

import os
from typing import *

import allure
import pytest

from klayout_pex.kpex_cli import KpexCLI
from tests.common.cli_runner import run_cli
from tests.common.pdk_test_config import PDKName, PDKTestConfig


NFET_GDS_PATH = PDKTestConfig(PDKName.SKY130A).gds_path('test_patterns', 'nfet_li1.gds.gz')


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Logging")
@pytest.mark.parametrize('gds_path, log_dir', [
    (None, ''),  # NOTE: an error before the run directory is known, the logs stay in --out_dir
    (NFET_GDS_PATH, 'nfet_li1__nfet_li1'),  # NOTE: an error after, the logs move to the run directory
], ids=['missing layout', 'missing KLayout'])
def test_log_files_hold_their_own_run_only(gds_path: Optional[str], log_dir: str,
                                           tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('KPEX_KLAYOUT_EXE', str(tmp_path / 'no_klayout'))
    for run in ('first', 'second'):
        out_dir = str(tmp_path / run)
        code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D',
                                                '--gds', gds_path or os.path.join(out_dir, 'missing.gds'),
                                                '--out_dir', out_dir])
        assert code == 1, output
    for log_name in ('kpex.log', 'kpex_plain.log'):
        with open(tmp_path / 'first' / log_dir / log_name) as f:
            log = f.read()
        assert log.count('GDS input file passed, running in LVS mode') == 1, log
