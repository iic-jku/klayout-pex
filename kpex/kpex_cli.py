#! /usr/bin/env python3

import argparse
from enum import StrEnum
import os
import os.path
import sys

import klayout.db as kdb

from .fastercap.fastercap_file_writer import *
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


def parse_args(arg_list: List[str] = None) -> argparse.Namespace:
    main_parser = argparse.ArgumentParser(description=f"{PROGRAM_NAME}: "
                                                       "KLayout-integrated Parasitic Extraction Tool",
                                          epilog=f"See '{PROGRAM_NAME} <subcommand> -h' for help on subcommand",
                                          add_help=False)
    group_special = main_parser.add_argument_group("Special options")
    group_special.add_argument("--help", "-h", action='help', help="show this help message and exit")
    group_special.add_argument("--version", "-v", action='version', version=f'{PROGRAM_NAME} {__version__}')
    group_special.add_argument("--log_level", dest='log_level', default='info',
                               help=render_enum_help(topic='log_level', enum_cls=LogLevel))
    group_special.add_argument("--threads", dest='num_threads', type=int, default=0,
                               help="number of threads (e.g. for FasterCap)")

    group_pex = main_parser.add_argument_group("Parasitic Extraction Setup")
    group_pex.add_argument("--tech", "-t", dest="tech_pbjson_path", required=True,
                           help="Technology Protocol Buffer path (*.pb.json)")

    group_pex.add_argument("--out_dir", "-o", dest="output_dir_path", default=".",
                           help="Output directory path")

    group_pex_input = main_parser.add_argument_group("Parasitic Extraction Input",
                                                     description="Either LVS is run, or an existing LVSDB is used")
    group_pex_input.add_argument("--gds", "-g", dest="gds_path", help="GDS path (for LVS)")
    group_pex_input.add_argument("--schematic", "-s", dest="schematic_path",
                                 help="Schematic SPICE netlist path (for LVS)")
    group_pex_input.add_argument("--lvsdb", "-l", dest="lvsdb_path", help="KLayout LVSDB path (bypass LVS)")
    group_pex_input.add_argument("--cell", "-c", dest="cell_name", default="TOP", help="Cell (default is TOP)")

    group_fastercap = main_parser.add_argument_group("FasterCap options")
    group_fastercap.add_argument("--k_void", "-k", dest="k_void",
                                 type=float, default=3.5,
                                 help="Dielectric constant of void (default is 3.5)")
    group_fastercap.add_argument("--delaunay_amax", "-a", dest="delaunay_amax",
                                 type=float, default=0.5,
                                 help="Delaunay triangulation maximum area (default is 0.5)")
    group_fastercap.add_argument("--delaunay_b", "-b", dest="delaunay_b",
                                 type=float, default=0.5,
                                 help="Delaunay triangulation b (default is 0.5)")
    group_fastercap.add_argument("--tolerance", dest="fastercap_tolerance",
                                 type=float, default=0.05,
                                 help="FasterCap -aX error tolerance (default is 0.05)")
    group_fastercap.add_argument("--auto-preconditioner", dest="fastercap_auto_preconditioner",
                                 type=bool, default=True,
                                 help=f"FasterCap -ap Automatic preconditioner usage "
                                      f"(default is True)")
    group_fastercap.add_argument("--galerkin", dest="fastercap_galerkin_scheme",
                                 type=bool, default=True,
                                 help=f"FasterCap -g Use Galerkin scheme "
                                      f"(default is True)")
    group_fastercap.add_argument("--d_coeff", dest="fastercap_d_coeff",
                                 type=float, default=0.04,
                                 help=f"FasterCap -d direct potential interaction coefficient to mesh refinement "
                                      f"(default is 0.04)")
    group_fastercap.add_argument("--mesh", dest="fastercap_mesh_refinement_value",
                                 type=float, default=0.001,
                                 help=f"FasterCap -m Mesh relative refinement value "
                                      f"(default is 0.001)")

    if arg_list is None:
        arg_list = sys.argv[1:]
    args = main_parser.parse_args(arg_list)
    return args


