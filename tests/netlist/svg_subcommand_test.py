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

"""``netlist svg``: argument validation, exit codes, files written (with a stand-in for netlistsvg)"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from typing import *

import allure
import pytest

import klayout_pex
from klayout_pex.netlist.netlist_cli import NetlistCLI
from klayout_pex.pex25d.diagnostics import ExitCode
from tests.common.cli_runner import run_cli
from tests.common.rc_networks import write

parent_suite = "Unit Tests"
tags = ("Netlist", "Netlist SVG Diagram", "CLI")

DIVIDER_NETLIST = """\
.SUBCKT divider A B C
R1 A B 100
R2 B C 200
.ENDS divider
"""


def fake_netlistsvg(directory: str, exit_code: int = 0) -> str:
    """
    A stand-in for netlistsvg, which writes the arguments it got as the SVG (as JSON),
    or fails with the exit code

    :return: its path, for --exe
    """
    script_path = write(directory, 'fake_netlistsvg.py', textwrap.dedent(f"""\
        import json, os, sys
        if {exit_code}:
            print('fake netlistsvg fails')
            sys.exit({exit_code})
        args = sys.argv[1:]
        skin_path, input_path = args[args.index('--skin') + 1], args[-1]
        with open(input_path) as f:
            modules = list(json.load(f)['modules'])
        with open(args[args.index('-o') + 1], 'w') as f:
            json.dump({{'skin': skin_path, 'skin_exists': os.path.isfile(skin_path),
                        'input': input_path, 'modules': modules}}, f)
        """))
    if os.name == 'nt':
        exe_path = write(directory, 'netlistsvg.cmd', f'@"{sys.executable}" "{script_path}" %*\n')
    else:
        exe_path = write(directory, 'netlistsvg', f'#!/bin/sh\nexec "{sys.executable}" "{script_path}" "$@"\n')
        os.chmod(exe_path, 0o755)
    return exe_path


def run(*arguments: str) -> Tuple[int, str]:
    """The exit code and the output of netlist svg (see run_cli)"""
    return run_cli(NetlistCLI().main, ['netlist', 'svg', *arguments])


@pytest.fixture
def divider_netlist(tmp_path) -> str:
    return write(str(tmp_path), 'divider.spice', DIVIDER_NETLIST)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_draws_next_to_the_input_with_the_packaged_skin(divider_netlist: str, tmp_path,
                                                        monkeypatch: pytest.MonkeyPatch):
    # NOTE: the skin was in testdata, which a pip install doesn't have (#338)
    work_dir = tmp_path / 'work'
    work_dir.mkdir()
    monkeypatch.chdir(work_dir)
    code, output = run(divider_netlist, '--exe', fake_netlistsvg(str(tmp_path)))
    assert code == ExitCode.OK, output
    with open(os.path.splitext(divider_netlist)[0] + '.svg', encoding='utf-8') as f:
        netlistsvg_call = json.load(f)
    package_dir = os.path.dirname(os.path.abspath(klayout_pex.__file__))
    assert os.path.commonpath([netlistsvg_call['skin'], package_dir]) == package_dir
    assert netlistsvg_call['skin_exists']
    assert netlistsvg_call['modules'] == ['DIVIDER']
    assert not os.path.exists(netlistsvg_call['input'])  # NOTE: an intermediate file
    assert os.listdir(work_dir) == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_cell_chooses_the_circuit(tmp_path):
    netlist_path = write(str(tmp_path), 'two.spice', DIVIDER_NETLIST + DIVIDER_NETLIST.replace('divider', 'other'))
    exe_path = fake_netlistsvg(str(tmp_path))
    code, output = run(netlist_path, '--exe', exe_path)
    assert code == ExitCode.USAGE, output
    assert "Please specify the desired cell using the --cell argument" in output
    code, output = run(netlist_path, '--exe', exe_path, '--cell', 'missing')
    assert code == ExitCode.USAGE, output
    assert "No circuit missing in the SPICE netlist, its circuits are: DIVIDER, OTHER" in output

    code, output = run(netlist_path, '--exe', exe_path, '--cell', 'other')
    assert code == ExitCode.OK, output
    with open(os.path.splitext(netlist_path)[0] + '.svg', encoding='utf-8') as f:
        assert json.load(f)['modules'] == ['OTHER']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_missing_inputs_are_usage_errors(divider_netlist: str, tmp_path):
    exe_path = fake_netlistsvg(str(tmp_path))
    for arguments, message in [
        ([str(tmp_path / 'missing.spice'), '--exe', exe_path], "Input netlist not found"),
        ([divider_netlist, '--exe', str(tmp_path / 'missing_netlistsvg')], "Can't locate netlistsvg executable"),
        ([divider_netlist, '--exe', exe_path, '-o', str(tmp_path / 'missing' / 'divider.svg')],
         "The directory of the output SVG doesn't exist"),
    ]:
        code, output = run(*arguments)
        assert code == ExitCode.USAGE, output
        assert message in output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('netlist, exit_code, message', [
    (DIVIDER_NETLIST, 3, "netlistsvg failed with status code 3"),
    (DIVIDER_NETLIST.replace('R2 B C 200', 'R2 B'), 0, "Can't read the SPICE netlist"),
    ('', 0, "No top circuit found"),
], ids=['netlistsvg fails', 'unreadable netlist', 'no top circuit'])
def test_netlists_that_cannot_be_drawn_exit_one(netlist: str, exit_code: int, message: str, tmp_path):
    netlist_path = write(str(tmp_path), 'netlist.spice', netlist)
    code, output = run(netlist_path, '--exe', fake_netlistsvg(str(tmp_path), exit_code))
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert message in output
