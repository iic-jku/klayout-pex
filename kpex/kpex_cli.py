#! /usr/bin/env python3

import argparse
from datetime import datetime
from enum import Enum, StrEnum
import logging
import os
import os.path
import shlex
import shutil
import sys
from typing import *

import klayout.db as kdb

from .fastercap.fastercap_input_builder import FasterCapInputBuilder
from .fastercap.fastercap_model_generator import FasterCapModelGenerator
from .fastercap.fastercap_runner import run_fastercap, fastercap_parse_capacitance_matrix
from .fastercap.netlist_expander import NetlistExpander
from .klayout.lvs_runner import LVSRunner
from .klayout.lvsdb_extractor import KLayoutExtractionContext
from .klayout.netlist_reducer import NetlistReducer
from .log import (
    LogLevel,
    set_log_level,
    register_additional_handler,
    deregister_additional_handler,
    # console,
    # debug,
    info,
    # warning,
    error
)
from .tech_info import TechInfo
from .version import __version__


# ------------------------------------------------------------------------------------

PROGRAM_NAME = "kpex"


class InputMode(StrEnum):
    LVSDB = "lvsdb"
    GDS = "gds"


def render_enum_help(topic: str,
                     enum_cls: Type[Enum],
                     print_default: bool = True) -> str:
    if not hasattr(enum_cls, 'DEFAULT'):
        raise ValueError("Enum must declare case 'DEFAULT'")
    enum_help = f"{topic} ∈ {set([name.lower() for name, member in enum_cls.__members__.items()])}"
    if print_default:
        enum_help += f".\nDefaults to '{enum_cls.DEFAULT.name.lower()}'"
    return enum_help


def true_or_false(arg) -> bool:
    if isinstance(arg, bool):
        return arg

    match str(arg).lower():
        case 'yes' | 'true' | 't' | 'y' | 1:
            return True
        case 'no' | 'false' | 'f' | 'n' | 0:
            return False
        case _:
            raise argparse.ArgumentTypeError('Boolean value expected.')


