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

"""Diagnostics from failed simulator commands, including successful process exits."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.common.ngspice import ngspice_port_admittance


@pytest.mark.parametrize('returncode', [0, 1])
def test_missing_admittance_data_includes_simulator_diagnostics(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, returncode: int):
    # ngspice control commands can fail while the process still returns success.
    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args[0], returncode,
                                           stdout='simulation output', stderr='missing simulator vector')

    monkeypatch.setattr(subprocess, 'run', run)
    source = tmp_path / 'source.spice'
    source.write_text('.SUBCKT cell A B\nR1 A B 100\n.ENDS cell\n', encoding='utf-8')
    with pytest.raises(AssertionError) as exc_info:
        ngspice_port_admittance(str(source), 'cell', ['A', 'B'], (9, 9), str(tmp_path))
    assert 'simulation output' in str(exc_info.value)
    assert 'missing simulator vector' in str(exc_info.value)
