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

"""
The convert subcommand of the netlist tool: a SPICE netlist to a VACASK netlist.

NOTE: imports neither KLayout nor generated protobuf code (but for the tech info of --pdk)
"""

from __future__ import annotations
import argparse
import os
from typing import *

from rich_argparse import RichHelpFormatter

from ..log import error, info
from ..pdk_config import PDK
from ..pex25d.diagnostics import ExitCode
from ..version import __version__
from .netlist_format import NetlistFormat
from .spice_reader import SpiceReader, SpiceReaderError
from .vacask_writer import VacaskWriter, VacaskWriterError


CONVERSION_FORMATS = (NetlistFormat.VACASK,)


def add_convert_subcommand(subparsers: argparse._SubParsersAction):
    parser = subparsers.add_parser(
        'convert',
        help="Convert a SPICE netlist to another format (VACASK)",
        description="Convert a SPICE netlist (e.g. an extracted one) to another format. "
                    "Reads the elements R, C, L, K, D, M, V, I, E, F, G, H and X, "
                    "subcircuits and .global, with numbers as values "
                    "(no parameters, expressions, models, includes or analyses)",
        formatter_class=RichHelpFormatter)
    parser.add_argument('input_netlist_path',
                        help="Path to the input SPICE netlist")
    parser.add_argument('--to', dest='output_format', required=True,
                        choices=[f.value for f in CONVERSION_FORMATS],
                        help="Format of the output netlist")
    parser.add_argument('--output', '-o', dest='output_path', default=None,
                        help="Path of the output netlist (default is the input path "
                             "with the extension of the format, e.g. .inc for VACASK)")
    all_pdk_choices = [p.value for p in PDK] + list(PDK.legacy_aliases().keys())
    parser.add_argument('--pdk', dest='pdk', default=None, choices=all_pdk_choices,
                        help="PDK of the netlist, whose VACASK subcircuits that declare m "
                             "(e.g. the MOS) are called with m = N, "
                             "other subcircuits N times (default is none, all of them N times)")


def run_convert(args: argparse.Namespace) -> ExitCode:
    output_format = NetlistFormat(args.output_format)
    input_path: str = args.input_netlist_path
    if not os.path.isfile(input_path):
        error(f"Can't read the input netlist at {input_path}")
        return ExitCode.USAGE

    output_path: str = args.output_path or os.path.splitext(input_path)[0] + output_format.file_extension
    if os.path.realpath(output_path) == os.path.realpath(input_path):
        error(f"The output path is the input path {input_path}, give another one with --output")
        return ExitCode.USAGE

    subcircuits_with_m: Set[str] = set()
    if args.pdk is not None:
        from ..tech_info import TechInfo  # NOTE: imports generated protobuf code (and KLayout)
        pdk = PDK.from_string(args.pdk)
        tech_info = TechInfo.from_json(pdk.config.tech_pb_json_path, dielectric_filter=None)
        subcircuits_with_m = tech_info.device_models.vacask_subcircuits_with_m

    try:
        convert_to_vacask(input_path, output_path, subcircuits_with_m)
    except SpiceReaderError as e:
        error(f"Can't read the SPICE netlist {e}")
        return ExitCode.DIAGNOSTIC_ERRORS
    except VacaskWriterError as e:
        error(f"Can't write the SPICE netlist {input_path} as VACASK netlist: {e}")
        return ExitCode.DIAGNOSTIC_ERRORS

    info(f"Wrote {output_path}")
    return ExitCode.OK


def convert_to_vacask(input_path: str,
                      output_path: str,
                      subcircuits_with_m: Collection[str]) -> str:
    """
    Converts a SPICE netlist to a VACASK netlist, for netlist convert and kpex --netlist_format vacask

    :param subcircuits_with_m: see VacaskWriter
    :return: the path written
    :raises SpiceReaderError: if the SPICE netlist can't be read
    :raises VacaskWriterError: if it has no VACASK equivalent (nothing is written then)
    """
    netlist = SpiceReader().read(input_path)
    writer = VacaskWriter(subcircuits_with_m=subcircuits_with_m,
                          header=[f"VACASK netlist converted by KLayout-PEX {__version__}",
                                  f"from the SPICE netlist {os.path.basename(input_path)}"])
    writer.write(netlist, output_path)
    return output_path
