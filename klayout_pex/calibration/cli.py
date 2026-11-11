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

"""Command-line preparation of finite 3D calibration patterns."""

import argparse
from pathlib import Path
import sys

from google.protobuf.json_format import ParseError
from rich_argparse import RichHelpFormatter

from .patterns import CalibrationError, read_patterns
from .prepare import prepare_calibration, validate_output_directory
from ..klayout.pex25d_stack import BuildError
from ..log import error, info, set_log_level
from ..pdk_config import PDK
from ..pex25d.diagnostics import ExitCode
from ..pex25d.resolver import ResolveError
from ..tech_info import TechDefError, TechInfo
from ..util.argparse_helpers import add_log_level_argument


def add_calibration_subparser(subparsers: argparse._SubParsersAction):
    parser = subparsers.add_parser(
        'calibrate', help='Prepare finite 3D cases for parasitic-table calibration',
        description='Prepare physical test patterns and provenance. Reference solving and coefficient '
                    'fitting are not performed by this command.', formatter_class=RichHelpFormatter)
    commands = parser.add_subparsers(dest='calibration_command', required=True)
    prepare = commands.add_parser(
        'prepare', help='Write validated PEX25D patterns and a preparation manifest',
        description='Create finite parallel plates and wires from explicit dimensions in a JSON specification. '
                    'The output is ready for inspection or export, not a qualified reference solution.',
        formatter_class=RichHelpFormatter)
    prepare.add_argument('--pdk', required=True, type=PDK.from_string, choices=list(PDK),
                         help='Technology whose complete physical stack supplies the patterns')
    prepare.add_argument('--patterns', required=True, type=Path, metavar='SPEC.json',
                         help='Pattern specification with dimensions in µm, exact grid and domain margin')
    prepare.add_argument('--out-dir', required=True, type=Path, metavar='PATH',
                         help='New output directory under an existing parent; existing paths are refused')
    add_log_level_argument(prepare)


def run_calibration_command(args: argparse.Namespace):
    set_log_level(args.log_level)
    try:
        spec = read_patterns(args.patterns)
        validate_output_directory(args.out_dir)
        tech_info = TechInfo.from_json(args.pdk.config.tech_pb_json_path, dielectric_filter=None)
        result = prepare_calibration(tech_info, spec, args.out_dir)
    except (CalibrationError, OSError, ParseError) as exc:
        error(str(exc))
        sys.exit(ExitCode.USAGE)
    except (TechDefError, BuildError, ResolveError) as exc:
        error(str(exc))
        for note in getattr(exc, '__notes__', ()):
            error(note)
        sys.exit(ExitCode.DIAGNOSTIC_ERRORS)
    info(f'Prepared {len(spec.cases)} finite 3D cases: {result.manifest_path}')
    info('Reference solving and coefficient fitting have not run')
