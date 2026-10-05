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

"""Exercise installed plugin metadata and preserve the built-in export API."""

from __future__ import annotations

import ast
import errno
import json
import logging
from importlib import metadata
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple, Type
from unittest.mock import Mock

import pytest

from klayout_pex import pex25d
from klayout_pex.plugin_api.v1 import (
    EXPORTER_ENTRY_POINT_GROUP,
    ExportError,
    ExporterUnavailable,
    PEX25DSceneExporter,
)
from klayout_pex.plugin.exporter_registry import ExporterRegistry

from .pex25d_fixtures import MINIMAL, STACK_ONLY

if TYPE_CHECKING:
    from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelGenerator
    from klayout_pex.fastercap.pex25d_model_builder import PEX25DFasterCapModelBuilder
    from klayout_pex.fastercap.pex25d_exporter import FasterCapExporterOptions

    from klayout_pex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene


PLUGIN_SOURCE = '''
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Mapping, Optional

if TYPE_CHECKING:
    from klayout_pex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene

class Exporter:
    def export(self, scene: PEX25DScene, *, output_dir_path: str,
               prefix: str = '', options: Optional[Mapping[str, Any]] = None) -> List[str]:
        options = options or {}
        directory = Path(output_dir_path)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (prefix + 'input.txt')
        path.write_text(f"{scene.conductors[0].name}:{options.get('mesh_size', 0.25)}", encoding='utf-8')
        return [str(path)]

def create_exporter() -> Exporter:
    return Exporter()
'''


@pytest.fixture
def scene() -> PEX25DScene:
    return pex25d.resolve(pex25d.read_text(MINIMAL.encode('utf-8')))


@pytest.fixture
def install_exporter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., str]]:
    """Create real dist-info metadata, restricting discovery to this fixture."""
    monkeypatch.syspath_prepend(str(tmp_path))
    modules = []

    def entry_points(*, group: str) -> metadata.EntryPoints:
        return metadata.EntryPoints(
            ep for dist in metadata.distributions(path=[str(tmp_path)])
            for ep in dist.entry_points
        ).select(group=group)

    monkeypatch.setattr(metadata, 'entry_points', entry_points)

    def install(distribution: str, name: str, source: str = PLUGIN_SOURCE,
                group: str = EXPORTER_ENTRY_POINT_GROUP,
                factory: str = 'create_exporter') -> str:
        module = 'test_exporter_' + distribution.lower().replace('-', '_')
        modules.append(module)
        (tmp_path / f'{module}.py').write_text(textwrap.dedent(source), encoding='utf-8')
        dist_info = tmp_path / f'{distribution.replace("-", "_")}-1.0.dist-info'
        dist_info.mkdir()
        (dist_info / 'METADATA').write_text(
            f'Metadata-Version: 2.1\nName: {distribution}\nVersion: 1.0\n', encoding='utf-8')
        (dist_info / 'entry_points.txt').write_text(
            f'[{group}]\n{name} = {module}:{factory}\n', encoding='utf-8')
        return module

    yield install
    for module in modules:
        sys.modules.pop(module, None)


def test_discovery_does_not_import_plugins_and_ignores_other_api_versions(
        install_exporter: Callable[..., str]):
    module = install_exporter('test-one', 'example', 'raise ImportError("missing dependency")')
    other = install_exporter('test-two', 'future', group='klayout_pex.exporters.v2')

    registry = pex25d.exporter_registry()
    assert {info.qualified_name for info in registry.exporters} == {
        'klayout-pex:fastercap', 'klayout-pex:fastcap2', 'test-one:example',
    }
    assert module not in sys.modules
    assert other not in sys.modules
    with pytest.raises(ExportError, match="No exporter for 'future'"):
        registry.load('future')


def test_public_api_exports_with_an_installed_plugin(
        install_exporter: Callable[..., str], tmp_path: Path, scene: PEX25DScene):
    install_exporter('test-one', 'example')
    options = {'mesh_size': 0.25}
    paths = pex25d.export(scene, 'example', str(tmp_path / 'output'),
                         prefix='custom_', options=options)

    assert len(paths) == 1
    assert Path(paths[0]).name == 'custom_input.txt'
    assert Path(paths[0]).read_text(encoding='utf-8') == 'A:0.25'
    assert options == {'mesh_size': 0.25}


