#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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

"""Run lifecycle, reproducible evidence and schema boundaries."""

import json
import math
from pathlib import Path
import sys
from unittest import mock

import allure
import pytest
from typing import Any, Callable, Dict, List
from kpex.tech_info import TechInfo

from kpex.calibration.artifacts import read_message, write_message, sha256_file
from kpex.calibration.patterns import read_patterns
from kpex.calibration.prepare import prepare_calibration
from kpex.calibration.prepared_input import read_preparation, validated_scenes
from kpex.calibration.solve import (solve_calibration, SolveOptions, MAX_MESH_MIN_ANGLE_DEG,
                                           options_message, validate_options_message)
from kpex.calibration.collect import collect_calibration
from kpex.calibration.validation import CalibrationError
from kpex.fastercap.fastercap_runner import FasterCapRunResult
from kpex_protobuf.kpex.result.solver_execution_pb2 import SolverIdentity
from kpex_protobuf.kpex.calibration.solving_pb2 import CalibrationCollection, CalibrationCaseResult

pytestmark = allure.parent_suite('Unit Tests')


@pytest.fixture
def preparation(tmp_path: Path, pattern_data: Dict[str, Any], tech_info: TechInfo) -> Path:
    source = tmp_path / 'patterns.json'
    source.write_text(json.dumps(pattern_data), encoding='utf-8')
    return prepare_calibration(tech_info, read_patterns(source), tmp_path / 'patterns').manifest_path


@pytest.fixture
def fake_solver(monkeypatch: pytest.MonkeyPatch) -> Callable:
    executable = Path(sys.executable).resolve()
    identity = SolverIdentity(name='fastercap', version='6.2.1', executable_path=str(executable),
                              executable_sha256=sha256_file(executable), operating_system='test', architecture='test')
    monkeypatch.setattr('kpex.calibration.solve._solver_identity', lambda _: identity)

    def run(exe: str, deck: str, log: str, *args: Any, **kwargs: Any) -> FasterCapRunResult:
        # Native order differs deliberately: projection must follow identities,
        # not assume the ground is always the first or last row.
        Path(log).write_text('Capacitance matrix is:\nDimension 3 x 3\n'
                             'g1_B 5e-9 -2e-9 -1e-9\n'
                             'g2_substrate -2e-9 6e-9 -3e-9\n'
                             'g3_A -1e-9 -3e-9 7e-9\n'
                             'Solve statistics:\nNumber of panels after refinement: 123\n', encoding='utf-8')
        return FasterCapRunResult((str(exe), deck), 0, 0.1)
    monkeypatch.setattr('kpex.fastercap.fastercap_runner.run_fastercap', run)
    return run


def test_preparation_is_validated_against_geometry(preparation: Path):
    prepared = read_preparation(preparation)
    assert len(validated_scenes(prepared)) == 2


def test_solve_and_offline_recollection(preparation: Path, fake_solver: Callable, tmp_path: Path):
    result = solve_calibration(preparation, tmp_path / 'runs')
    assert result.successful_cases == 2
    assert set(result.written_paths) == {p for p in (tmp_path / 'runs').rglob('*') if p.is_file()}
    collection = read_message(result.collection_path, CalibrationCollection())
    assert collection.execution_complete
    assert list(collection.cases[0].measured_matrix.conductor_ids) == ['A', 'B']
    assert list(collection.cases[0].measured_matrix.rows[0].values) == pytest.approx([7e-15, -1e-15])
    assert collection.cases[0].refined_panels == 123
    with mock.patch('subprocess.Popen', side_effect=AssertionError('collection must never execute')):
        again = collect_calibration(result.manifest_path, tmp_path / 'again')
    assert read_message(again.manifest_path, CalibrationCollection()) == collection


