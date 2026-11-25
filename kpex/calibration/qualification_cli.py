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
"""Command-line numerical qualification using existing collected results."""

import argparse
from pathlib import Path
import sys

from rich_argparse import RichHelpFormatter

from .validation import CalibrationError
from ..log import error, info
from ..pex25d.diagnostics import ExitCode
from ..util.argparse_helpers import add_log_level_argument


def add_qualification_subparser(commands: argparse._SubParsersAction):
    parser = commands.add_parser(
        'qualify', help='Check numerical stabilization of collected calibration matrices',
        description='Check physical matrix diagnostics and independent solver, mesh and domain refinement '
                    'using saved collections. Write a protobuf JSON qualification report.',
        formatter_class=RichHelpFormatter, allow_abbrev=False)
    parser.add_argument('--study', required=True, type=Path, metavar='FILE',
                        help='CalibrationQualificationStudy in protobuf JSON')
    parser.add_argument('--out-dir', required=True, type=Path, metavar='DIR',
                        help='New output directory under an existing parent')
    add_log_level_argument(parser)


def run_qualification_command(args: argparse.Namespace):
    from .qualification import qualify_study
    from kpex_protobuf.kpex.calibration.qualification_pb2 import CalibrationQualificationStatus as Status

    try:
        result = qualify_study(args.study, args.out_dir)
    except (OSError, CalibrationError) as exc:
        error(str(exc))
        sys.exit(ExitCode.USAGE)
    stabilized = sum(case.status == Status.STABILIZED for case in result.report.cases)
    count = len(result.report.cases)
    info(f'Qualification report: {stabilized} of {count} cases stabilized: {result.report_path}')
    if stabilized != count:
        sys.exit(ExitCode.DIAGNOSTIC_ERRORS)
