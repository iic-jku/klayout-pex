#! /usr/bin/env python3

import argparse
import os
import os.path
import sys
import vtk

from kpex.fastercap.fastercap_file_reader import *
from kpex.log import (
    # console,
    # debug,
    # info,
    # warning,
    error
)
from kpex.version import __version__

from .vtk.vtk_view import VTKView

# ------------------------------------------------------------------------------------

PROGRAM_NAME = "fastercap_file_viewer"


def parse_args(arg_list: List[str] = None) -> argparse.Namespace:
    main_parser = argparse.ArgumentParser(description=f"{PROGRAM_NAME}: "
                                                      f"FasterCap File Viewer",
                                          epilog=f"See '{PROGRAM_NAME} <subcommand> -h' for help on subcommand",
                                          add_help=False)
    group_special = main_parser.add_argument_group("Special options")
    group_special.add_argument("--help", "-h", action='help', help="show this help message and exit")
    group_special.add_argument("--version", "-v", action='version', version=f'{PROGRAM_NAME} {__version__}')

    main_parser.add_argument('path', nargs='+', help="FasterCap input file path")

    if arg_list is None:
        arg_list = sys.argv[1:]
    args = main_parser.parse_args(arg_list)
    return args


def validate_args(args: argparse.Namespace):
    found_errors = False

    for p in args.path:
        if not os.path.exists(p):
            error(f"Input path does not exist: {p}")
            found_errors = True

    if found_errors:
        sys.exit(1)


def load_path(path: str) -> InputFile3D:
    input_filename = os.path.basename(path)
    input_dir = os.path.dirname(path)

    def provide_fastcap_file(name: str) -> TextIO:
        p = os.path.join(input_dir, name)
        textio = open(p, mode="r")
        return textio

    reader = FasterCapFileReader()
    input_file_content = reader.read_3d_file(input_file_name=input_filename,
                                             file_provider=provide_fastcap_file)
    return input_file_content


def main():
    args = parse_args()
    validate_args(args)

    vtkView = VTKView(width=1400*2, height=1000*2)
    vtkView.show()


if __name__ == "__main__":
    main()
