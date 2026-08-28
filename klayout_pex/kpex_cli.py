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
import contextlib
from datetime import datetime
from enum import StrEnum
import logging
import os
import os.path
from pathlib import Path
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

from .common.path_validation import validate_files, FileValidationResult
from .env import EnvVar, Env
from .extraction_engine import ExtractionEngine
from .fastercap.fastercap_input_builder import FasterCapInputBuilder
from .fastercap.fastercap_model_generator import FasterCapModelGenerator
from .fastercap.fastercap_runner import run_fastercap, fastercap_parse_capacitance_matrix
from .fastcap.fastcap_runner import run_fastcap, fastcap_parse_capacitance_matrix
from .klayout.lvs_runner import LVSRunner
from .klayout.lvsdb_extractor import KLayoutExtractionContext, KLayoutExtractedLayerInfo
from .klayout.netlist_expander import NetlistExpander
from .klayout.netlist_csv import NetlistCSVWriter
from .klayout.netlist_printer import NetlistPrinter
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
from .magic.magic_ext_file_parser import parse_magic_pex_run
from .magic.magic_runner import (
    MagicPEXMode,
    MagicShortMode,
    MagicMergeMode,
    MagicUniqueMode,
    run_magic,
    prepare_magic_script,
)
from .magic.magic_log_analyzer import MagicLogAnalyzer
from .pex25d.artifact import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactNamingError,
    infer_artifact_spec,
)
from .klayout.pex25d_builder import DEFAULT_GRID_UM
from .pex25d.diagnostics import DiagnosticsReport, ExitCode, diagnostics_stream
from .pex25d.pex25d_cli import Pex25DCLI
from .pdk_config import PDK, PDKConfig
from .rcx25.extractor import RCX25Extractor, ExtractionResults
from .rcx25.netlist_expander import RCX25NetlistExpander
from .rcx25.pex_mode import PEXMode
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