@pytest.mark.parametrize('selector', ['example', 'TEST_One:example'])
def test_cli_exports_with_an_installed_plugin(
        install_exporter: Callable[..., str], tmp_path: Path, selector: str):
    from klayout_pex.pex25d.diagnostics import ExitCode
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    module = install_exporter('test-one', 'example')
    input_path = tmp_path / 'cell.pex25d'
    input_path.write_text(MINIMAL, encoding='utf-8')
    directory = tmp_path / 'deck'
    arguments = ['export', str(input_path), '--to', selector,
                 '--out_dir', str(directory), '--prefix', 'custom_']
    cli = Pex25DCLI()
    assert cli.parse_args(arguments).exporter_name == selector
    assert module not in sys.modules
    with pytest.raises(SystemExit) as completion:
        cli.main(['pex25d', *arguments])
    assert completion.value.code == ExitCode.OK
    assert (directory / 'custom_input.txt').read_text(encoding='utf-8') == 'A:0.25'


@pytest.mark.parametrize('extra_arguments, expected', [
    ([], {}),
    (['--field_margin', '15', '--delaunay_amax', '0.5', '--delaunay_b', '0.8',
      '--stl', '--geo_check'],
     {'field_margin_um': 15.0, 'delaunay_amax': 0.5, 'delaunay_b': 0.8,
      'write_stl': True, 'geometry_check': True}),
])
def test_cli_passes_only_explicit_export_options(
        install_exporter: Callable[..., str], tmp_path: Path,
        extra_arguments: List[str], expected: Dict[str, Any]):
    from klayout_pex.pex25d.diagnostics import ExitCode
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    source = PLUGIN_SOURCE.replace(
        '''f"{scene.conductors[0].name}:{options.get('mesh_size', 0.25)}"''', 'repr(options)')
    install_exporter('test-one', 'example', source)
    input_path = tmp_path / 'cell.pex25d'
    input_path.write_text(MINIMAL, encoding='utf-8')
    directory = tmp_path / 'deck'
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', 'export', str(input_path), '--to', 'example',
                         '--out_dir', str(directory), *extra_arguments])
    assert completion.value.code == ExitCode.OK
    actual = ast.literal_eval((directory / 'input.txt').read_text(encoding='utf-8'))
    assert actual == expected


@pytest.mark.parametrize('selector', ['unknown', 'example'])
def test_cli_unknown_or_ambiguous_exporters_exit_usage(
        install_exporter: Callable[..., str], tmp_path: Path, selector: str):
    from klayout_pex.pex25d.diagnostics import ExitCode
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    first = install_exporter('test-one', 'example')
    second = install_exporter('test-two', 'example')
    input_path = tmp_path / 'cell.pex25d'
    input_path.write_text(MINIMAL, encoding='utf-8')
    directory = tmp_path / 'deck'
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', 'export', str(input_path), '--to', selector,
                         '--out_dir', str(directory)])
    assert completion.value.code == ExitCode.USAGE
    assert not directory.exists()
    assert first not in sys.modules
    assert second not in sys.modules


def test_collisions_require_an_explicit_distribution(install_exporter: Callable[..., str]):
    first = install_exporter('test-one', 'example')
    second = install_exporter('test-two', 'example')
    registry = ExporterRegistry()

    with pytest.raises(ExportError, match='Ambiguous exporter') as failure:
        registry.load('example')
    assert 'test-one:example' in str(failure.value)
    assert 'test-two:example' in str(failure.value)
    assert first not in sys.modules
    assert second not in sys.modules
    assert type(registry.load('TEST_One:example')).__module__ == first
    assert type(registry.load('test-two:example')).__module__ == second


@pytest.mark.parametrize('target, class_name', [
    ('fastercap', 'FasterCapSceneExporter'), ('fastcap2', 'FastCap2SceneExporter'),
])
def test_external_plugin_cannot_silently_replace_a_builtin(
        install_exporter: Callable[..., str], target: str, class_name: str):
    module = install_exporter('test-one', target)
    registry = pex25d.exporter_registry()

    builtin = registry.load(target)
    assert type(registry.load(f'klayout-pex:{target}')) is type(builtin)
    assert type(builtin).__name__ == class_name
    assert builtin.name == target
    assert module not in sys.modules
    assert type(registry.load(f'test-one:{target}')).__module__ == module


@pytest.mark.parametrize('source, factory, message', [
    ('raise ImportError("missing mesher")', 'create_exporter', 'missing mesher'),
    ('create_exporter = 42', 'create_exporter', 'zero-argument exporter factory'),
    ('def create_exporter():\n    raise RuntimeError("initialization failed")',
     'create_exporter', 'initialization failed'),
    ('def create_exporter():\n    return object()', 'create_exporter', 'export method'),
    ('class Exporter:\n    def export(self): pass\ndef create_exporter():\n    return Exporter',
     'create_exporter', 'export method'),
    (PLUGIN_SOURCE, 'missing_factory', 'missing_factory'),
])
def test_broken_plugins_report_the_provider_without_breaking_others(
        install_exporter: Callable[..., str], source: str, factory: str, message: str):
    install_exporter('test-broken', 'broken', source, factory=factory)
    good = install_exporter('test-good', 'working')
    registry = ExporterRegistry()

    with pytest.raises(ExporterUnavailable, match=message) as failure:
        registry.load('broken')
    assert 'test-broken:broken' in str(failure.value)
    assert failure.value.__cause__ is not None
    assert type(registry.load('working')).__module__ == good


