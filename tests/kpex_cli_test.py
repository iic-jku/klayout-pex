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

import os
from typing import *

import allure
import pytest

import klayout.db as kdb

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.pex25d.diagnostics import ExitCode
from tests.common.cli_runner import run_cli
from tests.common.device_model_mappings import NMOS, device_models
from tests.common.pdk_test_config import PDKName, PDKTestConfig


NFET_GDS_PATH = PDKTestConfig(PDKName.SKY130A).gds_path('test_patterns', 'nfet_li1.gds.gz')


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
        with open(tmp_path / 'first' / log_dir / log_name) as f:
            log = f.read()
        assert log.count('GDS input file passed, running in LVS mode') == 1, log


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
    schematic_path.write_text('.subckt nfet_li1 D G S\n.ends\n')
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D',
                                            '--gds', NFET_GDS_PATH, '--schematic', str(schematic_path),
                                            '--out-dir', str(tmp_path)])
    assert code == 1, output  # NOTE: no KLayout
    assert "--schematic is checked for its device classes only, " \
           "use regular LVS to compare layout against schematic" in output
    assert os.path.isfile(tmp_path / 'nfet_li1__nfet_li1' / 'nfet_li1_dummy_schematic.spice')


@allure.parent_suite("kpex/2.5D Extraction Tests [PEX-LVS]")
@allure.tag("PEX", "2.5D", "LVS")
@pytest.mark.slow
def test_pex_lvs_flattens_the_cells_a_schematic_has_as_subcircuits(tmp_path):
    # NOTE: the alignment with a schematic kept the cells it has as subcircuits, and the RC netlist
    #       called SUBNFET without defining it, its nfet cut off from the nets (#330)
    config = PDKTestConfig(PDKName.SKY130A)
    gds_path = config.gds_path('test_patterns', 'nfet_li1_in_subcell.gds.gz')
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', '--mode', 'RC',
                                            '--gds', gds_path,
                                            '--schematic', gds_path.replace('.gds.gz', '.spice'),
                                            '--out-dir', str(tmp_path)])
    assert code == 0, output
    run_dir = tmp_path / 'nfet_li1_in_subcell__nfet_li1_in_subcell'
    with open(run_dir / 'nfet_li1_in_subcell_k25d_pex_netlist.spice') as f:
        netlist = f.read()
    assert 'sky130_fd_pr__nfet_01v8' in netlist and 'SUBNFET' not in netlist, netlist
    with open(run_dir / 'nfet_li1_in_subcell_lvs.log') as f:
        assert "Netlists don't match" not in f.read()


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Schematic")
def test_unreadable_schematic_is_a_check_problem(tmp_path):
    schematic_path = tmp_path / 'chip.spice'
    schematic_path.write_text('.subckt chip a b\n.include models.lib\n.ends chip\n')
    problems = KpexCLI.schematic_device_class_problems(schematic_path=str(schematic_path),
                                                       lvs_netlist=kdb.Netlist(),
                                                       device_models=device_models(NMOS),
                                                       top_cell_name='chip')
    assert problems == [f"kpex can't read the schematic, so no device classes are compared: "
                        f"{schematic_path}: line 2: .include is not supported"]


def test_schematic_without_value_is_a_check_problem(tmp_path):
    schematic_path = tmp_path / 'chip.spice'
    schematic_path.write_text('.subckt chip a b\nXM1 a b b b sg13_lv_nmos w={w0*2}\n.ends chip\n')
    problems = KpexCLI.schematic_device_class_problems(schematic_path=str(schematic_path),
                                                       lvs_netlist=kdb.Netlist(),
                                                       device_models=device_models(NMOS),
                                                       top_cell_name='chip')
    assert problems == [f"kpex can't evaluate the schematic, so no device classes are compared: "
                        f"{schematic_path}: the parameter w = w0*2 of XM1: the parameter w0 is not defined"]


@allure.parent_suite("kpex/2.5D Extraction Tests [PEX-LVS]")
@allure.tag("PEX", "2.5D", "Schematic")
@pytest.mark.slow
def test_device_class_of_the_schematic_missing_in_the_layout_fails_the_rc_run(tmp_path):
    # NOTE: e.g. a device the PEX-LVS doesn't recognize, which the extraction then misses (#345)
    config = PDKTestConfig(PDKName.SKY130A)
    gds_path = config.gds_path('test_patterns', 'nfet_li1_in_subcell.gds.gz')
    with open(gds_path.replace('.gds.gz', '.spice')) as f:
        schematic = f.read()
    schematic_path = tmp_path / 'nfet_li1_in_subcell.spice'
    schematic_path.write_text(schematic.replace('.ends SUBNFET',
                                                'XM2 S G D VNB sky130_fd_pr__pfet_01v8 L=0.15 W=0.65\n.ends SUBNFET'))
    code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'sky130A', '--2.5D', '--mode', 'RC',
                                            '--gds', gds_path, '--schematic', str(schematic_path),
                                            '--out-dir', str(tmp_path)])
    assert code == ExitCode.DIAGNOSTIC_ERRORS, output
    assert "the schematic has devices of class sky130_fd_pr__pfet_01v8 (X1.XM2), the LVS netlist none" in output
