from __future__ import annotations

import allure
import os
import tempfile
import unittest

from kpex.klayout.lvs_runner import LVSRunner


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
                               lvsdb_path=lvsdb_path)
        print(f"LVS log file: {log_path}")
        print(f"LVSDB file: {lvsdb_path}")
