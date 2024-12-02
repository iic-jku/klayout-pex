#! /usr/bin/env python3

import argparse
import os
import os.path
import sys

from .fastercap.fastercap_file_writer import *
from .fastercap.fastercap_input_builder import FasterCapInputBuilder
from .klayout.lvsdb_extractor import KLayoutExtractionContext
from .logging import (
    LogLevel,
    set_log_level,
    # console,
    # debug,
    # info,
    # warning,
    error
)
from .tech_info import TechInfo
from .version import __version__

import klayout.db as kdb


# ------------------------------------------------------------------------------------

PROGRAM_NAME = "kpex"


def render_enum_help(topic: str,
                     enum_cls: Type[Enum]) -> str:
    if not hasattr(enum_cls, 'DEFAULT'):
        raise ValueError("Enum must declare case 'DEFAULT'")
    enum_help = f"{topic} ∈ {set([name.lower() for name, member in enum_cls.__members__.items()])}." \
                f"\nDefaults to '{enum_cls.DEFAULT.value}'"
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

    group_pex = main_parser.add_argument_group("Parasitic Extraction")
    group_pex.add_argument("--tech", "-t", dest="tech_pbjson_path", required=True,
                           help="Technology Protocol Buffer path (*.pb.json)")
    group_pex.add_argument("--lvsdb", "-l", dest="lvsdb_path", required=True, help="KLayout LVSDB path")
    group_pex.add_argument("--cell", "-c", dest="cell_name", default="TOP", help="Cell (default is TOP)")
    group_pex.add_argument("--out_dir", "-o", dest="output_dir_path", default=".",
                           help="Output directory path")

    if arg_list is None:
        arg_list = sys.argv[1:]
    args = main_parser.parse_args(arg_list)
    return args


def validate_args(args: argparse.Namespace):
    found_errors = False

    if not os.path.isfile(args.tech_pbjson_path):
        error(f"Can't read technology file at path {args.tech_pbjson_path}")
        found_errors = True

    if not os.path.isfile(args.lvsdb_path):
        error(f"Can't read KLayout LVSDB file at path {args.lvsdb_path}")
        found_errors = True

    if found_errors:
        sys.exit(1)


def main():
    args = parse_args()
    validate_args(args)

    log_level = LogLevel[args.log_level.upper()]
    set_log_level(log_level)

    tech_info = TechInfo.from_json(args.tech_pbjson_path)

    lvsdb = kdb.LayoutVsSchematic()
    lvsdb.read(args.lvsdb_path)

    pex_context = KLayoutExtractionContext.prepare_extraction(top_cell=args.cell_name, lvsdb=lvsdb)
    # pex_context.target_layout.write(gds_path)

    fastercap_input_builder = FasterCapInputBuilder(
        pex_context=pex_context,
        tech_info=tech_info
    )
    input_files_by_circuit: List[Tuple[kdb.Circuit, InputFile3D]] = fastercap_input_builder.build()

    def provide_fastcap_file(name: str) -> TextIO:
        if not os.path.isdir(args.output_dir_path):
            os.makedirs(args.output_dir_path, exist_ok=True)
        path = os.path.join(args.output_dir_path, name)
        textio = open(path, mode="w")
        return textio

    writer = FasterCapFileWriter()
    for circuit, fastercap_input_content in input_files_by_circuit:
        writer.write_3d_file(input_file=fastercap_input_content,
                             file_provider=provide_fastcap_file,
                             sub_file_strategy=FasterCapSubFileStrategy.MULTI_FILE)


if __name__ == "__main__":
    main()