def test_registry_refresh_and_fresh_instances(install_exporter: Callable[..., str]):
    before = ExporterRegistry()
    install_exporter('test-one', 'example')
    with pytest.raises(ExportError, match='No exporter'):
        before.load('example')
    after = ExporterRegistry()
    assert after.load('example') is not after.load('example')


def test_unknown_string_target_is_an_export_error(
        install_exporter: Callable[..., str], tmp_path: Path, scene: PEX25DScene):
    with pytest.raises(pex25d.ExportError, match="No exporter for 'unknown'"):
        pex25d.export(scene, 'unknown', str(tmp_path))
    assert pex25d.ExportError is ExportError
    assert pex25d.ExporterUnavailable is ExporterUnavailable


@pytest.mark.parametrize('target', ['fastercap', 'fastcap2'])
@pytest.mark.parametrize('options', [None, {
    'delaunay_amax': 0.5, 'delaunay_b': 0.8, 'field_margin_um': 12.0,
    'write_stl': True, 'geometry_check': True}, {'field_margin_um': 10.0}])
def test_builtin_calls_preserve_model_and_output_settings(
        install_exporter: Callable[..., str], monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path, target: str,
        options: Optional[Mapping[str, Any]],
        scene: PEX25DScene):
    from klayout_pex.fastercap import pex25d_model_builder
    from klayout_pex.fastercap.pex25d_exporter import FasterCapExporterOptions

    calls: List[Tuple[PEX25DScene, FasterCapExporterOptions]] = []
    generator = Mock()

    def build(model: PEX25DFasterCapModelBuilder) -> FasterCapModelGenerator:
        calls.append((model.scene, model.options))
        return generator

    def write_fastcap(output_dir_path: str, prefix: str) -> List[str]:
        directory = Path(output_dir_path)
        primary = directory / (prefix + '.lst')
        primary.write_text('solver list', encoding='utf-8')
        geometry = directory / (prefix + '.geo')
        geometry.write_text('geometry', encoding='utf-8')
        return [str(primary), str(geometry)]

    def dump_stl(output_dir_path: str, prefix: str) -> List[str]:
        mesh = Path(output_dir_path) / (prefix + '.stl')
        mesh.write_text('mesh', encoding='utf-8')
        return [str(mesh)]

    generator.write_fastcap.side_effect = write_fastcap
    generator.dump_stl.side_effect = dump_stl
    monkeypatch.setattr(pex25d_model_builder.PEX25DFasterCapModelBuilder, 'build', build)
    expected = FasterCapExporterOptions(**(options or {}))
    directory = tmp_path / 'output'
    written = pex25d.export(scene, target, str(directory), 'model', options)
    expected_paths = [str(directory / 'model.lst'), str(directory / 'model.geo')]
    if expected.write_stl:
        expected_paths.append(str(directory / 'model.stl'))
    assert written == expected_paths
    assert calls == [(scene, expected)]
    generator.write_fastcap.assert_called_once_with(output_dir_path=str(directory), prefix='model')
    assert generator.check.call_count == int(expected.geometry_check)
    assert generator.dump_stl.call_count == int(expected.write_stl)


def test_builtin_invalid_option_keys_fail_without_creating_output(
        install_exporter: Callable[..., str], tmp_path: Path, scene: PEX25DScene):
    options = {'typo': 1}
    directory = tmp_path / 'output'
    with pytest.raises(ExportError, match="Invalid options for 'fastcap2'"):
        pex25d.export(scene, 'fastcap2', str(directory), options=options)
    assert options == {'typo': 1}
    assert not directory.exists()


