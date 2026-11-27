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
"""Command-line finite-length fitting of qualified capacitance measurements."""

import argparse
from pathlib import Path
import sys

from rich_argparse import RichHelpFormatter

from .validation import CalibrationError
from ..log import error, info, set_log_level
from ..pex25d.diagnostics import ExitCode
from ..util.argparse_helpers import add_log_level_argument, positive_number


def add_fit_length_subparser(commands: argparse._SubParsersAction):
    parser = commands.add_parser(
        'fit-length', help='Fit distributed and end capacitance from qualified results',
        description='Fit coupling versus length from three or more training lengths and one or more '
                    'held-out lengths. Recheck the saved solver evidence and write a protobuf JSON report.',
        formatter_class=RichHelpFormatter, allow_abbrev=False,
    )
    _add_fit_arguments(parser)


def add_fit_overlap_subparser(commands: argparse._SubParsersAction):
    parser = commands.add_parser(
        'fit-overlap', help='Fit an overlap area coefficient from qualified parallel plates',
        description='Fit the area, edge and signed corner terms for one overlap target using four or more '
                    'training rectangles and one or more held-out rectangles. Write a protobuf JSON report.',
        formatter_class=RichHelpFormatter, allow_abbrev=False,
    )
    _add_fit_arguments(parser)


def _add_fit_arguments(parser: argparse.ArgumentParser):
    parser.add_argument('--study', type=Path, required=True, metavar='FILE',
                        help='Original CalibrationQualificationStudy and its relative collection paths')
    parser.add_argument('--qualification', type=Path, required=True, metavar='FILE',
                        help='CalibrationQualificationReport written by calibrate qualify')
    parser.add_argument('--residual-budget-f', type=positive_number, required=True, metavar='FARADS',
                        help='Maximum absolute residual per training or held-out measurement in farads')
    parser.add_argument('--out-dir', type=Path, required=True, metavar='DIR',
                        help='New output directory under an existing parent')
    add_log_level_argument(parser)


def run_fit_length_command(args: argparse.Namespace):
    from .length_fit import LengthFitPolicy
    from .length_report import fit_qualified_lengths
    from kpex_protobuf.kpex.calibration.length_fit_pb2 import CalibrationLengthFitResult

    set_log_level(args.log_level)
    try:
        policy = LengthFitPolicy(weight_floor_f=args.residual_budget_f, max_weighted_residual=1.0)
        path, report = fit_qualified_lengths(args.study, args.qualification, args.out_dir, policy)
    except (OSError, CalibrationError) as exc:
        error(str(exc))
        for note in getattr(exc, '__notes__', ()):
            error(note)
        sys.exit(ExitCode.USAGE)
    info(f'Length fit report: {path}')
    if any(result.status != CalibrationLengthFitResult.ACCEPTED for result in report.fits):
        error('The length fit exceeded the declared residual budget or was physically inadequate')
        sys.exit(ExitCode.DIAGNOSTIC_ERRORS)


def run_fit_overlap_command(args: argparse.Namespace):
    from .overlap_report import fit_qualified_overlap
    from kpex_protobuf.kpex.calibration.overlap_fit_pb2 import CalibrationOverlapFitResult

    try:
        path, report = fit_qualified_overlap(args.study, args.qualification, args.out_dir, args.residual_budget_f)
    except (OSError, CalibrationError) as exc:
        error(str(exc))
        sys.exit(ExitCode.USAGE)
    info(f'Overlap fit report: {path}')
    if report.fit.status != CalibrationOverlapFitResult.ACCEPTED:
        for diagnostic in report.fit.diagnostics:
            error(diagnostic)
        sys.exit(ExitCode.DIAGNOSTIC_ERRORS)
