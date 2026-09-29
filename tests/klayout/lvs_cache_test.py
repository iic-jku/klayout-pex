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
import argparse
import filecmp
import os
import shutil
import tempfile
import unittest
from unittest import mock

from klayout_pex.kpex_cli import InputMode, KpexCLI


TESTDATA_DIR = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata'))

# any LVS database will do, as long as it can be told apart from a stale one
CACHED_LVSDB_PATH = os.path.join(TESTDATA_DIR, 'klayout', 'lvs',
                                 'rfnmos_w1u_l0u72_broken_rfmos_model_mapping.lvsdb.gz')
CELL_NAME = 'rfnmos_w1u_l0u72'


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "KLayout")
class KpexCLILVSCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="lvs_cache_")
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

        self.output_dir_path = os.path.join(self.tmp_dir, 'output', f"{CELL_NAME}__{CELL_NAME}")
        os.makedirs(self.output_dir_path)
        self.lvsdb_path = os.path.join(self.output_dir_path, f"{CELL_NAME}.lvsdb.gz")

        self.gds_path = os.path.join(self.tmp_dir, f"{CELL_NAME}.gds")
        with open(self.gds_path, 'wb') as f:
            f.write(b'layout')

        self.args = argparse.Namespace(
            input_mode=InputMode.GDS,
            output_dir_path=self.output_dir_path,
            cache_dir_path=os.path.join(self.tmp_dir, 'output', '.kpex_cache'),
            cache_lvs=True,
            pdk='ihp-sg13g2',
            gds_path=self.gds_path,
            effective_gds_path=self.gds_path,
            effective_schematic_path=os.path.join(self.output_dir_path, f"{CELL_NAME}_dummy_schematic.spice"),
            effective_cell_name=CELL_NAME,
            klayout_exe_path='klayout',
            lvs_script_path='sg13g2.lvs',
            klayout_lvs_verbose=False,
        )

    @property
    def cached_lvsdb_path(self) -> str:
        return os.path.join(self.args.cache_dir_path, self.args.pdk,
                            os.path.splitroot(os.path.abspath(self.gds_path))[-1],
                            f"{CELL_NAME}.lvsdb.gz")

    def make_cache_hit(self):
        os.makedirs(os.path.dirname(self.cached_lvsdb_path))
        shutil.copy(CACHED_LVSDB_PATH, self.cached_lvsdb_path)
        os.utime(self.gds_path, (0, 0))  # the input layout is older than the cached LVS database

    def test_cache_hit_reads_the_cached_lvsdb(self):
        self.make_cache_hit()
        # left over from an earlier run in the same output directory
        with open(self.lvsdb_path, 'w') as f:
            f.write('#%lvsdb-klayout\n')

        with mock.patch('klayout_pex.klayout.lvs_runner.subprocess.Popen') as popen_mock:
            lvsdb = KpexCLI().create_lvsdb(self.args)

        popen_mock.assert_not_called()
        self.assertEqual(CELL_NAME, lvsdb.internal_top_cell().name)
        self.assertTrue(filecmp.cmp(self.cached_lvsdb_path, self.lvsdb_path, shallow=False))

    def test_cache_hit_without_earlier_run_in_the_output_directory(self):
        # e.g. a CI run with a restored cache directory
        self.make_cache_hit()

        with mock.patch('klayout_pex.klayout.lvs_runner.subprocess.Popen') as popen_mock:
            lvsdb = KpexCLI().create_lvsdb(self.args)

        popen_mock.assert_not_called()
        self.assertEqual(CELL_NAME, lvsdb.internal_top_cell().name)