def validate_args(args: argparse.Namespace):
    found_errors = False

    if not os.path.isfile(args.tech_pbjson_path):
        error(f"Can't read technology file at path {args.tech_pbjson_path}")
        found_errors = True

    # input mode: LVS or existing LVSDB?
    if hasattr(args, 'gds_path'):
        info(f"GDS input file passed, running in LVS mode")
        args.input_mode = InputMode.GDS
        if not os.path.isfile(args.gds_path):
            error(f"Can't read GDS file (LVS input) at path {args.gds_path}")
            found_errors = True
        if not hasattr(args, 'schematic_path'):
            error(f"LVS input schematic not specified (argument --schematic)")
            found_errors = True
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

    if found_errors:
        sys.exit(1)


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

    # def provide_fastcap_file(name: str) -> TextIO:
    #     if not os.path.isdir(args.output_dir_path):
    #         os.makedirs(args.output_dir_path, exist_ok=True)
    #     path = os.path.join(args.output_dir_path, name)
    #     textio = open(path, mode="w")
    #     return textio
    #
    # writer = FasterCapFileWriter()
    # for circuit, fastercap_input_content in input_files_by_circuit:
    #     writer.write_3d_file(input_file=fastercap_input_content,
    #                          file_provider=provide_fastcap_file,
    #                          sub_file_strategy=FasterCapSubFileStrategy.MULTI_FILE)

    gen.check()

    os.makedirs(args.output_dir_path, exist_ok=True)

    lst_file = gen.write_fastcap(output_dir_path=args.output_dir_path,
                                 prefix=f"{args.cell_name}_FasterCap_Input")

    gen.dump_stl(output_dir_path=args.output_dir_path,
                 prefix=f"{args.cell_name}_Geometry_")

    exe_path = "FasterCap"
    log_path = os.path.join(args.output_dir_path, f"{args.cell_name}_FasterCap_Output.txt")
    csv_path = os.path.join(args.output_dir_path, f"{args.cell_name}_FasterCap_Result_Matrix.csv")
    expanded_netlist_path = os.path.join(args.output_dir_path, f"{args.cell_name}_Expanded_Netlist.cir")
    reduced_netlist_path = os.path.join(args.output_dir_path, f"{args.cell_name}_Reduced_Netlist.cir")

    run_fastercap(exe_path=exe_path,
                  lst_file_path=lst_file,
                  log_path=log_path,
                  tolerance=args.fastercap_tolerance,
                  auto_preconditioner=args.fastercap_auto_preconditioner,
                  galerkin_scheme=args.fastercap_galerkin_scheme,
                  d_coeff=args.fastercap_d_coeff,
                  mesh_refinement_value=args.fastercap_mesh_refinement_value)

    cap_matrix = fastercap_parse_capacitance_matrix(log_path)
    cap_matrix.write_csv(csv_path)

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
    args = parse_args()
    validate_args(args)

    set_log_level(args.log_level)

    tech_info = TechInfo.from_json(args.tech_pbjson_path)

    lvsdb = kdb.LayoutVsSchematic()

    # TODO: make configurable (env vars or config file)
    klayout_exe_path = 'klayout'
    lvs_script_path = os.path.join(os.environ['HOME'], '.klayout', 'salt', 'sky130A_el',
                                   'lvs', 'core', 'sky130.lvs')

    match args.input_mode:
        case InputMode.LVSDB:
            lvsdb.read(args.lvsdb_path)
        case InputMode.GDS:
            layout = kdb.Layout()
            layout.read(args.gds_path)

            found_cell: Optional[kdb.Cell] = None
            is_only_top_cell = False
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

            lvs_log_path = os.path.join(args.output_dir_path, f"{args.cell_name}_lvs.log")
            lvsdb_path = os.path.join(args.output_dir_path, f"{args.cell_name}_lvs.lvsdb")
            lvs_runner = LVSRunner()
            lvs_runner.run_klayout_lvs(exe_path=klayout_exe_path,
                                       lvs_script=lvs_script_path,
                                       gds_path=effective_gds_path,
                                       schematic_path=args.schematic_path,
                                       log_path=lvs_log_path,
                                       lvsdb_path=lvsdb_path)
            lvsdb.read(lvsdb_path)

    pex_context = KLayoutExtractionContext.prepare_extraction(top_cell=args.cell_name, lvsdb=lvsdb)
    gds_path = os.path.join(args.output_dir_path, f"{args.cell_name}_l2n_extracted.gds.gz")
    pex_context.target_layout.write(gds_path)

    run_fastercap_extraction(args=args,
                             pex_context=pex_context,
                             tech_info=tech_info)


if __name__ == "__main__":
    main()
