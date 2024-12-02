from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from typing import *
from dataclasses import dataclass
from rich.pretty import pprint

import klayout.db as kdb

from kpex.log import (
    debug,
    info,
    warning,
    error
)


class LVSRunner:
    @staticmethod
    def run_klayout_lvs(exe_path: str,
                        lvs_script: str,
                        gds_path: str,
                        schematic_path: str,
                        log_path: str,
                        lvsdb_path: str):
        args = [
            exe_path,
            '-b',
            '-r', lvs_script,
            '-rd', f"input={os.path.abspath(gds_path)}",
            '-rd', f"report={os.path.abspath(lvsdb_path)}",
            '-rd', f"schematic={os.path.abspath(schematic_path)}",
            '-rd', 'thr=22',
            '-rd', 'run_mode=deep',
            '-rd', 'spice_net_names=true',
            '-rd', 'spice_comments=false',
            '-rd', 'scale=false',
            '-rd', 'verbose=true',
            '-rd', 'schematic_simplify=false',
            '-rd', 'net_only=false',
            '-rd', 'top_lvl_pins=false',
            '-rd', 'combine=false',
            '-rd', 'purge=false',
            '-rd', 'purge_nets=true',
        ]
        info(f"Calling {' '.join(args)}, output file: {log_path}")

        start = time.time()

        proc = subprocess.Popen(args,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                universal_newlines=True,
                                text=True)
        with open(log_path, 'w') as f:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                f.writelines([line])
        proc.wait()

        duration = time.time() - start

        if proc.returncode == 0:
            info(f"klayout LVS succeeded after {'%.4g' % duration}s")
        else:
            warning(f"klayout LVS failed with status code {proc.returncode} after {'%.4g' % duration}s"
                    f"see log file: {log_path}")


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
