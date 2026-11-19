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
from argparse import Namespace
import io
import json
import math
from pathlib import Path
from typing import Any, Dict, Optional
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
    from tests.common.fastercap_report import numerical_report
    # Asymmetry and signed zero are evidence, not values for collection to repair.
    return numerical_report(['g1_A', 'g2_B'],
                            [[math.nextafter(1e-9, math.inf), -1.2345678901234567e-10],
                             [-1.25e-10, -0.0]])


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


@pytest.fixture
def extraction_args(tmp_path: Path) -> Namespace:
    return Namespace(num_threads=1, output_dir_path=str(tmp_path), effective_cell_name='test',
                     fastercap_exe_path='FasterCap', fastercap_tolerance=0.05, fastercap_d_coeff=0.5,
                     fastercap_ooc_condition=0, fastercap_auto_preconditioner=True,
                     fastercap_galerkin_scheme=False, fastercap_jacobi_preconditioner=False)


@pytest.mark.parametrize('version', [None, '6.2.1', '6.3.0'])
def test_extraction_selects_report_by_version_and_replaces_previous_output(
        tmp_path: Path, report_data: Dict[str, Any], extraction_args: Namespace, version: Optional[str]):
    from packaging.version import Version
    from klayout_pex.kpex_cli import KpexCLI
    from klayout_pex.tool_version_constraints import Tool
    from klayout_pex.fastercap.fastercap_runner import FasterCapRunResult
    raw = tmp_path / 'test_FasterCap_Result_Matrix_Raw.csv'
    report = tmp_path / 'test_FasterCap_Report.json'
    report.write_text('stale report', encoding='utf-8')

    def run(**kwargs: Any) -> FasterCapRunResult:
        Path(kwargs['log_path']).write_text('Capacitance matrix is:\nDimension 2 x 2\n'
                                           'g1_A 9e-9 -2e-9\ng2_B -3e-9 8e-9\n', encoding='utf-8')
        if version == '6.3.0':
            assert kwargs['report_path'] == str(report)
            assert not report.exists()
            report.write_text(json.dumps(report_data), encoding='utf-8')
        else:
            assert kwargs['report_path'] is None
        return FasterCapRunResult(('FasterCap', 'geometry.lst'), 0, 0.1,
                                   str(report) if version == '6.3.0' else None)

    class MatrixObserved(Exception):
        pass

    def observe(matrix: CapacitanceMatrix) -> CapacitanceMatrix:
        if version == '6.3.0':
            assert matrix.rows == [[value / 1e6 for value in row]
                                   for row in report_data['iterations'][0]['matrix']['real']]
        else:
            assert matrix.rows[0] == [9e-9 / 1e6, -2e-9 / 1e6]
        assert raw.is_file()
        raise MatrixObserved  # Stop at the existing netlist-processing boundary.

    cli = KpexCLI()
    cli.run_result = mock.Mock()
    with mock.patch.object(Tool, 'detect_version', return_value=Version(version) if version else None), \
         mock.patch('klayout_pex.kpex_cli.run_fastercap', side_effect=run), \
         mock.patch.object(CapacitanceMatrix, 'averaged_off_diagonals', observe), \
         mock.patch.dict('os.environ', {}):
        for _ in range(2):
            with pytest.raises(MatrixObserved):
                cli.run_fastercap_extraction(extraction_args, mock.Mock(), 'geometry.lst', None)


@pytest.mark.parametrize('failed_exit', [False, True])
def test_extraction_keeps_failure_report_without_writing_matrix(
        tmp_path: Path, extraction_args: Namespace, failed_exit: bool):
    from packaging.version import Version
    from klayout_pex.kpex_cli import KpexCLI
    from klayout_pex.tool_version_constraints import Tool
    from klayout_pex.fastercap.fastercap_runner import FasterCapRunResult

    def run(**kwargs: Any) -> FasterCapRunResult:
        report = Path(kwargs['report_path'])
        report.write_text('{"schema_version":1,', encoding='utf-8')
        Path(kwargs['log_path']).write_text('Capacitance matrix is:\nDimension 1 x 1\ng1_A 1e-9\n', encoding='utf-8')
        result = FasterCapRunResult(('FasterCap', 'geometry.lst'), 75 if failed_exit else 0, 0.1, str(report))
        if failed_exit:
            raise FasterCapExecutionError('GMRES failed', result=result)
        return result

    cli = KpexCLI()
    cli.run_result = mock.Mock()
    with mock.patch.object(Tool, 'detect_version', return_value=Version('6.3.0')), \
         mock.patch('klayout_pex.kpex_cli.run_fastercap', side_effect=run), \
         mock.patch.dict('os.environ', {}):
        with pytest.raises(FasterCapError):
            cli.run_fastercap_extraction(extraction_args, mock.Mock(), 'geometry.lst', None)
    report = tmp_path / 'test_FasterCap_Report.json'
    assert report.is_file()
    assert any(call.args[1] == str(report) for call in cli.run_result.add_file.call_args_list)
    assert not (tmp_path / 'test_FasterCap_Result_Matrix_Raw.csv').exists()


@pytest.mark.parametrize('input_path', ['plain.lst', 'directory with spaces/geometry.lst', 'tab\tname.lst'])
def test_input_argument_survives_fastercap_tokenizer(tmp_path: Path, input_path: str):
    process = mock.Mock(returncode=0, stdout=io.StringIO(''))
    with mock.patch('klayout_pex.fastercap.fastercap_runner.subprocess.Popen', return_value=process) as launch:
        result = run_fastercap('FasterCap', input_path, str(tmp_path / 'solver.log'),
                               0.05, 0.5, 0, True, False, False)
    argument = result.arguments[-1]
    assert argument == (f'"{input_path}"' if any(c.isspace() for c in input_path) else input_path)
    assert tuple(launch.call_args.args[0]) == result.arguments
    assert not launch.call_args.kwargs.get('shell', False)


def test_literal_quote_in_input_is_rejected_before_creating_log(tmp_path: Path):
    with mock.patch('klayout_pex.fastercap.fastercap_runner.subprocess.Popen') as launch:
        with pytest.raises(FasterCapError, match='double quotes'):
            run_fastercap('FasterCap', 'a"b.lst', str(tmp_path / 'solver.log'),
                          0.05, 0.5, 0, True, False, False)
    launch.assert_not_called()
    assert not (tmp_path / 'solver.log').exists()