def parse_args(arg_list: List[str] = None) -> argparse.Namespace:
    main_parser = argparse.ArgumentParser(description=f"{PROGRAM_NAME}: "
                                                      f"KLayout-integrated Parasitic Extraction Tool",
                                          epilog=f"See '{PROGRAM_NAME} <subcommand> -h' for help on subcommand",
                                          add_help=False)
    group_special = main_parser.add_argument_group("Special options")
    group_special.add_argument("--help", "-h", action='help', help="show this help message and exit")
    group_special.add_argument("--version", "-v", action='version', version=f'{PROGRAM_NAME} {__version__}')
    group_special.add_argument("--log_level", dest='log_level', default='subprocess',
                               help=render_enum_help(topic='log_level', enum_cls=LogLevel))
    group_special.add_argument("--threads", dest='num_threads', type=int, default=0,
                               help="number of threads (e.g. for FasterCap)")
    group_special.add_argument('--klayout', dest='klayout_exe_path', default='klayout',
                               help="Path to klayout executuable (default is 'klayout')")

    group_pex = main_parser.add_argument_group("Parasitic Extraction Setup")
    group_pex.add_argument("--tech", "-t", dest="tech_pbjson_path", required=True,
                           help="Technology Protocol Buffer path (*.pb.json)")

    group_pex.add_argument("--out_dir", "-o", dest="output_dir_base_path", default=".",
                           help="Output directory path")

    group_pex_input = main_parser.add_argument_group("Parasitic Extraction Input",
                                                     description="Either LVS is run, or an existing LVSDB is used")
    group_pex_input.add_argument("--gds", "-g", dest="gds_path", help="GDS path (for LVS)")
    group_pex_input.add_argument("--schematic", "-s", dest="schematic_path",
                                 help="Schematic SPICE netlist path (for LVS)")
    group_pex_input.add_argument("--lvsdb", "-l", dest="lvsdb_path", help="KLayout LVSDB path (bypass LVS)")
    group_pex_input.add_argument("--cell", "-c", dest="cell_name", default="TOP", help="Cell (default is TOP)")
    default_lvs_script_path = os.path.join(os.environ['HOME'],
                                           '.klayout', 'salt', 'sky130A_el', 'lvs', 'core', 'sky130.lvs')
    group_pex_input.add_argument("--lvs_script", dest="lvs_script_path",
                                 default=default_lvs_script_path,
                                 help=f"Path to KLayout LVS script (default is {default_lvs_script_path})")

    group_fastercap = main_parser.add_argument_group("FasterCap options")
    group_fastercap.add_argument("--k_void", "-k", dest="k_void",
                                 type=float, default=3.9,
                                 help="Dielectric constant of void (default is 3.9)")
    group_fastercap.add_argument("--delaunay_amax", "-a", dest="delaunay_amax",
                                 type=float, default=0.5,
                                 help="Delaunay triangulation maximum area (default is 0.5)")
    group_fastercap.add_argument("--delaunay_b", "-b", dest="delaunay_b",
                                 type=float, default=0.5,
                                 help="Delaunay triangulation b (default is 0.5)")
    group_fastercap.add_argument("--geo_check", dest="geometry_check",
                                 type=true_or_false, default=False,
                                 help=f"Validate geometries before passing to FasterCap "
                                      f"(default is False)")
    group_fastercap.add_argument("--blackbox", dest="blackbox_devices",
                                 type=true_or_false, default=False,  # TODO: in the future this should be True by default
                                 help="Blackbox devices like MIM/MOM caps, as they are handled by SPICE models"
                                      "(default is False for testing now)")

    group_fastercap.add_argument("--tolerance", dest="fastercap_tolerance",
                                 type=float, default=0.05,
                                 help="FasterCap -aX error tolerance (default is 0.05)")
    group_fastercap.add_argument("--d_coeff", dest="fastercap_d_coeff",
                                 type=float, default=0.5,
                                 help=f"FasterCap -d direct potential interaction coefficient to mesh refinement "
                                      f"(default is 0.5)")
    group_fastercap.add_argument("--mesh", dest="fastercap_mesh_refinement_value",
                                 type=float, default=0.5,
                                 help=f"FasterCap -m Mesh relative refinement value "
                                      f"(default is 0.5)")
    group_fastercap.add_argument("--ooc", dest="fastercap_ooc_condition",
                                 type=float, default=2,
                                 help="FasterCap -f out-of-core free memory to link memory condition "
                                      "(0 = don't go OOC, default is 2)")
    group_fastercap.add_argument("--auto_precond", dest="fastercap_auto_preconditioner",
                                 type=true_or_false, default=True,
                                 help=f"FasterCap -ap Automatic preconditioner usage "
                                      f"(default is True)")
    group_fastercap.add_argument("--galerkin", dest="fastercap_galerkin_scheme",
                                 action='store_true', default=False,
                                 help=f"FasterCap -g Use Galerkin scheme "
                                      f"(default is False)")
    group_fastercap.add_argument("--jacobi", dest="fastercap_jacobi_preconditioner",
                                 action='store_true', default=False,
                                 help=f"FasterCap -pj Use Jacobi Preconditioner "
                                      f"(default is False)")

    if arg_list is None:
        arg_list = sys.argv[1:]
    args = main_parser.parse_args(arg_list)
    return args