@pytest.mark.parametrize('changes', [dict(jobs=0), dict(jobs=33), dict(threads_per_job=0), dict(threads_per_job=257),
                                    dict(solver_timeout_seconds=0), dict(solver_timeout_seconds=float('nan')),
                                    dict(automatic_tolerance=0), dict(mesh_refinement=1),
                                    dict(automatic_tolerance=0.1, mesh_refinement=1, gmres_tolerance=1e-7)])
def test_options_fail_before_solver(changes: Dict[str, Any]):
    with pytest.raises(CalibrationError):
        SolveOptions(**changes)


@pytest.mark.parametrize('changes', [dict(jobs=1), dict(jobs=32), dict(threads_per_job=1), dict(threads_per_job=256),
                                    dict(mesh_refinement=0.1, gmres_tolerance=1e-7)])
def test_option_boundaries(changes: Dict[str, Any]):
    SolveOptions(**changes)


def test_changed_input_rejected_before_launch(preparation: Path, fake_solver: Callable, tmp_path: Path):
    (preparation.parent / 'technology.pb.json').write_text('{}', encoding='utf-8')
    with pytest.raises(CalibrationError, match='changed'):
        solve_calibration(preparation, tmp_path / 'runs')
    assert not (tmp_path / 'runs').exists()


def test_unknown_schema_field_rejected(preparation: Path, tmp_path: Path):
    value = json.loads(preparation.read_text(encoding='utf-8'))
    value['invented'] = 42
    preparation.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(CalibrationError, match='invented'):
        read_preparation(preparation)


@pytest.mark.parametrize('status', ['exit', 'timeout', 'malformed'])
def test_failed_solves_preserve_evidence(preparation: Path, fake_solver: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str):
    from kpex.fastercap.fastercap_error import FasterCapExecutionError, FasterCapTimeoutError
    def fail(exe: str, deck: str, log: str, *args: Any, **kwargs: Any):
        result = fake_solver(exe, deck, log, *args, **kwargs)
        if status == 'malformed':
            with Path(log).open('a', encoding='utf-8') as stream:
                stream.write('Capacitance matrix is:\nDimension 3 x 3\ntruncated\n')
            return result
        error = FasterCapTimeoutError if status == 'timeout' else FasterCapExecutionError
        raise error('deliberate failure', result=FasterCapRunResult(result.arguments, 75, 0.1))
    monkeypatch.setattr('kpex.fastercap.fastercap_runner.run_fastercap', fail)
    result = solve_calibration(preparation, tmp_path / 'runs')
    assert result.successful_cases == 0 and result.failed_cases == 2
    collection = read_message(result.collection_path, CalibrationCollection())
    expected = CalibrationCaseResult.INVALID_RESULT if status == 'malformed' else CalibrationCaseResult.EXECUTION_FAILED
    assert all(case.status == expected and not case.HasField('measured_matrix') for case in collection.cases)
    assert (tmp_path / 'runs/cases/plates/solver.log').read_text(encoding='utf-8')


def test_cancelled_batch_is_collectable(preparation: Path, fake_solver: Callable, tmp_path: Path):
    import threading
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(CalibrationError, match='interrupted'):
        solve_calibration(preparation, tmp_path / 'runs', cancel_event=cancelled)
    assert not (tmp_path / 'runs/completed.pb.json').exists()
    result = collect_calibration(tmp_path / 'runs/manifest.json', tmp_path / 'collected')
    collection = read_message(result.manifest_path, CalibrationCollection())
    assert not collection.execution_complete
    assert all(case.status == CalibrationCaseResult.EXECUTION_FAILED for case in collection.cases)