def test_imports_and_builtin_discovery_need_no_geometry_or_generated_code():
    script = '''
        import importlib.abc
        import sys

        class BlockOptionalImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split('.')[0] in {'klayout', 'klayout_pex_protobuf', 'packaging'}:
                    raise ImportError('blocked optional dependency: ' + fullname)

        sys.meta_path.insert(0, BlockOptionalImports())
        from klayout_pex.plugin_api import v1
        from klayout_pex.plugin_api.v1.pex25d_importer import PEX25DImporter
        from klayout_pex.plugin_api.v1.pex25d_scene_exporter import PEX25DSceneExporter
        assert v1.PEX25DImporter is PEX25DImporter
        assert v1.PEX25DSceneExporter is PEX25DSceneExporter
        assert v1.ImporterFactory is not None

        from klayout_pex import pex25d
        registry = pex25d.exporter_registry()
        exporter = registry.load('klayout-pex:fastercap')
        try:
            exporter.export(object(), output_dir_path='unused')
        except pex25d.ExporterUnavailable as exc:
            assert 'needs KLayout' in str(exc)
        else:
            raise AssertionError('export should require KLayout')
    '''
    result = subprocess.run([sys.executable, '-c', textwrap.dedent(script)],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('write_stl', [False, True])
@pytest.mark.parametrize('target, prefix', [
    ('fastercap', 'FasterCap_Input_'),
    ('fastcap2', 'FastCap_Input_'),
])
def test_builtin_exports_create_solver_inputs_without_running_a_solver(
        install_exporter: Callable[..., str], tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, target: str, prefix: str, write_stl: bool):
    text = '''PEX25D 1.0-rc1
UNITS LENGTH um GRID 0.0001
GROUND_PLANE subs Z_OFFSETS -0.4 -0.1
METAL met1 Z_OFFSETS 1.0 1.4
DIELECTRIC_BACKGROUND air PERMITTIVITY 1.0
CONDUCTOR A neta
CONDUCTOR B netb
BOX CONDUCTOR A LAYER met1 LL 0.0 0.0 UR 1.0 0.5
BOX CONDUCTOR B LAYER met1 LL 2.0 0.0 UR 3.0 0.5
'''
    scene = pex25d.resolve(pex25d.read_text(text.encode('utf-8')))
    original = scene.SerializeToString()

    def forbid_solver(*args: Any, **kwargs: Any):
        raise AssertionError('export must not launch an external process')

    monkeypatch.setattr(subprocess, 'Popen', forbid_solver)
    exporter = pex25d.exporter_registry().load(target)
    options = {'write_stl': write_stl, 'geometry_check': write_stl}
    written = exporter.export(scene, output_dir_path=str(tmp_path / 'deck'), options=options)
    primary = Path(written[0])
    assert primary.name == f'{prefix}.lst'
    assert len(written) > 1
    assert all(Path(path).is_file() for path in written)
    lines = primary.read_text(encoding='utf-8').splitlines()
    conductors = [line for line in lines if line.startswith('C ')]
    assert len(conductors) == 3  # ground plane plus A and B
    for line in conductors:
        assert (primary.parent / line.split()[1]).is_file()
    assert scene.SerializeToString() == original
    assert any(Path(path).suffix == '.stl' for path in written) == write_stl
    assert options == {'write_stl': write_stl, 'geometry_check': write_stl}

    unrelated = primary.parent / (prefix + 'unrelated.geo')
    unrelated.write_text('not part of this export', encoding='utf-8')
    second = exporter.export(scene, output_dir_path=str(primary.parent))
    assert set(second) == {path for path in written if not path.endswith('.stl')}
    assert unrelated.read_text(encoding='utf-8') == 'not part of this export'
    assert all(Path(path).exists() for path in written)  # older STL files stay on disk


def test_empty_geometry_writers_return_only_files_written(tmp_path: Path):
    from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelGenerator

    generator = FasterCapModelGenerator(dbu=0.001, k_void=1.0, delaunay_amax=0.0,
                                        delaunay_b=1.0, materials={'empty': 2.0},
                                        net_names=['empty'])
    assert generator.write_fastcap(str(tmp_path), 'empty') == [str(tmp_path / 'empty.lst')]
    assert generator.dump_stl(str(tmp_path), 'empty') == []
    assert {path.name for path in tmp_path.iterdir()} == {'empty.lst'}


@pytest.mark.parametrize('name, value', [
    (name, value)
    for name in ('write_stl', 'geometry_check')
    for value in ('false', 0, 1, None)
] + [
    (name, value)
    for name in ('delaunay_amax', 'delaunay_b', 'field_margin_um')
    for value in ('8', True, None)
])
def test_builtin_rejects_invalid_option_values_before_building(
        install_exporter: Callable[..., str], monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path, scene: PEX25DScene, name: str, value: Any):
    from klayout_pex.fastercap.pex25d_model_builder import PEX25DFasterCapModelBuilder

    build = Mock(side_effect=AssertionError('invalid options must not reach meshing'))
    monkeypatch.setattr(PEX25DFasterCapModelBuilder, 'build', build)
    output = tmp_path / 'output'
    exporter = pex25d.exporter_registry().load('fastercap')
    with pytest.raises(ExportError, match=name):
        exporter.export(scene, output_dir_path=str(output), options={name: value})
    build.assert_not_called()
    assert not output.exists()


@pytest.mark.parametrize('number', [8, 8.0])
def test_builtin_numeric_options_accept_ints_and_floats(number: float):
    from klayout_pex.fastercap.pex25d_exporter import FasterCapExporterOptions

    settings = FasterCapExporterOptions(delaunay_amax=number, delaunay_b=number,
                                        field_margin_um=number)
    assert settings.delaunay_amax == settings.delaunay_b == settings.field_margin_um == number


@pytest.mark.parametrize('exception', ['KeyError("mesh_size")', 'RuntimeError("mesher crashed")'])
@pytest.mark.parametrize('log_level', ['info', 'debug'])
def test_plugin_execution_errors_are_wrapped_for_api_and_cli(
        install_exporter: Callable[..., str], tmp_path: Path, scene: PEX25DScene,
        capsys: pytest.CaptureFixture, caplog: pytest.LogCaptureFixture,
        exception: str, log_level: str):
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    caplog.set_level(logging.DEBUG, logger='__kpex__')
    source = PLUGIN_SOURCE.replace('options = options or {}', f'raise {exception}')
    install_exporter('test-one', 'example', source)
    with pytest.raises(ExportError) as failure:
        pex25d.export(scene, 'example', str(tmp_path / 'api-output'))
    assert type(failure.value.__cause__).__name__ == exception.split('(')[0]
    assert 'test-one:example' in str(failure.value)

    input_path = tmp_path / 'cell.pex25d'
    input_path.write_text(MINIMAL, encoding='utf-8')
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', '--log_level', log_level, 'export', str(input_path),
                         '--to', 'example', '--out_dir', str(tmp_path / 'cli-output')])
    assert completion.value.code == pex25d.ExitCode.INTERNAL_ERROR
    output = capsys.readouterr()
    assert 'test-one:example' in output.out + output.err
    assert ('Traceback' in output.out + output.err) == (log_level == 'debug')
    tracebacks = [record for record in caplog.records if record.exc_info]
    if log_level == 'debug':
        assert len(tracebacks) == 1
        assert tracebacks[0].levelno == logging.DEBUG
        assert tracebacks[0].exc_info[1].__cause__ is not None
    else:
        assert not tracebacks


