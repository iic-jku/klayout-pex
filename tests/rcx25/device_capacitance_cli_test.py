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

import json
from pathlib import Path
from typing import List, Optional, Tuple

import allure
import pytest

from tests.common.device_capacitance import DESIGN, PDK_CONFIG, reference_document, write_references

from klayout_pex.env import Env
from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.netlist.spice_reader import SpiceReader
from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.cli_runner import run_cli
from tests.rcx25.rcx25_test_helpers import RCX25Extraction

pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('RCX25', 'Device Capacitance CLI')]


@pytest.mark.parametrize('omitted,extra', [
    ('--gds', []), ('--2.5D', []), ('--blackbox', []), (None, ['--mode', 'R']),
])
def test_cli_checks_option_compatibility_before_loading(omitted: Optional[str], extra: List[str]):
    options = {'--gds': ['missing.gds'], '--2.5D': [], '--blackbox': ['y']}
    args = ['extract', '--pdk', 'ihp-sg13g2', '--check-device-caps', 'missing.json']
    for name, values in options.items():
        if name != omitted:
            args += [name, *values]
    code, output = run_cli(KpexCLI().main, ['main', *args, *extra])
    assert code == 2, output
    assert '--check-device-caps needs --gds' in output


def test_cli_rejects_invalid_references_before_loading_the_layout(tmp_path: Path):
    reference = write_references(tmp_path / 'bad.json', reference_document(capacitance=0))
    code, output = run_cli(KpexCLI().main, [
        'main', 'extract', '--pdk', 'ihp-sg13g2', '--2.5D', '--blackbox', 'y',
        '--gds', 'missing.gds', '--check-device-caps', reference])
    assert code == 2, output
    assert 'capacitance must be greater than zero' in output


@pytest.mark.slow
@pytest.mark.parametrize('mode', [PEXMode.CC, PEXMode.RC])
@pytest.mark.parametrize('exclusions', [(), ('--exclude-net', 'PLUS')])
@pytest.mark.parametrize('automatic', [False, True])
def test_mom_comparison_preserves_the_written_netlist(
        mode: PEXMode, exclusions: Tuple[str, ...], automatic: bool, tmp_path: Path):
    extraction = RCX25Extraction(PDK_CONFIG, mode, blackbox=True)
    original = extraction.run_kpex('test_patterns', DESIGN, extra_args=exclusions)
    original_csv = Path(original.rcx25_extracted_csv_path).read_text(encoding='utf-8')
    original_spice = SpiceReader().read(Path(original.rcx25_extracted_csv_path).with_suffix('.spice'))
    reference = write_references(tmp_path / 'reference.json', reference_document(
        device_class='cap_cmomf', terminals=['mim_top', 'mim_btm'], capacitance='228.75f'))
    reference_args = [] if automatic else [reference]
    checked = extraction.run_kpex('test_patterns', DESIGN, extra_args=[
        '--gds', PDK_CONFIG.gds_path('test_patterns', DESIGN), '--check-device-caps', *reference_args, *exclusions])
    assert Path(checked.rcx25_extracted_csv_path).read_text(encoding='utf-8') == original_csv
    assert SpiceReader().read(Path(checked.rcx25_extracted_csv_path).with_suffix('.spice')) == original_spice
    record, = checked.run_result.device_capacitance_checks
    # Independent white-box fixture result; no net-pair subtraction is used by the observer.
    # Exclusions filter the output, not the model's full internal capacitance.
    # Full pair counting restores the former 192.7094929601 fF sidewall share (#390).
    assert record['extracted_capacitance_f'] == pytest.approx(397.8574172426e-15, rel=1e-12, abs=0)
    assert record['ratio'] == pytest.approx(397.8574172426 / 228.75, rel=1e-12)
    assert record['status'] == 'informational'
    assert bool(record['reference_source']) == automatic


