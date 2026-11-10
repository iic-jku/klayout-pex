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

"""
The kpex command line tool, run more than once in a process (e.g. by tests or by a script)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
from typing import *
from unittest import mock

import allure
import pytest

import klayout.db as kdb
import klayout.rdb as rdb

from klayout_pex.fastercap.fastercap_error import FasterCapError
from klayout_pex.kpex_cli import KpexCLI, halo_default_help, side_halo_by_pdk
from klayout_pex.netlist.spice_reader import SpiceReader
from klayout_pex.pdk_config import PDK
from klayout_pex.pex25d.diagnostics import ExitCode
from klayout_pex.pex25d.reader import read_pex25d_text
from klayout_pex.rcx25.extraction_results import ExtractionResults, ExtractionSummary
from klayout_pex.rcx25.r.r_extractor import RExtractionTechError
from klayout_pex.run_result import RESULT_FILE_NAME
from klayout_pex.tech_info import TechDefError, TechInfo
from klayout_pex.version import __version__
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2
from tests.common.cli_runner import run_cli
from tests.common.device_model_mappings import NMOS, device_models
from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import spice_netlist_ports


NFET_GDS_PATH = PDKTestConfig(PDKName.SKY130A).gds_path('test_patterns', 'nfet_li1.gds.gz')
NFET_IN_SUBCELL_GDS_PATH = PDKTestConfig(PDKName.SKY130A).gds_path('test_patterns', 'nfet_li1_in_subcell.gds.gz')

SCHEMATIC_WARNING = "--schematic supplies matched device names for 2.5D output. --check checks device " \
                    "classes, totals and top pins. Use regular LVS for full verification"

PEAK_MEMORY_LINE = re.compile(r"Peak memory \(resident set size\) after (.+): \d+(\.\d)? (B|KiB|MiB|GiB)"
                              r"(, largest subprocess \d+(\.\d)? (B|KiB|MiB|GiB))?")


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Ports")
@pytest.mark.parametrize('command', ['extract', 'pex25d'])
@pytest.mark.parametrize('policy, message', [
    ('unknown', r"invalid choice: 'unknown' \(choose from '?auto'?, '?top'?\)"),
    ('top', '--port-labels top needs --gds'),
])
def test_port_policy_is_validated_before_loading_inputs(command: str, policy: str, message: str, tmp_path: Path):
    with mock.patch.object(kdb.LayoutVsSchematic, 'read', side_effect=AssertionError('must not load LVSDB')):
        code, output = run_cli(KpexCLI().main, ['kpex', command, '--pdk', 'sky130A',
                                                '--lvsdb', '/nonexistent/layout.lvsdb',
                                                '--port-labels', policy, '--out-dir', str(tmp_path)])
    assert code == ExitCode.USAGE, output
    assert re.search(message, ' '.join(output.split())), output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "PEX25D", "Ports")
@pytest.mark.parametrize('pattern, policy, pin_names', [
    ('internal_child_labels', 'auto', ['pin:outer']),
    ('label_only_in_child_cell', 'auto', ['pin:inner']),
    ('label_only_in_child_cell', 'top', []),
])
def test_pex25d_terminals_follow_the_port_label_policy(pattern: str, policy: str, pin_names: List[str], tmp_path: Path):
    gds = PDKTestConfig(PDKName.IHP_SG13G2).gds_path('test_patterns', f'{pattern}.gds.gz')
    path = tmp_path / 'ports.pex25d'
    code, output = run_cli(KpexCLI().main, ['kpex', 'pex25d', '--pdk', 'ihp-sg13g2',
                                            '--lvsdb', lvsdb_fixture_path('ihp-sg13g2', gds), '--gds', gds,
                                            '--port-labels', policy, '--out-file', str(path),
                                            '--out-dir', str(tmp_path)])
    assert code == 0, output
    scene = read_pex25d_text(path.read_bytes(), str(path))
    assert sorted(terminal.name for terminal in scene.terminals if terminal.name.startswith('pin:')) == pin_names


def logged_peak_memory_stages(output: str) -> List[str]:
    """
    :return: the stages that the output of run_cli logs the peak memory after
    """
    return [match.group(1) for match in map(PEAK_MEMORY_LINE.fullmatch, output.splitlines()) if match]


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Logging")
@pytest.mark.parametrize('gds_path, log_dir', [
    (None, ''),  # NOTE: an error before the run directory is known, the logs stay in --out-dir
    (NFET_GDS_PATH, 'nfet_li1__nfet_li1'),  # NOTE: an error after, the logs move to the run directory
], ids=['missing layout', 'missing KLayout'])
def test_log_files_hold_their_own_run_only(gds_path: Optional[str], log_dir: str,
                                           tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('KPEX_KLAYOUT_EXE', str(tmp_path / 'no_klayout'))
    for run in ('first', 'second'):
        out_dir = str(tmp_path / run)
        code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D',
                                                '--gds', gds_path or os.path.join(out_dir, 'missing.gds'),
                                                '--out-dir', out_dir])
        assert code == 1, output
    for log_name in ('kpex.log', 'kpex_plain.log'):
        with open(tmp_path / 'first' / log_dir / log_name, encoding='utf-8') as f:
            log = f.read()
        assert log.count('GDS input file passed, running in LVS mode') == 1, log


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Logging")
def test_written_netlist_csv_is_logged_as_written(tmp_path):
    # NOTE: read as UTF-8, which it is written in, and so are the log files,
    #       also where the platform's encoding differs (cp1252 on Windows, which has no Ω)
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D',
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--out-dir', str(tmp_path)])
    assert code == 0, output
    header = 'Device;Net1;Net2;Capacitance [fF];Resistance [Ω]'
    assert header in output.splitlines(), output
    for log_name in ('kpex.log', 'kpex_plain.log'):
        with open(tmp_path / 'nfet_li1__nfet_li1' / log_name, encoding='utf-8') as f:
            log_lines = f.read().splitlines()
        assert any(line.endswith(header) for line in log_lines), log_lines


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "PEX", "2.5D")
@pytest.mark.parametrize('mode', ['CC', 'R', 'RC'])
def test_extraction_summary_is_computed_once_for_all_netlist_outputs(mode: str, tmp_path: Path):
    summarize = ExtractionResults.summarize
    summaries: List[ExtractionSummary] = []

    def record_summary(results: ExtractionResults) -> ExtractionSummary:
        summary = summarize(results)
        summaries.append(summary)
        return summary

    cli = KpexCLI()
    with mock.patch.object(ExtractionResults, 'summarize', autospec=True, side_effect=record_summary) as summarize_mock:
        code, output = run_cli(cli.main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', '--mode', mode,
                                         '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                         '--out-dir', str(tmp_path)])
    assert code == 0, output
    assert summarize_mock.call_count == 1
    # NOTE: CSV writing, expansion and checks leave the shared summary's values unchanged, bit for bit
    assert summaries[0] == cli.rcx25_extraction_results.summarize()


@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
def test_run_without_subcommand_is_an_extraction_with_a_warning(tmp_path):
    # NOTE: the former command line, deprecated, which no other test uses
    code, output = run_cli(KpexCLI().main, ['kpex', '--pdk', 'sky130A', '--2.5D',
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--out-dir', str(tmp_path)])
    assert code == 0, output
    assert "Calling kpex without a subcommand is deprecated; treating this run as 'kpex extract …'" in output
    assert os.path.isfile(tmp_path / 'nfet_li1__nfet_li1' / 'nfet_li1_k25d_pex_netlist.spice'), output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Logging")
def test_log_names_the_peak_memory_after_each_stage(tmp_path):
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', '--mode', 'RC',
                                            '--reduce', 'floating',
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--out-dir', str(tmp_path)])
    assert code == 0, output
    assert logged_peak_memory_stages(output) == ['preparing the LVSDB', 'the resistance extraction',
                                                 'the capacitance extraction', 'the netlist', 'the netlist reduction',
                                                 'the run'], output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Logging")
def test_log_names_the_peak_memory_of_a_failed_run(tmp_path):
    # NOTE: e.g. to size the next run
    failure = FasterCapError("FasterCap failed with exit code 75 (GMRES didn't converge) after 1s, see log file: x")
    with mock.patch.object(KpexCLI, 'run_extraction', side_effect=failure):
        code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D',
                                                '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                                '--out-dir', str(tmp_path)])
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert logged_peak_memory_stages(output) == ['the run'], output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
def test_help_names_the_default_halo_of_the_tech_infos():
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--help'])
    assert code == 0, output
    assert "(default is the tech info's, 8 µm in all PDKs)" in ' '.join(output.split()), output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
@pytest.mark.parametrize('halo_by_pdk, default_help', [
    ({'gf180mcuD': 8.0, 'sky130A': 8.0}, "the tech info's, 8 µm in all PDKs"),
    ({'sky130A': 10.0, 'gf180mcuD': 8.0}, "the tech info's, 8 µm in gf180mcuD, 10 µm in sky130A"),
    ({}, "the tech info's"),
], ids=['same halo', 'different halos', 'no tech info'])
def test_halo_default_help_names_the_halo_of_each_pdk(halo_by_pdk: Dict[str, float], default_help: str):
    assert halo_default_help(halo_by_pdk) == default_help


@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
@pytest.mark.parametrize('failure', [FileNotFoundError('missing'), TechDefError('broken')], ids=['missing', 'broken'])
def test_pdk_without_readable_tech_info_is_left_out_of_the_halo_help(failure: Exception):
    # NOTE: its runs fail with an error (validate_args), the help and the runs of the other PDKs don't
    parse_tech_def = TechInfo.parse_tech_def

    def parse_but_sky130A(jsonpb_path: str) -> tech_pb2.Technology:
        if jsonpb_path == PDK.SKY130A.config.tech_pb_json_path:
            raise failure
        return parse_tech_def(jsonpb_path)

    side_halo_by_pdk.cache_clear()
    try:
        with mock.patch.object(TechInfo, 'parse_tech_def', side_effect=parse_but_sky130A):
            assert sorted(side_halo_by_pdk()) == sorted(set(PDK) - {PDK.SKY130A})
    finally:
        side_halo_by_pdk.cache_clear()


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Logging")
@pytest.mark.parametrize('halo_args, logged_halo', [
    ([], "Sidewall halo: 8 µm (tech info of sky130A)"),
    (['--halo', '2.5'], "Sidewall halo: 2.5 µm (--halo)"),
], ids=['tech info', 'custom'])
def test_log_names_the_halo_of_the_run(halo_args: List[str], logged_halo: str, tmp_path):
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', *halo_args,
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--out-dir', str(tmp_path)])
    assert code == 0, output
    assert logged_halo in output.splitlines(), output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
@pytest.mark.parametrize('halo', ['0', '-1', 'nan', 'inf'])
def test_halo_that_is_not_positive_is_a_usage_error(halo: str, tmp_path):
    # NOTE: 0 failed the extraction with a ZeroDivisionError, -1 left out all capacitances (#419)
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', f'--halo={halo}',
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--out-dir', str(tmp_path)])
    assert code == ExitCode.USAGE, output
    assert f"argument --halo: must be a finite number > 0 (in µm), got '{halo}'" in output
    assert list(tmp_path.iterdir()) == []  # NOTE: before the run, which writes its logs into --out-dir


@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
@pytest.mark.parametrize('command_args', [['extract', '--2.5D'], ['pex25d', '--out-file', 'x.pex25d']],
                         ids=['extract', 'pex25d'])
@pytest.mark.parametrize('pattern, reason', [
    ('all,none', "Multiple choice pattern can't have both subpatterns all and none"),
    ('al', "Multiple choice pattern can only have the subpatterns all, none, +name and -name, not 'al'"),
], ids=['all and none', 'typo'])
def test_invalid_dielectric_filter_is_a_usage_error(command_args: List[str], pattern: str, reason: str, tmp_path,
                                                    monkeypatch: pytest.MonkeyPatch):
    # NOTE: the message of the pattern only showed in a traceback, after the input was read (#431),
    #       a typo was ignored (#451)
    monkeypatch.chdir(tmp_path)  # NOTE: where a run that isn't stopped would write x.pex25d
    code, output = run_cli(KpexCLI().main, ['kpex', *command_args, '--pdk', 'sky130A', '--diel', pattern,
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--out-dir', str(tmp_path)])
    assert code == ExitCode.USAGE, output
    assert (f"argument --diel: {reason}, got '{pattern}': "
            "give all, optionally with -name subpatterns to exclude, or none, optionally with +name subpatterns "
            "to include, e.g. 'all,-name1,-name2' or 'none,+name1', or the subpatterns alone, "
            "e.g. '-name1,-name2'") in output
    assert 'Traceback' not in output
    assert list(tmp_path.iterdir()) == []  # NOTE: before the run, which writes its logs into --out-dir


@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
def test_dielectric_filter_naming_no_dielectric_is_reported_before_the_input_is_read(tmp_path, caplog):
    # NOTE: such names were ignored, the field oxide is never left out (#451)
    lvsdb_path = tmp_path / 'missing.lvsdb.gz'
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D',
                                            '--diel', 'all,-fox,-nild7', '--lvsdb', str(lvsdb_path),
                                            '--out-dir', str(tmp_path)])
    assert code == 1, output
    errors = [message for _, level, message in caplog.record_tuples if level == logging.ERROR]
    assert len(errors) == 2 and errors[1] == f"Can't read KLayout LVSDB file at path {lvsdb_path}", errors
    assert errors[0].startswith("--diel all,-fox,-nild7: the tech info of sky130A has no dielectric to filter "
                                "named fox, nild7, only: iox, spnit, psg, lint, nild2, "), errors


@allure.parent_suite("Unit Tests")
@allure.tag("CLI")
@pytest.mark.parametrize('command, option, value, expected', [
    pytest.param(command, option, value, expected, id=f'{option}={value}')
    for command, option, values, expected in (
        ('extract', '--delaunay-amax', ('-1', 'nan', 'inf'), ">= 0 (in µm²)"),
        ('extract', '--delaunay-b', ('-1', '1.5', 'nan', 'inf'), "from 0 to 1.1"),
        ('extract', '--k-void', ('0.5', '0', '-1', 'nan', 'inf'), ">= 1"),
        ('extract', '--tolerance', ('0', '1', '-1', 'nan', 'inf'), "> 0 and < 1"),
        ('extract', '--d-coeff', ('0', '-1', 'nan', 'inf'), "> 0"),
        ('extract', '--ooc', ('-1', 'nan', 'inf'), ">= 0"),
        ('pex25d', '--domain-margin', ('-1', 'nan', 'inf'), ">= 0 (in µm)"),
    )
    for value in values
])
def test_number_out_of_range_is_a_usage_error(command: str, option: str, value: str, expected: str, tmp_path):
    # NOTE: a --delaunay-b of 1.5 kept the triangulation from finishing, a negative --domain-margin
    #       turned the domain inside out, the others were ignored or failed with a traceback (#432);
    #       with a --tolerance of 0 FasterCap didn't finish, the other FasterCap options gave wrong
    #       capacitances or failed FasterCap (#446)
    code, output = run_cli(KpexCLI().main, ['kpex', command, '--pdk', 'sky130A', f'{option}={value}',
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--out-dir', str(tmp_path)])
    assert code == ExitCode.USAGE, output
    assert re.search(rf"argument {option}(/-\w)?: must be a finite number {re.escape(expected)}, got '{value}'",
                     output), output
    assert list(tmp_path.iterdir()) == []  # NOTE: before the run, which writes its logs into --out-dir


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "PEX25D")
@pytest.mark.parametrize('pattern', ['all,-topnit', '-topnit'])
def test_dielectric_filter_leaves_out_the_excluded_dielectrics(pattern: str, tmp_path):
    # NOTE: -topnit left out all dielectrics (#451)
    output_path = tmp_path / 'nfet_li1.pex25d'
    code, output = run_cli(KpexCLI().main, ['kpex', 'pex25d', '--pdk', 'sky130A', f'--diel={pattern}',
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--out-dir', str(tmp_path), '--out-file', str(output_path)])
    assert code == 0, output
    dielectric_names = [d.name for d in read_pex25d_text(output_path.read_bytes(), str(output_path)).dielectrics]
    # NOTE: without --diel, the film topnit wraps topox
    assert 'topox' in dielectric_names and 'topnit' not in dielectric_names, dielectric_names


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "FasterCap")
def test_mesh_is_deprecated_as_it_has_no_effect(tmp_path):
    # NOTE: FasterCap's automatic refinement (-a, which kpex always passes) overrides -m (#452)
    advice = "it has no effect, as FasterCap's automatic refinement (--tolerance) overrides it"
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--help'])
    assert code == 0, output
    assert f"FasterCap -m mesh relative refinement value, deprecated: {advice}" in ' '.join(output.split()), output

    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', '--mesh', '0.1',
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--out-dir', str(tmp_path)])
    assert code == 0, output
    assert f"--mesh is deprecated, {advice}" in output.splitlines(), output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Windows")
def test_klayout_writes_no_gzip_files(tmp_path):
    # NOTE: on Windows, KLayout leaks a C runtime stream with each gzip file it writes, of which a process has 512,
    #       so that the extractions after the first 250 or so failed (#361)
    written_paths: List[str] = []

    def recording(write: Callable[..., object]) -> Callable[..., object]:
        def record(self, path: str, *args) -> object:
            written_paths.append(path)
            return write(self, path, *args)
        return record

    with mock.patch.object(kdb.Layout, 'write', recording(kdb.Layout.write)), \
         mock.patch.object(rdb.ReportDatabase, 'save', recording(rdb.ReportDatabase.save)):
        code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D',
                                                '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                                '--out-dir', str(tmp_path)])
    assert code == 0, output
    assert [p for p in written_paths if p.endswith('.gz')] == []
    # NOTE: compressed by Python instead
    assert sorted(p.name for p in (tmp_path / 'nfet_li1__nfet_li1').glob('*.gz')) == \
           ['nfet_li1_k25d_pex_report.rdb.gz', 'nfet_li1_nonempty_LVS_layers.gds.gz',
            'nfet_li1_unnamed_LVS_layers.gds.gz']


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "FasterCap")
def test_fastercap_failure_is_an_error_not_a_traceback(tmp_path):
    failure = FasterCapError("FasterCap failed with exit code 75 (GMRES didn't converge) after 1s, see log file: x")
    with mock.patch.object(KpexCLI, 'run_extraction', side_effect=failure):
        code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D',
                                                '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                                '--out-dir', str(tmp_path)])
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert str(failure) in output
    assert 'Traceback' not in output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "PEX25D")
def test_pex25d_outputs_are_named_as_their_kind(tmp_path):
    # NOTE: the readers take the kind from the name, binary protobuf doesn't record it (#328)
    code, output = run_cli(KpexCLI().main, ['kpex', 'pex25d', '--pdk', 'sky130A', '--gds', str(tmp_path / 'missing.gds'),
                                            '--out-dir', str(tmp_path),
                                            '--out-file', 'x.pex25d.scene.pb', '--out-scene', 'x.scene.pex25d.pb'])
    assert code == 1, output
    assert ("--out-file x.pex25d.scene.pb is named as a PEX25D scene (.pex25d.scene.pb), which pex25d would read it as; "
            "name a file with one of: .pex25d, .pex25d.pb, .pex25d.textpb") in output
    assert ("--out-scene x.scene.pex25d.pb is named as a PEX25D file (.pex25d.pb), which pex25d would read it as; "
            "name a scene with one of: .pex25d.scene.pb, .pex25d.scene.textpb") in output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "PEX25D", "Schematic")
def test_pex25d_takes_no_schematic(tmp_path):
    # NOTE: it writes no netlist, which a schematic is checked against (#428)
    code, output = run_cli(KpexCLI().main, ['kpex', 'pex25d', '--pdk', 'sky130A',
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--schematic', str(tmp_path / 'nfet_li1.spice'),
                                            '--out-dir', str(tmp_path), '--out-file', str(tmp_path / 'x.pex25d')])
    assert code == ExitCode.USAGE, output
    assert "unrecognized arguments: --schematic" in output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "LVS")
def test_schematic_is_no_input_of_the_pex_lvs(tmp_path, monkeypatch: pytest.MonkeyPatch):
    # NOTE: the PEX-LVS compares the layout with a dummy schematic only (#330)
    monkeypatch.setenv('KPEX_KLAYOUT_EXE', str(tmp_path / 'no_klayout'))
    schematic_path = tmp_path / 'nfet_li1.spice'
    schematic_path.write_text('.subckt nfet_li1 D G S\n.ends\n', encoding='utf-8')
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D',
                                            '--gds', NFET_GDS_PATH, '--schematic', str(schematic_path),
                                            '--out-dir', str(tmp_path)])
    assert code == 1, output  # NOTE: no KLayout
    assert SCHEMATIC_WARNING in output
    assert os.path.isfile(tmp_path / 'nfet_li1__nfet_li1' / 'nfet_li1_dummy_schematic.spice')


@allure.parent_suite("kpex/2.5D Extraction Tests [PEX-LVS]")
@allure.tag("PEX", "2.5D", "LVS")
@pytest.mark.slow
def test_pex_lvs_flattens_the_cells_a_schematic_has_as_subcircuits(tmp_path):
    # NOTE: the alignment with a schematic kept the cells it has as subcircuits, and the RC netlist
    #       called SUBNFET without defining it, its nfet cut off from the nets (#330)
    gds_path = NFET_IN_SUBCELL_GDS_PATH
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', '--mode', 'RC',
                                            '--gds', gds_path,
                                            '--schematic', gds_path.replace('.gds.gz', '.spice'),
                                            '--out-dir', str(tmp_path)])
    assert code == 0, output
    run_dir = tmp_path / 'nfet_li1_in_subcell__nfet_li1_in_subcell'
    with open(run_dir / 'nfet_li1_in_subcell_k25d_pex_netlist.spice', encoding='utf-8') as f:
        netlist = f.read()
    assert 'sky130_fd_pr__nfet_01v8' in netlist and 'SUBNFET' not in netlist, netlist
    with open(run_dir / 'nfet_li1_in_subcell_lvs.log', encoding='utf-8') as f:
        assert "Netlists don't match" not in f.read()


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Schematic", "Pins")
@pytest.mark.parametrize('mode', ['CC', 'R', 'RC'])
def test_ports_of_labels_only_in_a_subcell_are_named_after_them(mode: str, tmp_path):
    # NOTE: the PEX-LVS flattens SUBNFET, whose nets KLayout names after the subcircuit and the labels,
    #       $1.D, $1.G and $1.S, unlike the pins D, G and S of the schematic, which --check compares the ports with
    #       (#417), with a warning, as other tools make ports of the labels of the top cell only
    gds_path = NFET_IN_SUBCELL_GDS_PATH
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', '--mode', mode,
                                            '--lvsdb', lvsdb_fixture_path('sky130A', gds_path),
                                            '--schematic', gds_path.replace('.gds.gz', '.spice'), '--check', 'y',
                                            '--out-dir', str(tmp_path)])
    assert code == 0, output
    netlist_path = tmp_path / 'nfet_li1_in_subcell__nfet_li1_in_subcell' / 'nfet_li1_in_subcell_k25d_pex_netlist.spice'
    with open(netlist_path, encoding='utf-8') as f:
        netlist = f.read()
    assert re.search(r'^\.SUBCKT nfet_li1_in_subcell D G S sky130_gnd$', netlist, re.MULTILINE), netlist
    assert "Ports named after labels in subcells: D, G, S (label them in the top cell to name ports explicitly)" \
           in output


def schematic_problems(schematic_path: str, port_names: Sequence[str]) -> List[str]:
    """
    :return: the problems of the schematic of the cell chip, against a netlist without devices with these ports
    """
    return KpexCLI.schematic_problems(schematic_path=schematic_path, lvs_netlist=kdb.Netlist(),
                                      device_models=device_models(NMOS), top_cell_name='chip', port_names=port_names)


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Schematic")
def test_unreadable_schematic_is_a_check_problem(tmp_path):
    schematic_path = tmp_path / 'chip.spice'
    schematic_path.write_text('.subckt chip a b\n.include models.lib\n.ends chip\n', encoding='utf-8')
    assert schematic_problems(str(schematic_path), ['a', 'b']) == [
        f"kpex can't read the schematic, so neither pins nor device classes are compared: "
        f"{schematic_path}: line 2: .include is not supported"]


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Schematic")
def test_schematic_without_value_is_a_check_problem(tmp_path):
    schematic_path = tmp_path / 'chip.spice'
    schematic_path.write_text('.subckt chip a b\nXM1 a b b b nmos w={w0*2}\n.ends chip\n', encoding='utf-8')
    assert schematic_problems(str(schematic_path), ['a', 'b']) == [
        f"kpex can't evaluate the schematic, so no device classes are compared: "
        f"{schematic_path}: the parameter w = w0*2 of XM1: the parameter w0 is not defined"]


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Schematic")
def test_schematic_with_diode_of_three_nodes_is_no_check_problem(tmp_path):
    # NOTE: the reader took the third node as the model and the model as the area, which it couldn't evaluate (#368)
    schematic_path = tmp_path / 'chip.spice'
    schematic_path.write_text('.subckt chip a b vss\nDD1 a b vss schottky_nbl1\n.ends chip\n', encoding='utf-8')
    assert schematic_problems(str(schematic_path), ['a', 'b', 'vss']) == []


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Schematic")
def test_pins_of_the_schematic_other_than_the_ports_are_check_problems(tmp_path):
    # NOTE: regardless of case, as SPICE reads names (#406)
    schematic_path = tmp_path / 'chip.spice'
    schematic_path.write_text('.subckt chip a b\n.ends chip\n', encoding='utf-8')
    assert schematic_problems(str(schematic_path), ['A', 'c']) == [
        "the schematic has pins without port in the netlist: b",
        "the netlist has ports without pin in the schematic: c"]


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Schematic")
def test_devices_of_models_without_mapping_are_a_warning(tmp_path, caplog):
    # NOTE: e.g. a standard cell, which the schematic calls, but doesn't define
    schematic_path = tmp_path / 'chip.spice'
    schematic_path.write_text('.subckt chip a b\nXinv a b sg13g2_inv_1\n.ends chip\n', encoding='utf-8')
    schematic_problems(str(schematic_path), ['a', 'b'])
    assert ('__kpex__', logging.WARNING,
            "The device class check leaves out the devices of the schematic of models without device model "
            "mapping:\n  - sg13g2_inv_1: Xinv") in caplog.record_tuples


def rc_run_from_lvsdb(gds_path: str, tmp_path: Path, *args: str) -> Tuple[int, str]:
    """
    :return: the exit code and the output (see run_cli) of the RC extraction of the sky130A design
             from its committed LVS database, with these further arguments
    """
    return run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', '--mode', 'RC',
                                    '--lvsdb', lvsdb_fixture_path('sky130A', gds_path), *args,
                                    '--out-dir', str(tmp_path)])


def edited_schematic_path(gds_path: str, tmp_path: Path, old: str, new: str) -> str:
    """
    :return: the path of a copy of the schematic of the design (next to its layout), with old replaced by new
    """
    source_path = gds_path.replace('.gds.gz', '.spice')
    with open(source_path, encoding='utf-8') as f:
        schematic = f.read()
    schematic_path = tmp_path / os.path.basename(source_path)
    schematic_path.write_text(schematic.replace(old, new), encoding='utf-8')
    return str(schematic_path)


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Schematic")
@pytest.mark.parametrize('mode', ['CC', 'RC'])
@pytest.mark.parametrize('hierarchical', [False, True])
def test_schematic_names_reach_the_extracted_netlist(mode: str, hierarchical: bool, tmp_path: Path):
    # The output must retain its RC nodes, geometry and port order when the name
    # changes. Child labels exercise the difference between LVS pins and ports.
    gds_path = NFET_IN_SUBCELL_GDS_PATH if hierarchical else NFET_GDS_PATH
    if hierarchical:
        schematic_path = edited_schematic_path(gds_path, tmp_path, 'XM1', 'Xtail')
        expected_name = 'X1.Xtail'
    else:
        schematic_path = str(tmp_path / 'schematic.spice')
        Path(schematic_path).write_text('.subckt nfet_li1 S G D\n'
                                        'Xtail S G D sky130_gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.65\n'
                                        '.ends\n', encoding='utf-8')
        expected_name = 'Xtail'
    outputs = []
    for with_schematic in (False, True):
        destination = tmp_path / f'extracted_{with_schematic}.spice'
        args = ['--mode', mode, '--out-netlist', str(destination)]
        if with_schematic:
            args += ['--schematic', schematic_path]
        code, output = rc_run_from_lvsdb(gds_path, tmp_path / str(with_schematic), *args)
        assert code == 0, output
        assert 'Schematic device names retained from layout' not in output, output
        outputs.append(SpiceReader().read(str(destination)))
    before, after = outputs
    old_device = next(device for device in before.subcircuits[0].elements if device.kind == 'X')
    new_device = next(device for device in after.subcircuits[0].elements if device.kind == 'X')
    assert new_device.name == expected_name, after
    new_device.name = old_device.name
    assert before == after


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Schematic")
@pytest.mark.parametrize('gds_args', [[], ['--gds', NFET_IN_SUBCELL_GDS_PATH]], ids=['lvsdb', 'lvsdb and gds'])
def test_device_class_of_the_schematic_missing_in_the_layout_fails_the_rc_run(gds_args: List[str], tmp_path):
    # NOTE: e.g. a device the PEX-LVS doesn't recognize, which the extraction then misses (#345),
    #       also from an LVSDB, which has the LVS netlist the checks compare with (#418)
    schematic_path = edited_schematic_path(NFET_IN_SUBCELL_GDS_PATH, tmp_path, '.ends SUBNFET',
                                           'XM2 S G D VNB sky130_fd_pr__pfet_01v8 L=0.15 W=0.65\n.ends SUBNFET')
    code, output = rc_run_from_lvsdb(NFET_IN_SUBCELL_GDS_PATH, tmp_path, *gds_args, '--schematic', schematic_path)
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert SCHEMATIC_WARNING in output
    assert "the schematic has devices of class sky130_fd_pr__pfet_01v8 (X1.XM2), the LVS netlist none" in output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Schematic")
def test_device_totals_of_the_schematic_that_differ_from_the_layout_fail_the_rc_run(tmp_path):
    # NOTE: e.g. a device the PEX-LVS doesn't recognize in a class it recognizes otherwise (#345)
    schematic_path = edited_schematic_path(NFET_IN_SUBCELL_GDS_PATH, tmp_path, 'W=0.65', 'W=0.65 m=2')
    code, output = rc_run_from_lvsdb(NFET_IN_SUBCELL_GDS_PATH, tmp_path, '--schematic', schematic_path)
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert "the schematic has Σ W·L = 0.195 of class sky130_fd_pr__nfet_01v8, the LVS netlist 0.0975" in output
    assert "the schematic has Σ W = 1.3 of class sky130_fd_pr__nfet_01v8, the LVS netlist 0.65" in output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Schematic")
def test_missing_schematic_is_an_error_also_with_lvsdb_input(tmp_path):
    schematic_path = tmp_path / 'missing.spice'
    code, output = rc_run_from_lvsdb(NFET_GDS_PATH, tmp_path, '--schematic', str(schematic_path))
    assert code == 1, output
    assert f"Can't read schematic at path {schematic_path}" in output
    assert SCHEMATIC_WARNING not in output  # NOTE: nothing is checked


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Schematic")
def test_missing_schematic_is_reported_before_the_input_is_read(tmp_path, caplog):
    schematic_path = tmp_path / 'missing.spice'
    lvsdb_path = tmp_path / 'missing.lvsdb.gz'
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D',
                                            '--lvsdb', str(lvsdb_path), '--schematic', str(schematic_path),
                                            '--out-dir', str(tmp_path)])
    assert code == 1, output
    assert [message for _, level, message in caplog.record_tuples if level == logging.ERROR] == [
        f"Can't read schematic at path {schematic_path}",
        f"Can't read KLayout LVSDB file at path {lvsdb_path}"], output


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Schematic")
def test_pins_of_the_schematic_other_than_the_ports_fail_the_rc_run(tmp_path):
    # NOTE: e.g. a label of the layout other than the pin of the schematic, by which a netlist that replaces
    #       the schematic is connected (#406), but not the substrate sky130_gnd, which the schematic leaves global
    schematic_path = tmp_path / 'nfet_li1.spice'
    schematic_path.write_text('.subckt nfet_li1 D G SRC\n'
                              'XM1 SRC G D sky130_gnd sky130_fd_pr__nfet_01v8 L=0.15 W=0.65\n'
                              '.ends nfet_li1\n', encoding='utf-8')
    code, output = rc_run_from_lvsdb(NFET_GDS_PATH, tmp_path, '--schematic', str(schematic_path))
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert "The extracted netlist is inconsistent with the LVS netlist (--check n to accept it):\n" \
           "  - the schematic has pins without port in the netlist: SRC\n" \
           "  - the netlist has ports without pin in the schematic: S" in output


def run_result(run_dir: Path) -> Dict[str, Any]:
    """
    :return: the result file of the run in the run directory (see klayout_pex.run_result)
    """
    with open(run_dir / RESULT_FILE_NAME, encoding='utf-8') as f:
        return json.load(f)


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Result File")
@pytest.mark.parametrize('mode', ['CC', 'RC'])
def test_result_file_names_the_outputs_and_ports_of_the_run(mode: str, tmp_path):
    out_result_path = tmp_path / 'results' / 'nfet_li1.json'
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', '--mode', mode,
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--out-dir', str(tmp_path), '--out-result', str(out_result_path)])
    assert code == 0, output
    run_dir = tmp_path / 'nfet_li1__nfet_li1'
    result = run_result(run_dir)
    for path in (run_dir / RESULT_FILE_NAME, out_result_path):
        assert f"Wrote result file to: {path}" in output.splitlines()
    with open(out_result_path, encoding='utf-8') as f:
        assert json.load(f) == result
    assert {key: result[key] for key in ('format_version', 'kpex_version', 'command', 'pdk', 'cell', 'engines',
                                         'mode', 'inputs', 'run_dir', 'stage', 'exit_code', 'halo_um', 'devices',
                                         'check_problems', 'errors')} == {
        'format_version': 1, 'kpex_version': __version__, 'command': 'extract', 'pdk': 'sky130A', 'cell': 'nfet_li1',
        'engines': ['KPEX/2.5D'], 'mode': mode,
        'inputs': {'gds': None, 'lvsdb': os.path.abspath(lvsdb_fixture_path('sky130A', NFET_GDS_PATH)),
                   'schematic': None},
        'run_dir': str(run_dir), 'stage': 'done', 'exit_code': 0, 'halo_um': 8.0,
        'devices': {'black_boxed': 0, 'white_boxed': 0, 'excluded': 0}, 'check_problems': [], 'errors': []}
    assert result['peak_memory']['process_bytes'] > 0
    assert [(written['kind'], written['engine'], os.path.basename(written['path']))
            for written in result['files']] == [
        ('log', None, 'kpex_plain.log'), ('log', None, 'kpex.log'),
        ('report', 'KPEX/2.5D', 'nfet_li1_k25d_pex_report.rdb.gz'),
        ('netlist_csv', 'KPEX/2.5D', 'nfet_li1_k25d_pex_netlist.csv'),
        ('netlist', 'KPEX/2.5D', 'nfet_li1_k25d_pex_netlist.spice')]
    assert all(os.path.isfile(written['path']) for written in result['files'])
    netlist = result['files'][-1]
    assert (netlist['format'], netlist['reduced']) == ('spice', False)
    assert netlist['ports'] == spice_netlist_ports(netlist['path']) == ['D', 'G', 'S', 'sky130_gnd']


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Result File")
def test_result_file_of_a_failed_run_has_its_stage_and_exit_code(tmp_path):
    # NOTE: and while in the stage, the result file has it without exit code, which a run killed by the OS leaves
    run_dir = tmp_path / 'nfet_li1__nfet_li1'
    results_in_stage: List[Dict[str, Any]] = []
    failure = RExtractionTechError("the tech info has no sheet resistance of li1")

    def fail(**kwargs):
        results_in_stage.append(run_result(run_dir))
        raise failure

    with mock.patch.object(KpexCLI, 'run_kpex_2_5d_engine', side_effect=fail):
        code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D',
                                                '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                                '--out-dir', str(tmp_path)])
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert [(result['stage'], result['exit_code']) for result in results_in_stage] == [('2.5d', None)]
    result = run_result(run_dir)
    assert (result['stage'], result['exit_code'], result['errors']) == ('2.5d', ExitCode.DIAGNOSTIC_ERRORS,
                                                                        [str(failure)])
    assert all(os.path.isfile(written['path']) for written in result['files'])


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Result File")
def test_result_file_of_a_run_with_invalid_arguments_has_their_errors(tmp_path):
    schematic_path = tmp_path / 'missing.spice'
    code, output = rc_run_from_lvsdb(NFET_GDS_PATH, tmp_path, '--schematic', str(schematic_path))
    assert code == 1, output
    result = run_result(tmp_path / 'nfet_li1__nfet_li1')
    assert (result['stage'], result['exit_code'], result['cell']) == ('arguments', 1, 'nfet_li1')
    assert result['errors'] == [f"Can't read schematic at path {schematic_path}"]
    # NOTE: no warning of what --schematic is checked for, as there is none to check (#425)
    assert result['warnings'] == []


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Result File", "Schematic")
def test_result_file_of_a_failed_check_has_its_problems(tmp_path):
    schematic_path = edited_schematic_path(NFET_IN_SUBCELL_GDS_PATH, tmp_path, 'W=0.65', 'W=0.65 m=2')
    code, output = rc_run_from_lvsdb(NFET_IN_SUBCELL_GDS_PATH, tmp_path, '--schematic', schematic_path)
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    result = run_result(tmp_path / 'nfet_li1_in_subcell__nfet_li1_in_subcell')
    assert (result['stage'], result['exit_code']) == ('2.5d', ExitCode.DIAGNOSTIC_ERRORS)
    assert "the schematic has Σ W = 1.3 of class sky130_fd_pr__nfet_01v8, the LVS netlist 0.65" \
           in result['check_problems']
    assert result['errors'] == ["The extracted netlist is inconsistent with the LVS netlist (--check n to accept it):\n" +
                                '\n'.join(f"  - {problem}" for problem in result['check_problems'])]
    assert SCHEMATIC_WARNING in result['warnings']
    # NOTE: written before the check fails the run
    assert 'netlist' in [written['kind'] for written in result['files']]


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Result File")
def test_out_result_that_cannot_be_written_fails_before_the_run(tmp_path):
    (tmp_path / 'file').write_text('', encoding='utf-8')
    out_result_path = tmp_path / 'file' / 'result.json'
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D',
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--out-dir', str(tmp_path / 'out'), '--out-result', str(out_result_path)])
    assert code == ExitCode.USAGE, output
    assert f"Can't write the result file to: {out_result_path}: " in output
    assert not (tmp_path / 'out').exists()  # NOTE: before the run, which writes its logs into --out-dir


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Result File", "PEX25D")
def test_result_file_of_pex25d_names_its_outputs(tmp_path):
    pex25d_path = tmp_path / 'nfet_li1.pex25d'
    code, output = run_cli(KpexCLI().main, ['kpex', 'pex25d', '--pdk', 'sky130A',
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--out-dir', str(tmp_path), '--out-file', str(pex25d_path)])
    assert code == 0, output
    result = run_result(tmp_path / 'nfet_li1__nfet_li1')
    assert (result['command'], result['engines'], result['stage'], result['exit_code']) == ('pex25d', [], 'done', 0)
    assert [(written['kind'], written['path']) for written in result['files'] if written['kind'] != 'log'] == \
           [('pex25d_file', str(pex25d_path))]