def test_crash_checkpoint_remains_incomplete(preparation: Path, fake_solver: Callable, tmp_path: Path):
    from kpex_protobuf.kpex.calibration.solving_pb2 import CalibrationRunCheckpoint
    from kpex_protobuf.kpex.result.solver_execution_pb2 import SolverExecution
    result = solve_calibration(preparation, tmp_path / 'runs')
    (tmp_path / 'runs/completed.pb.json').unlink()
    path = tmp_path / 'runs/cases/plates/checkpoint.pb.json'
    checkpoint = read_message(path, CalibrationRunCheckpoint())
    checkpoint.execution.status = SolverExecution.RUNNING
    checkpoint.ClearField('log')
    write_message(path, checkpoint, replace=True)
    (tmp_path / 'runs/cases/wires/checkpoint.pb.json').unlink()
    result = collect_calibration(result.manifest_path, tmp_path / 'collected')
    collection = read_message(result.manifest_path, CalibrationCollection())
    assert not collection.execution_complete
    assert [case.status for case in collection.cases] == [CalibrationCaseResult.INCOMPLETE] * 2
    assert (tmp_path / 'collected/runs/cases/plates/solver.log').is_file()


def test_changed_completed_log_is_rejected(preparation: Path, fake_solver: Callable, tmp_path: Path):
    result = solve_calibration(preparation, tmp_path / 'runs')
    (tmp_path / 'runs/cases/plates/solver.log').write_text('different result', encoding='utf-8')
    with pytest.raises(CalibrationError, match='changed'):
        collect_calibration(result.manifest_path, tmp_path / 'collected')
    assert not (tmp_path / 'collected').exists()


@pytest.mark.parametrize('name', ['../outside', '/absolute', 'a/../b', 'a\\b', 'C:drive', './a', 'a//b'])
def test_artifact_paths_cannot_escape(tmp_path: Path, name: str):
    from kpex.calibration.artifacts import artifact_path
    with pytest.raises(CalibrationError, match='Invalid'):
        artifact_path(tmp_path, name, required=False)


def test_existing_output_is_untouched(preparation: Path, tmp_path: Path):
    output = tmp_path / 'existing'
    output.mkdir()
    sentinel = output / 'notes.txt'
    sentinel.write_text('keep', encoding='utf-8')
    with mock.patch('kpex.calibration.solve._solver_identity') as detect:
        with pytest.raises(CalibrationError, match='already exists'):
            solve_calibration(preparation, output)
    detect.assert_not_called()
    assert sentinel.read_text(encoding='utf-8') == 'keep'


def test_saved_collection_does_not_import_klayout(preparation: Path, fake_solver: Callable, tmp_path: Path):
    import subprocess
    result = solve_calibration(preparation, tmp_path / 'runs')
    code = """
import sys
from pathlib import Path
sys.modules['klayout'] = None
sys.modules['klayout.db'] = None
from kpex.calibration.collect import collect_calibration
collect_calibration(Path(sys.argv[1]), Path(sys.argv[2]))
"""
    completed = subprocess.run([sys.executable, '-c', code, str(result.manifest_path), str(tmp_path / 'offline')],
                               capture_output=True, text=True, encoding='utf-8')
    assert completed.returncode == 0, completed.stderr


def test_cli_commands_and_validation_before_loading(tmp_path: Path):
    from tests.common.cli_runner import run_cli
    from kpex.kpex_cli import KpexCLI
    code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', '--help'])
    assert code == 0 and '{prepare,solve,collect,qualify,fit-length,fit-overlap}' in output, output
    for command, manifest_type in [('solve', 'CalibrationManifest'), ('collect', 'CalibrationRunManifest')]:
        code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', command, '--help'])
        assert code == 0 and '--manifest FILE' in output and manifest_type in output, output
    code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'solve', '--manifest', 'missing.json',
                                          '--jobs', '0', '--out-dir', str(tmp_path / 'out')])
    assert code == 2 and 'jobs must be an integer' in output, output


def test_cli_solve_and_collect(preparation: Path, fake_solver: Callable, tmp_path: Path):
    from tests.common.cli_runner import run_cli
    from kpex.kpex_cli import KpexCLI
    for args in [['solve', '--manifest', str(preparation), '--out-dir', str(tmp_path / 'runs')],
                 ['collect', '--manifest', str(tmp_path / 'runs/manifest.json'), '--out-dir', str(tmp_path / 'copy')]]:
        code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', *args])
        assert code == 0, output
        assert 'Numerical qualification and coefficient fitting have not run' in output