class KpexCLI:
    # ---------------------------------------------------------- argument groups
    #
    # Each group is attached to a *given* parser rather than to one flat parser,
    # so that a subcommand declares exactly the options it can act on. That is
    # the point of the verb layer: `kpex pex25d` cannot be handed --magic_halo,
    # and the validation below no longer has to hand-check which combinations
    # of flags make sense together.

    @staticmethod
    def _add_special_options(parser: argparse.ArgumentParser,
                             include_threads: bool = False) -> None:
        group_special = parser.add_argument_group("Special Options")
        group_special.add_argument("--help", "-h", action='help',
                                   help="show this help message and exit")
        group_special.add_argument("--log_level", dest='log_level', default='subprocess',
                                   help=render_enum_help(topic='log_level', enum_cls=LogLevel))
        if include_threads:
            group_special.add_argument("--threads", dest='num_threads', type=int,
                                       default=os.cpu_count() * 4,
                                       help="number of threads (e.g. for FasterCap) "
                                            "(default is %(default)s)")

    @staticmethod
    def _add_pex_setup_arguments(parser: argparse.ArgumentParser,
                                 env: Env,
                                 include_spice_output: bool = True) -> None:
        group_pex = parser.add_argument_group("Parasitic Extraction Setup")

        all_pdk_choices = list(PDK) + list(PDK.legacy_aliases().keys())

        default_pdk = env.default_pdk
        pdk_help = render_enum_help(topic='pdk', enum_cls=PDK, print_default=False)
        if default_pdk:
            pdk_help += f" (default is '{default_pdk}')"

        group_pex.add_argument("--pdk", dest="pdk", required=default_pdk is None,
                               type=PDK.from_string, choices=all_pdk_choices,
                               help=pdk_help, default=default_pdk)

        group_pex.add_argument("--out_dir", dest="output_dir_base_path", default="output",
                               help="Run directory path (default is '%(default)s')")

        if include_spice_output:
            group_pex.add_argument("--out_spice", "-o", dest="output_spice_path", default=None,
                                   help="Optional additional SPICE output path (default is none)")


    @staticmethod
    def _add_pex_input_arguments(parser: argparse.ArgumentParser) -> None:
        group_pex_input = parser.add_argument_group("Parasitic Extraction Input",
                                                         description="Either LVS is run, or an existing LVSDB is used")
        group_pex_input.add_argument("--gds", "-g", dest="gds_path", default=None,
                                     help="GDS path (for LVS)")
        group_pex_input.add_argument("--schematic", "-s", dest="schematic_path",
                                     help="Schematic SPICE netlist path (for LVS). "
                                          "If none given, a dummy schematic will be created")
        # Developer shortcut, not a supported entry point. It exists so that a
        # PEX25D or engine run can be repeated without paying for LVS again while
        # working on the code downstream of it. An LVSDB is tied to the kpex
        # version and PDK that produced it and is not an interchange format —
        # PEX25D is. Anyone who wants to hand a scene to somebody else, or keep
        # one, should be writing PEX25D, not passing LVSDBs around.
        group_pex_input.add_argument("--lvsdb", "-l", dest="lvsdb_path", default=None,
                                     help="KLayout PEX-LVSDB path from a previous run "
                                          "(bypass PEX-LVS). Developer shortcut for "
                                          "re-running without repeating LVS; not an "
                                          "interchange format — use PEX25D for that")
        group_pex_input.add_argument("--cell", "-c", dest="cell_name", default=None,
                                     help="Cell (default is the top cell)")

        group_pex_input.add_argument("--cache-lvs", dest="cache_lvs",
                                     type=true_or_false, default=True,
                                     help="Used cached LVSDB (for given input GDS) (default is %(default)s)")
        group_pex_input.add_argument("--cache-dir", dest="cache_dir_path", default=None,
                                     help="Path for cached LVSDB (default is .kpex_cache within --out_dir)")
        group_pex_input.add_argument("--lvs-verbose", dest="klayout_lvs_verbose",
                                     type=true_or_false, default=False,
                                     help="Verbose KLayout LVS output (default is %(default)s)")


    @staticmethod
    def _add_engine_arguments(parser: argparse.ArgumentParser) -> None:
        group_pex_options = parser.add_argument_group("Extraction Engines")
        group_pex_options.add_argument("--fastercap", dest="run_fastercap",
                                      action='store_true', default=False,
                                      help="Run FasterCap engine (default is %(default)s)")
        group_pex_options.add_argument("--fastcap", dest="run_fastcap",
                                      action='store_true', default=False,
                                      help="Run FastCap2 engine (default is %(default)s)")
        group_pex_options.add_argument("--magic", dest="run_magic",
                                      action='store_true', default=False,
                                      help="Run MAGIC engine (default is %(default)s)")
        group_pex_options.add_argument("--2.5D", dest="run_2_5D",
                                      action='store_true', default=False,
                                      help="Run 2.5D analytical engine (default is %(default)s)")


    @staticmethod
    def _add_extraction_options(parser: argparse.ArgumentParser) -> None:
        group_pex_options = parser.add_argument_group("Parasitic Extraction Options")
        group_pex_options.add_argument("--blackbox", dest="blackbox_devices",
                                      type=true_or_false, default=False,  # TODO: in the future this should be True by default
                                      help="Blackbox devices like MIM/MOM caps, as they are handled by SPICE models "
                                           "(default is %(default)s for testing now)")

    @staticmethod
    def _add_tech_arguments(parser: argparse.ArgumentParser) -> None:
        group_tech = parser.add_argument_group("Technology Options")
        group_tech.add_argument("--diel", dest="dielectric_filter",
                                type=str, default="all",
                                help=f"Comma separated list of dielectric filter patterns. "
                                     f"Allowed patterns are: (none, all, -dielname1, +dielname2) "
                                     f"(default is %(default)s)")

    @staticmethod
    def _add_fastercap_arguments(parser: argparse.ArgumentParser) -> None:
        group_fastercap = parser.add_argument_group("FasterCap Options")
        group_fastercap.add_argument("--k_void", "-k", dest="k_void",
                                     type=float, default=3.9,
                                     help="Dielectric constant of void (default is %(default)s)")

        # TODO: reflect that these are also now used by KPEX/2.5D engine!
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


    @staticmethod
    def _add_magic_arguments(parser: argparse.ArgumentParser, env: Env) -> None:
        group_magic = parser.add_argument_group("MAGIC Options")

        default_magicrc_path = env.default_magicrc_path
        if default_magicrc_path:
            magicrc_help = f"Path to magicrc configuration file (default is '{default_magicrc_path}')"
        else:
            magicrc_help = "Path to magicrc configuration file "\
                           "(default not available, PDK and PDK_ROOT must be set!)"

        group_magic.add_argument('--magicrc', dest='magicrc_path', default=default_magicrc_path,
                                  help=magicrc_help)
        group_magic.add_argument("--magic_mode", dest='magic_pex_mode',
                                 default=MagicPEXMode.DEFAULT, type=MagicPEXMode, choices=list(MagicPEXMode),
                                 help=render_enum_help(topic='magic_mode', enum_cls=MagicPEXMode))
        group_magic.add_argument("--magic_cthresh", dest="magic_cthresh",
                                 type=float, default=0.01,
                                 help="Threshold (in fF) for ignored parasitic capacitances (default is %(default)s). "
                                      "(MAGIC command: ext2spice cthresh <value>)")
        group_magic.add_argument("--magic_rthresh", dest="magic_rthresh",
                                 type=int, default=100,
                                 help="Threshold (in Ω) for ignored parasitic resistances (default is %(default)s). "
                                      "(MAGIC command: ext2spice rthresh <value>)")
        group_magic.add_argument("--magic_thresh", dest="magic_thresh",
                                 type=int, default=None,
                                 help="Lumped resistance threshold (in mΩ) to trigger network extraction. "
                                      "If not supplied, MAGIC's default is implicitly used. "
                                      "(MAGIC command: extresist threshold <value>)")
        group_magic.add_argument("--magic_minres", dest="magic_minres",
                                 type=int, default=None,
                                 help="Threshold (in mΩ) for removing individual resistors during network simplification. "
                                      "If not supplied, MAGIC's default is implicitly used. "
                                      "(MAGIC command: extresist minres <value>)")
        group_magic.add_argument("--magic_mindel", dest="magic_mindel",
                                 type=int, default=None,
                                 help="Minimum delay threshold (in ps) to trigger network extraction. "
                                      "If not supplied, MAGIC's default is implicitly used. "
                                      "(MAGIC command: extresist mindelay <value>)")
        group_magic.add_argument("--magic_halo", dest="magic_halo",
                                 type=float, default=None,
                                 help="Custom sidewall halo distance (in µm) "
                                      "(MAGIC command: extract halo <value>) (default is no custom halo)")
        group_magic.add_argument("--magic_short", dest='magic_short_mode',
                                 default=MagicShortMode.DEFAULT, type=MagicShortMode, choices=list(MagicShortMode),
                                 help=render_enum_help(topic='magic_short', enum_cls=MagicShortMode))
        group_magic.add_argument("--magic_merge", dest='magic_merge_mode',
                                 default=MagicMergeMode.DEFAULT, type=MagicMergeMode, choices=list(MagicMergeMode),
                                 help=render_enum_help(topic='magic_merge', enum_cls=MagicMergeMode))
        group_magic.add_argument("--magic_pre_flatten", dest='magic_pre_flatten',
                                 action='store_true', default=False,
                                 help="Flatten GDS before reading it with Magic (default is %(default)s).")
        group_magic.add_argument("--magic_unique", dest='magic_unique_mode',
                                 default=MagicUniqueMode.DEFAULT, type=MagicUniqueMode, choices=list(MagicUniqueMode),
                                 help="Control net uniqueness during extraction "
                                 " ('implicit' omits the command, uses MAGIC's default value). "
                                 + render_enum_help(topic='magic_unique', enum_cls=MagicUniqueMode))


    @staticmethod
    def _add_analytical_25d_arguments(parser: argparse.ArgumentParser) -> None:
        group_25d = parser.add_argument_group("2.5D Options")
        group_25d.add_argument("--mode", dest='pex_mode',
                               default=PEXMode.DEFAULT, type=PEXMode, choices=list(PEXMode),
                               help=render_enum_help(topic='mode', enum_cls=PEXMode))
        group_25d.add_argument("--halo", dest="halo",
                                 type=float, default=None,
                                 help="Custom sidewall halo distance (in µm) to override tech info "
                                      "(default is no custom halo)")
        group_25d.add_argument("--scale", dest="scale_ratio_to_fit_halo",
                                type=true_or_false, default=True,
                                help=f"Scale fringe ratios, so that halo distance is 100%% (default is %(default)s)")


    @staticmethod
    def _add_pex25d_output_arguments(parser: argparse.ArgumentParser) -> None:
        group_out = parser.add_argument_group(
            "PEX25D Output",
            description="At least one of --output_file / --output_scene must be given. "
                        "They are two options rather than one --emit switch because the "
                        "two artifacts are different things with different consumers, and "
                        "a single switch would leave it unclear where each one lands."
        )
        group_out.add_argument("--output_file", dest='pex25d_file_path',
                               default=None, metavar='PATH',
                               help="Write the unresolved PEX25DFile here ('-' for stdout). "
                                    "The literal form: one message per PEX25D record, "
                                    "references still plain strings, nothing derived. This is "
                                    "what a reader produces and what a validator checks.")
        group_out.add_argument("--output_scene", dest='pex25d_scene_path',
                               default=None, metavar='PATH',
                               help="Write the resolved PEX25DScene here ('-' for stdout). "
                                    "The adapter-ready form: absolute z extents, CONNECTS / "
                                    "BETWEEN / WRAPS resolved, wrap depth flattened, terminal "
                                    "intersections computed.")
        group_out.add_argument("--format", dest='pex25d_format',
                               default=ArtifactFormat.AUTO, type=ArtifactFormat,
                               choices=list(ArtifactFormat),
                               help="Override the encoding otherwise inferred from the output "
                                    "file names (default is '%(default)s'). Naming convention: "
                                    "NAME.pex25d is text, NAME.pex25d.pb is binary protobuf, "
                                    "NAME.pex25d.textpb is protobuf text format, and a .scene "
                                    "infix marks a resolved scene. A trailing .gz is honoured.")
        group_out.add_argument("--grid", dest='pex25d_grid',
                               default=DEFAULT_GRID_UM, metavar='UM',
                               help="Coordinate grid in µm (default is %(default)s). "
                                    "Every z offset, thickness and coordinate must be "
                                    "an integer multiple of it, and it must divide the "
                                    "layout DBU exactly.")
        group_out.add_argument("--domain_margin", dest='pex25d_domain_margin',
                               type=float, default=None, metavar='UM',
                               help="Emit DOMAIN_MARGIN with this clearance in µm "
                                    "(default is none, leaving the domain unset for "
                                    "the solver adapter to choose)")
        group_out.add_argument("--comments", dest='pex25d_comments',
                               type=true_or_false, default=False,
                               help="Include the syntax hints from the specification as "
                                    "comments (default is %(default)s). Text format only — "
                                    "the protobuf encodings have no comments.")
        group_out.add_argument("--with_source_refs", dest='pex25d_with_source_refs',
                               type=true_or_false, default=False,
                               help="Populate every SourceRef (default is %(default)s). "
                                    "Protobuf output formats only — the text format has no "
                                    "spelling for a source reference. Roughly doubles the size "
                                    "of a layout-scale file, and means little for geometry "
                                    "built in memory rather than parsed from text; useful "
                                    "mainly when diffing generated output against a "
                                    "hand-written file.")

    # ------------------------------------------------------------------ parsing

    @staticmethod
    def parse_args(arg_list: List[str],
                   env: Env) -> argparse.Namespace:
        # epilog = f"See '{PROGRAM_NAME} <subcommand> -h' for help on subcommand"
        epilog = EnvVar.help_epilog_table()
        epilog_md = rich.console.Group(
            rich.text.Text('Environmental variables:', style='argparse.groups'),
            rich.markdown.Markdown(epilog, style='argparse.text')
        )
        main_parser = argparse.ArgumentParser(prog=PROGRAM_NAME,
                                              description=f"{PROGRAM_NAME}: "
                                                          f"KLayout-integrated Parasitic Extraction Tool",
                                              epilog=epilog_md,
                                              add_help=False,
                                              formatter_class=RichHelpFormatter)

        group_special = main_parser.add_argument_group("Special Options")
        group_special.add_argument("--help", "-h", action='help',
                                   help="show this help message and exit")
        group_special.add_argument("--version", "-v", action='version',
                                   version=f'{PROGRAM_NAME} {__version__}')

        subparsers = main_parser.add_subparsers(dest="command", metavar='<subcommand>',
                                                help="Sub-commands help")

        parser_extract = subparsers.add_parser(
            "extract",
            help="Run one or more parasitic extraction engines",
            description="Run PEX end to end: LVS for connectivity, then the selected "
                        "engine(s), then netlist expansion and reduction.",
            add_help=False, formatter_class=RichHelpFormatter, epilog=epilog_md)
        KpexCLI._add_special_options(parser_extract, include_threads=True)
        KpexCLI._add_pex_setup_arguments(parser_extract, env)
        KpexCLI._add_pex_input_arguments(parser_extract)
        KpexCLI._add_engine_arguments(parser_extract)
        KpexCLI._add_extraction_options(parser_extract)
        KpexCLI._add_tech_arguments(parser_extract)
        KpexCLI._add_fastercap_arguments(parser_extract)
        KpexCLI._add_magic_arguments(parser_extract, env)
        KpexCLI._add_analytical_25d_arguments(parser_extract)

        parser_pex25d = subparsers.add_parser(
            "pex25d",
            help="Generate PEX25D solver input from a layout, without running a solver",
            description="Run LVS for connectivity and write the scene as PEX25D, stopping "
                        "before any engine is started. This is the cut point in the "
                        "pipeline that lets the geometry be inspected, archived, diffed, "
                        "or handed to somebody else's solver. Format-only work on the "
                        "result — validating, re-encoding, exporting to an engine's "
                        "native input — is the standalone 'pex25d' tool's job.",
            add_help=False, formatter_class=RichHelpFormatter, epilog=epilog_md)
        KpexCLI._add_special_options(parser_pex25d)
        KpexCLI._add_pex_setup_arguments(parser_pex25d, env, include_spice_output=False)
        KpexCLI._add_pex_input_arguments(parser_pex25d)
        KpexCLI._add_extraction_options(parser_pex25d)
        KpexCLI._add_tech_arguments(parser_pex25d)
        KpexCLI._add_pex25d_output_arguments(parser_pex25d)
        Pex25DCLI._add_diagnostics_arguments(parser_pex25d)

        if arg_list is None:
            arg_list = sys.argv[1:]
        args = main_parser.parse_args(arg_list)
        if args.command is None:
            main_parser.print_help()
            sys.exit(ExitCode.USAGE)

        # The engine switches only exist on 'extract'. Defaulting them here keeps
        # the shared validation and logging paths free of subcommand checks.
        for engine_attr in ('run_magic', 'run_fastcap', 'run_fastercap', 'run_2_5D'):
            if not hasattr(args, engine_attr):
                setattr(args, engine_attr, False)

        # environmental variables and their defaults
        args.fastcap_exe_path = env[EnvVar.FASTCAP_EXE]
        args.fastercap_exe_path = env[EnvVar.FASTERCAP_EXE]
        args.klayout_exe_path = env[EnvVar.KLAYOUT_EXE]
        args.magic_exe_path = env[EnvVar.MAGIC_EXE]

        return args

    @staticmethod
    def validate_args(args: argparse.Namespace):
        found_errors = False

        pdk_config: PDKConfig = args.pdk.config
        args.tech_pbjson_path = pdk_config.tech_pb_json_path
        args.lvs_script_path = pdk_config.pex_lvs_script_path

        def input_file_stem(path: str):
            # could be *.gds, or *.gds.gz, so remove all extensions
            return os.path.basename(path).split(sep='.')[0]

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

        # Which engines may be combined with which inputs is a question only
        # 'extract' has; a dump run has no engine to disagree with.
        if args.command == 'extract':
            # check engines VS input possiblities
            match (args.run_magic, args.run_fastcap, args.run_fastercap, args.run_2_5D,
                   args.gds_path, args.lvsdb_path):
                case (True, _, _, _, None, _):
                    error(f"Running PEX engine MAGIC requires --gds (--lvsdb not possible)")
                    found_errors = True
                case (False, False, False, False, _, _): # at least one engine must be activated
                    error("No PEX engines activated")
                    engine_help = """
            | Argument     | Description                     |
            | ------------ | ------------------------------- |
            | --2.5D       | Run KPEX/2.5D analytical engine |
            | --fastcap    | Run KPEX/FastCap2 3D engine     |
            | --fastercap  | Run KPEX/FasterCap 3D engine    |
            | --magic      | Run MAGIC wrapper engine        |
            """
                    subproc(f"\n\nPlease activate one or more engines using the arguments:")
                    rich.print(rich.markdown.Markdown(engine_help, style='argparse.text'))
                    found_errors = True
                case (_, _, _, _, None, None):
                    error(f"Neither GDS nor LVSDB was provided")
                    found_errors = True

        # check if we find magicrc
        if args.run_magic:
            if args.magicrc_path is None:
                error(f"magicrc not available, requires any those:\n"
                      f"\t• set environmental variables PDK_ROOT / PDK\n"
                      f"\t• pass argument --magicrc")
                found_errors = True
            else:
                result = validate_files([args.magicrc_path])
                for f in result.failures:
                    error(f"Invalid magicrc: {f.reason} at {str(f.path)}")
                    found_errors = True

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
                        run_dir_id = f"{input_file_stem(args.gds_path)}__{args.effective_cell_name}"
                        args.output_dir_path = os.path.join(args.output_dir_base_path, run_dir_id)
                        os.makedirs(args.output_dir_path, exist_ok=True)
                        args.effective_gds_path = os.path.join(args.output_dir_path,
                                                               f"{args.cell_name}_exported.gds.gz")
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

                if not hasattr(args, 'effective_gds_path'):
                    args.effective_gds_path = args.gds_path
        elif args.lvsdb_path is not None:
            info(f"LVSDB input file passed, bypassing LVS")
            args.input_mode = InputMode.LVSDB
            if not os.path.isfile(args.lvsdb_path):
                error(f"Can't read KLayout LVSDB file at path {args.lvsdb_path}")
                found_errors = True
            else:
                lvsdb = kdb.LayoutVsSchematic()
                lvsdb.read(args.lvsdb_path)
                top_cell: kdb.Cell = lvsdb.internal_top_cell()
                args.effective_cell_name = top_cell.name

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
                    with open(args.effective_schematic_path, 'w', encoding='utf-8') as f:
                        f.writelines([
                            f".subckt {args.effective_cell_name} VDD VSS\n",
                            '.ends\n',
                            '.end\n'
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

        if args.cache_dir_path is None:
            args.cache_dir_path = os.path.join(args.output_dir_base_path, '.kpex_cache')

        if args.command == 'pex25d':
            if args.pex25d_file_path is None and args.pex25d_scene_path is None:
                error("Nothing to write. Give --output_file (the unresolved PEX25DFile), "
                      "--output_scene (the resolved PEX25DScene), or both.")
                found_errors = True

            if args.pex25d_file_path is not None \
                    and args.pex25d_file_path == args.pex25d_scene_path:
                error("--output_file and --output_scene point at the same destination")
                found_errors = True

            # Resolved here rather than at write time so that a mistyped output
            # name fails now, and not after a multi-minute LVS run.
            args.pex25d_file_spec = None
            args.pex25d_scene_spec = None
            try:
                if args.pex25d_file_path is not None:
                    args.pex25d_file_spec = infer_artifact_spec(
                        args.pex25d_file_path,
                        kind=ArtifactKind.FILE,
                        format=args.pex25d_format,
                        default_format=ArtifactFormat.TEXT)
                if args.pex25d_scene_path is not None:
                    args.pex25d_scene_spec = infer_artifact_spec(
                        args.pex25d_scene_path,
                        kind=ArtifactKind.SCENE,
                        format=args.pex25d_format,
                        default_format=ArtifactFormat.PB)
            except ArtifactNamingError as e:
                error(str(e))
                found_errors = True

        if found_errors:
            raise ArgumentValidationError("Argument validation failed")

    def create_netlist_printer(self,
                               args: argparse.Namespace,
                               extraction_engine: ExtractionEngine):
        printer = NetlistPrinter(extraction_engine=extraction_engine,
                                 pdk=args.pdk)
        return printer

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

        log_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FasterCap_Output.txt")
        raw_csv_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FasterCap_Result_Matrix_Raw.csv")
        avg_csv_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FasterCap_Result_Matrix_Avg.csv")
        expanded_netlist_path = os.path.join(args.output_dir_path,
                                             f"{args.effective_cell_name}_FasterCap_Expanded_Netlist.cir")
        expanded_netlist_csv_path = os.path.join(args.output_dir_path,
                                                 f"{args.effective_cell_name}_FasterCap_Expanded_Netlist.csv")
        reduced_netlist_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FasterCap_Reduced_Netlist.cir")

        run_fastercap(exe_path=args.fastercap_exe_path,
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
            top_cell_name=pex_context.annotated_top_cell.name,
            cap_matrix=cap_matrix,
            blackbox_devices=args.blackbox_devices
        )

        # create a nice CSV for reports, useful for spreadsheets
        netlist_csv_writer = NetlistCSVWriter()
        netlist_csv_writer.write_csv(netlist=expanded_netlist,
                                     top_cell_name=pex_context.annotated_top_cell.name,
                                     output_path=expanded_netlist_csv_path)

        rule("Extended netlist (CSV format):")
        with open(expanded_netlist_csv_path, 'r') as f:
            for line in f.readlines():
                subproc(line[:-1])  # abusing subproc, simply want verbatim
        rule()

        info(f"Wrote expanded netlist CSV to: {expanded_netlist_csv_path}")

        netlist_printer = self.create_netlist_printer(args, ExtractionEngine.FASTERCAP)
        netlist_printer.write(expanded_netlist, expanded_netlist_path)
        info(f"Wrote expanded netlist to: {expanded_netlist_path}")

        # FIXME: should this be already reduced?
        if args.output_spice_path:
            netlist_printer.write(expanded_netlist, args.output_spice_path)
            info(f"Copied expanded SPICE netlist to: {args.output_spice_path}")

        netlist_reducer = NetlistReducer()
        reduced_netlist = netlist_reducer.reduce(netlist=expanded_netlist,
                                                 top_cell_name=pex_context.annotated_top_cell.name)
        netlist_printer.write(reduced_netlist, reduced_netlist_path)
        info(f"Wrote reduced netlist to: {reduced_netlist_path}")

        self._fastercap_extracted_csv_path = expanded_netlist_csv_path

    def run_magic_extraction(self,
                             args: argparse.Namespace):
        if args.input_mode != InputMode.GDS:
            error(f"MAGIC engine only works with GDS input mode"
                  f" (currently {args.input_mode})")
            return

        magic_run_dir = os.path.join(args.output_dir_path, f"magic_{args.magic_pex_mode}")
        magic_log_path = os.path.join(magic_run_dir,
                                      f"{args.effective_cell_name}_MAGIC_{args.magic_pex_mode}_Output.txt")
        magic_script_path = os.path.join(magic_run_dir,
                                         f"{args.effective_cell_name}_MAGIC_{args.magic_pex_mode}_Script.tcl")

        output_netlist_path = os.path.join(magic_run_dir, f"{args.effective_cell_name}.pex.spice")
        report_db_path = os.path.join(magic_run_dir, f"{args.effective_cell_name}_MAGIC_report.rdb.gz")

        os.makedirs(magic_run_dir, exist_ok=True)

        layout = kdb.Layout()
        layout.read(args.effective_gds_path)

        if args.magic_pre_flatten:
            tops = list(layout.top_cells())
            if not tops:
                raise Exception("No top cells found in the input layout.")
            for top in tops:
                top.flatten(True)
            flattened_gds_path=os.path.join(magic_run_dir, f"{args.effective_cell_name}.gds")
            layout.write(flattened_gds_path)
            gds_path = flattened_gds_path
        else:
            gds_path = args.effective_gds_path

        prepare_magic_script(gds_path=gds_path,
                             cell_name=args.effective_cell_name,
                             run_dir_path=magic_run_dir,
                             script_path=magic_script_path,
                             output_netlist_path=output_netlist_path,
                             pex_mode=args.magic_pex_mode,
                             c_threshold=args.magic_cthresh,
                             r_threshold=args.magic_rthresh,
                             threshold=args.magic_thresh,
                             min_res=args.magic_minres,
                             min_delay=args.magic_mindel,
                             halo=args.magic_halo,
                             short_mode=args.magic_short_mode,
                             merge_mode=args.magic_merge_mode,
                             unique_mode=args.magic_unique_mode)

        run_magic(exe_path=args.magic_exe_path,
                  magicrc_path=args.magicrc_path,
                  script_path=magic_script_path,
                  log_path=magic_log_path)

        magic_pex_run = parse_magic_pex_run(Path(magic_run_dir))

        report = rdb.ReportDatabase('')
        magic_log_analyzer = MagicLogAnalyzer(magic_pex_run=magic_pex_run,
                                              report=report,
                                              dbu=layout.dbu)
        magic_log_analyzer.analyze()
        report.save(report_db_path)

        rule("Paths")
        subproc(f"Report DB saved at: {report_db_path}")
        subproc(f"SPICE netlist saved at: {output_netlist_path}")

        if os.path.exists(output_netlist_path):
            if args.output_spice_path and os.path.exists(output_netlist_path):
                shutil.copy(output_netlist_path, args.output_spice_path)
                info(f"Copied expanded SPICE netlist to: {args.output_spice_path}")

            rule("MAGIC PEX SPICE netlist")
            with open(output_netlist_path, 'r') as f:
                subproc(f.read())
            rule()

    def run_fastcap_extraction(self,
                               args: argparse.Namespace,
                               pex_context: KLayoutExtractionContext,
                               lst_file: str):
        rule('FastCap2 Execution')

        log_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FastCap2_Output.txt")
        raw_csv_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FastCap2_Result_Matrix_Raw.csv")
        avg_csv_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_FastCap2_Result_Matrix_Avg.csv")
        expanded_netlist_path = os.path.join(args.output_dir_path,
                                             f"{args.effective_cell_name}_FastCap2_Expanded_Netlist.cir")
        reduced_netlist_path = os.path.join(args.output_dir_path,
                                            f"{args.effective_cell_name}_FastCap2_Reduced_Netlist.cir")

        run_fastcap(exe_path=args.fastcap_exe_path,
                    lst_file_path=lst_file,
                    log_path=log_path)

        cap_matrix = fastcap_parse_capacitance_matrix(log_path)
        cap_matrix.write_csv(raw_csv_path)

        cap_matrix = cap_matrix.averaged_off_diagonals()
        cap_matrix.write_csv(avg_csv_path)

        netlist_expander = NetlistExpander()
        expanded_netlist = netlist_expander.expand(
            extracted_netlist=pex_context.lvsdb.netlist(),
            top_cell_name=pex_context.annotated_top_cell.name,
            cap_matrix=cap_matrix,
            blackbox_devices=args.blackbox_devices
        )

        netlist_printer = self.create_netlist_printer(args, ExtractionEngine.FASTCAP2)
        netlist_printer.write(expanded_netlist, expanded_netlist_path)
        info(f"Wrote expanded netlist to: {expanded_netlist_path}")

        # FIXME: should this be already reduced?
        if args.output_spice_path:
            netlist_printer.write(expanded_netlist, args.output_spice_path)
            info(f"Copied expanded SPICE netlist to: {args.output_spice_path}")

        netlist_reducer = NetlistReducer()
        reduced_netlist = netlist_reducer.reduce(netlist=expanded_netlist,
                                                 top_cell_name=pex_context.annotated_top_cell.name)
        netlist_printer.write(reduced_netlist, reduced_netlist_path)

        info(f"Wrote reduced netlist to: {reduced_netlist_path}")

    def run_kpex_2_5d_engine(self,
                             args: argparse.Namespace,
                             pex_context: KLayoutExtractionContext,
                             tech_info: TechInfo,
                             report_path: str,
                             netlist_csv_path: Optional[str],
                             expanded_netlist_path: Optional[str]):
        # TODO: make this separatly configurable
        #       for now we use 0
        args.rcx25d_delaunay_amax = 0
        args.rcx25d_delaunay_b = 0.5

        extractor = RCX25Extractor(pex_context=pex_context,
                                   pex_mode=args.pex_mode,
                                   delaunay_amax=args.rcx25d_delaunay_amax,
                                   delaunay_b=args.rcx25d_delaunay_b,
                                   scale_ratio_to_fit_halo=args.scale_ratio_to_fit_halo,
                                   tech_info=tech_info,
                                   report_path=report_path)
        extraction_results = extractor.extract()

        if netlist_csv_path is not None:
            # TODO: merge this with klayout_pex/klayout/netlist_csv.py

            with open(netlist_csv_path, 'w', encoding='utf-8') as f:
                summary = extraction_results.summarize()

                f.write('Device;Net1;Net2;Capacitance [fF];Resistance [Ω]\n')
                for idx, (key, cap_value) in enumerate(sorted(summary.capacitances.items())):
                    f.write(f"C{idx + 1};{key.net1};{key.net2};{round(cap_value, 3)};\n")
                for idx, (key, res_value) in enumerate(sorted(summary.resistances.items())):
                    f.write(f"R{idx + 1};{key.net1};{key.net2};;{round(res_value, 3)}\n")

            rule('kpex/2.5D extracted netlist (CSV format)')
            with open(netlist_csv_path, 'r') as f:
                for line in f.readlines():
                    subproc(line[:-1])  # abusing subproc, simply want verbatim

            rule('Extracted netlist CSV')
            subproc(f"{netlist_csv_path}")

        if expanded_netlist_path is not None:
            rule('kpex/2.5D extracted netlist (SPICE format)')
            netlist_expander = RCX25NetlistExpander()
            expanded_netlist = netlist_expander.expand(
                extracted_netlist=pex_context.lvsdb.netlist(),
                top_cell_name=pex_context.annotated_top_cell.name,
                extraction_results=extraction_results,
                blackbox_devices=args.blackbox_devices
            )

            netlist_printer = self.create_netlist_printer(args, ExtractionEngine.K25D)
            netlist_printer.write(expanded_netlist, expanded_netlist_path)
            subproc(f"Wrote expanded netlist to: {expanded_netlist_path}")

            # FIXME: should this be already reduced?
            if args.output_spice_path:
                netlist_printer.write(expanded_netlist, args.output_spice_path)
                info(f"Copied expanded SPICE netlist to: {args.output_spice_path}")

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
                                               lvsdb_path=lvsdb_path,
                                               verbose=args.klayout_lvs_verbose)
                    if args.cache_lvs:
                        cache_dir_path = os.path.dirname(lvsdb_cache_path)
                        if not os.path.exists(cache_dir_path):
                            os.makedirs(cache_dir_path, exist_ok=True)
                        shutil.copy(lvsdb_path, lvsdb_cache_path)

                lvsdb.read(lvsdb_path)
        return lvsdb

    SUBCOMMANDS = ('extract', 'pex25d')
    LEGACY_SUBCOMMAND = 'extract'

    @classmethod
    def normalize_argv(cls, argv: List[str]) -> List[str]:
        """
        Accept the pre-subcommand, flat command line.

        Before the verb layer, kpex was invoked as
        ``kpex --pdk sky130A --gds foo.gds --2.5D``. Every such run still works
        and means ``kpex extract <same options>``; it just warns. The two forms
        cannot be confused, because a subcommand name never begins with '-' and
        every legacy option does — so the fallback needs no heuristics and can
        never mistake one for the other.

        This exists for the scripts, CI jobs and docs that already say
        ``kpex --gds ...``, including the test suite. It is meant to be removed
        once those have moved on.
        """
        tail = argv[1:]
        if not tail:
            return argv
        first = tail[0]
        if first in ('-h', '--help', '-v', '--version'):
            return argv
        if not first.startswith('-'):
            return argv  # a subcommand, or a typo argparse will report better than we can
        if any(arg in cls.SUBCOMMANDS for arg in tail):
            # A subcommand is present, just not first — most likely a top-level
            # option that now belongs to the subcommand. Leave it alone and let
            # argparse say so, rather than silently rewriting it into something
            # that fails somewhere else.
            return argv
        warning(f"Calling {PROGRAM_NAME} without a subcommand is deprecated; "
                f"treating this run as '{PROGRAM_NAME} {cls.LEGACY_SUBCOMMAND} …'. "
                f"See '{PROGRAM_NAME} --help' for the available subcommands.")
        return [argv[0], cls.LEGACY_SUBCOMMAND] + tail

    @staticmethod
    def _writes_artifact_to_stdout(argv: List[str]) -> bool:
        """
        Whether this invocation sends a PEX25D artifact to stdout.

        Answered from the raw argv rather than from parsed arguments, because
        the redirect has to be in place before anything — argument validation
        included — has a chance to print.
        """
        return any(previous in ('--output_file', '--output_scene') and current == '-'
                   for previous, current in zip(argv, argv[1:]))

    def main(self, argv: List[str]):
        env = Env.from_os_environ()
        argv = self.normalize_argv(argv)

        # A PEX25D artifact may be destined for stdout, and in that case stdout
        # belongs to the artifact alone — one stray log line and whatever is on
        # the other end of the pipe is parsing garbage. Redirecting sys.stdout to
        # stderr for the whole run is blunt but total: the rich console resolves
        # sys.stdout at write time, so every rule()/info()/subproc() follows,
        # including ones written by code that never considered being in a
        # pipeline. Artifact I/O uses sys.__stdout__ and is unaffected.
        writes_to_stdout = self._writes_artifact_to_stdout(argv)

        with contextlib.ExitStack() as stack:
            if writes_to_stdout:
                stack.enter_context(contextlib.redirect_stdout(sys.stderr))

            if not ({'-v', '--version', '-h', '--help'} & set(argv)):
                rule('Command line arguments')
                subproc(' '.join(map(shlex.quote, argv)))

            args = self.parse_args(arg_list=argv[1:], env=env)

            os.makedirs(args.output_dir_base_path, exist_ok=True)
            self.setup_logging(args)

            tech_info = TechInfo.from_json(args.tech_pbjson_path,
                                           dielectric_filter=args.dielectric_filter)

            match args.command:
                case 'pex25d':
                    self.run_pex25d_generation(args=args, tech_info=tech_info)
                case _:
                    self.run_extraction(args=args, tech_info=tech_info)

    def run_pex25d_generation(self,
                              args: argparse.Namespace,
                              tech_info: TechInfo):
        """
        The dump path: LVS for connectivity, then PEX25D out, and stop.

        Deliberately does not touch any engine. Everything downstream of the
        artifacts written here — validating them, re-encoding them, exporting
        them to a solver's native input — is the standalone ``pex25d`` tool's
        job, and needs neither a layout nor KLayout to do it.
        """
        from .klayout.pex25d_builder import BuilderOptions, build_pex25d_file
        from .pex25d.codec import save_artifact
        from .pex25d.resolver import ResolveError, resolve

        report = DiagnosticsReport(warnings_are_errors=args.warnings_are_errors)

        rule('Prepare LVSDB')
        lvsdb = self.create_lvsdb(args)

        pex_context = KLayoutExtractionContext.prepare_extraction(
            top_cell=args.effective_cell_name,
            lvsdb=lvsdb,
            tech=tech_info,
            blackbox_devices=args.blackbox_devices)

        rule('Non-empty layers in LVS database')
        for gds_pair, layer_info in pex_context.extracted_layers.items():
            names = [l.lvs_layer_name for l in layer_info.source_layers]
            info(f"{gds_pair} -> ({' '.join(names)})")

        rule('PEX25D Generation')
        try:
            pex25d_file = build_pex25d_file(
                pex_context=pex_context,
                tech_info=tech_info,
                cell_name=args.effective_cell_name,
                options=BuilderOptions(
                    grid_um=args.pex25d_grid,
                    with_source_refs=args.pex25d_with_source_refs,
                    dielectric_filter=args.dielectric_filter,
                    domain_margin_um=args.pex25d_domain_margin))

            if args.pex25d_file_spec is not None:
                save_artifact(pex25d_file, args.pex25d_file_spec,
                              comments=args.pex25d_comments)
                info(f"Wrote {args.pex25d_file_spec}")

            if args.pex25d_scene_spec is not None:
                scene = resolve(pex25d_file, report=report, strict=args.strict)
                save_artifact(scene, args.pex25d_scene_spec,
                              comments=args.pex25d_comments)
                info(f"Wrote {args.pex25d_scene_spec}")

        except ResolveError as e:
            # The scene is not written: the diagnostics say why, and half a
            # scene is worse than none.
            error(str(e))
            report.render(args.diagnostics_format)
            sys.exit(ExitCode.DIAGNOSTIC_ERRORS)
        except NotImplementedError as e:
            error(f"Not implemented yet: {e}")
            sys.exit(ExitCode.NOT_IMPLEMENTED)

        writes_to_stdout = any(spec is not None and spec.is_stdio
                               for spec in (args.pex25d_file_spec, args.pex25d_scene_spec))
        with diagnostics_stream(writes_to_stdout=writes_to_stdout) as stream:
            report.render(args.diagnostics_format, stream=stream)

        if report.exit_code != ExitCode.OK:
            sys.exit(report.exit_code)

    def run_extraction(self,
                       args: argparse.Namespace,
                       tech_info: TechInfo):
        if args.halo is not None:
            tech_info.tech.process_parasitics.side_halo = args.halo

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

        gds_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_l2n_extracted.oas")
        pex_context.annotated_layout.write(gds_path)

        gds_path = os.path.join(args.output_dir_path, f"{args.effective_cell_name}_l2n_internal.oas")
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
            netlist_csv_path = os.path.abspath(os.path.join(args.output_dir_path,
                                                            f"{args.effective_cell_name}_k25d_pex_netlist.csv"))
            netlist_spice_path = os.path.abspath(os.path.join(args.output_dir_path,
                                                              f"{args.effective_cell_name}_k25d_pex_netlist.spice"))

            self._rcx25_extraction_results = self.run_kpex_2_5d_engine(  # NOTE: store for test case
                args=args,
                pex_context=pex_context,
                tech_info=tech_info,
                report_path=report_path,
                netlist_csv_path=netlist_csv_path,
                expanded_netlist_path=netlist_spice_path
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
