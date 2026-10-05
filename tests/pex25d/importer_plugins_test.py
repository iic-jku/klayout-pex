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

"""Exercise importer plugin discovery, ``pex25d.import_file`` and ``pex25d import``."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sys
from typing import Callable, List, Tuple

import pytest

from klayout_pex import pex25d
from klayout_pex.plugin_api.v1 import IMPORTER_ENTRY_POINT_GROUP, ImporterError

from .pex25d_fixtures import MINIMAL, STACK_ONLY


IMPORTER_SOURCE = '''
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:
    from klayout_pex_protobuf.kpex.pex25d.pex25d_file_pb2 import PEX25DFile

    from klayout_pex.pex25d.diagnostics import DiagnosticsReport

class Importer:
    """Read PEX25D text split over named supporting files and the primary input."""

    def import_file(self, input_file_path: str, *,
                    supporting_files: Optional[Mapping[str, str]] = None,
                    options: Optional[Mapping[str, Any]] = None,
                    report: Optional[DiagnosticsReport] = None) -> PEX25DFile:
        from klayout_pex import pex25d
        text = ''.join(Path(path).read_text(encoding='utf-8')
                       for _, path in sorted((supporting_files or {}).items()))
        text += Path(input_file_path).read_text(encoding='utf-8')
        return pex25d.read_text(text.encode('utf-8'), report=report)

def create_importer() -> Importer:
    return Importer()
'''


@pytest.fixture
def install_importer(install_plugin: Callable[..., str]) -> Callable[..., str]:
    """Install an importer plugin, by default IMPORTER_SOURCE."""
    def install(distribution: str, name: str, source: str = IMPORTER_SOURCE,
                factory: str = 'create_importer') -> str:
        return install_plugin(distribution, name, source, IMPORTER_ENTRY_POINT_GROUP, factory)

    return install


@pytest.fixture
def inputs(tmp_path: Path) -> Tuple[Path, Path]:
    """MINIMAL split into a primary input and a process-stack supporting file."""
    stack = tmp_path / 'stack.txt'
    stack.write_text(STACK_ONLY, encoding='utf-8')
    primary = tmp_path / 'design.txt'
    primary.write_text(MINIMAL[len(STACK_ONLY):], encoding='utf-8')
    return primary, stack


def run_cli(arguments: List[str]) -> int:
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', *arguments])
    return completion.value.code


def test_discovery_lists_importers_without_loading_them(
        install_importer: Callable[..., str], capsys: pytest.CaptureFixture):
    module = install_importer('test-one', 'example', 'raise ImportError("missing parser")')
    assert [info.qualified_name for info in pex25d.importer_registry().importers] == ['test-one:example']
    assert run_cli(['importers']) == pex25d.ExitCode.OK
    assert capsys.readouterr().out.split() == ['test-one:example']
    assert module not in sys.modules


def test_public_api_imports_with_supporting_files(
        install_importer: Callable[..., str], inputs: Tuple[Path, Path]):
    install_importer('test-one', 'example')
    primary, stack = inputs
    supporting = {'process_stack': str(stack)}
    imported = pex25d.import_file(str(primary), 'example', supporting_files=supporting)
    assert imported.SerializeToString() == pex25d.read_text(MINIMAL.encode('utf-8')).SerializeToString()
    assert supporting == {'process_stack': str(stack)}


def test_cli_imports_validates_and_writes(
        install_importer: Callable[..., str], inputs: Tuple[Path, Path], tmp_path: Path):
    install_importer('test-one', 'example')
    primary, stack = inputs
    output = tmp_path / 'cell.pex25d'
    assert run_cli(['import', str(primary), '--from', 'test-one:example',
                    '--supporting', f'process_stack={stack}', '-o', str(output)]) == pex25d.ExitCode.OK
    assert pex25d.read(str(output)).SerializeToString() == \
        pex25d.read_text(MINIMAL.encode('utf-8')).SerializeToString()


def test_cli_writes_invalid_import_and_reports_it(
        install_importer: Callable[..., str], inputs: Tuple[Path, Path], tmp_path: Path):
    install_importer('test-one', 'example')
    primary, stack = inputs
    primary.write_text('CONDUCTOR A neta\nBOX CONDUCTOR A LAYER nosuch LL 0 0 UR 1 1\n', encoding='utf-8')
    output = tmp_path / 'cell.pex25d'
    diagnostics = tmp_path / 'diagnostics.json'
    assert run_cli(['import', str(primary), '--from', 'example', '--supporting', f'stack={stack}',
                    '-o', str(output), '--diagnostics', 'json',
                    '--diagnostics_out', str(diagnostics)]) == pex25d.ExitCode.DIAGNOSTIC_ERRORS
    assert output.exists()
    assert 'PEX25D-E0201' in {d['code'] for d in json.loads(diagnostics.read_text())['diagnostics']}


def test_cli_points_to_invalid_import_after_diagnostics(
        install_importer: Callable[..., str], inputs: Tuple[Path, Path], tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture):
    install_importer('test-one', 'example')
    primary, stack = inputs
    primary.write_text('CONDUCTOR A neta\nBOX CONDUCTOR A LAYER nosuch LL 0 0 UR 1 1\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.INFO, logger='__kpex__')
    assert run_cli(['import', primary.name, '--from', 'example', '--supporting', f'stack={stack.name}',
                    '-o', 'cell.pex25d']) == pex25d.ExitCode.DIAGNOSTIC_ERRORS
    messages = [record.getMessage() for record in caplog.records]
    assert any('PEX25D-E0201' in message for message in messages)
    assert messages[-1] == 'The imported file is invalid; review it at:'
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == os.path.join(os.getcwd(), 'cell.pex25d')


@pytest.mark.parametrize('arguments', [
    ['--supporting', 'stack.txt'],
    ['--supporting', 'stack=a.txt', '--supporting', 'stack=b.txt'],
    ['-o', 'cell.pex25d.scene.pb'],
], ids=['no-name', 'duplicate-name', 'scene-output'])
def test_cli_rejects_bad_arguments_before_loading(
        install_importer: Callable[..., str], tmp_path: Path, arguments: List[str]):
    module = install_importer('test-one', 'example')
    arguments = ['-o', str(tmp_path / 'cell.pex25d'), *arguments]
    assert run_cli(['import', str(tmp_path / 'design.txt'), '--from', 'example', *arguments]) \
        == pex25d.ExitCode.USAGE
    assert module not in sys.modules


@pytest.mark.parametrize('selector, source', [
    ('unknown', IMPORTER_SOURCE),
    ('example', 'raise ImportError("missing parser")'),
    ('example', IMPORTER_SOURCE.replace(
        "        from klayout_pex import pex25d\n",
        "        from klayout_pex.plugin_api.v1 import ImporterError\n"
        "        raise ImporterError('unsupported construct')\n")),
    ('example', IMPORTER_SOURCE.replace("        from klayout_pex import pex25d\n",
                                        "        open(input_file_path + '.missing')\n")),
], ids=['unknown', 'unavailable', 'importer-error', 'os-error'])
def test_expected_failures_keep_identity_and_exit_usage(
        install_importer: Callable[..., str], inputs: Tuple[Path, Path], tmp_path: Path,
        capsys: pytest.CaptureFixture, selector: str, source: str):
    install_importer('test-one', 'example', source)
    primary, _ = inputs
    with pytest.raises((ImporterError, OSError)) as failure:
        pex25d.import_file(str(primary), selector)
    assert not isinstance(failure.value, pex25d.ImporterExecutionError)
    assert run_cli(['import', str(primary), '--from', selector,
                    '-o', str(tmp_path / 'cell.pex25d')]) == pex25d.ExitCode.USAGE
    if selector == 'unknown':
        assert 'test-one:example' in str(failure.value)
    assert 'crashed' not in capsys.readouterr().err


@pytest.mark.parametrize('replacement, message', [
    ("        raise KeyError('process_stack')\n", "crashed: KeyError"),
    ("        return None\n", "returned NoneType, not a PEX25DFile"),
], ids=['crash', 'wrong-result'])
def test_importer_crash_or_wrong_result_exits_internal_error(
        install_importer: Callable[..., str], inputs: Tuple[Path, Path], tmp_path: Path,
        replacement: str, message: str):
    install_importer('test-one', 'example', IMPORTER_SOURCE.replace(
        "        from klayout_pex import pex25d\n", replacement))
    primary, _ = inputs
    with pytest.raises(pex25d.ImporterExecutionError, match=f"Importer 'test-one:example' {message}"):
        pex25d.import_file(str(primary), 'example')
    output = tmp_path / 'cell.pex25d'
    assert run_cli(['import', str(primary), '--from', 'example', '-o', str(output)]) \
        == pex25d.ExitCode.INTERNAL_ERROR
    assert not output.exists()
