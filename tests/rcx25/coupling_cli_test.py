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

"""CLI decisions for coupled and grounded analytical capacitance output."""

from typing import Optional, Sequence

import allure
import pytest

from klayout_pex.env import Env
from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.rcx25.coupling import CouplingPolicy
from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.cli_runner import run_cli

pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('CLI', 'RCX25', 'Capacitance Modes')]


@pytest.mark.parametrize('mode,capacitance,resistance', [('C', True, False), ('CC', True, False),
                                                       ('RC', True, True), ('R', False, True)])
def test_mode_flags(mode: str, capacitance: bool, resistance: bool):
    assert PEXMode(mode).need_capacitance() == capacitance
    assert PEXMode(mode).need_resistance() == resistance


@pytest.mark.parametrize('mode,policy,expected', [
    ('C', None, CouplingPolicy.GROUNDED), ('C', 'grounded', CouplingPolicy.GROUNDED),
    ('CC', None, CouplingPolicy.COUPLED), ('RC', None, CouplingPolicy.COUPLED),
    ('CC', 'grounded', CouplingPolicy.GROUNDED), ('RC', 'grounded', CouplingPolicy.GROUNDED),
    ('R', None, CouplingPolicy.COUPLED),
])
def test_cli_modes_and_coupling_defaults(mode: str, policy: Optional[str], expected: CouplingPolicy):
    args = KpexCLI.parse_args(['extract', '--pdk', 'sky130A', '--2.5D', '--mode', mode,
                               *(['--coupling', policy] if policy else [])], Env.from_os_environ())
    assert args.coupling_policy == expected
    assert args.blackbox_devices is False  # The new mode does not silently change device treatment


@pytest.mark.parametrize('arguments,reason', [
    (['--mode', 'C'], 'need --2.5D'),
    (['--coupling', 'grounded'], 'need --2.5D'),
    (['--2.5D', '--mode', 'R', '--coupling', 'grounded'], 'R extracts no capacitance'),
    (['--2.5D', '--mode', 'R', '--coupling', 'coupled'], 'R extracts no capacitance'),
    (['--2.5D', '--mode', 'C', '--coupling', 'coupled'], '--mode C means grounded coupling'),
    (['--2.5D', '--coupling', 'reference-only'], 'invalid CouplingPolicy value'),
])
def test_invalid_combinations_fail_before_reading_layout(arguments: Sequence[str], reason: str):
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A',
                                            '--gds', '/nonexistent/layout.gds', *arguments])
    assert code == 2, output
    assert reason in ' '.join(output.split()), output
    assert 'Cannot read GDS' not in output
