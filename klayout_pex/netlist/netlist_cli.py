#! /usr/bin/env python3
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

import argparse
from datetime import datetime
import logging
import os
import os.path

from rich_argparse import RichHelpFormatter
import shlex
import shutil
import sys
from typing import *

import klayout.db as kdb

from klayout_pex.klayout.netlist_expander import NetlistExpander
from klayout_pex.klayout.netlist_csv import NetlistCSVWriter
from klayout_pex.klayout.netlist_reducer import NetlistReducer

from klayout_pex.log import (
    LogLevel,
    set_log_level,
    register_additional_handler,
    deregister_additional_handler,
    # console,
    # debug,
    info,
    warning,
    subproc,
    error,
    rule
)
from klayout_pex.netlistsvg.netlist_json import NetlistJSONWriter
from klayout_pex.netlistsvg.netlistsvg_runner import run_netlistsvg
from klayout_pex.util.argparse_helpers import render_enum_help, true_or_false
from klayout_pex.version import __version__


# ------------------------------------------------------------------------------------

PROGRAM_NAME = "netlist"


class ArgumentValidationError(Exception):
    pass


class NetlistCLI:
    def parse_args(self, arg_list: List[str] = None) -> argparse.Namespace:

        main_parser = argparse.ArgumentParser(description=f"{PROGRAM_NAME}: "
                                                          f"Netlist tool for KLayout-PEX",
                                              add_help=False,
                                              formatter_class=RichHelpFormatter,
        epilog = f"See '{PROGRAM_NAME} <subcommand> -h' for help on subcommand")

        group_special = main_parser.add_argument_group("Special options")
        group_special.add_argument("--help", "-h", action='help', help="show this help message and exit")
        group_special.add_argument("--version", "-v", action='version', version=f'{PROGRAM_NAME} {__version__}')
        group_special.add_argument("--log_level", dest='log_level',
                                   default=LogLevel.DEFAULT, type=LogLevel, choices=list(LogLevel),
                                   help=render_enum_help(topic='log_level', enum_cls=LogLevel))

        subparsers = main_parser.add_subparsers(dest="command", help="Sub-commands help")

        parser_netlistsvg = subparsers.add_parser("svg",
                                                  help="Run netlistsvg on a given netlist",
                                                  formatter_class=RichHelpFormatter)
        parser_netlistsvg.add_argument("input_netlist_path",
                                       type=str, help="Path to the input netlist file")

        parser_netlistsvg.add_argument('--exe', dest='netlistsvg_exe_path',
                                       default='netlistsvg',
                                       help="Path to netlistsvg executable (default is '%(default)s')")

        parser_netlistsvg.add_argument("--output", "-o", dest="output_svg_path",
                                       help="Output SVG path", default=None)
        parser_netlistsvg.add_argument("--preview", "-p", dest="preview_svg",
                                       action='store_true', default=False,
                                       help="Preview SVG")
        parser_netlistsvg.add_argument("--cell", "-c", dest="cell_name", default=None,
                                       help="Cell (default is the top cell)")

        if arg_list is None:
            arg_list = sys.argv[1:]
        args = main_parser.parse_args(arg_list)

        self.validate_args(main_parser, args)

        return args

    @staticmethod
    def validate_args(main_parser: argparse.ArgumentParser,
                      args: argparse.Namespace):
        print("")
        found_errors = False

        match args.command:
            case None:
                error(f"Command argument missing")
                found_errors = True
                print("")
                rule('Usage')
                main_parser.print_help()

                sys.exit(1)

            case 'svg':
                if not os.path.isfile(args.netlistsvg_exe_path):
                    path = shutil.which(args.netlistsvg_exe_path)
                    if not path:
                        error(f"Can't locate netlistsvg executable at {args.netlistsvg_exe_path}")
                        found_errors = True

        if found_errors:
            raise ArgumentValidationError("Argument validation failed")

    def run_netlistsvg(self,
                       args: argparse.Namespace):
        netlist = kdb.Netlist()
        netlist_reader = kdb.NetlistSpiceReader()
        netlist.read(args.input_netlist_path, netlist_reader)

        rule('netlistsvg Execution')

        top_circuits = netlist.top_circuits()
        top_circuit_names = [c.name for c in top_circuits]
        n_circuits = len(top_circuit_names)

        top_circuit: kdb.Circuit

        match n_circuits:
            case 0:
                error(f"No top circuit found in SPICE netlist, perhaps the SUBCKT with the ports is missing?!")
                sys.exit(1)
            case 1:
                top_circuit = top_circuits[0]
            case _:
                info(f"Multiple top circuits found in SPICE netlist: {top_circuit_names}")
                error('Please specify the desired cell using the --cell argument')
                sys.exit(2)

        run_dir = os.path.join('netlist_run', top_circuit.name.lower())
        os.makedirs(run_dir, exist_ok=True)

        skin_path = os.path.realpath(os.path.join(os.path.dirname(__file__), '..', '..',
                                                  'testdata', 'netlistsvg', 'analog_skin.svg'))

        yosys_json_netlist_path = os.path.join(run_dir, f"yosys_netlist.json")
        log_path = os.path.join(run_dir, 'netlistsvg_log.txt')
        output_svg_path = args.output_svg_path
        if output_svg_path is None:
            output_svg_path = os.path.join(run_dir, f"{os.path.basename(args.input_netlist_path)}.svg")

        json_writer = NetlistJSONWriter()
        json_writer.write_json(netlist=netlist,
                               top_circuit=top_circuit,
                               output_path=yosys_json_netlist_path)

        run_netlistsvg(exe_path=args.netlistsvg_exe_path,
                       skin_path=skin_path,
                       yosys_json_netlist_path=yosys_json_netlist_path,
                       output_svg_path=output_svg_path,
                       layout_elk_path=None,
                       log_path=log_path)

        if args.preview_svg:
            import webbrowser
            webbrowser.open(f"file://{os.path.abspath(output_svg_path)}")
            
            # import cairosvg
            # from PIL import Image
            # import io
            # import matplotlib.pyplot as plt
            #
            # png_data = cairosvg.svg2png(url=output_svg_path)
            # image = Image.open(io.BytesIO(png_data))
            # plt.imshow(image)
            # plt.axis('off')
            # plt.show()

    def setup_logging(self, args: argparse.Namespace):
        set_log_level(args.log_level)

    @staticmethod
    def modification_date(filename: str) -> datetime:
        t = os.path.getmtime(filename)
        return datetime.fromtimestamp(t)

    def main(self, argv: List[str]):
        if '-v' not in argv and \
           '--version' not in argv and \
           '-h' not in argv and \
           '--help' not in argv:
            rule('Command line arguments')
            subproc(' '.join(map(shlex.quote, sys.argv)))

        args = self.parse_args(argv[1:])

        self.setup_logging(args)

        match args.command:
            case 'svg':
                self.run_netlistsvg(args)


if __name__ == "__main__":
    cli = NetlistCLI()
    cli.main(sys.argv)
