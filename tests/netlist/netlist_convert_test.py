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
import os
import tempfile
from typing import *
import unittest

import allure

from klayout_pex.netlist.netlist_cli import NetlistCLI
from klayout_pex.pex25d.diagnostics import ExitCode
from tests.common.cli_runner import (
    assert_netlist_cli_loads_neither_klayout_nor_protobuf,
    run_cli,
    run_cli_process,
)


# as KPEX writes an extracted netlist: the net A,B,C as A|B|C
EXTRACTED_SPICE = """\
*********************************************************
*** NGSPICE file created by KLayout-PEX 0.6.8
*********************************************************

.SUBCKT divider A C sub!
Cext_1 A sub! 223.458a
Cext_2 A|B|C sub! 459.32a
Rext_1 A A|B|C 426.666666667
Rext_2 A|B|C C 72.5333333333
XQ1 A|B|C C sub! pnpMPA a=2e-12 p=6e-06 m=2
XM1 C A|B|C sub! sub! sg13_lv_nmos w=1e-06 l=1.3e-07 as=0 ad=0 ps=0 pd=0 m=2
.ENDS divider
"""

EXPECTED_VACASK_BODY = """\
load "capacitor.osdi"
load "resistor.osdi"

subckt divider (A C 'sub!')
  model capacitor capacitor
  model resistor resistor
  Cext_1 (A 'sub!') capacitor c=2.23458e-16
  Cext_2 ('A|B|C' 'sub!') capacitor c=4.5932e-16
  Rext_1 (A 'A|B|C') resistor r=426.666666667
  Rext_2 ('A|B|C' C) resistor r=72.5333333333
  XQ1_1 ('A|B|C' C 'sub!') pnpMPA a=2e-12 p=6e-06
  XQ1_2 ('A|B|C' C 'sub!') pnpMPA a=2e-12 p=6e-06
{mos}
ends
"""

MOS_WITH_M = "  XM1 (C 'A|B|C' 'sub!' 'sub!') sg13_lv_nmos w=1e-06 l=1.3e-07 as=0 ad=0 ps=0 pd=0 m=2"
MOS_COPIES = '\n'.join(f"  XM1_{i} (C 'A|B|C' 'sub!' 'sub!') sg13_lv_nmos w=1e-06 l=1.3e-07 as=0 ad=0 ps=0 pd=0"
                       for i in (1, 2))