@pytest.mark.parametrize('mutation', ['enum', 'unknown', 'version', 'case', 'log', 'report', 'duplicate'])
def test_invalid_saved_contracts_fail_before_output(preparation: Path, fake_solver: Callable, tmp_path: Path, mutation: str):
    from kpex_protobuf.kpex.calibration.solving_pb2 import CalibrationRunCheckpoint, CalibrationRunManifest
    result = solve_calibration(preparation, tmp_path / 'runs')
    (tmp_path / 'runs/completed.pb.json').unlink()
    path = tmp_path / 'runs/cases/plates/checkpoint.pb.json'
    if mutation == 'unknown':
        data = json.loads(path.read_text(encoding='utf-8'))
        data['unchecked'] = True
        path.write_text(json.dumps(data), encoding='utf-8')
    elif mutation == 'duplicate':
        manifest = read_message(result.manifest_path, CalibrationRunManifest())
        manifest.cases[1].CopyFrom(manifest.cases[0])
        write_message(result.manifest_path, manifest, replace=True)
    else:
        checkpoint = read_message(path, CalibrationRunCheckpoint())
        if mutation == 'enum':
            checkpoint.execution.status = 999
        elif mutation == 'version':
            checkpoint.schema_version = 99
        elif mutation == 'case':
            checkpoint.case_id = 'other'
        elif mutation == 'log':
            checkpoint.log.path = '../outside.log'
        elif mutation == 'report':
            checkpoint.numerical_report.path = '../outside.json'
        write_message(path, checkpoint, replace=True)
    with pytest.raises(CalibrationError):
        collect_calibration(result.manifest_path, tmp_path / 'collected')
    assert not (tmp_path / 'collected').exists()


def test_solver_identity_is_checked_before_output(preparation: Path, tmp_path: Path):
    from kpex.tool_version_constraints import Tool
    with pytest.raises(CalibrationError, match='was not found'):
        solve_calibration(preparation, tmp_path / 'runs', executable='nonexistent-calibration-solver')
    with mock.patch.object(Tool, 'detect_version', return_value=None):
        with pytest.raises(CalibrationError, match='requires FasterCap'):
            solve_calibration(preparation, tmp_path / 'runs', executable=sys.executable)
    assert not (tmp_path / 'runs').exists()


