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
from pathlib import Path
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
    assert run(line_netlist, '--ticer-tau', '1p')[0] == ExitCode.OK
    assert line_node_names(os.path.splitext(line_netlist)[0] + '_reduced.spice') == ['A', 'B', 'gnd!']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_options_choose_the_passes(line_netlist: str, tmp_path):
    output = str(tmp_path / 'out' / 'reduced.spice')
    assert run(line_netlist, '-o', output, '--ticer', 'n')[0] == ExitCode.OK
    assert line_node_names(output) == ['A', 'B', 'gnd!', 'm1', 'm2']
    assert run(line_netlist, '-o', output, '--floating', 'n', '--ticer-tau', '1e-12')[0] == ExitCode.OK
    assert line_node_names(output) == ['A', 'B', 'gnd!', 'plate']
    assert run(line_netlist, '-o', output, '--ticer-tau', '0.01p')[0] == ExitCode.OK  # τ(m1) = 50 fs
    assert line_node_names(output) == ['A', 'B', 'gnd!', 'm1', 'm2']
    assert run(line_netlist, '-o', output, '--ticer-tau', '1p', '--ticer-max-degree', '1')[0] == ExitCode.OK
    assert line_node_names(output) == ['A', 'B', 'gnd!', 'm1', 'm2']
    assert run(line_netlist, '-o', output, '--ticer-tau', '1p', '--floating-max-degree', '1')[0] == ExitCode.OK
    assert line_node_names(output) == ['A', 'B', 'gnd!', 'plate']
    with open(output, encoding='utf-8') as f:
        assert 'Rtie_1 plate 0 1e+12' in f.read().splitlines()


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_keep_protects_nodes(line_netlist: str, tmp_path):
    output = str(tmp_path / 'reduced.spice')
    assert run(line_netlist, '-o', output, '--ticer-tau', '1p', '--keep', 'm2', '--keep', 'PLATE')[0] == ExitCode.OK
    assert line_node_names(output) == ['A', 'B', 'gnd!', 'm2', 'plate']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('arguments, message', [
    (['--ticer-tau', '0'], "argument --ticer-tau: must be > 0 s, got '0'"),
    # NOTE: with '=', as Python 3.12's argparse reads '-1p' as an option
    (['--ticer-tau=-1p'], "argument --ticer-tau: must be > 0 s, got '-1p'"),
    (['--ticer-tau', 'fast'], "argument --ticer-tau: Not a SPICE number: 'fast' (examples of valid numbers: "
                              "'1.5', '2e-15', '0.1p', '10k', '1Meg')"),
    (['--ticer-max-degree', '0'], "argument --ticer-max-degree: must be an integer ≥ 1, got '0'"),
    (['--floating-max-degree', '2.5'], "argument --floating-max-degree: must be an integer ≥ 1, got '2.5'"),
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
    with open(line_netlist, encoding='utf-8') as f:
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
    result = run_cli_process('klayout_pex.netlist', ['reduce', line_netlist, '-o', output, '--ticer-tau', '1p'])
    assert result.returncode == ExitCode.OK, result.stderr
    assert line_node_names(output) == ['A', 'B', 'gnd!'], result.stderr

    result = run_cli_process('klayout_pex.netlist', ['reduce', line_netlist, '--ticer-max-degree', 'many'])
    assert result.returncode == ExitCode.USAGE, result.stderr
    assert "argument --ticer-max-degree: must be an integer ≥ 1, got 'many'" in result.stderr


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_reduce_loads_neither_klayout_nor_the_protobuf(line_netlist: str, tmp_path):
    assert_netlist_cli_loads_neither_klayout_nor_protobuf(
        ['netlist', 'reduce', line_netlist, '-o', os.path.join(str(tmp_path), 'out.spice')])


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('check_args', [
    ['--check-frequency', '1G'],
    ['--check-frequency-range', '1Meg', '1G', '--check-points-per-decade', '2'],
])
def test_requested_admittance_check_rejects_excessive_error_but_keeps_output(tmp_path: Path,
                                                                            check_args: List[str]):
    # Removing this series resistor changes Y by omega*R*C = 0.628 at 1 GHz.
    source = '.SUBCKT cell A B\nR1 A n 100\nC1 n B 1p\n.ENDS cell\n'
    input_path = write(str(tmp_path), 'series.spice', source)
    output_path = str(tmp_path / 'checked.spice')
    code, output = run(input_path, '-o', output_path, '--ticer-tau', '1n', *check_args)
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert 'relative Frobenius error 0.628319' in output
    assert 'limit 0.01' in output
    assert Path(output_path).is_file()
    assert Path(input_path).read_text(encoding='utf-8') == source


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('frequency', ['0', '1Meg'])
def test_requested_admittance_check_accepts_accurate_reduction(line_netlist: str, frequency: str):
    code, output = run(line_netlist, '--check-frequency', frequency)
    assert code == ExitCode.OK, output
    assert 'relative Frobenius error' in output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('arguments', [
    ['--check-frequency=-1'], ['--check-frequency', 'nan'], ['--check-frequency', 'inf'],
    ['--check-frequency', '1e999'], ['--check-frequency', 'invalid'],
    ['--check-frequency', '1G', '--check-max-relative-error', '0'],
    ['--check-frequency', '1G', '--check-max-relative-error', '1'],
    ['--check-frequency', '1G', '--check-max-relative-error', 'nan'],
    ['--check-frequency', '1G', '--check-max-relative-error', 'inf'],
    ['--check-max-relative-error', '0.1'],
    ['--check-frequency-range', '1Meg'],
    ['--check-frequency-range', '0', '1G'],
    ['--check-frequency-range', '-1', '1G'],
    ['--check-frequency-range', '1G', '1Meg'],
    ['--check-frequency-range', '1Meg', 'inf'],
    ['--check-frequency-range', 'nan', '1G'],
    ['--check-frequency-range', '1Meg', '1e999'],
    ['--check-frequency-range', '1Meg', '1G', '--check-frequency', '1G'],
    ['--check-points-per-decade', '10'], ['--check-include-dc'],
    ['--check-frequency', '1G', '--check-points-per-decade', '10'],
    ['--check-frequency', '0', '--check-include-dc'],
    ['--check-frequency-range', '1Meg', '1G', '--check-points-per-decade', '0'],
    ['--check-frequency-range', '1Meg', '1G', '--check-points-per-decade', '1.5'],
    ['--check-frequency-range', '1', '10', '--check-points-per-decade', '1001'],
    ['--check-frequency-range', '1Meg', '1G', '--check-max-relative-error', '1'],
])
def test_invalid_admittance_options_fail_before_reading_input(tmp_path: Path, arguments: List[str]):
    code, output = run(str(tmp_path / 'missing.spice'), *arguments)
    assert code == ExitCode.USAGE
    assert 'Input netlist not found' not in output
    assert '--check-' in output


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('check_args', [
    ['--check-frequency', '1Meg'], ['--check-frequency-range', '1Meg', '10Meg', '--check-include-dc'],
])
def test_checked_reduction_is_format_only_and_reports_process_failure(line_netlist: str, tmp_path: Path,
                                                                       check_args: List[str]):
    assert_netlist_cli_loads_neither_klayout_nor_protobuf(
        ['netlist', 'reduce', line_netlist, '-o', str(tmp_path / 'checked.spice'), *check_args])
    source = '.SUBCKT cell A B\nR1 A n 100\nC1 n B 1p\n.ENDS cell\n'
    path = write(str(tmp_path), 'series.spice', source)
    result = run_cli_process('klayout_pex.netlist', ['reduce', path, '--ticer-tau', '1n', '--check-frequency', '1G'])
    assert result.returncode == ExitCode.DIAGNOSTIC_ERRORS, result.stderr
    assert 'relative Frobenius error 0.628319' in result.stdout + result.stderr, result.stderr


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('start, stop, modifiers, count', [
    ('1Meg', '10Meg', [], 11),
    ('1Meg', '10Meg', ['--check-points-per-decade', '2'], 3),
    ('1Meg', '10Meg', ['--check-points-per-decade', '2', '--check-include-dc'], 4),
    ('1Meg', '1Meg', [], 1),
    ('1Meg', '1Meg', ['--check-include-dc'], 2),
])
def test_frequency_range_accepts_two_values_and_reports_sampled_worst_error(
        line_netlist: str, start: str, stop: str, modifiers: List[str], count: int):
    code, output = run(line_netlist, '--check-frequency-range', start, stop, *modifiers,
                       '--check-max-relative-error', '0.02')
    assert code == ExitCode.OK, output
    assert f'{count} sampled frequencies' in output
    assert 'worst relative Frobenius error' in output
    assert 'limit 0.02' in output
    assert ('including DC' in output) == ('--check-include-dc' in modifiers)
