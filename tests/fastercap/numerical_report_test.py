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

"""External report boundaries: precision, provenance, failures and unsupported physics."""

import copy
import io
import json
import math
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import allure
import pytest

from klayout_pex.common.capacitance_matrix import CapacitanceMatrix
from klayout_pex.fastercap.fastercap_error import FasterCapError, FasterCapExecutionError
from klayout_pex.fastercap.fastercap_runner import run_fastercap
from klayout_pex.fastercap.numerical_report import read_numerical_report

pytestmark = allure.parent_suite('Unit Tests')


@pytest.fixture
def report_data() -> Dict[str, Any]:
    # This is FasterCap's third-party JSON contract, not a project-owned format.
    # Keep asymmetric entries and signed zero: collection must preserve evidence.
    return {
        'schema_version': 1, 'input_file': 'geometry.lst',
        'build': {'version': 'FasterCap version 6.3.0'},
        'status': {'exit_code': 0, 'name': 'FC_NORMAL_END'},
        'last_completed_iteration': 0,
        'iterations': [{
            'iteration': 0, 'solve_status': {'exit_code': 0, 'name': 'FC_NORMAL_END'}, 'finite': True,
            'panels': 24, 'links': 576,
            'matrix': {'units': 'F', 'reference_column': None,
                       'row_conductors': ['g1_A', 'g2_B'], 'column_conductors': ['g1_A', 'g2_B'],
                       'real': [[math.nextafter(1e-9, math.inf), -1.2345678901234567e-10],
                                [-1.25e-10, -0.0]],
                       'imaginary': [[0.0, -0.0], [0.0, 0.0]]},
        }],
    }


def read_data(tmp_path: Path, data: Dict[str, Any]) -> CapacitanceMatrix:
    path = tmp_path / 'report.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return read_numerical_report(path, expected_input='geometry.lst', expected_version='6.3.0')


def test_report_retains_full_precision_signs_and_native_order(tmp_path: Path, report_data: Dict[str, Any]):
    matrix = read_data(tmp_path, report_data)
    assert matrix.conductor_names == ['g1_A', 'g2_B']
    assert matrix.rows == [[value / 1e6 for value in row]
                           for row in report_data['iterations'][0]['matrix']['real']]
    assert matrix.rows[0][1] != matrix.rows[1][0]
    assert math.copysign(1.0, matrix.rows[1][1]) == -1.0


@pytest.mark.parametrize('field,value', [
    ('schema_version', 2), ('schema_version', True), ('schema_version', 1.0),
    ('last_completed_iteration', None), ('last_completed_iteration', True),
    ('last_completed_iteration', -1), ('last_completed_iteration', 1),
    ('input_file', 'another.lst'), ('iterations', []), ('iterations', None),
    ('build', {'version': 'FasterCap version 6.2.1'}),
    ('status', {'exit_code': 75, 'name': 'FC_CANNOT_CONVERGE'}),
    ('status', {'exit_code': False, 'name': 'FC_NORMAL_END'}),
    ('status', {'exit_code': 0, 'name': 'FC_FILE_ERROR'}),
])
def test_report_rejects_incompatible_identity_and_completion(
        tmp_path: Path, report_data: Dict[str, Any], field: str, value: Any):
    report_data[field] = value
    with pytest.raises(FasterCapError):
        read_data(tmp_path, report_data)


@pytest.mark.parametrize('field,value', [
    ('units', 'F/m'), ('units', None), ('reference_column', 2),
    ('row_conductors', []), ('row_conductors', ['g1_A', 'g1_A']),
    ('row_conductors', ['g1_A', '']), ('column_conductors', ['g2_B', 'g1_A']),
    ('real', [[1.0]]), ('real', [[1.0, 2.0]]),
    ('real', [[1.0, 2.0], [3.0, True]]), ('real', [[1.0, 2.0], [3.0, None]]),
    ('real', [[1.0, 2.0], [3.0, '4']]), ('real', [[1.0, 2.0], [3.0, math.nan]]),
    ('real', [[1.0, 2.0], [3.0, math.inf]]),
    ('real', [[1.0, 2.0], [3.0, math.nextafter(0.0, 1.0)]]),
    ('imaginary', [[0.0, 0.0], [0.0, math.nextafter(0.0, 1.0)]]),
    ('imaginary', [[0.0, 0.0], [0.0, None]]),
])
def test_report_rejects_invalid_matrix_and_unsupported_complex_or_2d_values(
        tmp_path: Path, report_data: Dict[str, Any], field: str, value: Any):
    # Even the smallest nonzero imaginary part is unsupported, not rounded away.
    report_data['iterations'][0]['matrix'][field] = value
    with pytest.raises(FasterCapError):
        read_data(tmp_path, report_data)