@pytest.mark.parametrize('log_level', ['info', 'debug'])
def test_builtin_crashes_have_distinct_exit_status_and_debug_traceback(
        install_exporter: Callable[..., str], tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
        caplog: pytest.LogCaptureFixture, log_level: str):
    from klayout_pex.fastercap.pex25d_exporter import FasterCapSceneExporter
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    caplog.set_level(logging.DEBUG, logger='__kpex__')
    bug = AttributeError('no_such_field')

    def crash(backend: PEX25DSceneExporter, scene: PEX25DScene, *, output_dir_path: str,
              prefix: str = '', options: Optional[Mapping[str, Any]] = None) -> List[str]:
        raise bug

    monkeypatch.setattr(FasterCapSceneExporter, 'export', crash)
    input_path = tmp_path / 'cell.pex25d'
    input_path.write_text(MINIMAL, encoding='utf-8')
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', '--log_level', log_level, 'export', str(input_path),
                         '--to', 'fastercap', '--out_dir', str(tmp_path / 'deck')])
    assert completion.value.code == pex25d.ExitCode.INTERNAL_ERROR
    output = capsys.readouterr()
    assert 'klayout-pex:fastercap' in output.out + output.err
    assert 'AttributeError: no_such_field' in output.out + output.err
    assert ('Traceback' in output.out + output.err) == (log_level == 'debug')
    tracebacks = [record for record in caplog.records if record.exc_info]
    if log_level == 'debug':
        assert len(tracebacks) == 1
        assert tracebacks[0].levelno == logging.DEBUG
        assert tracebacks[0].exc_info[1].__cause__ is bug
    else:
        assert not tracebacks


def test_public_loaded_exporter_api_reuses_instance_and_preserves_crash_cause(
        install_exporter: Callable[..., str], monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path, scene: PEX25DScene):
    install_exporter('test-one', 'example')
    registry = pex25d.exporter_registry()
    exporter = registry.load('example')
    written = pex25d.export_with_backend(exporter, scene, target='example',
                                        output_dir_path=str(tmp_path / 'default-registry'))
    assert Path(written[0]).read_text(encoding='utf-8') == 'A:0.25'
    monkeypatch.setattr(registry, 'load', Mock(side_effect=AssertionError('must reuse the backend')))
    discover = Mock(side_effect=AssertionError('reusing the registry needs no discovery'))
    monkeypatch.setattr(metadata, 'entry_points', discover)
    written = pex25d.export_with_backend(exporter, scene, target='example',
                                        output_dir_path=str(tmp_path / 'deck'), registry=registry)
    assert Path(written[0]).read_text(encoding='utf-8') == 'A:0.25'
    bug = AttributeError('no_such_field')
    monkeypatch.setattr(exporter, 'export', Mock(side_effect=bug))
    with pytest.raises(pex25d.ExporterExecutionError, match='test-one:example') as failure:
        pex25d.export_with_backend(exporter, scene, target='example',
                                   output_dir_path=str(tmp_path / 'deck'), registry=registry)
    assert failure.value.__cause__ is bug
    discover.assert_not_called()


