#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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

from rich_argparse import RichHelpFormatter

from ..env import EnvVar
from ..log import error, info
from ..pex25d.diagnostics import ExitCode
from ..util.argparse_helpers import (add_log_level_argument,
                                     non_negative_square_micrometers, positive_number, relative_error)
from .validation import CalibrationError


def add_execution_subparsers(commands: argparse._SubParsersAction):
    solve = commands.add_parser(
        'solve', help='Run prepared cases and collect raw FasterCap matrices',
        description='Export cases, run FasterCap and collect raw matrices automatically. '
                    'A successful run is not a numerical qualification.',
        formatter_class=RichHelpFormatter, allow_abbrev=False)
    solve.add_argument('--manifest', required=True, type=Path, metavar='FILE',
                       help='Input CalibrationManifest from calibrate prepare (protobuf JSON)')
    execution = solve.add_argument_group('Execution controls')
    execution.add_argument('--solver', choices=['fastercap'], default='fastercap',
                           help='Solver backend (default: fastercap)')
    execution.add_argument('--fastercap-exe', default=None, metavar='PATH',
                           help='Executable name or path (default: KPEX_FASTERCAP_EXE, then FasterCap)')
    execution.add_argument('--jobs', type=int, default=1, metavar='N',
                           help='Concurrent solver processes, 1–32 (default: 1); no memory limit is imposed')
    execution.add_argument('--threads-per-job', type=int, default=1, metavar='N',
                           help='OpenMP/numerical-library threads requested per solver process, 1–256 '
                                '(default: 1); support depends on the solver build')
    execution.add_argument('--solver-timeout-seconds', type=positive_number, default=600, metavar='SECONDS',
                           help='Wall-clock deadline per solver process (default: 600); '
                                'excludes queueing and geometry export; timed-out evidence is retained')
    numerical = solve.add_argument_group('FasterCap numerical controls')
    numerical.add_argument('--fastercap-auto-tolerance', type=relative_error, metavar='FRACTION',
                           help='Automatic refinement stopping tolerance, 0 < value < 1 (default: 0.05). '
                                'Cannot be combined with manual mesh/GMRES controls; '
                                'not a guaranteed capacitance error bound')
    numerical.add_argument('--fastercap-mesh-refinement', type=positive_number, metavar='VALUE',
                           help='Manual relative refinement parameter (-m), > 0; requires '
                                '--fastercap-gmres-tolerance and excludes --fastercap-auto-tolerance')
    numerical.add_argument('--fastercap-gmres-tolerance', type=relative_error, metavar='FRACTION',
                           help='Manual iterative-solver tolerance (-t), 0 < value < 1; requires '
                                '--fastercap-mesh-refinement and excludes --fastercap-auto-tolerance')
    numerical.add_argument('--fastercap-interaction-ratio', type=positive_number, default=0.5, metavar='RATIO',
                           help='Direct potential interaction coefficient / mesh refinement (-d), '
                                '> 0 (default: 0.5); applies in both refinement modes')
    mesh = solve.add_argument_group('Initial geometry mesh')
    mesh.add_argument('--mesh-max-area-um2', type=non_negative_square_micrometers, default=0, metavar='AREA',
                      help='Maximum initial triangle area in µm², >= 0 (default: 0, mesher chooses); '
                           'independent of FasterCap adaptive refinement')
    mesh.add_argument('--mesh-min-angle-deg', type=float, default=30, metavar='DEGREES',
                      help='Requested minimum initial triangle angle in degrees, 0–about 33.367 '
                           '(default: 30); preserves the mesher quality limit')
    collect = commands.add_parser(
        'collect', help='Collect saved solver logs without running a solver',
        description='Read recorded checkpoints and logs, validate their hashes, and collect raw matrices. '
                    'No solver installation is needed. Failed or incomplete cases remain explicit.',
        formatter_class=RichHelpFormatter, allow_abbrev=False)
    collect.add_argument('--manifest', required=True, type=Path, metavar='FILE',
                         help='Input CalibrationRunManifest from calibrate solve (protobuf JSON)')
    for parser in (solve, collect):
        parser.add_argument('--out-dir', required=True, type=Path, metavar='DIR',
                            help='New output directory under an existing parent; existing paths are refused')
        add_log_level_argument(parser)


def run_execution_command(args: argparse.Namespace):
    from .collect import collect_calibration
    from .solve import SolveOptions, solve_calibration
    import os

    try:
        if args.calibration_command == 'solve':
            options = SolveOptions(jobs=args.jobs, threads_per_job=args.threads_per_job,
                                   solver_timeout_seconds=args.solver_timeout_seconds,
                                   automatic_tolerance=args.fastercap_auto_tolerance,
                                   mesh_refinement=args.fastercap_mesh_refinement,
                                   gmres_tolerance=args.fastercap_gmres_tolerance,
                                   interaction_ratio=args.fastercap_interaction_ratio,
                                   mesh_max_area_um2=args.mesh_max_area_um2, mesh_min_angle_deg=args.mesh_min_angle_deg)
            executable = args.fastercap_exe or os.environ.get(EnvVar.FASTERCAP_EXE,
                                                             EnvVar.FASTERCAP_EXE.default_value)
            result = solve_calibration(args.manifest, args.out_dir, executable=executable, options=options)
            info(f'Run manifest: {result.manifest_path}')
            path = result.collection_path
        elif args.calibration_command == 'collect':
            result = collect_calibration(args.manifest, args.out_dir)
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