class Workspace:
    """
    A directory with a SPICE netlist in it, and a way to convert it
    """

    def __init__(self, directory: str, text: str = EXTRACTED_SPICE):
        self.directory = directory
        self.input_path = self.path('divider.spice')
        with open(self.input_path, 'w', encoding='utf-8') as f:
            f.write(text)

    def path(self, name: str) -> str:
        return os.path.join(self.directory, name)

    def run(self, *arguments: str) -> Tuple[int, str]:
        """
        :return: the exit code and the output (see run_cli)
        """
        return run_cli(NetlistCLI().main, ['netlist', *arguments])

    def read(self, name: str) -> str:
        with open(self.path(name), encoding='utf-8') as f:
            return f.read()


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "VACASK", "CLI")
class NetlistConvertTest(unittest.TestCase):
    def workspace(self, text: str = EXTRACTED_SPICE) -> Workspace:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Workspace(directory.name, text)

    @staticmethod
    def body(vacask_text: str) -> str:
        """
        The netlist without the comments of its header
        """
        return vacask_text.split('\n\n', 1)[1]

    def test_extracted_netlist_is_converted_with_m_as_copies(self):
        workspace = self.workspace()
        code, output = workspace.run('convert', '--to', 'vacask', workspace.input_path,
                                     '-o', workspace.path('divider.inc'))
        self.assertEqual(ExitCode.OK, code, output)
        text = workspace.read('divider.inc')
        self.assertTrue(text.startswith('// VACASK netlist converted by KLayout-PEX'), text)
        self.assertEqual(EXPECTED_VACASK_BODY.format(mos=MOS_COPIES), self.body(text))

    def test_pdk_tells_the_subcircuits_that_declare_m(self):
        # NOTE: the IHP MOS declare m in VACASK, the PNP doesn't
        workspace = self.workspace()
        code, output = workspace.run('convert', '--to', 'vacask', '--pdk', 'ihp-sg13g2', workspace.input_path)
        self.assertEqual(ExitCode.OK, code, output)
        self.assertEqual(EXPECTED_VACASK_BODY.format(mos=MOS_WITH_M), self.body(workspace.read('divider.inc')))

    def test_output_defaults_to_the_input_path_with_the_extension_of_the_format(self):
        workspace = self.workspace()
        code, output = workspace.run('convert', '--to', 'vacask', workspace.input_path)
        self.assertEqual(ExitCode.OK, code, output)
        self.assertTrue(os.path.isfile(workspace.path('divider.inc')), output)

    def test_format_is_required_and_validated(self):
        workspace = self.workspace()
        code, output = workspace.run('convert', workspace.input_path)
        self.assertEqual(ExitCode.USAGE, code)
        self.assertIn('the following arguments are required: --to', output)

        code, output = workspace.run('convert', '--to', 'spectre', workspace.input_path)
        self.assertEqual(ExitCode.USAGE, code)
        self.assertIn("invalid choice: 'spectre'", output)
        self.assertIn('vacask', output)

    def test_pdk_is_validated(self):
        workspace = self.workspace()
        code, output = workspace.run('convert', '--to', 'vacask', '--pdk', 'ihp', workspace.input_path)
        self.assertEqual(ExitCode.USAGE, code)
        self.assertIn("invalid choice: 'ihp'", output)
        self.assertIn('ihp-sg13g2', output)

    def test_missing_input_is_a_usage_error(self):
        workspace = self.workspace()
        code, output = workspace.run('convert', '--to', 'vacask', workspace.path('missing.spice'))
        self.assertEqual(ExitCode.USAGE, code)
        self.assertIn("Can't read the input netlist", output)

    def test_output_over_the_input_is_a_usage_error(self):
        workspace = self.workspace()
        code, output = workspace.run('convert', '--to', 'vacask', workspace.input_path, '-o', workspace.input_path)
        self.assertEqual(ExitCode.USAGE, code)
        self.assertIn('The output path is the input path', output)
        self.assertEqual(EXTRACTED_SPICE, workspace.read('divider.spice'))

    def test_unsupported_card_is_an_error_naming_the_line_and_writes_nothing(self):
        workspace = self.workspace('.subckt cell a b\n.include models.lib\n.ends\n')
        code, output = workspace.run('convert', '--to', 'vacask', workspace.input_path)
        self.assertEqual(ExitCode.DIAGNOSTIC_ERRORS, code)
        self.assertIn('line 2: .include is not supported', output)
        self.assertFalse(os.path.exists(workspace.path('divider.inc')))

    def test_expression_is_an_error_and_writes_nothing(self):
        workspace = self.workspace('.subckt cell a b\nR1 a b {r}\n.ends\n')
        code, output = workspace.run('convert', '--to', 'vacask', workspace.input_path)
        self.assertEqual(ExitCode.DIAGNOSTIC_ERRORS, code)
        self.assertIn("The value of the element 'R1' of subcircuit 'cell' is the expression r", output)
        self.assertFalse(os.path.exists(workspace.path('divider.inc')))

    def test_netlist_without_vacask_equivalent_is_an_error_and_writes_nothing(self):
        workspace = self.workspace('.subckt cell a b\nXQ1 a b b pnpMPA m=1.5\n.ends\n')
        code, output = workspace.run('convert', '--to', 'vacask', workspace.input_path)
        self.assertEqual(ExitCode.DIAGNOSTIC_ERRORS, code)
        self.assertIn('m=1.5', output)
        self.assertFalse(os.path.exists(workspace.path('divider.inc')))

    # ------------------------------------------------------------ the installed tool

    def test_netlist_tool_converts_in_a_subprocess(self):
        workspace = self.workspace()
        result = run_cli_process('klayout_pex.netlist', ['convert', '--to', 'vacask',
                                                         workspace.input_path, '-o', workspace.path('out.inc')])
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(EXPECTED_VACASK_BODY.format(mos=MOS_COPIES), self.body(workspace.read('out.inc')))

        result = run_cli_process('klayout_pex.netlist', ['convert', '--to', 'vacask', workspace.path('missing.spice')])
        self.assertEqual(ExitCode.USAGE, result.returncode, result.stdout + result.stderr)

    def test_conversion_needs_neither_klayout_nor_generated_protobuf(self):
        workspace = self.workspace()
        assert_netlist_cli_loads_neither_klayout_nor_protobuf(
            ['netlist', 'convert', '--to', 'vacask', workspace.input_path, '-o', workspace.path('out.inc')])
        self.assertTrue(os.path.isfile(workspace.path('out.inc')))
