#! /usr/bin/env python3
#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/martinjankoehler/klayout-pex).
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
from enum import StrEnum
from functools import cached_property
import logging
import os
import os.path

import rich.console
import rich.markdown
import rich.text
from rich_argparse import RichHelpFormatter
import shlex
import shutil
import sys
from typing import *

import klayout.db as kdb
import klayout.rdb as rdb

from .fastercap.fastercap_input_builder import FasterCapInputBuilder
from .fastercap.fastercap_model_generator import FasterCapModelGenerator
from .fastercap.fastercap_runner import run_fastercap, fastercap_parse_capacitance_matrix
from .fastcap.fastcap_runner import run_fastcap, fastcap_parse_capacitance_matrix
from .klayout.lvs_runner import LVSRunner
from .klayout.lvsdb_extractor import KLayoutExtractionContext, KLayoutExtractedLayerInfo
from .klayout.netlist_expander import NetlistExpander
from .klayout.netlist_csv import NetlistCSVWriter
from .klayout.netlist_reducer import NetlistReducer
from .klayout.repair_rdb import repair_rdb
from .log import (
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
from .magic.magic_runner import MagicPEXMode, run_magic, prepare_magic_script
from .pdk_config import PDKConfig
from .rcx25.extractor import RCExtractor, ExtractionResults
from .tech_info import TechInfo
from .util.multiple_choice import MultipleChoicePattern
from .util.argparse_helpers import render_enum_help, true_or_false
from .version import __version__


# ------------------------------------------------------------------------------------

PROGRAM_NAME = "kpex"


class ArgumentValidationError(Exception):
    pass


class InputMode(StrEnum):
    LVSDB = "lvsdb"
    GDS = "gds"


# TODO: this should be externally configurable
class PDK(StrEnum):
    IHP_SG13G2 = 'ihp_sg13g2'
    SKY130A = 'sky130A'

    @cached_property
    def config(self) -> PDKConfig:
        # NOTE: installation paths of resources in the distribution wheel differs from source repo
        base_dir = os.path.dirname(os.path.realpath(__file__))

        if os.path.isdir(os.path.join(base_dir, '..', '.git')): # in source repo
            base_dir = os.path.dirname(base_dir)
            tech_pb_json_dir = os.path.join(base_dir, 'klayout_pex_protobuf')
        else:  # site-packages/klayout_pex -> site-packages/klayout_pex_protobuf
            tech_pb_json_dir = os.path.join(os.path.dirname(base_dir), 'klayout_pex_protobuf')

        match self:
            case PDK.IHP_SG13G2:
                return PDKConfig(
                    name=self,
                    pex_lvs_script_path=os.path.join(base_dir, 'pdk', self, 'libs.tech', 'kpex', 'sg130g2.lvs'),
                    tech_pb_json_path=os.path.join(tech_pb_json_dir, f"{self}_tech.pb.json")
                )
            case PDK.SKY130A:
                return PDKConfig(
                    name=self,
                    pex_lvs_script_path=os.path.join(base_dir, 'pdk', self, 'libs.tech', 'kpex', 'sky130.lvs'),
                    tech_pb_json_path=os.path.join(tech_pb_json_dir, f"{self}_tech.pb.json")
                )


class KpexCLI:
    @staticmethod
    def parse_args(arg_list: List[str] = None) -> argparse.Namespace:
        # epilog = f"See '{PROGRAM_NAME} <subcommand> -h' for help on subcommand"
        epilog = """
| Variable | Example              | Description                             |
| -------- | -------------------- | --------------------------------------- |
| PDKPATH  | (e.g. $HOME/.volare) | Optional (required for default magicrc) |
| PDK      | (e.g. sky130A)       | Optional (required for default magicrc) |
"""
        epilog_md = rich.console.Group(
            rich.text.Text('Environmental variables:', style='argparse.groups'),
            rich.markdown.Markdown(epilog, style='argparse.text')
        )
        main_parser = argparse.ArgumentParser(description=f"{PROGRAM_NAME}: "
                                                          f"KLayout-integrated Parasitic Extraction Tool",
                                              epilog=epilog_md,
                                              add_help=False,
                                              formatter_class=RichHelpFormatter)

        group_special = main_parser.add_argument_group("Special options")
        group_special.add_argument("--help", "-h", action='help', help="show this help message and exit")
        group_special.add_argument("--version", "-v", action='version', version=f'{PROGRAM_NAME} {__version__}')
        group_special.add_argument("--log_level", dest='log_level', default='subprocess',
                                   help=render_enum_help(topic='log_level', enum_cls=LogLevel))
        group_special.add_argument("--threads", dest='num_threads', type=int,
                                   default=os.cpu_count() * 4,
                                   help="number of threads (e.g. for FasterCap) (default is %(default)s)")
        group_special.add_argument('--klayout', dest='klayout_exe_path', default='klayout',
                                   help="Path to klayout executable (default is '%(default)s')")

        group_pex = main_parser.add_argument_group("Parasitic Extraction Setup")
        group_pex.add_argument("--pdk", dest="pdk", required=True, type=PDK,
                               help=render_enum_help(topic='pdk', enum_cls=PDK))

        group_pex.add_argument("--out_dir", "-o", dest="output_dir_base_path", default="output",
                               help="Output directory path (default is '%(default)s')")

        group_pex_input = main_parser.add_argument_group("Parasitic Extraction Input",
                                                         description="Either LVS is run, or an existing LVSDB is used")
        group_pex_input.add_argument("--gds", "-g", dest="gds_path", help="GDS path (for LVS)")
        group_pex_input.add_argument("--schematic", "-s", dest="schematic_path",
                                     help="Schematic SPICE netlist path (for LVS)")
        group_pex_input.add_argument("--lvsdb", "-l", dest="lvsdb_path", help="KLayout LVSDB path (bypass LVS)")
        group_pex_input.add_argument("--cell", "-c", dest="cell_name", default=None,
                                     help="Cell (default is the top cell)")

        group_pex_input.add_argument("--cache-lvs", dest="cache_lvs",
                                     type=true_or_false, default=True,
                                     help="Used cached LVSDB (for given input GDS) (default is %(default)s)")
        group_pex_input.add_argument("--cache-dir", dest="cache_dir_path", default=None,
                                     help="Path for cached LVSDB (default is .kpex_cache within --out_dir)")

        group_pex_options = main_parser.add_argument_group("Parasitic Extraction Options")
        group_pex_options.add_argument("--blackbox", dest="blackbox_devices",
                                      type=true_or_false, default=False,  # TODO: in the future this should be True by default
                                      help="Blackbox devices like MIM/MOM caps, as they are handled by SPICE models "
                                           "(default is %(default)s for testing now)")
        group_pex_options.add_argument("--fastercap", dest="run_fastercap",
                                      type=true_or_false, default=False,
                                      help="Run FasterCap engine (default is %(default)s)")
        group_pex_options.add_argument("--fastcap", dest="run_fastcap",
                                      type=true_or_false, default=False,
                                      help="Run FastCap2 engine (default is %(default)s)")
        group_pex_options.add_argument("--magic", dest="run_magic",
                                      type=true_or_false, default=False,
                                      help="Run MAGIC engine (default is %(default)s)")
        group_pex_options.add_argument("--2.5D", dest="run_2_5D",
                                      type=true_or_false, default=False,
                                      help="Run 2.5D analytical engine (default is %(default)s)")

        group_fastercap = main_parser.add_argument_group("FasterCap options")
        group_fastercap.add_argument("--k_void", "-k", dest="k_void",
                                     type=float, default=3.9,
                                     help="Dielectric constant of void (default is %(default)s)")
        group_fastercap.add_argument("--delaunay_amax", "-a", dest="delaunay_amax",
                                     type=float, default=50,
                                     help="Delaunay triangulation maximum area (default is %(default)s)")
        group_fastercap.add_argument("--delaunay_b", "-b", dest="delaunay_b",
                                     type=float, default=0.5,
                                     help="Delaunay triangulation b (default is %(default)s)")
        group_fastercap.add_argument("--geo_check", dest="geometry_check",
                                     type=true_or_false, default=False,
                                     help=f"Validate geometries before passing to FasterCap "
                                          f"(default is False)")
        group_fastercap.add_argument("--diel", dest="dielectric_filter",
                                     type=str, default="all",
                                     help=f"Comma separated list of dielectric filter patterns. "
                                          f"Allowed patterns are: (none, all, -dielname1, +dielname2) "
                                          f"(default is %(default)s)")

        group_fastercap.add_argument("--tolerance", dest="fastercap_tolerance",
                                     type=float, default=0.05,
                                     help="FasterCap -aX error tolerance (default is %(default)s)")
        group_fastercap.add_argument("--d_coeff", dest="fastercap_d_coeff",
                                     type=float, default=0.5,
                                     help=f"FasterCap -d direct potential interaction coefficient to mesh refinement "
                                          f"(default is %(default)s)")
        group_fastercap.add_argument("--mesh", dest="fastercap_mesh_refinement_value",
                                     type=float, default=0.5,
                                     help="FasterCap -m Mesh relative refinement value (default is %(default)s)")
        group_fastercap.add_argument("--ooc", dest="fastercap_ooc_condition",
                                     type=float, default=2,
                                     help="FasterCap -f out-of-core free memory to link memory condition "
                                          "(0 = don't go OOC, default is %(default)s)")
        group_fastercap.add_argument("--auto_precond", dest="fastercap_auto_preconditioner",
                                     type=true_or_false, default=True,
                                     help=f"FasterCap -ap Automatic preconditioner usage (default is %(default)s)")
        group_fastercap.add_argument("--galerkin", dest="fastercap_galerkin_scheme",
                                     action='store_true', default=False,
                                     help=f"FasterCap -g Use Galerkin scheme (default is %(default)s)")
        group_fastercap.add_argument("--jacobi", dest="fastercap_jacobi_preconditioner",
                                     action='store_true', default=False,
                                     help="FasterCap -pj Use Jacobi preconditioner (default is %(default)s)")

        PDKPATH = os.environ.get('PDKPATH', None)
        default_magicrc_path = \
            None if PDKPATH is None \
            else os.path.abspath(f"{PDKPATH}/libs.tech/magic/{os.environ['PDK']}.magicrc")
        group_magic = main_parser.add_argument_group("MAGIC options")
        group_magic.add_argument('--magicrc', dest='magicrc_path', default=default_magicrc_path,
                                  help=f"Path to magicrc configuration file (default is '%(default)s')")
        group_magic.add_argument("--magic_mode", dest='magic_pex_mode', default='CC',
                                 help=render_enum_help(topic='log_level', enum_cls=MagicPEXMode))
        group_magic.add_argument("--magic_cthresh", dest="magic_cthresh",
                                 type=float, default=0.01,
                                 help="Threshold for ignored parasitic capacitances (default is %(default)s)")
        group_magic.add_argument("--magic_rthresh", dest="magic_rthresh",
                                 type=float, default=100.0,
                                 help="Threshold for ignored parasitic resistances (default is %(default)s)")
        group_magic.add_argument("--magic_halo", dest="magic_halo",
                                 type=float, default=None,
                                 help="Custom sidewall halo distance in µm "
                                      "(MAGIC command: extract halo <value>) (default is no custom halo)")
        group_magic.add_argument('--magic_exe', dest='magic_exe_path', default='magic',
                                  help="Path to magic executable (default is '%(default)s')")

        if arg_list is None:
            arg_list = sys.argv[1:]
        args = main_parser.parse_args(arg_list)
        return args

    @staticmethod
    def validate_args(args: argparse.Namespace):
        found_errors = False

        pdk_config: PDKConfig = args.pdk.config
        args.tech_pbjson_path = pdk_config.tech_pb_json_path
        args.lvs_script_path = pdk_config.pex_lvs_script_path

        if not os.path.isfile(args.klayout_exe_path):
            path = shutil.which(args.klayout_exe_path)
            if not path:
                error(f"Can't locate KLayout executable at {args.klayout_exe_path}")
                found_errors = True

        if not os.path.isfile(args.tech_pbjson_path):
            error(f"Can't read technology file at path {args.tech_pbjson_path}")
            found_errors = True

        if not os.path.isfile(args.lvs_script_path):
            error(f"Can't locate LVS script path at {args.lvs_script_path}")
            found_errors = True

        rule('Input Layout')

        # input mode: LVS or existing LVSDB?
        if args.gds_path:
            info(f"GDS input file passed, running in LVS mode")
            args.input_mode = InputMode.GDS
            if not os.path.isfile(args.gds_path):
                error(f"Can't read GDS file (LVS input) at path {args.gds_path}")
                found_errors = True
            else:
                args.layout = kdb.Layout()
                args.layout.read(args.gds_path)

                top_cells = args.layout.top_cells()

                if args.cell_name:  # explicit user-specified cell name
                    args.effective_cell_name = args.cell_name

                    found_cell: Optional[kdb.Cell] = None
                    for cell in args.layout.cells('*'):
                        if cell.name == args.effective_cell_name:
                            found_cell = cell
                            break
                    if not found_cell:
                        error(f"Could not find cell {args.cell_name} in GDS {args.gds_path}")
                        found_errors = True

                    is_only_top_cell = len(top_cells) == 1 and top_cells[0].name == args.cell_name
                    if is_only_top_cell:
                        info(f"Found cell {args.cell_name} in GDS {args.gds_path} (only top cell)")
                    else:  # there are other cells => extract the top cell to a tmp layout
                        args.effective_gds_path = os.path.join(args.output_dir_path, f"{args.cell_name}_exported.gds.gz")
                        info(f"Found cell {args.cell_name} in GDS {args.gds_path}, "
                             f"but it is not the only top cell, "
                             f"so layout is exported to: {args.effective_gds_path}")

                        found_cell.write(args.effective_gds_path)
                else:  # find top cell
                    if len(top_cells) == 1:
                        args.effective_cell_name = top_cells[0].name
                        info(f"No explicit top cell specified, using top cell '{args.effective_cell_name}'")
                    else:
                        args.effective_cell_name = 'TOP'
                        error(f"Could not determine the default top cell in GDS {args.gds_path}, "
                              f"there are multiple: {', '.join([c.name for c in top_cells])}. "
                              f"Use --cell to specify the cell")
                        found_errors = True

                args.effective_gds_path = args.gds_path
        else:
            info(f"LVSDB input file passed, bypassing LVS")
            args.input_mode = InputMode.LVSDB
            if not hasattr(args, 'lvsdb_path'):
                error(f"LVSDB input path not specified (argument --lvsdb)")
                found_errors = True
            elif not os.path.isfile(args.lvsdb_path):
                error(f"Can't read KLayout LVSDB file at path {args.lvsdb_path}")
                found_errors = True
            else:
                lvsdb = kdb.LayoutVsSchematic()
                lvsdb.read(args.lvsdb_path)
                top_cell: kdb.Cell = lvsdb.internal_top_cell()
                args.effective_cell_name = top_cell.name

        def input_file_stem(path: str):
            # could be *.gds, or *.gds.gz, so remove all extensions
            return os.path.basename(path).split(sep='.')[0]

        if hasattr(args, 'effective_cell_name'):
            run_dir_id: str
            match args.input_mode:
                case InputMode.GDS:
                    run_dir_id = f"{input_file_stem(args.gds_path)}__{args.effective_cell_name}"
                case InputMode.LVSDB:
                    run_dir_id = f"{input_file_stem(args.lvsdb_path)}__{args.effective_cell_name}"
                case _:
                    raise NotImplementedError(f"Unknown input mode {args.input_mode}")

            args.output_dir_path = os.path.join(args.output_dir_base_path, run_dir_id)
            os.makedirs(args.output_dir_path, exist_ok=True)
            if args.input_mode == InputMode.GDS:
                if args.schematic_path:
                    args.effective_schematic_path = args.schematic_path
                    if not os.path.isfile(args.schematic_path):
                        error(f"Can't read schematic (LVS input) at path {args.schematic_path}")
                        found_errors = True
                else:
                    info(f"LVS input schematic not specified (argument --schematic), using dummy schematic")
                    args.effective_schematic_path = os.path.join(args.output_dir_path,
                                                                 f"{args.effective_cell_name}_dummy_schematic.spice")
                    with open(args.effective_schematic_path, 'w') as f:
                        f.writelines([
                            f".subckt {args.effective_cell_name} VDD VSS",
                            '.ends',
                            '.end'
                        ])

        try:
            args.log_level = LogLevel[args.log_level.upper()]
        except KeyError:
            error(f"Requested log level {args.log_level.lower()} does not exist, "
                  f"{render_enum_help(topic='log_level', enum_cls=LogLevel, print_default=False)}")
            found_errors = True

        try:
            pattern_string: str = args.dielectric_filter
            args.dielectric_filter = MultipleChoicePattern(pattern=pattern_string)
        except ValueError as e:
            error("Failed to parse --diel arg", e)
            found_errors = True

        # at least one engine must be activated

        if not (args.run_magic or args.run_fastcap or args.run_fastercap or args.run_2_5D):
            error("No PEX engines activated")
            engine_help = """
| Argument       | Description                             |
| -------------- | --------------------------------------- |
| --fastercap y  | Run kpex/FasterCap engine               |
| --2.5D y       | Run kpex/2.5D engine                    |
| --magic y      | Run MAGIC engine                        |
"""
            subproc(f"\nPlease activate one or more engines using the arguments:\n{engine_help}")
            found_errors = True

        if args.cache_dir_path is None:
            args.cache_dir_path = os.path.join(args.output_dir_base_path, '.kpex_cache')

        if found_errors:
            raise ArgumentValidationError("Argument validation failed")

    def build_fastercap_input(self,
                              args: argparse.Namespace,
                              pex_context: KLayoutExtractionContext,
                              tech_info: TechInfo) -> str:
        rule('Process stackup')
        fastercap_input_builder = FasterCapInputBuilder(pex_context=pex_context,
                                                        tech_info=tech_info,
                                                        k_void=args.k_void,
                                                        delaunay_amax=args.delaunay_amax,
                                                        delaunay_b=args.delaunay_b)
        gen: FasterCapModelGenerator = fastercap_input_builder.build()

        rule('FasterCap Input File Generation')
        faster_cap_input_dir_path = os.path.join(args.output_dir_path, 'FasterCap_Input_Files')
        os.makedirs(faster_cap_input_dir_path, exist_ok=True)

        lst_file = gen.write_fastcap(output_dir_path=faster_cap_input_dir_path, prefix='FasterCap_Input_')

        rule('STL File Generation')
        geometry_dir_path = os.path.join(args.output_dir_path, 'Geometries')
        os.makedirs(geometry_dir_path, exist_ok=True)
        gen.dump_stl(output_dir_path=geometry_dir_path, prefix='')

        if args.geometry_check:
            rule('Geometry Validation')
            gen.check()

        return lst_file


    def run_fastercap_extraction(self,
                                 args: argparse.Namespace,
                                 pex_context: KLayoutExtractionContext,
                                 lst_file: str):
        rule('FasterCap Execution')
        info(f"Configure number of OpenMP threads (environmental variable OMP_NUM_THREADS) as {args.num_threads}")
        os.environ['OMP_NUM_THREADS'] = f"{args.num_threads}"

        exe_path = "FasterCap"
        log_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FasterCap_Output.txt")
        raw_csv_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FasterCap_Result_Matrix_Raw.csv")
        avg_csv_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FasterCap_Result_Matrix_Avg.csv")
        expanded_netlist_path = os.path.join(args.output_dir_path,
                                             f"{args.effective_cell_name}_FasterCap_Expanded_Netlist.cir")
        expanded_netlist_csv_path = os.path.join(args.output_dir_path,
                                                 f"{args.effective_cell_name}_FasterCap_Expanded_Netlist.csv")
        reduced_netlist_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FasterCap_Reduced_Netlist.cir")

        run_fastercap(exe_path=exe_path,
                      lst_file_path=lst_file,
                      log_path=log_path,
                      tolerance=args.fastercap_tolerance,
                      d_coeff=args.fastercap_d_coeff,
                      mesh_refinement_value=args.fastercap_mesh_refinement_value,
                      ooc_condition=args.fastercap_ooc_condition,
                      auto_preconditioner=args.fastercap_auto_preconditioner,
                      galerkin_scheme=args.fastercap_galerkin_scheme,
                      jacobi_preconditioner=args.fastercap_jacobi_preconditioner)

        cap_matrix = fastercap_parse_capacitance_matrix(log_path)
        cap_matrix.write_csv(raw_csv_path)

        cap_matrix = cap_matrix.averaged_off_diagonals()
        cap_matrix.write_csv(avg_csv_path)

        netlist_expander = NetlistExpander()
        expanded_netlist = netlist_expander.expand(
            extracted_netlist=pex_context.lvsdb.netlist(),
            top_cell_name=pex_context.top_cell.name,
            cap_matrix=cap_matrix,
            blackbox_devices=args.blackbox_devices
        )

        # create a nice CSV for reports, useful for spreadsheets
        netlist_csv_writer = NetlistCSVWriter()
        netlist_csv_writer.write_csv(netlist=expanded_netlist,
                                     top_cell_name=pex_context.top_cell.name,
                                     output_path=expanded_netlist_csv_path)

        rule("Extended netlist (CSV format):")
        with open(expanded_netlist_csv_path, 'r') as f:
            for line in f.readlines():
                subproc(line[:-1])  # abusing subproc, simply want verbatim
        rule()

        info(f"Wrote expanded netlist CSV to: {expanded_netlist_csv_path}")

        spice_writer = kdb.NetlistSpiceWriter()
        spice_writer.use_net_names = True
        spice_writer.with_comments = False
        expanded_netlist.write(expanded_netlist_path, spice_writer)
        info(f"Wrote expanded netlist to: {expanded_netlist_path}")

        netlist_reducer = NetlistReducer()
        reduced_netlist = netlist_reducer.reduce(netlist=expanded_netlist,
                                                 top_cell_name=pex_context.top_cell.name)
        reduced_netlist.write(reduced_netlist_path, spice_writer)
        info(f"Wrote reduced netlist to: {reduced_netlist_path}")

        self._fastercap_extracted_csv_path = expanded_netlist_csv_path

    def run_magic_extraction(self,
                             args: argparse.Namespace):
        if args.input_mode != InputMode.GDS:
            error(f"MAGIC engine only works with GDS input mode"
                  f" (currently {args.input_mode})")
            return

        magic_run_dir = os.path.join(args.output_dir_path, f"magic_{args.magic_pex_mode}")
        magic_log_path = os.path.join(magic_run_dir, f"{args.effective_cell_name}_MAGIC_CC_Output.txt")
        magic_script_path = os.path.join(magic_run_dir, f"{args.effective_cell_name}_MAGIC_CC_Script.tcl")

        output_netlist_path = f"{magic_run_dir}/{args.effective_cell_name}.pex.spice"

        os.makedirs(magic_run_dir, exist_ok=True)

        prepare_magic_script(gds_path=args.effective_gds_path,
                             cell_name=args.effective_cell_name,
                             run_dir_path=magic_run_dir,
                             script_path=magic_script_path,
                             output_netlist_path=output_netlist_path,
                             pex_mode=args.magic_pex_mode,
                             c_threshold=args.magic_cthresh,
                             r_threshold=args.magic_rthresh,
                             halo=args.magic_halo)

        run_magic(exe_path=args.magic_exe_path,
                  magicrc_path=args.magicrc_path,
                  script_path=magic_script_path,
                  log_path=magic_log_path)

        subproc(f"SPICE netlist saved at: {output_netlist_path}")
        rule("MAGIC PEX SPICE netlist")
        with open(output_netlist_path, 'r') as f:
            subproc(f.read())
        rule()

    def run_fastcap_extraction(self,
                               args: argparse.Namespace,
                               pex_context: KLayoutExtractionContext,
                               lst_file: str):
        rule('FastCap2 Execution')
        exe_path = "fastcap"
        log_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FastCap2_Output.txt")
        raw_csv_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FastCap2_Result_Matrix_Raw.csv")
        avg_csv_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FastCap2_Result_Matrix_Avg.csv")
        expanded_netlist_path = os.path.join(args.output_dir_path,
                                             f"{args.effective_cell_name}_FastCap2_Expanded_Netlist.cir")
        reduced_netlist_path = os.path.join(args.output_dir_path,
                                            f"{args.effective_cell_name}_FastCap2_Reduced_Netlist.cir")

        run_fastcap(exe_path=exe_path,
                    lst_file_path=lst_file,
                    log_path=log_path)

        cap_matrix = fastcap_parse_capacitance_matrix(log_path)
        cap_matrix.write_csv(raw_csv_path)

        cap_matrix = cap_matrix.averaged_off_diagonals()
        cap_matrix.write_csv(avg_csv_path)

        netlist_expander = NetlistExpander()
        expanded_netlist = netlist_expander.expand(
            extracted_netlist=pex_context.lvsdb.netlist(),
            top_cell_name=pex_context.top_cell.name,
            cap_matrix=cap_matrix,
            blackbox_devices=args.blackbox_devices
        )

        spice_writer = kdb.NetlistSpiceWriter()
        spice_writer.use_net_names = True
        spice_writer.with_comments = False
        expanded_netlist.write(expanded_netlist_path, spice_writer)
        info(f"Wrote expanded netlist to: {expanded_netlist_path}")

        netlist_reducer = NetlistReducer()
        reduced_netlist = netlist_reducer.reduce(netlist=expanded_netlist,
                                                 top_cell_name=pex_context.top_cell.name)
        reduced_netlist.write(reduced_netlist_path, spice_writer)
        info(f"Wrote reduced netlist to: {reduced_netlist_path}")

    def run_kpex_2_5d_engine(self,
                             args: argparse.Namespace,
                             pex_context: KLayoutExtractionContext,
                             tech_info: TechInfo,
                             report_path: str,
                             netlist_csv_path: str):
        extractor = RCExtractor(pex_context=pex_context,
                                tech_info=tech_info,
                                report_path=report_path)
        extraction_results = extractor.extract()

        with open(netlist_csv_path, 'w') as f:
            f.write('Device;Net1;Net2;Capacitance [fF]\n')
            # f.write('Device;Net1;Net2;Capacitance [F];Capacitance [fF]\n')
            summary = extraction_results.summarize()
            for idx, (key, cap_value) in enumerate(summary.capacitances.items()):
                # f.write(f"C{idx + 1};{key.net1};{key.net2};{cap_value / 1e15};{round(cap_value, 3)}\n")
                f.write(f"C{idx + 1};{key.net1};{key.net2};{round(cap_value, 3)}\n")

        rule("kpex/2.5D extracted netlist (CSV format):")
        with open(netlist_csv_path, 'r') as f:
            for line in f.readlines():
                subproc(line[:-1])  # abusing subproc, simply want verbatim

        rule("Extracted netlist CSV")
        subproc(f"{netlist_csv_path}")


        # NOTE: there was a KLayout bug that some of the categories were lost,
        #       so that the marker browser could not load the report file
        try:
            report = rdb.ReportDatabase('')
            report.load(report_path)  # try loading rdb
        except Exception as e:
            rule("Repair broken marker DB")
            warning(f"Detected KLayout bug: RDB can't be loaded due to exception {e}")
            repair_rdb(report_path)

        return extraction_results

    def setup_logging(self, args: argparse.Namespace):
        def register_log_file_handler(log_path: str,
                                      formatter: Optional[logging.Formatter]) -> logging.Handler:
            handler = logging.FileHandler(log_path)
            handler.setLevel(LogLevel.SUBPROCESS)
            if formatter:
                handler.setFormatter(formatter)
            register_additional_handler(handler)
            return handler

        def reregister_log_file_handler(handler: logging.Handler,
                                        log_path: str,
                                        formatter: Optional[logging.Formatter]):
            deregister_additional_handler(handler)
            handler.flush()
            handler.close()
            os.makedirs(args.output_dir_path, exist_ok=True)
            new_path = os.path.join(args.output_dir_path, os.path.basename(log_path))
            if os.path.exists(new_path):
                ctime = os.path.getctime(new_path)
                dt = datetime.fromtimestamp(ctime)
                timestamp = dt.strftime('%Y-%m-%d_%H-%M-%S')
                backup_path = f"{new_path[:-4]}_{timestamp}.bak.log"
                shutil.move(new_path, backup_path)
            log_path = shutil.move(log_path, new_path)
            register_log_file_handler(log_path, formatter)

        # setup preliminary logger
        cli_log_path_plain = os.path.join(args.output_dir_base_path, f"kpex_plain.log")
        cli_log_path_formatted = os.path.join(args.output_dir_base_path, f"kpex.log")
        formatter = logging.Formatter('[%(asctime)s] [%(levelname)s]    %(message)s')
        file_handler_plain = register_log_file_handler(cli_log_path_plain, None)
        file_handler_formatted = register_log_file_handler(cli_log_path_formatted, formatter)
        try:
            self.validate_args(args)
        except ArgumentValidationError:
            if hasattr(args, 'output_dir_path'):
                reregister_log_file_handler(file_handler_plain, cli_log_path_plain, None)
                reregister_log_file_handler(file_handler_formatted, cli_log_path_formatted, formatter)
            sys.exit(1)
        reregister_log_file_handler(file_handler_plain, cli_log_path_plain, None)
        reregister_log_file_handler(file_handler_formatted, cli_log_path_formatted, formatter)

        set_log_level(args.log_level)

    @staticmethod
    def modification_date(filename: str) -> datetime:
        t = os.path.getmtime(filename)
        return datetime.fromtimestamp(t)

    def create_lvsdb(self, args: argparse.Namespace) -> kdb.LayoutVsSchematic:
        lvsdb = kdb.LayoutVsSchematic()

        match args.input_mode:
            case InputMode.LVSDB:
                lvsdb.read(args.lvsdb_path)
            case InputMode.GDS:
                lvs_log_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_lvs.log")
                lvsdb_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}.lvsdb.gz")
                lvsdb_cache_path = os.path.join(args.cache_dir_path, args.pdk,
                                                os.path.splitroot(os.path.abspath(args.gds_path))[-1],
                                                f"{args.effective_cell_name}.lvsdb.gz")

                lvs_needed = True

                if args.cache_lvs:
                    if not os.path.exists(lvsdb_cache_path):
                        info(f"Cache miss: extracted LVSDB does not exist")
                        subproc(lvsdb_cache_path)
                    elif self.modification_date(lvsdb_cache_path) <= self.modification_date(args.gds_path):
                        info(f"Cache miss: extracted LVSDB is older than the input GDS")
                        subproc(lvsdb_cache_path)
                    else:
                        warning(f"Cache hit: Reusing cached LVSDB")
                        subproc(lvsdb_cache_path)
                        lvs_needed = False

                if lvs_needed:
                    lvs_runner = LVSRunner()
                    lvs_runner.run_klayout_lvs(exe_path=args.klayout_exe_path,
                                               lvs_script=args.lvs_script_path,
                                               gds_path=args.effective_gds_path,
                                               schematic_path=args.effective_schematic_path,
                                               log_path=lvs_log_path,
                                               lvsdb_path=lvsdb_path)
                    if args.cache_lvs:
                        cache_dir_path = os.path.dirname(lvsdb_cache_path)
                        if not os.path.exists(cache_dir_path):
                            os.makedirs(cache_dir_path, exist_ok=True)
                        shutil.copy(lvsdb_path, lvsdb_cache_path)

                lvsdb.read(lvsdb_path)
        return lvsdb

    def main(self, argv: List[str]):
        if '-v' not in argv and \
           '--version' not in argv and \
           '-h' not in argv and \
           '--help' not in argv:
            rule('Command line arguments')
            subproc(' '.join(map(shlex.quote, sys.argv)))

        args = self.parse_args(argv[1:])

        os.makedirs(args.output_dir_base_path, exist_ok=True)
        self.setup_logging(args)

        tech_info = TechInfo.from_json(args.tech_pbjson_path,
                                       dielectric_filter=args.dielectric_filter)

        if args.run_magic:
            rule('MAGIC')
            self.run_magic_extraction(args)

        # no need to run LVS etc if only running magic engine
        if not (args.run_fastcap or args.run_fastercap or args.run_2_5D):
            return

        rule('Prepare LVSDB')
        lvsdb = self.create_lvsdb(args)

        pex_context = KLayoutExtractionContext.prepare_extraction(top_cell=args.effective_cell_name,
                                                                  lvsdb=lvsdb,
                                                                  tech=tech_info,
                                                                  blackbox_devices=args.blackbox_devices)
        rule('Non-empty layers in LVS database')
        for gds_pair, layer_info in pex_context.extracted_layers.items():
            names = [l.lvs_layer_name for l in layer_info.source_layers]
            info(f"{gds_pair} -> ({' '.join(names)})")

        gds_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_l2n_extracted.gds.gz")
        pex_context.target_layout.write(gds_path)

        gds_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_l2n_internal.gds.gz")
        pex_context.lvsdb.internal_layout().write(gds_path)

        def dump_layers(cell: str,
                        layers: List[KLayoutExtractedLayerInfo],
                        layout_dump_path: str):
            layout = kdb.Layout()
            layout.dbu = lvsdb.internal_layout().dbu

            top_cell = layout.create_cell(cell)
            for ulyr in layers:
                li = kdb.LayerInfo(*ulyr.gds_pair)
                li.name = ulyr.lvs_layer_name
                layer = layout.insert_layer(li)
                layout.insert(top_cell.cell_index(), layer, ulyr.region.dup())

            layout.write(layout_dump_path)

        if len(pex_context.unnamed_layers) >= 1:
            layout_dump_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_unnamed_LVS_layers.gds.gz")
            dump_layers(cell=args.effective_cell_name,
                        layers=pex_context.unnamed_layers,
                        layout_dump_path=layout_dump_path)

        if len(pex_context.extracted_layers) >= 1:
            layout_dump_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_nonempty_LVS_layers.gds.gz")
            nonempty_layers = [l \
                               for layers in pex_context.extracted_layers.values() \
                               for l in layers.source_layers]
            dump_layers(cell=args.effective_cell_name,
                        layers=nonempty_layers,
                        layout_dump_path=layout_dump_path)
        else:
            error("No extracted layers found")
            sys.exit(1)

        if args.run_fastcap or args.run_fastercap:
            lst_file = self.build_fastercap_input(args=args,
                                                  pex_context=pex_context,
                                                  tech_info=tech_info)
            if args.run_fastercap:
                self.run_fastercap_extraction(args=args,
                                              pex_context=pex_context,
                                              lst_file=lst_file)
            if args.run_fastcap:
                self.run_fastcap_extraction(args=args,
                                            pex_context=pex_context,
                                            lst_file=lst_file)

        if args.run_2_5D:
            rule("kpex/2.5D PEX Engine")
            report_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_k25d_pex_report.rdb.gz")
            netlist_csv_path = os.path.abspath(os.path.join(args.output_dir_path, f"{args.effective_cell_name}_k25d_pex_netlist.csv"))

            self._rcx25_extraction_results = self.run_kpex_2_5d_engine(  # NOTE: store for test case
                args=args,
                pex_context=pex_context,
                tech_info=tech_info,
                report_path=report_path,
                netlist_csv_path=netlist_csv_path
            )

            self._rcx25_extracted_csv_path = netlist_csv_path

    @property
    def rcx25_extraction_results(self) -> ExtractionResults:
        if not hasattr(self, '_rcx25_extraction_results'):
            raise Exception('rcx25_extraction_results is not initialized, was run_kpex_2_5d_engine called?')
        return self._rcx25_extraction_results

    @property
    def rcx25_extracted_csv_path(self) -> str:
        if not hasattr(self, '_rcx25_extracted_csv_path'):
            raise Exception('rcx25_extracted_csv_path is not initialized, was run_kpex_2_5d_engine called?')
        return self._rcx25_extracted_csv_path

    @property
    def fastercap_extracted_csv_path(self) -> str:
        if not hasattr(self, '_fastercap_extracted_csv_path'):
            raise Exception('fastercap_extracted_csv_path is not initialized, was run_fastercap_extraction called?')
        return self._fastercap_extracted_csv_path


if __name__ == "__main__":
    cli = KpexCLI()
    cli.main(sys.argv)
