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

from pathlib import Path
from typing import Optional
from unittest import mock

import allure
import pytest

from klayout_pex.env import Env
from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.magic.magic_runner import (
    MagicMergeMode, MagicPEXMode, MagicShortMode, MagicUniqueMode, prepare_magic_script,
)
from klayout_pex.pex25d.diagnostics import ExitCode
from tests.common.cli_runner import run_cli

pytestmark = [allure.parent_suite("Unit Tests"), allure.tag("MAGIC", "Pruning")]


def write_script(tmp_path: Path, fraction: Optional[float]) -> Path:
    script = tmp_path / 'extract.tcl'
    prepare_magic_script(
        gds_path='input.gds', cell_name='TOP', run_dir_path=str(tmp_path), script_path=str(script),
        output_netlist_path=str(tmp_path / 'output.spice'), pex_mode=MagicPEXMode.RC,
        c_threshold=0.01, r_threshold=0, threshold=None, min_res=None, min_delay=None,
        prune_frac=fraction, halo=None, short_mode=MagicShortMode.NONE,
        merge_mode=MagicMergeMode.NONE, unique_mode=MagicUniqueMode.IMPLICIT)
    return script


@pytest.mark.parametrize('fraction', [None, 0.0, 0.01, 0.9999999403953552])
def test_prune_command_is_optional_and_precedes_extraction(fraction: Optional[float], tmp_path: Path):
    lines = write_script(tmp_path, fraction).read_text(encoding='utf-8').splitlines()
    commands = [line for line in lines if line.startswith('extresist prune')]
    if fraction is None:
        assert commands == []
    else:
        assert commands == [f'extresist prune {fraction}']
        assert lines.index(commands[0]) < lines.index('extract all')


@pytest.mark.parametrize('option', ['--magic-prune', '--magic_prune'])
@pytest.mark.parametrize('value', ['0', '-0', '1e-45', '0.01', '0.9999999403953552'])
def test_valid_prune_fractions_and_alias(option: str, value: str):
    # Zero disables this pass; the smallest positive float32 and the largest
    # float32 below one exercise both representable boundaries.
    args = KpexCLI.parse_args(['extract', '--magic', f'{option}={value}'], Env.from_os_environ())
    assert args.magic_prune == float(value)


@pytest.mark.parametrize('value', [
    '-1e-45', '-0.01', '1', '1.01', 'nan', 'inf', '-inf', '1e1000', 'invalid',
    # Both Python floats are below one, but round to one in MAGIC's C float.
    '0.99999999', '0.9999999701976776', '0.9999999999999999',
])
def test_invalid_prune_fractions_fail_before_loading_inputs(value: str):
    with mock.patch.object(KpexCLI, 'validate_args', side_effect=AssertionError('must not load inputs')):
        code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--magic', f'--magic-prune={value}'])
    assert code == ExitCode.USAGE, output
    assert '--magic-prune' in output, output


@pytest.mark.parametrize('fraction', [float('nan'), 0.99999999])
def test_script_generation_rejects_invalid_pruning_before_writing(fraction: float, tmp_path: Path):
    with pytest.raises(ValueError, match='pruning fraction'):
        write_script(tmp_path, fraction)
    assert not (tmp_path / 'extract.tcl').exists()


def test_help_distinguishes_pruning_from_other_simplification():
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--help'])
    assert code == 0, output
    assert '0 disables this pruning pass, not other network simplification' in ' '.join(output.split())