@pytest.mark.parametrize('field,value', [
    ('iteration', 1), ('iteration', True), ('finite', False), ('finite', 1),
    ('solve_status', {'exit_code': 75, 'name': 'FC_CANNOT_CONVERGE'}),
])
def test_report_checks_final_linear_solve_independently_of_process_status(
        tmp_path: Path, report_data: Dict[str, Any], field: str, value: Any):
    report_data['iterations'][0][field] = value
    with pytest.raises(FasterCapError):
        read_data(tmp_path, report_data)


def test_report_uses_last_completed_iteration(tmp_path: Path, report_data: Dict[str, Any]):
    last = copy.deepcopy(report_data['iterations'][0])
    last['iteration'] = 1
    last['matrix']['real'][0][0] = 2e-9
    report_data['iterations'].append(last)
    report_data['last_completed_iteration'] = 1
    assert read_data(tmp_path, report_data).rows[0][0] == 2e-9 / 1e6


@pytest.mark.parametrize('text', ['{', '[]', 'null', '{"schema_version":1,"schema_version":1}',
                                '{"schema_version":NaN}'])
def test_report_rejects_truncated_or_ambiguous_json(tmp_path: Path, text: str):
    path = tmp_path / 'report.json'
    path.write_text(text, encoding='utf-8')
    with pytest.raises(FasterCapError):
        read_numerical_report(path)


def test_missing_report_never_falls_back_to_console(tmp_path: Path):
    with pytest.raises(FasterCapError, match='Could not read'):
        read_numerical_report(tmp_path / 'missing.json')


@pytest.mark.parametrize('exit_code', [0, 75])
def test_runner_returns_created_report_even_when_solver_fails(tmp_path: Path, exit_code: int):
    report = tmp_path / 'report with spaces.json'
    process = mock.Mock(returncode=exit_code, stdout=io.StringIO('solver output'))
    def launch(arguments: Any, **kwargs: Any) -> Any:
        assert f'--report={report}' in arguments
        assert arguments[-1] == 'geometry.lst'
        report.write_text('{"incomplete":', encoding='utf-8')
        return process
    with mock.patch('klayout_pex.fastercap.fastercap_runner.subprocess.Popen', side_effect=launch):
        arguments = dict(exe_path='FasterCap', lst_file_path='geometry.lst',
                         log_path=str(tmp_path / 'solver.log'), tolerance=0.05, d_coeff=0.5,
                         ooc_condition=None, auto_preconditioner=False, galerkin_scheme=False,
                         jacobi_preconditioner=False, report_path=str(report))
        if exit_code == 0:
            result = run_fastercap(**arguments)
        else:
            with pytest.raises(FasterCapExecutionError) as failure:
                run_fastercap(**arguments)
            result = failure.value.result
    assert result.report_path == str(report)
    assert report.read_text(encoding='utf-8') == '{"incomplete":'


@pytest.mark.parametrize('invalid', ['existing', 'same-as-log', 'empty', 'quoted'])
def test_runner_rejects_unsafe_report_path_before_starting_or_truncating_log(tmp_path: Path, invalid: str):
    report = tmp_path / 'report.json'
    log = tmp_path / 'solver.log'
    value = str(report)
    if invalid == 'existing':
        report.write_text('keep report', encoding='utf-8')
    elif invalid == 'same-as-log':
        value = str(log)
    elif invalid == 'empty':
        value = ''
    elif invalid == 'quoted':
        value = str(tmp_path / 'a"b.json')
    with mock.patch('klayout_pex.fastercap.fastercap_runner.subprocess.Popen') as launch:
        with pytest.raises(FasterCapError):
            run_fastercap('FasterCap', 'geometry.lst', str(log), 0.05, 0.5, None,
                          False, False, False, report_path=value)
        launch.assert_not_called()
    assert not log.exists()
    if invalid == 'existing':
        assert report.read_text(encoding='utf-8') == 'keep report'
