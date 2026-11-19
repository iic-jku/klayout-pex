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

"""CLI for bounded solves and offline raw-result collection."""

import argparse
from pathlib import Path
import sys

from ..env import EnvVar
from ..log import error, info
from ..pex25d.diagnostics import ExitCode
from ..util.argparse_helpers import add_log_level_argument
from .validation import CalibrationError


def add_execution_subparsers(commands: argparse._SubParsersAction):
    solve = commands.add_parser('solve', help='Run prepared cases and collect raw FasterCap matrices')
    solve.add_argument('--prepared', required=True, type=Path, metavar='MANIFEST.json')
    solve.add_argument('--solver', choices=['fastercap'], default='fastercap')
    solve.add_argument('--fastercap-exe', default=None, metavar='PATH')
    solve.add_argument('--jobs', type=int, default=1, help='Concurrent processes (1–32); does not bound memory')
    solve.add_argument('--threads', type=int, default=1, help='Child numerical-library thread limit (1–256)')
    solve.add_argument('--timeout-seconds', type=float, default=600)
    solve.add_argument('--fastercap-tolerance', type=float,
                       help='Automatic refinement; couples mesh and solver tolerance (default 0.05)')
    solve.add_argument('--fastercap-mesh-refinement', type=float)
    solve.add_argument('--fastercap-gmres-tolerance', type=float)
    solve.add_argument('--fastercap-d-coeff', type=float, default=0.5)
    solve.add_argument('--delaunay-amax-um2', type=float, default=0)
    solve.add_argument('--delaunay-b', type=float, default=1)
    collect = commands.add_parser('collect', help='Collect saved solver logs without running a solver')
    collect.add_argument('--runs', required=True, type=Path, metavar='MANIFEST.json')
    for parser in (solve, collect):
        parser.add_argument('--out-dir', required=True, type=Path, metavar='PATH',
                            help='New directory under an existing parent; existing paths are refused')
        add_log_level_argument(parser)


def run_execution_command(args: argparse.Namespace):
    from .collect import collect_calibration
    from .solve import SolveOptions, solve_calibration
    import os

    try:
        if args.calibration_command == 'solve':
            options = SolveOptions(jobs=args.jobs, threads=args.threads, timeout_seconds=args.timeout_seconds,
                                   tolerance=args.fastercap_tolerance,
                                   mesh_refinement=args.fastercap_mesh_refinement,
                                   gmres_tolerance=args.fastercap_gmres_tolerance,
                                   d_coeff=args.fastercap_d_coeff,
                                   delaunay_amax_um2=args.delaunay_amax_um2, delaunay_b=args.delaunay_b)
            executable = args.fastercap_exe or os.environ.get(EnvVar.FASTERCAP_EXE,
                                                             EnvVar.FASTERCAP_EXE.default_value)
            result = solve_calibration(args.prepared, args.out_dir, executable=executable, options=options)
            path = result.collection_path
        elif args.calibration_command == 'collect':
            result = collect_calibration(args.runs, args.out_dir)
            path = result.manifest_path
        else:
            raise NotImplementedError(f'Calibration execution command {args.calibration_command!r}')
    except (CalibrationError, OSError) as exc:
        error(str(exc))
        sys.exit(ExitCode.USAGE)
    info(f'Raw collection: {result.successful_cases} collected, {result.failed_cases} failed or incomplete: {path}')
    info('Numerical qualification and coefficient fitting have not run')
    if result.failed_cases:
        sys.exit(ExitCode.DIAGNOSTIC_ERRORS)