@pytest.mark.parametrize('error_type', ['ExportError', 'ExporterUnavailable'])
@pytest.mark.parametrize('phase', ['factory', 'export'])
def test_plugin_domain_errors_keep_their_identity(
        install_exporter: Callable[..., str], tmp_path: Path,
        scene: PEX25DScene, error_type: str, phase: str):
    source = PLUGIN_SOURCE.replace(
        'from pathlib import Path',
        f'from pathlib import Path\nfrom klayout_pex.plugin_api.v1 import {error_type}\n'
        f'failure = {error_type}("configuration error")')
    source = source.replace('return Exporter()' if phase == 'factory' else 'options = options or {}',
                            'raise failure')
    module = install_exporter('test-one', 'example', source)
    with pytest.raises(ExportError) as failure:
        pex25d.export(scene, 'example', str(tmp_path))
    assert failure.value is sys.modules[module].failure


@pytest.mark.parametrize('selector', ['unknown', 'example', 'broken'])
def test_cli_checks_exporter_before_reading_or_resolving(
        install_exporter: Callable[..., str], monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path, selector: str):
    from klayout_pex.pex25d import codec, resolver
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    install_exporter('test-one', 'example')
    install_exporter('test-two', 'example')
    install_exporter('test-broken', 'broken', 'raise ImportError("missing mesher")')
    load = Mock(side_effect=AssertionError('input must not be opened'))
    resolve = Mock(side_effect=AssertionError('input must not be resolved'))
    monkeypatch.setattr(codec, 'load_artifact', load)
    monkeypatch.setattr(resolver, 'resolve', resolve)
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', 'export', str(tmp_path / 'missing.pex25d'),
                         '--to', selector, '--out_dir', str(tmp_path / 'deck')])
    assert completion.value.code == pex25d.ExitCode.USAGE
    load.assert_not_called()
    resolve.assert_not_called()


def test_cli_emits_collected_diagnostics_when_export_fails(
        install_exporter: Callable[..., str], tmp_path: Path):
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    source = PLUGIN_SOURCE.replace('from pathlib import Path',
                                  'from pathlib import Path\nfrom klayout_pex.plugin_api.v1 import ExportError')
    source = source.replace('options = options or {}', 'raise ExportError("unsupported geometry")')
    install_exporter('test-one', 'example', source)
    input_path = tmp_path / 'empty.pex25d'
    input_path.write_text(STACK_ONLY + 'DOMAIN_MARGIN X 4 Y 4 Z 2\n', encoding='utf-8')
    diagnostics = tmp_path / 'diagnostics.json'
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', 'export', str(input_path), '--to', 'example',
                         '--out_dir', str(tmp_path / 'deck'), '--diagnostics', 'json',
                         '--diagnostics_out', str(diagnostics)])
    assert completion.value.code == pex25d.ExitCode.USAGE
    assert 'PEX25D-E0250' in {d['code'] for d in json.loads(diagnostics.read_text())['diagnostics']}


def test_unknown_selector_lists_available_identifiers_without_loading_plugins(
        install_exporter: Callable[..., str]):
    module = install_exporter('test-one', 'example', 'raise ImportError("missing mesher")')
    with pytest.raises(ExportError) as failure:
        pex25d.exporter_registry().load('unknown')
    for name in ('klayout-pex:fastercap', 'klayout-pex:fastcap2', 'test-one:example'):
        assert name in str(failure.value)
    assert module not in sys.modules


def test_cli_lists_exporters_without_input_or_plugin_imports(
        install_exporter: Callable[..., str], capsys: pytest.CaptureFixture):
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    module = install_exporter('test-one', 'example', 'raise ImportError("missing mesher")')
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', 'exporters'])
    assert completion.value.code == pex25d.ExitCode.OK
    output = capsys.readouterr().out
    for name in ('klayout-pex:fastercap', 'klayout-pex:fastcap2', 'test-one:example'):
        assert name in output
    assert module not in sys.modules