def test_parallel_results_keep_specification_order_and_thread_limits(preparation: Path, fake_solver: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import os
    import threading
    lock = threading.Lock()
    both_started = threading.Barrier(2, timeout=30)
    wires_finished = threading.Event()
    completed = []
    active = 0
    maximum = 0
    original = dict(os.environ)
    def run(exe: str, deck: str, log: str, *args: Any, **kwargs: Any) -> FasterCapRunResult:
        nonlocal active, maximum
        case_id = 'plates' if 'plates' in deck else 'wires'
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            assert kwargs['env']['OMP_NUM_THREADS'] == '2'
            # Synchronize overlap and reverse completion instead of assuming how
            # quickly a loaded CI runner schedules the second worker. Timeouts
            # bound failures if execution accidentally becomes serial.
            both_started.wait()
            if case_id == 'plates':
                assert wires_finished.wait(timeout=30), 'The wires solver did not finish'
            result = fake_solver(exe, deck, log, *args, **kwargs)
            with lock:
                completed.append(case_id)
            return result
        finally:
            with lock:
                active -= 1
            if case_id == 'wires':
                wires_finished.set()
    monkeypatch.setattr('kpex.fastercap.fastercap_runner.run_fastercap', run)
    result = solve_calibration(preparation, tmp_path / 'runs', options=SolveOptions(jobs=2, threads_per_job=2))
    assert result.successful_cases == 2 and result.failed_cases == 0
    assert maximum == 2
    assert completed == ['wires', 'plates']
    assert dict(os.environ) == original
    collection = read_message(result.collection_path, CalibrationCollection())
    assert [case.case_id for case in collection.cases] == ['plates', 'wires']


def test_export_order_does_not_define_primary_input(preparation: Path, fake_solver: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from kpex.fastercap.pex25d_exporter import FasterCapSceneExporter
    export = FasterCapSceneExporter.export
    def reordered(self: Any, *args: Any, **kwargs: Any) -> Any:
        return list(reversed(export(self, *args, **kwargs)))
    monkeypatch.setattr(FasterCapSceneExporter, 'export', reordered)
    result = solve_calibration(preparation, tmp_path / 'runs')
    assert result.successful_cases == 2


def test_unchanged_metadata_cannot_hide_changed_geometry(preparation: Path, tmp_path: Path):
    from kpex_protobuf.kpex.calibration.preparation_pb2 import CalibrationManifest
    from kpex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene
    manifest = read_message(preparation, CalibrationManifest())
    scene_path = preparation.parent / manifest.cases[0].scene
    scene = PEX25DScene.FromString(scene_path.read_bytes())
    scene.background.permittivity = 9
    scene_path.write_bytes(scene.SerializeToString())
    next(item for item in manifest.artifacts if item.path == scene_path.name).sha256 = sha256_file(scene_path)
    write_message(preparation, manifest, replace=True)
    with pytest.raises(CalibrationError, match='geometry differs'):
        validated_scenes(read_preparation(preparation))


def test_public_klayout_context_imports_are_preserved():
    import kpex.klayout as bindings
    from kpex.klayout.lvsdb_extractor import KLayoutExtractionContext, KLayoutExtractedLayerInfo
    assert bindings.KLayoutExtractionContext is KLayoutExtractionContext
    assert bindings.KLayoutExtractedLayerInfo is KLayoutExtractedLayerInfo


def test_stale_catalog_selection_is_rejected(preparation: Path):
    from kpex_protobuf.kpex.calibration.preparation_pb2 import CalibrationManifest
    manifest = read_message(preparation, CalibrationManifest())
    manifest.technology.selection.technology_id = 'another_technology'
    write_message(preparation, manifest, replace=True)
    with pytest.raises(CalibrationError, match='catalog selection'):
        read_preparation(preparation)


@pytest.mark.parametrize('field', ['automatic_tolerance', 'gmres_tolerance'])
@pytest.mark.parametrize('value', [-1.0, 0.0, 1.0, math.nextafter(1.0, math.inf),
                                   math.nan, math.inf, -math.inf])
def test_relative_tolerances_reject_invalid_bounds(field: str, value: float):
    # A fraction of one or larger was accepted by KPEX but rejected by FasterCap.
    # Check both numerical modes, including the representable value above one.
    values = {field: value}
    if field == 'gmres_tolerance':
        values['mesh_refinement'] = 0.05
    with pytest.raises(CalibrationError, match=field):
        SolveOptions(**values)


@pytest.mark.parametrize('field', ['automatic_tolerance', 'gmres_tolerance'])
@pytest.mark.parametrize('value', [sys.float_info.min, 0.05, math.nextafter(1.0, 0.0)])
def test_relative_tolerances_accept_valid_bounds(field: str, value: float):
    values = {field: value}
    if field == 'gmres_tolerance':
        values['mesh_refinement'] = 0.05
    options = SolveOptions(**values)
    assert validate_options_message(options_message(options)) == options


@pytest.mark.parametrize('angle', [0.0, 30.0, MAX_MESH_MIN_ANGLE_DEG])
def test_mesh_angle_keeps_existing_exporter_bounds(
        angle: float, preparation: Path, fake_solver: Callable, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch):
    from kpex.fastercap.pex25d_exporter import FasterCapSceneExporter
    from kpex.util.number_range import DELAUNAY_B_MAX
    export = FasterCapSceneExporter.export
    observed = []
    def record(self: Any, *args: Any, **kwargs: Any) -> Any:
        observed.append(kwargs['options']['delaunay_b'])
        return export(self, *args, **kwargs)
    monkeypatch.setattr(FasterCapSceneExporter, 'export', record)
    result = solve_calibration(preparation, tmp_path / 'runs',
                               options=SolveOptions(mesh_min_angle_deg=angle))
    assert result.successful_cases == 2
    expected = {0.0: 0.0, 30.0: 1.0, MAX_MESH_MIN_ANGLE_DEG: DELAUNAY_B_MAX}[angle]
    assert observed == pytest.approx([expected, expected])
    assert all(0 <= value <= DELAUNAY_B_MAX for value in observed)


@pytest.mark.parametrize('angle', [math.nextafter(0.0, -math.inf),
                                   math.nextafter(MAX_MESH_MIN_ANGLE_DEG, math.inf), math.nan, math.inf])
def test_mesh_angle_rejects_values_outside_mesher_limit(angle: float):
    with pytest.raises(CalibrationError, match='mesh_min_angle_deg'):
        SolveOptions(mesh_min_angle_deg=angle)


@pytest.mark.parametrize('arguments', [
    ['--jobs', '0'], ['--threads-per-job', '0'], ['--solver-timeout-seconds', '0'],
    ['--fastercap-auto-tolerance', '1'],
    ['--fastercap-mesh-refinement', '0.05', '--fastercap-gmres-tolerance', '1'],
    ['--fastercap-interaction-ratio', 'nan'], ['--mesh-max-area-um2', '-1'],
    ['--mesh-min-angle-deg', '34'], ['--solver', 'unavailable'],
    ['--fastercap-mesh-refinement', '0.05'], ['--fastercap-gmres-tolerance', '1e-7'],
    ['--fastercap-auto-tolerance', '0.05', '--fastercap-mesh-refinement', '0.05',
     '--fastercap-gmres-tolerance', '1e-7'],
])
def test_cli_invalid_controls_fail_before_reading_manifest(arguments: List[str], tmp_path: Path):
    from tests.common.cli_runner import run_cli
    from kpex.kpex_cli import KpexCLI
    with mock.patch('kpex.calibration.solve.read_preparation',
                    side_effect=AssertionError('validate controls before loading the manifest')):
        code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'solve', '--manifest', 'missing.json',
                                              '--out-dir', str(tmp_path / 'out'), *arguments])
    assert code == 2, output
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('option', ['--prepared', '--runs', '--threads', '--timeout-seconds',
                                    '--fastercap-tolerance', '--fastercap-d-coeff',
                                    '--delaunay-amax-um2', '--delaunay-b', '--mesh-min-angle'])
