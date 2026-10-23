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
import os
import os.path

import rich.console
import rich.markdown
import rich.text
from rich_argparse import RichHelpFormatter
import shlex
import shutil
import sys
import tempfile
from typing import *

from klayout_pex.log import (
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
from klayout_pex.netlist.netlist_convert import add_convert_subcommand, run_convert
from klayout_pex.netlist.reduce_subcommand import add_reduce_subcommand, run_reduce_subcommand
from klayout_pex.pex25d.diagnostics import ExitCode
from klayout_pex.util.argparse_helpers import (
    SectionedHelpFormatter,
    add_argument_with_former_name,
    add_help_subcommand,
    add_log_level_argument,
    add_subcommand_sections,
    handle_help_subcommand,
    warn_deprecated_options,
)
from klayout_pex.version import __version__


# ------------------------------------------------------------------------------------

PROGRAM_NAME = "netlist"

SUBCOMMAND_SECTIONS: Dict[str, Tuple[str, ...]] = {
    'Inspect': ('svg',),
    'Transform': ('reduce', 'convert'),
    'Help': ('help',),
}
"""How ``netlist --help`` groups the subcommands; every subcommand is in exactly one section."""


SVG_EPILOG_MARKDOWN = """\
| Exit code | Meaning |
| --------- | ------- |
| 0 | success |
| 1 | the netlist can't be drawn: it can't be read, it has no top circuit, or netlistsvg failed |
| 2 | the command line is wrong, e.g. the input netlist, netlistsvg or the directory of the output is missing |
"""


def svg_output_path(args: argparse.Namespace) -> str:
    """The SVG that netlist svg writes: --out-svg, else the input path with the extension .svg"""
    return args.output_svg_path or os.path.splitext(args.input_netlist_path)[0] + '.svg'


class ArgumentValidationError(Exception):
    pass


class NetlistCLI:
    def parse_args(self, arg_list: List[str] = None) -> argparse.Namespace:

        main_parser = argparse.ArgumentParser(prog=PROGRAM_NAME,
                                              description=f"{PROGRAM_NAME}: "
                                                          f"Netlist tool for KLayout-PEX",
                                              add_help=False,
                                              formatter_class=SectionedHelpFormatter)

        group_special = main_parser.add_argument_group("Special Options")
        group_special.add_argument("--help", "-h", action='help', help="show this help message and exit")
        group_special.add_argument("--version", "-v", action='version', version=f'{PROGRAM_NAME} {__version__}')
        add_log_level_argument(group_special)

        subparsers = main_parser.add_subparsers(dest="command", metavar='<subcommand>')

        parser_netlistsvg = subparsers.add_parser("svg",
                                                  help="Draw the schematic of a SPICE netlist as SVG "
                                                       "(with netlistsvg)",
                                                  formatter_class=RichHelpFormatter,
                                                  epilog=rich.console.Group(
                                                      rich.text.Text('Exit codes:', style='argparse.groups'),
                                                      rich.markdown.Markdown(SVG_EPILOG_MARKDOWN,
                                                                             style='argparse.text')))
        parser_netlistsvg.add_argument("input_netlist_path",
                                       type=str, help="Path to the input netlist file")

        parser_netlistsvg.add_argument('--exe', dest='netlistsvg_exe_path',
                                       default='netlistsvg',
                                       help="Path to netlistsvg executable (default is '%(default)s')")

        add_argument_with_former_name(parser_netlistsvg, "--out-svg", "--output", "-o", dest="output_svg_path",
                                      help="Output SVG path (default is the input path with the extension .svg)",
                                      default=None)
        parser_netlistsvg.add_argument("--preview", "-p", dest="preview_svg",
                                       action='store_true', default=False,
                                       help="Preview SVG")
        parser_netlistsvg.add_argument("--cell", "-c", dest="cell_name", default=None,
                                       help="Cell (default is the top cell)")

        add_reduce_subcommand(subparsers)
        add_convert_subcommand(subparsers)
        add_help_subcommand(subparsers)
        add_subcommand_sections(main_parser, subparsers, SUBCOMMAND_SECTIONS)

        if arg_list is None:
            arg_list = sys.argv[1:]
        args = main_parser.parse_args(arg_list)
        handle_help_subcommand(main_parser, args)

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
                if not os.path.isfile(args.input_netlist_path):
                    error(f"Input netlist not found: {args.input_netlist_path}")
                    found_errors = True
                if shutil.which(args.netlistsvg_exe_path) is None:
                    error(f"Can't locate netlistsvg executable at {args.netlistsvg_exe_path} "
                          f"(install it with 'npm install -g netlistsvg', or give its path with --exe)")
                    found_errors = True
                output_dir = os.path.dirname(os.path.abspath(svg_output_path(args)))
                if not os.path.isdir(output_dir):
                    error(f"The directory of the output SVG doesn't exist: {output_dir}")
                    found_errors = True

        if found_errors:
            raise ArgumentValidationError("Argument validation failed")

    def run_netlistsvg(self,
                       args: argparse.Namespace) -> ExitCode:
        """
        :return: the exit code (see the epilog)
        """
        # NOTE: only this subcommand needs KLayout, the others (e.g. reduce) must not load it
        import klayout.db as kdb
        from klayout_pex.netlistsvg.netlist_json import NetlistJSONWriter
        from klayout_pex.netlistsvg.netlistsvg_runner import NetlistSVGError, SKIN_PATH, run_netlistsvg

        netlist = kdb.Netlist()
        netlist_reader = kdb.NetlistSpiceReader()
        try:
            netlist.read(args.input_netlist_path, netlist_reader)
        except RuntimeError as e:
            error(f"Can't read the SPICE netlist {args.input_netlist_path}: {e}")
            return ExitCode.DIAGNOSTIC_ERRORS

        rule('netlistsvg Execution')

        top_circuits = netlist.top_circuits()
        top_circuit_names = [c.name for c in top_circuits]
        n_circuits = len(top_circuit_names)

        top_circuit: kdb.Circuit

        match n_circuits:
            case 0:
                error(f"No top circuit found in SPICE netlist, perhaps the SUBCKT with the ports is missing?!")
                return ExitCode.DIAGNOSTIC_ERRORS
            case 1:
                top_circuit = top_circuits[0]
            case _:
                info(f"Multiple top circuits found in SPICE netlist: {top_circuit_names}")
                error('Please specify the desired cell using the --cell argument')
                return ExitCode.USAGE

        output_svg_path = svg_output_path(args)

        # NOTE: the netlistsvg input is an intermediate file
        with tempfile.TemporaryDirectory() as tmp_dir:
            yosys_json_netlist_path = os.path.join(tmp_dir, f"yosys_netlist.json")
            json_writer = NetlistJSONWriter()
            json_writer.write_json(netlist=netlist,
                                   top_circuit=top_circuit,
                                   output_path=yosys_json_netlist_path)

            try:
                run_netlistsvg(exe_path=shutil.which(args.netlistsvg_exe_path),
                               skin_path=SKIN_PATH,
                               yosys_json_netlist_path=yosys_json_netlist_path,
                               output_svg_path=output_svg_path,
                               layout_elk_path=None)
            except NetlistSVGError as e:
                error(str(e))
                return ExitCode.DIAGNOSTIC_ERRORS

        info(f"Wrote {output_svg_path}")

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

        return ExitCode.OK

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
           '--help' not in argv and \
           argv[1:2] != ['help']:
            rule('Command line arguments')
            subproc(' '.join(map(shlex.quote, sys.argv)))

        try:
            args = self.parse_args(argv[1:])
        except ArgumentValidationError:
            sys.exit(ExitCode.USAGE)

        self.setup_logging(args)
        warn_deprecated_options(args)

        match args.command:
            case 'svg':
                sys.exit(self.run_netlistsvg(args))
            case 'reduce':
                sys.exit(run_reduce_subcommand(args))
            case 'convert':
                sys.exit(run_convert(args))


if __name__ == "__main__":
    cli = NetlistCLI()
    cli.main(sys.argv)
