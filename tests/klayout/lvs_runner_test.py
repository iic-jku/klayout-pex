#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/martinjankoehler/klayout-pex).
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
import os
import tempfile
import unittest

from klayout_pex.klayout.lvs_runner import LVSRunner


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
