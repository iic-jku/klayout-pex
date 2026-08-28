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

from __future__ import annotations

import allure
import json
import os
import tempfile
from typing import *
import unittest

from klayout_pex.pex25d.diagnostics import ExitCode
from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

from .pex25d_fixtures import MINIMAL, replacing


class Workspace:
    """A directory with the fixture in it, and a way to run the tool on it."""

    def __init__(self, directory: str, text: str = MINIMAL):
        self.directory = directory
        self.input_path = self.path('tiny.pex25d')
        with open(self.input_path, 'w') as f:
            f.write(text)

    def path(self, name: str) -> str:
        return os.path.join(self.directory, name)

    def run(self, *arguments: str) -> ExitCode:
        try:
            Pex25DCLI().main(['pex25d', *arguments])
        except SystemExit as exit:
            return ExitCode(exit.code)
        return ExitCode.OK


@allure.parent_suite("Unit Tests")
@allure.tag("PEX25D", "CLI")
class Pex25DCLITest(unittest.TestCase):
    def workspace(self, text: str = MINIMAL) -> Any:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Workspace(directory.name, text)

    # ------------------------------------------------------------ exit codes

    def test_a_valid_file_exits_zero(self):
        workspace = self.workspace()
        assert workspace.run('validate', workspace.input_path) == ExitCode.OK

    def test_an_invalid_file_exits_one(self):
        workspace = self.workspace(
            replacing('DIELECTRIC_SIMPLE ild WRAPS lint', 'DIELECTRIC_SIMPLE ild WRAPS met1'))
        assert workspace.run('validate', workspace.input_path) \
            == ExitCode.DIAGNOSTIC_ERRORS

    def test_a_bad_command_line_exits_two(self):
        workspace = self.workspace()
        # 'convert' re-encodes; turning a file into a scene is 'resolve'.
        assert workspace.run('convert', workspace.input_path,
                             '-o', workspace.path('out.pex25d.scene.pb')) \
            == ExitCode.USAGE

    def test_an_unconventional_output_name_exits_two(self):
        workspace = self.workspace()
        assert workspace.run('resolve', workspace.input_path,
                             '-o', workspace.path('out.dat')) == ExitCode.USAGE

    def test_werror_turns_a_warning_into_a_failure(self):
        workspace = self.workspace(
            replacing('CONDUCTOR B netb', 'CONDUCTOR B netb\nCONDUCTOR C netc'))
        assert workspace.run('validate', workspace.input_path) == ExitCode.OK
        assert workspace.run('validate', workspace.input_path, '--werror') \
            == ExitCode.DIAGNOSTIC_ERRORS

    # ---------------------------------------------------------------- verbs

    def test_convert_is_idempotent_through_every_encoding(self):
        workspace = self.workspace()
        first = workspace.path('a.pex25d.pb')
        second = workspace.path('b.pex25d.textpb')
        third = workspace.path('c.pex25d')

        assert workspace.run('convert', workspace.input_path, '-o', first) == ExitCode.OK
        assert workspace.run('convert', first, '-o', second) == ExitCode.OK
        assert workspace.run('convert', second, '-o', third) == ExitCode.OK

        with open(first, 'rb') as f:
            once = f.read()
        fourth = workspace.path('d.pex25d.pb')
        assert workspace.run('convert', third, '-o', fourth) == ExitCode.OK
        with open(fourth, 'rb') as f:
            assert f.read() == once

    def test_resolve_writes_a_scene(self):
        workspace = self.workspace()
        output = workspace.path('out.pex25d.scene.textpb')
        assert workspace.run('resolve', workspace.input_path, '-o', output) == ExitCode.OK
        with open(output) as f:
            assert 'wrap_depth' in f.read()

    def test_resolve_refuses_to_write_half_a_scene(self):
        workspace = self.workspace(
            replacing('VIA via1 CONNECTS met1 met2', 'VIA via1 CONNECTS met1 met9'))
        output = workspace.path('out.pex25d.scene.pb')
        assert workspace.run('resolve', workspace.input_path, '-o', output) \
            == ExitCode.DIAGNOSTIC_ERRORS
        assert not os.path.exists(output)

    def test_show_reads_both_kinds(self):
        workspace = self.workspace()
        scene = workspace.path('out.pex25d.scene.pb')
        assert workspace.run('resolve', workspace.input_path, '-o', scene) == ExitCode.OK
        assert workspace.run('show', workspace.input_path) == ExitCode.OK
        assert workspace.run('show', scene) == ExitCode.OK

    # ---------------------------------------------------------- diagnostics

    def test_json_diagnostics_carry_the_codes(self):
        workspace = self.workspace(
            replacing('DIELECTRIC_SIMPLE ild WRAPS lint', 'DIELECTRIC_SIMPLE ild WRAPS met1'))
        report_path = workspace.path('diagnostics.json')
        assert workspace.run('validate', workspace.input_path,
                             '--diagnostics', 'json',
                             '--diagnostics_out', report_path) \
            == ExitCode.DIAGNOSTIC_ERRORS

        with open(report_path) as f:
            rendered = json.load(f)
        codes = [d['code'] for d in rendered['diagnostics']]
        assert 'PEX25D-E0260' in codes
        for diagnostic in rendered['diagnostics']:
            assert diagnostic['severity'].startswith('SEVERITY_')
            assert diagnostic['tier'].startswith('TIER_')