@pytest.mark.filterwarnings(
    'ignore:Implicit None on return values is deprecated and will raise KeyErrors:DeprecationWarning:importlib.metadata')
@pytest.mark.parametrize('missing_name', ['metadata', 'none', 'key_error'])
def test_missing_distribution_name_does_not_break_other_exporters(
        install_exporter: Callable[..., str], monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path, missing_name: str):
    module = install_exporter('test-one', 'example')
    if missing_name == 'metadata':
        (tmp_path / 'test_one-1.0.dist-info' / 'METADATA').write_text(
            'Metadata-Version: 2.1\nVersion: 1.0\n', encoding='utf-8')
    else:
        def distribution_name(distribution: metadata.Distribution) -> Optional[str]:
            if missing_name == 'key_error':
                raise KeyError('Name')
            return None

        monkeypatch.setattr(metadata.Distribution, 'name', property(distribution_name))
    registry = pex25d.exporter_registry()
    assert type(registry.load('fastercap')).__name__ == 'FasterCapSceneExporter'
    assert type(registry.load('unknown:example')).__module__ == module


def test_reusing_registry_avoids_repeated_metadata_discovery(
        install_exporter: Callable[..., str], monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path, scene: PEX25DScene):
    install_exporter('test-one', 'example')
    discover = Mock(wraps=metadata.entry_points)
    monkeypatch.setattr(metadata, 'entry_points', discover)
    registry = pex25d.exporter_registry()
    for index in range(2):
        paths = pex25d.export(scene, 'example', str(tmp_path / str(index)), registry=registry)
        assert Path(paths[0]).read_text(encoding='utf-8') == 'A:0.25'
    discover.assert_called_once()


def test_cli_loads_selected_factory_only_once(
        install_exporter: Callable[..., str], tmp_path: Path):
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    source = PLUGIN_SOURCE.replace('def create_exporter() -> Exporter:',
                                  'calls = 0\ndef create_exporter() -> Exporter:\n'
                                  '    global calls\n    calls += 1')
    module = install_exporter('test-one', 'example', source)
    input_path = tmp_path / 'cell.pex25d'
    input_path.write_text(MINIMAL, encoding='utf-8')
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', 'export', str(input_path), '--to', 'example',
                         '--out_dir', str(tmp_path / 'deck')])
    assert completion.value.code == pex25d.ExitCode.OK
    assert sys.modules[module].calls == 1


def test_format_import_does_not_load_registry():
    script = """
        import importlib.abc
        import sys

        class BlockRegistryImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == 'klayout_pex.plugin.exporter_registry':
                    raise ImportError('format import loaded ' + fullname)

        sys.meta_path.insert(0, BlockRegistryImports())
        from klayout_pex import pex25d
        assert callable(pex25d.read_text)
        assert 'klayout_pex.plugin.exporter_registry' not in sys.modules
    """
    result = subprocess.run([sys.executable, '-c', textwrap.dedent(script)],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_builtin_returns_all_conductor_dielectric_and_stl_files(
        install_exporter: Callable[..., str], tmp_path: Path, scene: PEX25DScene):
    directory = tmp_path / 'deck'
    written = pex25d.export(scene, 'fastercap', str(directory), options={'write_stl': True})
    primary = Path(written[0])
    lines = primary.read_text(encoding='utf-8').splitlines()
    interfaces = [line.split()[1] for line in lines if line.startswith(('C ', 'D '))]
    assert any(line.startswith('D ') for line in lines)
    assert {str(primary.parent / name) for name in interfaces} == {
        path for path in written if path.endswith('.geo')}
    assert set(written) == {str(path) for path in directory.iterdir()}
    assert len(written) == len(set(written))


@pytest.mark.parametrize('target', ['fastercap', 'example'])
@pytest.mark.parametrize('error_number', [errno.EACCES, errno.ENOSPC, errno.ENOENT],
                         ids=['permission-denied', 'disk-full', 'missing-path'])
def test_export_io_errors_keep_identity_and_exit_usage(
        install_exporter: Callable[..., str], monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path, scene: PEX25DScene, capsys: pytest.CaptureFixture,
        caplog: pytest.LogCaptureFixture, target: str, error_number: int):
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    caplog.set_level(logging.DEBUG, logger='__kpex__')
    install_exporter('test-one', 'example')
    registry = pex25d.exporter_registry()
    exporter = registry.load(target)
    directory = tmp_path / 'deck'
    failure = OSError(error_number, 'output unavailable', str(directory))
    monkeypatch.setattr(type(exporter), 'export', Mock(side_effect=failure))

    with pytest.raises(OSError) as raised:
        pex25d.export(scene, target, str(directory), registry=registry)
    assert raised.value is failure

    input_path = tmp_path / 'cell.pex25d'
    input_path.write_text(MINIMAL, encoding='utf-8')
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', '--log_level', 'debug', 'export', str(input_path),
                         '--to', target, '--out_dir', str(directory)])
    assert completion.value.code == pex25d.ExitCode.USAGE
    output = capsys.readouterr()
    assert any('output unavailable' in record.getMessage() for record in caplog.records)
    assert 'crashed' not in output.out + output.err
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize('target', ['fastercap', 'example'])
def test_cli_rejects_output_directory_that_is_a_file(
        install_exporter: Callable[..., str], tmp_path: Path,
        capsys: pytest.CaptureFixture, target: str):
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    install_exporter('test-one', 'example')
    input_path = tmp_path / 'cell.pex25d'
    input_path.write_text(MINIMAL, encoding='utf-8')
    output_path = tmp_path / 'deck'
    output_path.write_text('existing file', encoding='utf-8')
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', 'export', str(input_path), '--to', target,
                         '--out_dir', str(output_path)])
    assert completion.value.code == pex25d.ExitCode.USAGE
    output = capsys.readouterr()
    assert 'crashed' not in output.out + output.err
    assert output_path.read_text(encoding='utf-8') == 'existing file'