def validate_args(args: argparse.Namespace):
    found_errors = False

    if not os.path.isfile(args.klayout_exe_path):
        path = shutil.which(args.klayout_exe_path)
        if not path:
            error(f"Can't locate KLayout executable at {args.klayout_exe_path}")
            found_errors = True
    
    if not os.path.isfile(args.tech_pbjson_path):
        error(f"Can't read technology file at path {args.tech_pbjson_path}")
        found_errors = True

    # input mode: LVS or existing LVSDB?
    if args.gds_path:
        info(f"GDS input file passed, running in LVS mode")
        args.input_mode = InputMode.GDS
        if not os.path.isfile(args.gds_path):
            error(f"Can't read GDS file (LVS input) at path {args.gds_path}")
            found_errors = True
        if not args.schematic_path:
            info(f"LVS input schematic not specified (argument --schematic), using dummy schematic")
        elif not os.path.isfile(args.schematic_path):
            error(f"Can't read schematic (LVS input) at path {args.schematic_path}")
            found_errors = True
    else:
        info(f"LVSDB input file passed, bypassing LVS")
        args.input_mode = InputMode.LVSDB
        if not hasattr(args, 'lvsdb_path'):
            error(f"LVSDB input path not specified (argument --lvsdb)")
            found_errors = True
        elif not os.path.isfile(args.lvsdb_path):
            error(f"Can't read KLayout LVSDB file at path {args.lvsdb_path}")
            found_errors = True

    try:
        args.log_level = LogLevel[args.log_level.upper()]
    except KeyError:
        error(f"Requested log level {args.log_level.lower()} does not exist, "
              f"{render_enum_help(topic='log_level', enum_cls=LogLevel, print_default=False)}")
        found_errors = True

    def input_file_stem(path: str):
        # could be *.gds, or *.gds.gz, so remove all extensions
        return os.path.basename(path).split(sep='.')[0]

    run_dir_id: str
    match args.input_mode:
        case InputMode.GDS:
            run_dir_id = f"{input_file_stem(args.gds_path)}__{args.cell_name}"
        case InputMode.LVSDB:
            run_dir_id = f"{input_file_stem(args.lvsdb_path)}__{args.cell_name}"
        case _:
            run_dir_id = args.cell_name
    args.output_dir_path = os.path.join(args.output_dir_base_path, run_dir_id)

    if found_errors:
        raise Exception("Argument validation failed")


def run_fastercap_extraction(args: argparse.Namespace,
                             pex_context: KLayoutExtractionContext,
                             tech_info: TechInfo):
    num_threads = args.num_threads if args.num_threads > 0 else os.cpu_count() * 4
    info(f"Configure number of OpenMP threads (environmental variable OMP_NUM_THREADS) as {num_threads}")
    os.environ['OMP_NUM_THREADS'] = f"{num_threads}"

    fastercap_input_builder = FasterCapInputBuilder(pex_context=pex_context,
                                                    tech_info=tech_info,
                                                    k_void=args.k_void,
                                                    delaunay_amax=args.delaunay_amax,
                                                    delaunay_b=args.delaunay_b)
    gen: FasterCapModelGenerator = fastercap_input_builder.build()

    if args.geometry_check:
        gen.check()

    faster_cap_input_dir_path = os.path.join(args.output_dir_path, 'FasterCap_Input_Files')
    os.makedirs(faster_cap_input_dir_path, exist_ok=True)

    lst_file = gen.write_fastcap(output_dir_path=faster_cap_input_dir_path, prefix='FasterCap_Input_')

    geometry_dir_path = os.path.join(args.output_dir_path, 'Geometries')
    os.makedirs(geometry_dir_path, exist_ok=True)
    gen.dump_stl(output_dir_path=geometry_dir_path, prefix='')

    exe_path = "FasterCap"
    log_path = os.path.join(args.output_dir_path, f"{args.cell_name}_FasterCap_Output.txt")
    raw_csv_path = os.path.join(args.output_dir_path, f"{args.cell_name}_FasterCap_Result_Matrix_Raw.csv")
    avg_csv_path = os.path.join(args.output_dir_path, f"{args.cell_name}_FasterCap_Result_Matrix_Avg.csv")
    expanded_netlist_path = os.path.join(args.output_dir_path, f"{args.cell_name}_Expanded_Netlist.cir")
    reduced_netlist_path = os.path.join(args.output_dir_path, f"{args.cell_name}_Reduced_Netlist.cir")

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
        cap_matrix=cap_matrix
    )

    spice_writer = kdb.NetlistSpiceWriter()
    spice_writer.use_net_names = True
    expanded_netlist.write(expanded_netlist_path, spice_writer)
    info(f"Wrote expanded netlist to: {expanded_netlist_path}")

    netlist_reducer = NetlistReducer()
    reduced_netlist = netlist_reducer.reduce(netlist=expanded_netlist,
                                             top_cell_name=pex_context.top_cell.name)
    spice_writer = kdb.NetlistSpiceWriter()
    spice_writer.use_net_names = True
    reduced_netlist.write(reduced_netlist_path, spice_writer)
    info(f"Wrote reduced netlist to: {reduced_netlist_path}")


