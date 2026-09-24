#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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
from __future__ import annotations

import allure
import argparse
import io
import os
import tempfile
import unittest
from typing import List
from unittest import mock

from klayout_pex.kpex_cli import InputMode, KpexCLI
from klayout_pex.klayout.lvs_runner import LVSError, LVSRunner


# What KLayout 0.30 prints when an %include of an LVS script can't be resolved
# (see https://github.com/iic-jku/klayout-pex/issues/210)
KLAYOUT_INCLUDE_ERROR_OUTPUT = """\
ERROR: In /pdk/sg13cmos5l.lvs: Unable to open file: /pdk/rule_decks//sram_integration.lvs (errno=2) in MacroInterpreter::include_expansion
ERROR: RuntimeError: Unable to open file: /pdk/rule_decks//sram_integration.lvs (errno=2) in MacroInterpreter::include_expansion in Executable::execute
  :/built-in-macros/lvs_interpreters.lym:27:in 'RBA::MacroInterpreter#include_expansion'
  :/built-in-macros/lvs_interpreters.lym:27:in 'LVS::LVSExecutable#execute'
"""


class FakeKLayoutProcess:
    """
    Stands in for subprocess.Popen, emulating a KLayout LVS run
    """
    def __init__(self, output: str, returncode: int, writes_report: bool):
        self.output = output
        self.returncode = returncode
        self.writes_report = writes_report

    def __call__(self, args: List[str], **kwargs):
        if self.writes_report:
            report_path = next(a.removeprefix('report=') for a in args if a.startswith('report='))
            with open(report_path, 'w') as f:
                f.write('#%lvsdb-klayout\n')
        proc = mock.Mock()
        proc.stdout = io.StringIO(self.output)
        proc.returncode = self.returncode
        return proc


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "KLayout")
class LVSRunnerFailureTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="lvs_run_")
        self.log_path = os.path.join(self.tmp_dir, "cell_lvs.log")
        self.lvsdb_path = os.path.join(self.tmp_dir, "cell.lvsdb.gz")

    def run_lvs(self, fake_klayout: FakeKLayoutProcess):
        with mock.patch('klayout_pex.klayout.lvs_runner.subprocess.Popen', fake_klayout):
            LVSRunner.run_klayout_lvs(exe_path="klayout",
                                      lvs_script="sg13cmos5l.lvs",
                                      gds_path="cell.gds",
                                      schematic_path="cell.spice",
                                      log_path=self.log_path,
                                      lvsdb_path=self.lvsdb_path,
                                      verbose=False)

    def test_missing_lvsdb_raises_with_klayout_errors_and_log_path(self):
        with self.assertRaises(LVSError) as ctx:
            self.run_lvs(FakeKLayoutProcess(output=KLAYOUT_INCLUDE_ERROR_OUTPUT,
                                            returncode=1,
                                            writes_report=False))
        msg = str(ctx.exception)
        self.assertIn('status code 1', msg)
        self.assertIn('ERROR: In /pdk/sg13cmos5l.lvs: Unable to open file: '
                      '/pdk/rule_decks//sram_integration.lvs', msg)
        self.assertIn(self.log_path, msg)
        with open(self.log_path) as f:
            self.assertEqual(KLAYOUT_INCLUDE_ERROR_OUTPUT, f.read())

    def test_missing_lvsdb_raises_even_on_status_code_zero(self):
        with self.assertRaises(LVSError) as ctx:
            self.run_lvs(FakeKLayoutProcess(output="", returncode=0, writes_report=False))
        self.assertIn(self.log_path, str(ctx.exception))

    def test_stale_lvsdb_from_earlier_run_is_not_mistaken_for_result(self):
        with open(self.lvsdb_path, 'w') as f:
            f.write('stale')
        with self.assertRaises(LVSError):
            self.run_lvs(FakeKLayoutProcess(output=KLAYOUT_INCLUDE_ERROR_OUTPUT,
                                            returncode=1,
                                            writes_report=False))
        self.assertFalse(os.path.exists(self.lvsdb_path))

    def test_netlist_mismatch_is_no_error(self):
        # e.g. the sky130 LVS script exits with 1 on a netlist mismatch
        with mock.patch('klayout_pex.klayout.lvs_runner.warning') as warning_mock, \
             mock.patch('klayout_pex.klayout.lvs_runner.error') as error_mock:
            self.run_lvs(FakeKLayoutProcess(output="ERROR : Netlists don't match\n",
                                            returncode=1,
                                            writes_report=True))
        self.assertTrue(os.path.isfile(self.lvsdb_path))
        warning_mock.assert_not_called()
        error_mock.assert_not_called()

    def test_cli_exits_with_error_instead_of_failing_to_cache_missing_lvsdb(self):
        args = argparse.Namespace(
            input_mode=InputMode.GDS,
            output_dir_path=self.tmp_dir,
            cache_dir_path=os.path.join(self.tmp_dir, '.kpex_cache'),
            cache_lvs=True,
            pdk='ihp-sg13cmos5l',
            gds_path=os.path.join(self.tmp_dir, 'cell.gds'),
            effective_gds_path=os.path.join(self.tmp_dir, 'cell.gds'),
            effective_schematic_path=os.path.join(self.tmp_dir, 'cell.spice'),
            effective_cell_name='cell',
            klayout_exe_path='klayout',
            lvs_script_path='sg13cmos5l.lvs',
            klayout_lvs_verbose=False,
        )
        fake_klayout = FakeKLayoutProcess(output=KLAYOUT_INCLUDE_ERROR_OUTPUT,
                                          returncode=1,
                                          writes_report=False)
        with mock.patch('klayout_pex.klayout.lvs_runner.subprocess.Popen', fake_klayout), \
             mock.patch('klayout_pex.kpex_cli.error') as error_mock:
            with self.assertRaises(SystemExit) as ctx:
                KpexCLI().create_lvsdb(args)
        self.assertEqual(1, ctx.exception.code)
        error_mock.assert_called_once()
        self.assertIn('cell_lvs.log', error_mock.call_args.args[0])


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "KLayout")
@unittest.skip   # NOTE: this is relatively long running!
class Test(unittest.TestCase):
    @property
    def testdata_dir(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata', 'klayout', 'lvs'))

    def test_run_klayout_lvs(self):
        gds_path = os.path.join(self.testdata_dir, 'nmos_diode2', 'nmos_diode2.gds.gz')
        schematic_path = os.path.join(self.testdata_dir, 'nmos_diode2', 'nmos_diode2.spice')

        tmp_dir = tempfile.mkdtemp(prefix="lvs_run_")
        log_path = os.path.join(tmp_dir, "out.log")
        lvsdb_path = os.path.join(tmp_dir, "out.lvsdb.gz")

        # TODO!
        # lvs_script = os.path.join(os.environ['PDKPATH'], 'libs.tech', 'klayout', 'lvs', 'sky130.lvs')
        lvs_script = os.path.join(os.environ['HOME'], '.klayout', 'salt', 'sky130A_el',
                                  'lvs', 'core', 'sky130.lvs')

        runner = LVSRunner()
        runner.run_klayout_lvs(exe_path="klayout",
                               lvs_script=lvs_script,
                               gds_path=gds_path,
                               schematic_path=schematic_path,
                               log_path=log_path,
                               lvsdb_path=lvsdb_path,
                               verbose=False)
        print(f"LVS log file: {log_path}")
        print(f"LVSDB file: {lvsdb_path}")