@pytest.mark.slow
def test_requested_ratio_failure_keeps_output_even_with_structural_checks_disabled(tmp_path: Path):
    reference = write_references(tmp_path / 'reference.json', reference_document(
        device_class='cap_cmomf', terminals=['mim_top', 'mim_btm'], capacitance='228.75f', max_ratio=1.0))
    extraction = RCX25Extraction(PDK_CONFIG, PEXMode.CC, blackbox=True)
    cli = KpexCLI()
    with pytest.raises(SystemExit) as error:
        cli.main(['main', 'extract', '--pdk', str(PDK_CONFIG.name), '--2.5D', '--blackbox', 'y', '--check', 'n',
                  '--lvsdb', extraction.lvsdb_fixture('test_patterns', DESIGN).up_to_date_lvsdb_path(),
                  '--gds', PDK_CONFIG.gds_path('test_patterns', DESIGN), '--check-device-caps', reference,
                  '--out-dir', str(tmp_path / 'output')])
    assert error.value.code == 1
    record, = cli.run_result.device_capacitance_checks
    assert record['status'] == 'failed'
    assert any('marker coupling' in problem for problem in cli.run_result.check_problems)
    assert any(item.kind == 'netlist' and Path(item.path).is_file() for item in cli.run_result.files)
    written = json.loads(Path(cli.run_result.paths()[0]).read_text(encoding='utf-8'))
    assert written['device_capacitance_checks'] == [record]
    assert written['exit_code'] == 1


@pytest.mark.slow
@pytest.mark.parametrize('device_fails', [False, True])
@pytest.mark.parametrize('reduction_fails', [False, True])
def test_device_and_reduction_checks_preserve_both_outcomes(
        tmp_path: Path, device_fails: bool, reduction_fails: bool):
    # Check the complete decision table: a passing check must not erase another
    # failure. Aggressive reduction changes the high-frequency routing response.
    # Full sidewall counting puts this uncalibrated fit near 1.74 times the model
    # reference (#390). Explicit bands select each outcome without changing the model.
    min_ratio, max_ratio = (0.8, 1.2) if device_fails else (1.7, 1.8)
    reference = write_references(tmp_path / 'reference.json', reference_document(
        device_class='cap_cmomf', terminals=['mim_top', 'mim_btm'], capacitance='228.75f',
        min_ratio=min_ratio, max_ratio=max_ratio))
    extraction = RCX25Extraction(PDK_CONFIG, PEXMode.RC, blackbox=True)
    cli = KpexCLI()
    code, output = run_cli(cli.main, [
        'main', 'extract', '--pdk', str(PDK_CONFIG.name), '--2.5D', '--blackbox', 'y', '--mode', 'RC',
        '--check', 'n', '--lvsdb', extraction.lvsdb_fixture('test_patterns', DESIGN).up_to_date_lvsdb_path(),
        '--gds', PDK_CONFIG.gds_path('test_patterns', DESIGN), '--check-device-caps', reference,
        '--reduce', 'ticer', '--reduce-tau', '1n' if reduction_fails else '1a',
        '--check-frequency-range', '1G', '1T', '--check-points-per-decade', '1', '--check-include-dc',
        '--out-dir', str(tmp_path / 'output')])
    assert code == (1 if device_fails or reduction_fails else 0), output
    problems = cli.run_result.check_problems
    assert any('marker coupling' in problem for problem in problems) == device_fails, problems
    assert any('relative Frobenius error' in problem for problem in problems) == reduction_fails, problems
    assert ('requested device capacitance comparison failed' in output) == device_fails, output
    assert ('reduced netlist failed its requested admittance check' in output) == reduction_fails, output
    assert Path(cli.rcx25_reduced_netlist_path).is_file()
    written = json.loads(Path(cli.run_result.paths()[0]).read_text(encoding='utf-8'))
    assert written['check_problems'] == problems
    assert written['exit_code'] == code


def test_bare_check_device_caps_is_distinct_from_disabled_and_explicit_file():
    # Parsing must not consume the next option or try to open an empty filename.
    cli = KpexCLI()
    args = cli.parse_args(['extract', '--pdk', 'ihp-sg13g2', '--check-device-caps',
                           '--gds', 'missing.gds', '--2.5D', '--blackbox', 'y'], env=Env.from_os_environ())
    assert args.device_capacitance_reference_path == ''
    assert args.device_capacitance_references is None
