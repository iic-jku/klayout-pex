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
from klayout_pex.pdk_config import PDK
from klayout_pex.pex25d.diagnostics import ExitCode
from klayout_pex.tech_info import TechDefError, TechInfo
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2
from tests.common.cli_runner import run_cli
from tests.common.device_model_mappings import NMOS, device_models
from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.pdk_test_config import PDKName, PDKTestConfig


NFET_GDS_PATH = PDKTestConfig(PDKName.SKY130A).gds_path('test_patterns', 'nfet_li1.gds.gz')
NFET_IN_SUBCELL_GDS_PATH = PDKTestConfig(PDKName.SKY130A).gds_path('test_patterns', 'nfet_li1_in_subcell.gds.gz')

SCHEMATIC_WARNING = "--schematic is checked for its device classes, their totals and the pins of its top circuit " \
                    "only, use regular LVS to compare layout against schematic"

PEAK_MEMORY_LINE = re.compile(r"Peak memory \(resident set size\) after (.+): \d+(\.\d)? (B|KiB|MiB|GiB)"
                              r"(, largest subprocess \d+(\.\d)? (B|KiB|MiB|GiB))?")


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
@pytest.mark.parametrize('command, option, value, expected', [
    pytest.param(command, option, value, expected, id=f'{option}={value}')
    for command, option, values, expected in (
        ('extract', '--delaunay-amax', ('-1', 'nan', 'inf'), ">= 0 (in µm²)"),
        ('extract', '--delaunay-b', ('-1', '1.5', 'nan', 'inf'), "from 0 to 1.1"),
        ('pex25d', '--domain-margin', ('-1', 'nan', 'inf'), ">= 0 (in µm)"),
    )
    for value in values
])
def test_triangulation_or_margin_out_of_range_is_a_usage_error(command: str, option: str, value: str, expected: str,
                                                               tmp_path):
    # NOTE: a --delaunay-b of 1.5 kept the triangulation from finishing, a negative --domain-margin
    #       turned the domain inside out, the others were ignored or failed with a traceback (#432)
    code, output = run_cli(KpexCLI().main, ['kpex', command, '--pdk', 'sky130A', f'{option}={value}',
                                            '--lvsdb', lvsdb_fixture_path('sky130A', NFET_GDS_PATH),
                                            '--out-dir', str(tmp_path)])
    assert code == ExitCode.USAGE, output
    assert re.search(rf"argument {option}(/-\w)?: must be a finite number {re.escape(expected)}, got '{value}'",
                     output), output
    assert list(tmp_path.iterdir()) == []  # NOTE: before the run, which writes its logs into --out-dir


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
    # NOTE: --check n, as the ports are the pins $1.D, $1.G and $1.S of the LVS netlist, which flattens SUBNFET
    #       (#417), unlike the pins D, G and S of the schematic, which --check compares them with (#406)
    gds_path = NFET_IN_SUBCELL_GDS_PATH
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', '--mode', 'RC',
                                            '--gds', gds_path,
                                            '--schematic', gds_path.replace('.gds.gz', '.spice'),
                                            '--check', 'n',
                                            '--out-dir', str(tmp_path)])
    assert code == 0, output
    run_dir = tmp_path / 'nfet_li1_in_subcell__nfet_li1_in_subcell'
    with open(run_dir / 'nfet_li1_in_subcell_k25d_pex_netlist.spice', encoding='utf-8') as f:
        netlist = f.read()
    assert 'sky130_fd_pr__nfet_01v8' in netlist and 'SUBNFET' not in netlist, netlist
    with open(run_dir / 'nfet_li1_in_subcell_lvs.log', encoding='utf-8') as f:
        assert "Netlists don't match" not in f.read()


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


def test_schematic_without_value_is_a_check_problem(tmp_path):
    schematic_path = tmp_path / 'chip.spice'
    schematic_path.write_text('.subckt chip a b\nXM1 a b b b nmos w={w0*2}\n.ends chip\n', encoding='utf-8')
    assert schematic_problems(str(schematic_path), ['a', 'b']) == [
        f"kpex can't evaluate the schematic, so no device classes are compared: "
        f"{schematic_path}: the parameter w = w0*2 of XM1: the parameter w0 is not defined"]


def test_schematic_with_diode_of_three_nodes_is_no_check_problem(tmp_path):
    # NOTE: the reader took the third node as the model and the model as the area, which it couldn't evaluate (#368)
    schematic_path = tmp_path / 'chip.spice'
    schematic_path.write_text('.subckt chip a b vss\nDD1 a b vss schottky_nbl1\n.ends chip\n', encoding='utf-8')
    assert schematic_problems(str(schematic_path), ['a', 'b', 'vss']) == []


def test_pins_of_the_schematic_other_than_the_ports_are_check_problems(tmp_path):
    # NOTE: regardless of case, as SPICE reads names (#406)
    schematic_path = tmp_path / 'chip.spice'
    schematic_path.write_text('.subckt chip a b\n.ends chip\n', encoding='utf-8')
    assert schematic_problems(str(schematic_path), ['A', 'c']) == [
        "the schematic has pins without port in the netlist: b",
        "the netlist has ports without pin in the schematic: c"]


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
