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

from klayout_pex.env import Env
from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.netlist.netlist_format import NetlistFormat
from tests.common.cli_runner import run_cli


def run_kpex(*arguments: str) -> Tuple[int, str]:
    return run_cli(KpexCLI().main, ['kpex', *arguments])


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "VACASK", "CLI")
class KpexNetlistFormatTest(unittest.TestCase):
    def test_netlist_format_defaults_to_spice(self):
        args = KpexCLI.parse_args(['extract', '--pdk', 'ihp-sg13g2', '--gds', 'x.gds', '--2.5D'],
                                  env=Env.from_os_environ())
        self.assertEqual(NetlistFormat.SPICE, args.netlist_format)

    def test_netlist_format_is_validated(self):
        code, output = run_kpex('extract', '--pdk', 'ihp-sg13g2', '--gds', 'x.gds', '--2.5D',
                                '--netlist-format', 'spectre')
        self.assertEqual(2, code)
        self.assertIn("invalid choice: 'spectre'", output)
        self.assertIn('vacask', output)

    def test_vacask_netlists_are_written_by_the_2_5d_engine_only(self):
        # NOTE: an error before the layout is read (here: there is none)
        with tempfile.TemporaryDirectory() as out_dir:
            code, output = run_kpex('extract', '--pdk', 'ihp-sg13g2', '--gds', os.path.join(out_dir, 'x.gds'),
                                    '--2.5D', '--fastercap', '--magic', '--netlist-format', 'vacask',
                                    '--out-dir', out_dir)
        self.assertEqual(1, code)
        self.assertIn('Only the 2.5D engine writes vacask netlists (--netlist-format vacask), '
                      'not MAGIC, FasterCap', output)

    def test_deprecated_out_spice_writes_spice_only(self):
        # NOTE: errors before the layout is read (here: there is none)
        with tempfile.TemporaryDirectory() as out_dir:
            arguments = ['extract', '--pdk', 'ihp-sg13g2', '--gds', os.path.join(out_dir, 'x.gds'), '--2.5D',
                         '--out-dir', out_dir]
            code, output = run_kpex(*arguments, '--netlist-format', 'vacask', '--out_spice', 'x.inc')
            self.assertEqual(1, code)
            self.assertIn('--out_spice writes a SPICE netlist, not --netlist-format vacask, use --out-netlist',
                          output)
            code, output = run_kpex(*arguments, '--out_spice', 'x.spice', '--out-netlist', 'y.spice')
            self.assertEqual(1, code)
            self.assertIn('--out_spice is the deprecated name of --out-netlist, give --out-netlist only', output)

    def test_deprecated_out_spice_is_hidden(self):
        code, output = run_kpex('extract', '--help')
        self.assertEqual(0, code)
        self.assertIn('--out-netlist', output)
        self.assertNotIn('--out_spice', output)
