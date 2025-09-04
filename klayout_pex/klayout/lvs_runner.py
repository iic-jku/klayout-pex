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

import os
import subprocess
import time

from ..log import (
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
                        lvsdb_path: str,
                        verbose: bool):
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
            '-rd', f"verbose={'true' if verbose else 'false'}",
            '-rd', 'schematic_simplify=false',
            '-rd', 'net_only=false',
            '-rd', 'top_lvl_pins=true',
            '-rd', 'combine=false',
            '-rd', 'combine_devices=false', # IHP
            '-rd', 'purge=false',
            '-rd', 'purge_nets=false',
            '-rd', 'no_simplify=true', # IHP
        ]
        rule('Calling KLayout LVS script')
        subproc(' '.join(args))
        subproc(log_path)
        start = time.time()

        proc = subprocess.Popen(args,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                universal_newlines=True,
                                text=True)
        with open(log_path, 'w', encoding='utf-8') as f:
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
