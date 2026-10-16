#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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
The long options of the command line tools: dashes between words (e.g. --out-dir), and out at the start
of the name of an output (e.g. --out-file), their former names (e.g. --out_dir) hidden from the help,
and the options all tools have (e.g. --log-level)
"""

from __future__ import annotations

import argparse
import re
from typing import *

import allure
import pytest

from klayout_pex.env import Env
from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.log import LogLevel
from klayout_pex.magic import magic_log_analyzer
from klayout_pex.netlist.netlist_cli import NetlistCLI
from klayout_pex.pex25d.pex25d_cli import Pex25DCLI
from tests.common.cli_runner import run_cli
from tests.common.rc_networks import LINE_NETLIST, write

HELP_COMMANDS: Dict[str, Callable[[], Tuple[int, str]]] = {
    **{f"kpex {sub}": (lambda sub=sub: run_cli(KpexCLI().main, ['kpex', sub, '--help']))
       for sub in ('extract', 'pex25d')},
    **{f"pex25d {sub}".rstrip(): (lambda sub=sub: run_cli(Pex25DCLI().main, ['pex25d', *sub.split(), '--help']))
       for sub in ('', 'show', 'validate', 'convert', 'resolve', 'import', 'export')},
    **{f"netlist {sub}".rstrip(): (lambda sub=sub: run_cli(NetlistCLI().main, ['netlist', *sub.split(), '--help']))
       for sub in ('', 'svg', 'reduce', 'convert')},
    # NOTE: without --help (add_help=False), its usage error has its options
    'magic log analyzer': lambda: run_cli(magic_log_analyzer._parse_args, []),
}

def help_options(command: str) -> List[str]:
    """The long options the help or usage of the command names, its descriptions included"""
    code, output = HELP_COMMANDS[command]()
    assert code in (0, 2), output
    options = sorted(set(re.findall(r'--\w(?:[\w.-]*\w)?', output)))
    assert options, output
    return options


@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
@pytest.mark.parametrize('command', HELP_COMMANDS)
def test_long_options_have_dashes_and_outputs_start_with_out(command: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('COLUMNS', '300')  # NOTE: no option name wrapped
    options = help_options(command)
    assert [o for o in options if '_' in o] == []
    assert [o for o in options if o.startswith('--output')] == []


# ------------------------------------------------------------------------------- the former names still work

@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
def test_kpex_reads_former_option_names():
    args = KpexCLI.parse_args(['extract', '--pdk', 'sky130A', '--gds', 'x.gds', '--out_dir', 'out',
                               '--netlist_format', 'vacask', '--magic_pre_flatten', '--log_level', 'debug'],
                              env=Env.from_os_environ())
    assert (args.output_dir_base_path, args.netlist_format, args.magic_pre_flatten) == ('out', 'vacask', True)
    assert [former for former, _ in args.deprecated_options] == \
           ['--out_dir', '--netlist_format', '--magic_pre_flatten', '--log_level']


@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
def test_netlist_reduce_reads_former_option_names_and_warns(tmp_path):
    input_path = write(str(tmp_path), 'line.spice', LINE_NETLIST)
    output_path = str(tmp_path / 'reduced.spice')
    code, output = run_cli(NetlistCLI().main, ['netlist', 'reduce', input_path, '--output', output_path,
                                               '--ticer_tau', '1p'])
    assert code == 0, output
    assert (tmp_path / 'reduced.spice').exists()
    assert '--output is deprecated, use --out-netlist' in output
    assert '--ticer_tau is deprecated, use --ticer-tau' in output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
def test_magic_log_analyzer_reads_former_option_names(tmp_path):
    args = magic_log_analyzer._parse_args(['--magic_log_dir', str(tmp_path), '--out', 'report.rdb.gz'])
    assert (args.magic_log_dir_path, args.output_rdb_path) == (str(tmp_path), 'report.rdb.gz')
    assert args.deprecated_options == [('--magic_log_dir', '--magic-log-dir'), ('--out', '--out-rdb')]


# ------------------------------------------------------------------------------- the options of all tools

@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
@pytest.mark.parametrize('parse', [
    lambda *a: KpexCLI.parse_args(['extract', '--pdk', 'sky130A', '--gds', 'x.gds', *a], env=Env.from_os_environ()),
    lambda *a: Pex25DCLI().parse_args([*a, 'plugins']),
    lambda *a: NetlistCLI().parse_args([*a, 'convert', 'x.spice', '--to', 'vacask']),
], ids=['kpex', 'pex25d', 'netlist'])
def test_log_level_by_name(parse: Callable[..., argparse.Namespace]):
    assert parse().log_level == LogLevel.SUBPROCESS
    assert parse('--log-level', 'debug').log_level == LogLevel.DEBUG
