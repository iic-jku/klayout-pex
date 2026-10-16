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

"""``netlist reduce``: argument validation, exit codes, files written"""

from __future__ import annotations

import os
from typing import *

import allure
import pytest

from klayout_pex.netlist.netlist_cli import NetlistCLI
from klayout_pex.pex25d.diagnostics import ExitCode
from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist
from tests.common.cli_runner import (
    assert_netlist_cli_loads_neither_klayout_nor_protobuf,
    run_cli,
    run_cli_process,
)
from tests.common.rc_networks import (
    LINE_NETLIST,
    node_names,
    scope_named,
    write,
)

parent_suite = "Unit Tests"
tags = ("Netlist", "Reduction", "CLI")


def run(*arguments: str) -> Tuple[int, str]:
    """The exit code and the output of netlist reduce (see run_cli)"""
    return run_cli(NetlistCLI().main, ['netlist', 'reduce', *arguments])


@pytest.fixture
def line_netlist(tmp_path) -> str:
    return write(str(tmp_path), 'line.spice', LINE_NETLIST)


def line_node_names(path: str) -> List[str]:
    return node_names(scope_named(SpiceRCNetlist.read(path), 'line').network)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_writes_next_to_the_input_by_default(line_netlist: str):
    assert run(line_netlist, '--ticer_tau', '1p')[0] == ExitCode.OK
    assert line_node_names(os.path.splitext(line_netlist)[0] + '_reduced.spice') == ['A', 'B', 'gnd!']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_options_choose_the_passes(line_netlist: str, tmp_path):
    output = str(tmp_path / 'out' / 'reduced.spice')
    assert run(line_netlist, '-o', output, '--ticer', 'n')[0] == ExitCode.OK
    assert line_node_names(output) == ['A', 'B', 'gnd!', 'm1', 'm2']
    assert run(line_netlist, '-o', output, '--floating', 'n', '--ticer_tau', '1e-12')[0] == ExitCode.OK
    assert line_node_names(output) == ['A', 'B', 'gnd!', 'plate']
    assert run(line_netlist, '-o', output, '--ticer_tau', '0.01p')[0] == ExitCode.OK  # τ(m1) = 50 fs
    assert line_node_names(output) == ['A', 'B', 'gnd!', 'm1', 'm2']
    assert run(line_netlist, '-o', output, '--ticer_tau', '1p', '--ticer_max_degree', '1')[0] == ExitCode.OK
    assert line_node_names(output) == ['A', 'B', 'gnd!', 'm1', 'm2']
    assert run(line_netlist, '-o', output, '--ticer_tau', '1p', '--floating_max_degree', '1')[0] == ExitCode.OK
    assert line_node_names(output) == ['A', 'B', 'gnd!', 'plate']
    with open(output) as f:
        assert 'Rtie_1 plate 0 1e+12' in f.read().splitlines()


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_keep_protects_nodes(line_netlist: str, tmp_path):
    output = str(tmp_path / 'reduced.spice')
    assert run(line_netlist, '-o', output, '--ticer_tau', '1p', '--keep', 'm2', '--keep', 'PLATE')[0] == ExitCode.OK
    assert line_node_names(output) == ['A', 'B', 'gnd!', 'm2', 'plate']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('arguments, message', [
    (['--ticer_tau', '0'], "argument --ticer_tau: must be > 0 s, got '0'"),
    # NOTE: with '=', as Python 3.12's argparse reads '-1p' as an option
    (['--ticer_tau=-1p'], "argument --ticer_tau: must be > 0 s, got '-1p'"),
    (['--ticer_tau', 'fast'], "argument --ticer_tau: Not a SPICE number: 'fast' (examples of valid numbers: "
                              "'1.5', '2e-15', '0.1p', '10k', '1Meg')"),
    (['--ticer_max_degree', '0'], "argument --ticer_max_degree: must be an integer ≥ 1, got '0'"),
    (['--floating_max_degree', '2.5'], "argument --floating_max_degree: must be an integer ≥ 1, got '2.5'"),
])
def test_invalid_values_are_usage_errors(line_netlist: str, arguments: List[str], message: str):
    code, output = run(line_netlist, *arguments)
    assert code == ExitCode.USAGE
    assert message in output
    assert not os.path.exists(os.path.splitext(line_netlist)[0] + '_reduced.spice')


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_nothing_to_do_is_a_usage_error(line_netlist: str):
    code, output = run(line_netlist, '--ticer', 'n', '--floating', 'n')
    assert code == ExitCode.USAGE
    assert 'ticer and floating are both False, there is nothing to do' in output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_missing_input_and_overwriting_it_are_usage_errors(line_netlist: str, tmp_path):
    code, output = run(str(tmp_path / 'missing.spice'))
    assert code == ExitCode.USAGE
    assert 'Input netlist not found' in output
    code, output = run(line_netlist, '-o', line_netlist)
    assert code == ExitCode.USAGE
    assert 'The output would overwrite the input netlist' in output
    with open(line_netlist) as f:
        assert f.read() == LINE_NETLIST


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_unknown_node_to_keep_is_a_usage_error(line_netlist: str):
    code, output = run(line_netlist, '--keep', 'nosuch')
    assert code == ExitCode.USAGE
    assert 'node(s) to keep nosuch; the nodes are: A, B, gnd!, m1, m2, plate' in output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_invalid_netlist_exits_one(tmp_path):
    path = write(str(tmp_path), 'broken.spice', LINE_NETLIST.replace('.ENDS line', ''))
    code, output = run(path)
    assert code == ExitCode.DIAGNOSTIC_ERRORS
    assert '.SUBCKT line without .ENDS' in output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_console_script_runs_as_a_process(line_netlist: str, tmp_path):
    output = str(tmp_path / 'reduced.spice')
    result = run_cli_process('klayout_pex.netlist', ['reduce', line_netlist, '-o', output, '--ticer_tau', '1p'])
    assert result.returncode == ExitCode.OK, result.stderr
    assert line_node_names(output) == ['A', 'B', 'gnd!'], result.stderr

    result = run_cli_process('klayout_pex.netlist', ['reduce', line_netlist, '--ticer_max_degree', 'many'])
    assert result.returncode == ExitCode.USAGE, result.stderr
    assert "argument --ticer_max_degree: must be an integer ≥ 1, got 'many'" in result.stderr


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_reduce_loads_neither_klayout_nor_the_protobuf(line_netlist: str, tmp_path):
    assert_netlist_cli_loads_neither_klayout_nor_protobuf(
        ['netlist', 'reduce', line_netlist, '-o', os.path.join(str(tmp_path), 'out.spice')])
