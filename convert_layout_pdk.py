#! /usr/bin/env python3

import argparse
from dataclasses import dataclass
import os
import os.path
import shlex
import sys
from typing import *

import klayout.db as kdb

from kpex.log import (
    LogLevel,
    set_log_level,
    # debug,
    info,
    # warning,
    error, warning
)
from kpex.version import __version__
from kpex.util.argparse_helpers import render_enum_help

# ------------------------------------------------------------------------------------

PROGRAM_NAME = "convert_layout_pdk"


@dataclass(frozen=True)
class GDSPair:
    layer: int
    datatype: int

    def __str__(self):
        return f"{self.layer}/{self.datatype}"


def parse_args(arg_list: List[str] = None) -> argparse.Namespace:
    main_parser = argparse.ArgumentParser(description=f"{PROGRAM_NAME}: "
                                                      f"KLayout-based Layer Mapping Tool",
                                          epilog=f"See '{PROGRAM_NAME} <subcommand> -h' for help on subcommand",
                                          add_help=False)
    group_special = main_parser.add_argument_group("Special options")
    group_special.add_argument("--help", "-h", action='help', help="show this help message and exit")
    group_special.add_argument("--version", "-v", action='version', version=f'{PROGRAM_NAME} {__version__}')
    group_special.add_argument("--log_level", dest='log_level', default='subprocess',
                               help=render_enum_help(topic='log_level', enum_cls=LogLevel))

    group_pex_input = main_parser.add_argument_group("Conversion")
    group_pex_input.add_argument("--in", "-i", dest="input_gds_path", required=True,
                                 help="Input GDS path")
    group_pex_input.add_argument("--out", "-o", dest="output_gds_path", required=True,
                                 help="Output GDS path")

    if arg_list is None:
        arg_list = sys.argv[1:]
    args = main_parser.parse_args(arg_list)
    return args


def validate_args(args: argparse.Namespace):
    found_errors = False

    if not os.path.isfile(args.input_gds_path):
        error(f"Can't read GDS input file at path {args.gds_path}")
        found_errors = True

    try:
        args.log_level = LogLevel[args.log_level.upper()]
    except KeyError:
        error(f"Requested log level {args.log_level.lower()} does not exist, "
              f"{render_enum_help(topic='log_level', enum_cls=LogLevel, print_default=False)}")
        found_errors = True

    if found_errors:
        raise Exception("Argument validation failed")


def setup_logging(args: argparse.Namespace):
    try:
        validate_args(args)
    except Exception:
        sys.exit(1)

    set_log_level(args.log_level)


def main():
    info("Called with arguments:")
    info(' '.join(map(shlex.quote, sys.argv)))

    from_tech = "sky130A"
    to_tech = "sg13g2"

    warning(f"At the moment, only conversion from PDK {from_tech} -> {to_tech} is supported!")

    args = parse_args()

    setup_logging(args)

    layout = kdb.Layout()

    info(f"Reading layout from {args.input_gds_path}")
    layout.read(args.input_gds_path)

    for c in layout.top_cells():
        c: kdb.Cell
        layout.flatten(
            c.cell_index(),
            -1,   # all levels
            True  # prune orthan cells
        )

    layer_mapping = {
        (122, 16): (46, 2),   # pwell.pin    -> PWell.pin
        # (64, 59):  None,      # pwell.label  -> -
        (67, 20):  (8, 0),    # li1.drawing  -> Metal1.drawing
        (67, 16):  (8, 2),    # li1.pin      -> Metal1.pin
        (67, 5):   (8, 25),   # li1.label    -> Metal1.text
        (67, 44):  (19, 0),   # mcon.drawing -> Via1.drawing
        (68, 20):  (10, 0),   # met1.drawing -> Metal2.drawing
        (68, 16):  (10, 2),   # met1.pin     -> Metal2.pin
        (68, 5):   (10, 25),  # met1.label   -> Metal2.text
        (68, 44):  (29, 0),   # via.drawing  -> Via2.drawing
        (69, 20):  (30, 0),   # met2.drawing -> Metal3.drawing
        (69, 16):  (30, 2),   # met2.pin     -> Metal3.pin
        (69, 5):   (30, 25),  # met2.label   -> Metal3.text
        (69, 44):  (49, 0),   # via2.drawing -> Via3.drawing
        (70, 20):  (50, 0),   # met3.drawing -> Metal4.drawing
        (70, 16):  (50, 2),   # met3.pin     -> Metal4.pin
        (70, 5):   (50, 25),  # met3.label   -> Metal4.text
        (70, 44):  (66, 0),   # via3.drawing -> Via4.drawing
        (71, 20):  (67, 0),   # met4.drawing -> Metal5.drawing
        (71, 16):  (67, 2),   # met4.pin     -> Metal5.pin
        (71, 5):   (67, 25),  # met4.label   -> Metal5.text
        (71, 44):  (125, 0),  # via4.drawing -> TopVia1.drawing
        (72, 20):  (126, 0),  # met5.drawing -> TopMetal1.drawing
        (72, 16):  (126, 2),  # met5.pin     -> TopMetal1.pin
        (72, 5):   (126, 25), # met5.label   -> TopMetal1.text
        (82, 64):  (99, 39)   # capacitor.drawing -> Recog.mom
    }
    layer_mapping = {GDSPair(*k): GDSPair(*v) for k, v in layer_mapping.items()}

    layer_infos = [layout.layer_infos()[idx] for idx in layout.layer_indexes()]
    for li in layer_infos:
        gds_pair = GDSPair(li.layer, li.datatype)
        dest_gds_pair = layer_mapping.get(gds_pair, None)
        if not dest_gds_pair:
            dest_gds_pair = GDSPair(1000 + li.layer, li.datatype)
            error(f"Unable to map layer {gds_pair} from PDK {from_tech} to {to_tech}, "
                  f"mapping to dummy layer {dest_gds_pair}")
        info(f"Mapping layer {gds_pair} -> {dest_gds_pair}")
        lyr = layout.layer(li)
        layout.set_info(lyr, kdb.LayerInfo(dest_gds_pair.layer, dest_gds_pair.datatype))

    info(f"Writing layout to {args.output_gds_path}")
    layout.write(args.output_gds_path)


if __name__ == "__main__":
    main()
