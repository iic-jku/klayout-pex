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

"""The preparation subcommand runs without layout input and refuses unsupported work."""

import json
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import allure
import pytest

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.tech_info import TechInfo
from tests.common.cli_runner import run_cli

pytestmark = allure.parent_suite('Unit Tests')


def test_help_explains_preparation_scope():
    code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'prepare', '--help'])
    assert code == 0, output
    assert '--patterns' in output and '--out-dir' in output
    assert 'not a qualified reference solution' in ' '.join(output.split())


def test_calibration_prepare_needs_no_layout_or_solver(tmp_path: Path, pattern_data: Dict[str, Any], tech_info: TechInfo):
    spec = tmp_path / 'patterns.json'
    spec.write_text(json.dumps(pattern_data), encoding='utf-8')
    output_dir = tmp_path / 'prepared'
    with mock.patch.object(TechInfo, 'from_json', return_value=tech_info):
        code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'prepare', '--pdk', 'sky130A',
                                              '--patterns', str(spec), '--out-dir', str(output_dir)])
    assert code == 0, output
    assert 'Reference solving and coefficient fitting have not run' in output
    assert (output_dir / 'manifest.json').is_file()


def test_invalid_dimensions_fail_before_loading_selected_technology(tmp_path: Path, pattern_data: Dict[str, Any]):
    spec = tmp_path / 'patterns.json'
    pattern_data['cases'][0]['width_um'] = '0'
    spec.write_text(json.dumps(pattern_data), encoding='utf-8')
    with mock.patch.object(TechInfo, 'from_json') as load:
        code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'prepare', '--pdk', 'sky130A',
                                              '--patterns', str(spec), '--out-dir', str(tmp_path / 'output')])
    assert code == 2, output
    assert 'positive finite decimal' in output
    load.assert_not_called()
    assert not (tmp_path / 'output').exists()


def test_unknown_pdk_lists_valid_values():
    code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'prepare', '--pdk', 'missing',
                                          '--patterns', 'missing.json', '--out-dir', 'missing'])
    assert code == 2, output
    assert 'sky130A' in output
