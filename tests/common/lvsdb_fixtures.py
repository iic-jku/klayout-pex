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
The LVS databases of the test designs (testdata/lvsdb), committed, so that the extraction tests
run without KLayout's LVS, e.g. in the unit test jobs of CI, which have the KLayout Python module only.

Like an entry of the LVS cache, a fixture is rebuilt when the inputs of its PEX-LVS change
(the LVS deck, the layout, the KLayout version, see lvs_cache.fingerprint_differences):
in place where the KLayout executable is available (KPEX_KLAYOUT_EXE), so that the changed fixtures
show up in git status, else a test that uses an outdated fixture fails, naming the changes.

Rebuilds all outdated fixtures (with the KLayout executable):
    poetry run python -m tests.common.lvsdb_fixtures
"""

from __future__ import annotations

from dataclasses import dataclass
import functools
import glob
import importlib.metadata
import os
import shutil
import sys
import tempfile
from typing import *

import klayout.db as kdb

from klayout_pex.env import Env, EnvVar
from klayout_pex.klayout.lvs_cache import (
    LVSInputFingerprint,
    fingerprint_differences,
    lvs_input_fingerprint,
    read_fingerprint,
    write_fingerprint,
)
from klayout_pex.klayout.lvs_runner import LVSRunner
from klayout_pex.pdk_config import PDK
from klayout_pex.tool_version_constraints import Tool

REPO_DIR = os.path.realpath(os.path.join(__file__, '..', '..', '..'))
DESIGNS_DIR = os.path.join(REPO_DIR, 'testdata', 'designs')
FIXTURES_DIR = os.path.join(REPO_DIR, 'testdata', 'lvsdb')

REBUILD_COMMAND = 'poetry run python -m tests.common.lvsdb_fixtures'


@functools.lru_cache(maxsize=None)
def klayout_exe_path() -> Optional[str]:
    """
    The KLayout executable (KPEX_KLAYOUT_EXE, as for kpex), None if there is none (e.g. CI's unit test jobs)
    """
    exe_path = Env.from_os_environ()[EnvVar.KLAYOUT_EXE]
    return exe_path if Tool.KLAYOUT.detect_version(exe_path) is not None else None


@functools.lru_cache(maxsize=None)
def klayout_version() -> str:
    """
    The version of the KLayout executable, as in the fingerprint of kpex, else the one of the KLayout Python module,
    which KPEX requires to be the same
    """
    exe_path = klayout_exe_path()
    if exe_path is not None:
        return str(Tool.KLAYOUT.detect_version(exe_path))
    return importlib.metadata.version('klayout')


@dataclass(frozen=True)
class LVSDBFixture:
    pdk: PDK
    gds_path: str  # within testdata/designs/<pdk>

    @classmethod
    def of_inputs_path(cls, inputs_path: str) -> LVSDBFixture:
        """
        The fixture whose inputs (<design>.lvs_inputs.json) these are
        """
        pdk_dir_name = os.path.relpath(inputs_path, FIXTURES_DIR).split(os.sep)[0]
        stored = read_fingerprint(inputs_path)
        if stored is None:
            raise ValueError(f"Can't read the LVS inputs of {inputs_path}")
        return LVSDBFixture(pdk=PDK.from_string(pdk_dir_name),
                            gds_path=os.path.join(DESIGNS_DIR, pdk_dir_name, stored.layout.path))

    @property
    def relative_gds_path(self) -> str:
        return os.path.relpath(self.gds_path, os.path.join(DESIGNS_DIR, self.pdk))

    @property
    def path_stem(self) -> str:
        relative_path = self.relative_gds_path
        for suffix in ('.gds.gz', '.gds'):
            relative_path = relative_path.removesuffix(suffix)
        return os.path.join(FIXTURES_DIR, self.pdk, relative_path)

    @property
    def lvsdb_path(self) -> str:
        return f"{self.path_stem}.lvsdb.gz"

    @property
    def inputs_path(self) -> str:
        return f"{self.path_stem}.lvs_inputs.json"

    @functools.cached_property
    def cell_name(self) -> str:
        # NOTE: like kpex without --cell, the top cell
        layout = kdb.Layout()
        layout.read(self.gds_path)
        return layout.top_cell().name

    def current_inputs(self, schematic_path: str) -> LVSInputFingerprint:
        """
        The inputs of the PEX-LVS of kpex for the design (see KpexCLI.lvs_input_fingerprint)
        """
        lvs_script_path = self.pdk.config.pex_lvs_script_path
        fingerprint = lvs_input_fingerprint(pdk=str(self.pdk),
                                            klayout_version=klayout_version(),
                                            lvs_script_path=lvs_script_path,
                                            script_parameters=LVSRunner.result_script_parameters(),
                                            gds_path=self.gds_path,
                                            cell_name=self.cell_name,
                                            schematic_path=schematic_path)

        # NOTE: without the paths of this machine, which differ from those of others (and of CI)
        fingerprint.deck.script_path = os.path.relpath(lvs_script_path, REPO_DIR)
        fingerprint.layout.path = self.relative_gds_path
        fingerprint.schematic.path = ''
        return fingerprint

    def outdated_inputs(self) -> List[str]:
        """
        What changed since the fixture was built, empty if it is up to date
        """
        stored = read_fingerprint(self.inputs_path)
        if stored is None or not os.path.isfile(self.lvsdb_path):
            return ["there is no LVS database yet"]
        with tempfile.TemporaryDirectory() as tmp_dir:
            schematic_path = os.path.join(tmp_dir, 'dummy_schematic.spice')
            LVSRunner.write_dummy_schematic(schematic_path, self.cell_name)
            return fingerprint_differences(stored, self.current_inputs(schematic_path))

    def rebuild(self, exe_path: str):
        """
        Runs the PEX-LVS of kpex on the design, and writes its LVS database and inputs
        """
        os.makedirs(os.path.dirname(self.path_stem), exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp_dir:
            schematic_path = os.path.join(tmp_dir, f"{self.cell_name}_dummy_schematic.spice")
            LVSRunner.write_dummy_schematic(schematic_path, self.cell_name)
            lvsdb_path = os.path.join(tmp_dir, f"{self.cell_name}.lvsdb.gz")
            LVSRunner.run_klayout_lvs(exe_path=exe_path,
                                      lvs_script=self.pdk.config.pex_lvs_script_path,
                                      gds_path=self.gds_path,
                                      schematic_path=schematic_path,
                                      log_path=os.path.join(tmp_dir, f"{self.cell_name}_lvs.log"),
                                      lvsdb_path=lvsdb_path,
                                      netlist_path=os.path.join(tmp_dir, f"{self.cell_name}_extracted.cir"),
                                      verbose=False)
            inputs_path = os.path.join(tmp_dir, 'lvs_inputs.json')
            write_fingerprint(inputs_path, self.current_inputs(schematic_path))

            # NOTE: each replaced at once, the inputs last, as parallel test workers may read them meanwhile
            shutil.copy(lvsdb_path, f"{self.lvsdb_path}.tmp")
            os.replace(f"{self.lvsdb_path}.tmp", self.lvsdb_path)
            shutil.copy(inputs_path, f"{self.inputs_path}.tmp")
            os.replace(f"{self.inputs_path}.tmp", self.inputs_path)

    def up_to_date_lvsdb_path(self) -> str:
        """
        The LVS database, rebuilt first if its inputs changed and the KLayout executable is available

        :raises AssertionError: if it is outdated, but there is no KLayout executable to rebuild it
        """
        outdated_inputs = self.outdated_inputs()
        if outdated_inputs:
            exe_path = klayout_exe_path()
            if exe_path is None:
                raise AssertionError(
                    f"The LVS database of {self.pdk}/{self.relative_gds_path} "
                    f"({os.path.relpath(self.lvsdb_path, REPO_DIR)}) is outdated: {'; '.join(outdated_inputs)}. "
                    f"Rebuild it with the KLayout executable (KPEX_KLAYOUT_EXE): run the tests, "
                    f"or {REBUILD_COMMAND}, and commit it"
                )
            self.rebuild(exe_path)
        return self.lvsdb_path


def lvsdb_fixture_path(pdk: str, gds_path: str) -> str:
    """
    The up-to-date LVS database of the design (see LVSDBFixture.up_to_date_lvsdb_path), for kpex --lvsdb
    """
    return LVSDBFixture(pdk=PDK.from_string(pdk), gds_path=gds_path).up_to_date_lvsdb_path()


def committed_fixtures() -> List[LVSDBFixture]:
    return [LVSDBFixture.of_inputs_path(path)
            for path in sorted(glob.glob(os.path.join(FIXTURES_DIR, '**', '*.lvs_inputs.json'), recursive=True))]


def main() -> int:
    exe_path = klayout_exe_path()
    if exe_path is None:
        print(f"No KLayout executable (KPEX_KLAYOUT_EXE) to rebuild the LVS databases with", file=sys.stderr)
        return 1
    for fixture in committed_fixtures():
        outdated_inputs = fixture.outdated_inputs()
        if outdated_inputs:
            print(f"Rebuilding {os.path.relpath(fixture.lvsdb_path, REPO_DIR)}: {'; '.join(outdated_inputs)}")
            fixture.rebuild(exe_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