@pytest.mark.parametrize('with_registry', [False, True])
def test_unregistered_loaded_exporter_writes_without_metadata_lookup(
        install_exporter: Callable[..., str], monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path, scene: PEX25DScene, with_registry: bool):
    class LocalExporter(PEX25DSceneExporter):
        def export(self, scene: PEX25DScene, *, output_dir_path: str,
                   prefix: str = '', options: Optional[Mapping[str, Any]] = None) -> List[str]:
            output = Path(output_dir_path) / (prefix + 'input.txt')
            output.write_text(scene.conductors[0].name, encoding='utf-8')
            return [str(output)]

    registry = pex25d.exporter_registry() if with_registry else None
    if registry is not None:
        lookup = Mock(wraps=registry.get_info)
        monkeypatch.setattr(registry, 'get_info', lookup)
    discover = Mock(side_effect=AssertionError('successful exports must not scan metadata'))
    monkeypatch.setattr(metadata, 'entry_points', discover)
    exporter = LocalExporter()
    for prefix in ('first_', 'second_'):
        paths = pex25d.export_with_backend(exporter, scene, 'mine', str(tmp_path),
                                           prefix=prefix, registry=registry)
        assert paths == [str(tmp_path / (prefix + 'input.txt'))]
        assert Path(paths[0]).read_text(encoding='utf-8') == 'A'
    discover.assert_not_called()
    if registry is not None:
        lookup.assert_not_called()


@pytest.mark.parametrize('with_registry, failure_mode', [
    (False, 'missing'), (True, 'missing'),
    (False, 'discovery'), (True, 'lookup'),
])
def test_loaded_exporter_crash_survives_provider_lookup_failure(
        install_exporter: Callable[..., str], monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path, scene: PEX25DScene, with_registry: bool, failure_mode: str):
    registry = pex25d.exporter_registry() if with_registry else None
    if failure_mode == 'discovery':
        monkeypatch.setattr(metadata, 'entry_points', Mock(side_effect=RuntimeError('metadata unavailable')))
    elif failure_mode == 'lookup':
        monkeypatch.setattr(registry, 'get_info', Mock(side_effect=RuntimeError('lookup failed')))
    bug = AttributeError('broken scene')
    exporter = Mock(spec=PEX25DSceneExporter)
    exporter.export.side_effect = bug

    with pytest.raises(pex25d.ExporterExecutionError,
                       match="Exporter 'mine' crashed: AttributeError: broken scene") as failure:
        pex25d.export_with_backend(exporter, scene, 'mine', str(tmp_path), registry=registry)
    assert failure.value.__cause__ is bug
    exporter.export.assert_called_once_with(scene, output_dir_path=str(tmp_path), prefix='', options=None)


@pytest.mark.parametrize('error_type', [ExportError, NotImplementedError, PermissionError])
def test_loaded_exporter_expected_errors_do_not_scan_metadata(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        scene: PEX25DScene, error_type: Type[Exception]):
    failure = error_type('cannot export')
    exporter = Mock(spec=PEX25DSceneExporter)
    exporter.export.side_effect = failure
    discover = Mock(side_effect=AssertionError('handled errors must not scan metadata'))
    monkeypatch.setattr(metadata, 'entry_points', discover)
    with pytest.raises(error_type) as raised:
        pex25d.export_with_backend(exporter, scene, 'mine', str(tmp_path))
    assert raised.value is failure
    discover.assert_not_called()