def main():
    info("Called with arguments:")
    info(' '.join(map(shlex.quote, sys.argv)))

    args = parse_args()

    os.makedirs(args.output_dir_base_path, exist_ok=True)

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
        validate_args(args)
    except Exception:
        if args.output_dir_path:
            reregister_log_file_handler(file_handler_plain, cli_log_path_plain, None)
            reregister_log_file_handler(file_handler_formatted, cli_log_path_formatted, formatter)
        sys.exit(1)
    reregister_log_file_handler(file_handler_plain, cli_log_path_plain, None)
    reregister_log_file_handler(file_handler_formatted, cli_log_path_formatted, formatter)

    set_log_level(args.log_level)

    tech_info = TechInfo.from_json(args.tech_pbjson_path)

    lvsdb = kdb.LayoutVsSchematic()

    match args.input_mode:
        case InputMode.LVSDB:
            lvsdb.read(args.lvsdb_path)
        case InputMode.GDS:
            layout = kdb.Layout()
            layout.read(args.gds_path)

            found_cell: Optional[kdb.Cell] = None
            for cell in layout.cells('*'):
                if cell.name == args.cell_name:
                    found_cell = cell
                    break
            if not found_cell:
                error(f"Could not find cell {args.cell_name} in GDS {args.gds_path}")
                sys.exit(1)

            effective_gds_path = args.gds_path

            top_cells = layout.top_cells()
            is_only_top_cell = len(top_cells) == 1 and top_cells[0].name == args.cell_name
            if is_only_top_cell:
                info(f"Found cell {args.cell_name} in GDS {args.gds_path} (only top cell)")
            else:  # there are other cells => extract the top cell to a tmp layout
                effective_gds_path = os.path.join(args.output_dir_path, f"{args.cell_name}_exported.gds.gz")
                info(f"Found cell {args.cell_name} in GDS {args.gds_path}, "
                     f"but it is not the only top cell, "
                     f"so layout is exported to: {effective_gds_path}")

                found_cell.write(effective_gds_path)

            effective_schematic_path = args.schematic_path
            if not args.schematic_path:
                effective_schematic_path = os.path.join(args.output_dir_path, f"{args.cell_name}_dummy_schematic.spice")
                with open(effective_schematic_path, 'w') as f:
                    f.writelines([
                        f".subckt {args.cell_name} VDD VSS",
                        '.ends',
                        '.end'
                    ])

            lvs_log_path = os.path.join(args.output_dir_path, f"{args.cell_name}_lvs.log")
            lvsdb_path = os.path.join(args.output_dir_path, f"{args.cell_name}.lvsdb.gz")
            lvs_runner = LVSRunner()
            lvs_runner.run_klayout_lvs(exe_path=args.klayout_exe_path,
                                       lvs_script=args.lvs_script_path,
                                       gds_path=effective_gds_path,
                                       schematic_path=effective_schematic_path,
                                       log_path=lvs_log_path,
                                       lvsdb_path=lvsdb_path)
            lvsdb.read(lvsdb_path)

    pex_context = KLayoutExtractionContext.prepare_extraction(top_cell=args.cell_name,
                                                              lvsdb=lvsdb,
                                                              tech=tech_info,
                                                              blackbox_devices=args.blackbox_devices)
    gds_path = os.path.join(args.output_dir_path, f"{args.cell_name}_l2n_extracted.gds.gz")
    pex_context.target_layout.write(gds_path)

    gds_path = os.path.join(args.output_dir_path, f"{args.cell_name}_l2n_internal.gds.gz")
    pex_context.lvsdb.internal_layout().write(gds_path)

    if len(pex_context.unnamed_layers) >= 1:
        layout = kdb.Layout()
        layout.dbu = lvsdb.internal_layout().dbu

        top_cell = layout.create_cell("TOP")
        for ulyr in pex_context.unnamed_layers:
            li = kdb.LayerInfo(*ulyr.gds_pair)
            layer = layout.insert_layer(li)
            layout.insert(top_cell.cell_index(), layer, ulyr.region.dup())

        layout_dump_path = os.path.join(args.output_dir_path, f"{args.cell_name}_unnamed_LVS_layers.gds.gz")
        layout.write(layout_dump_path)

    run_fastercap_extraction(args=args,
                             pex_context=pex_context,
                             tech_info=tech_info)


if __name__ == "__main__":
    main()