def test_cli_rejects_removed_names_and_partial_options(option: str, tmp_path: Path):
    from tests.common.cli_runner import run_cli
    from kpex.kpex_cli import KpexCLI
    code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'solve', '--manifest', 'missing.json',
                                          '--out-dir', str(tmp_path / 'out'), option, '1'])
    assert code == 2 and 'unrecognized arguments' in output, output


@pytest.mark.parametrize('controls,automatic', [([], 0.05),
    (['--fastercap-auto-tolerance', '0.1'], 0.1),
    (['--fastercap-mesh-refinement', '0.05', '--fastercap-gmres-tolerance', '1e-7'], None)])
def test_cli_records_explicit_controls_and_refinement_mode(
        controls: List[str], automatic: Any, preparation: Path, fake_solver: Callable, tmp_path: Path):
    from tests.common.cli_runner import run_cli
    from kpex.kpex_cli import KpexCLI
    from kpex_protobuf.kpex.calibration.solving_pb2 import CalibrationRunManifest
    run_dir = tmp_path / 'CLI run with spaces'
    code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'solve', '--manifest', str(preparation),
        '--solver', 'fastercap', '--fastercap-exe', sys.executable, '--out-dir', str(run_dir),
        '--jobs', '2', '--threads-per-job', '3', '--solver-timeout-seconds', '20',
        '--fastercap-interaction-ratio', '0.4', '--mesh-max-area-um2', '2',
        '--mesh-min-angle-deg', '25', *controls])
    assert code == 0, output
    assert f'Run manifest: {run_dir / "manifest.json"}' in output
    manifest = read_message(run_dir / 'manifest.json', CalibrationRunManifest())
    options = validate_options_message(manifest.options)
    assert options == SolveOptions(jobs=2, threads_per_job=3, solver_timeout_seconds=20,
        interaction_ratio=0.4, mesh_max_area_um2=2, mesh_min_angle_deg=25,
        automatic_tolerance=automatic, mesh_refinement=0.05 if automatic is None else None,
        gmres_tolerance=1e-7 if automatic is None else None)


