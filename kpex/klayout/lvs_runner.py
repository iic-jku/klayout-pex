from __future__ import annotations

import os
import subprocess
import time

from kpex.log import (
    debug,
    info,
    warning,
    error,
    subproc,
    rule
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
            '-rd', 'top_lvl_pins=true',
            '-rd', 'combine=false',
            '-rd', 'combine_devices=false', # IHP
            '-rd', 'purge=false',
            '-rd', 'purge_nets=false',
            '-rd', 'no_simplify=true', # IHP
        ]
        info(f"Calling {' '.join(args)}, output file: {log_path}")
        rule()
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
                subproc(line[:-1])  # remove newline
                f.writelines([line])
        proc.wait()

        duration = time.time() - start

        rule()

        if proc.returncode == 0:
            info(f"klayout LVS succeeded after {'%.4g' % duration}s")
        else:
            warning(f"klayout LVS failed with status code {proc.returncode} after {'%.4g' % duration}s, "
                    f"see log file: {log_path}")