@pytest.fixture(params=['6.3.0', '6.4.0'])
def report_version(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def report_solver(fake_solver: Callable, monkeypatch: pytest.MonkeyPatch, report_version: str) -> Callable:
    from tests.common.fastercap_report import numerical_report
    from kpex.calibration.solve import _solver_identity
    identity = _solver_identity('unused')
    identity.version = report_version

    def run(exe: str, deck: str, log: str, *args: Any, **kwargs: Any) -> FasterCapRunResult:
        result = fake_solver(exe, deck, log, *args, **kwargs)
        # Report values differ below the console's precision and are deliberately
        # asymmetric. Replacing them with rounded or averaged values loses evidence.
        data = numerical_report(['g1_B', 'g2_substrate', 'g3_A'],
                                [[5.000000000123456e-9, -2e-9, -1.000000000123456e-9],
                                 [-2e-9, 6e-9, -3e-9], [-1.01e-9, -3e-9, 7.000000000123456e-9]], deck)
        data['build']['version'] = f'FasterCap version {report_version}'
        Path(kwargs['report_path']).write_text(json.dumps(data), encoding='utf-8')
        return result
    monkeypatch.setattr('kpex.fastercap.fastercap_runner.run_fastercap', run)
    return run


def test_numerical_report_precision_artifacts_and_relocated_offline_collection(
        preparation: Path, report_solver: Callable, report_version: str, tmp_path: Path):
    import shutil
    from kpex_protobuf.kpex.calibration.solving_pb2 import CalibrationRunManifest
    from kpex_protobuf.kpex.result.capacitance_matrix_pb2 import MaxwellCapacitanceMatrix as Matrix
    result = solve_calibration(preparation, tmp_path / 'runs')
    assert result.successful_cases == 2
    assert set(result.written_paths) == {p for p in (tmp_path / 'runs').rglob('*') if p.is_file()}
    data = read_message(result.collection_path, CalibrationCollection())
    case = data.cases[0]
    # Raising the minimum for new solves must not relabel or reject saved runs
    # from the earlier report-capable solver during offline collection.
    assert read_message(result.manifest_path, CalibrationRunManifest()).solver.version == report_version
    assert case.measured_matrix.index_convention == Matrix.EXCITATION_ROWS
    assert case.native_matrix.index_convention == Matrix.EXCITATION_ROWS
    assert list(case.measured_matrix.rows[0].values) == [7.000000000123456e-9 / 1e6, -1.01e-9 / 1e6]
    assert case.measured_matrix.rows[1].values[0] == -1.000000000123456e-9 / 1e6
    # Report and console counts have different link conventions. Keep each source intact.
    assert case.refined_panels == 123
    raw = tmp_path / 'runs/cases/plates/numerical-report.json'
    assert (tmp_path / 'runs/collection/runs/cases/plates/numerical-report.json').read_bytes() == raw.read_bytes()
    shutil.move(tmp_path / 'runs', tmp_path / 'relocated')
    with mock.patch('subprocess.Popen', side_effect=AssertionError('collection must never execute')), \
            mock.patch('kpex.calibration.solve._solver_identity',
                       side_effect=AssertionError('collection must not require an installed solver')):
        again = collect_calibration(tmp_path / 'relocated/manifest.json', tmp_path / 'again')
    assert read_message(again.manifest_path, CalibrationCollection()) == data


@pytest.mark.parametrize('failure', ['missing', 'truncated', 'status', 'identity', 'exit', 'timeout'])
def test_report_failure_never_uses_successful_console_matrix(
        preparation: Path, report_solver: Callable, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str):
    from kpex.fastercap.fastercap_error import FasterCapExecutionError, FasterCapTimeoutError
    def run(exe: str, deck: str, log: str, *args: Any, **kwargs: Any) -> FasterCapRunResult:
        result = report_solver(exe, deck, log, *args, **kwargs)
        report = Path(kwargs['report_path'])
        if failure == 'missing':
            report.unlink()
        elif failure in ('truncated', 'timeout'):
            report.write_text('{"schema_version":1,', encoding='utf-8')
        else:
            data = json.loads(report.read_text(encoding='utf-8'))
            if failure == 'identity':
                data['input_file'] = 'another.lst'
            else:
                data['status'] = {'exit_code': 75, 'name': 'FC_CANNOT_CONVERGE'}
            report.write_text(json.dumps(data), encoding='utf-8')
        if failure in ('exit', 'timeout'):
            error = FasterCapTimeoutError if failure == 'timeout' else FasterCapExecutionError
            raise error('solver failed', result=FasterCapRunResult(result.arguments, 75, 0.1))
        return result
    monkeypatch.setattr('kpex.fastercap.fastercap_runner.run_fastercap', run)
    result = solve_calibration(preparation, tmp_path / 'runs')
    assert result.successful_cases == 0 and result.failed_cases == 2
    data = read_message(result.collection_path, CalibrationCollection())
    expected = (CalibrationCaseResult.EXECUTION_FAILED if failure in ('exit', 'timeout')
                else CalibrationCaseResult.INVALID_RESULT)
    assert all(case.status == expected and not case.HasField('native_matrix') for case in data.cases)
    if failure != 'missing':
        assert (tmp_path / 'runs/collection/runs/cases/plates/numerical-report.json').read_bytes() == (
            tmp_path / 'runs/cases/plates/numerical-report.json').read_bytes()


def test_changed_numerical_report_is_rejected(preparation: Path, report_solver: Callable, tmp_path: Path):
    result = solve_calibration(preparation, tmp_path / 'runs')
    (tmp_path / 'runs/cases/plates/numerical-report.json').write_text('{}', encoding='utf-8')
    with pytest.raises(CalibrationError, match='changed'):
        collect_calibration(result.manifest_path, tmp_path / 'collected')
    assert not (tmp_path / 'collected').exists()


@pytest.mark.parametrize('version,accepted', [
    ('6.2.1', False), ('6.3.0', False), ('6.3.99', False), ('6.4.0.dev1', False), ('6.4.0rc1', False),
    ('6.4.0', True), ('6.4.1', True),
])
def test_calibration_requires_corrected_solver(version: str, accepted: bool, monkeypatch: pytest.MonkeyPatch):
    from kpex.calibration.solve import _solver_identity
    from kpex.tool_version_constraints import Tool
    monkeypatch.setattr(Tool, 'detect_version', lambda *_: Tool.FASTERCAP.parse_version(f'FasterCap version {version}'))
    if accepted:
        assert _solver_identity(sys.executable).version == version
    else:
        with pytest.raises(CalibrationError, match='6.4.0'):
            _solver_identity(sys.executable)
