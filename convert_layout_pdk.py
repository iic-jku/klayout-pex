#! /usr/bin/env python3

import argparse
from dataclasses import dataclass
from functools import cached_property
import os
import os.path
import re
import shlex
import sys
from typing import *
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element

import klayout.db as kdb

from kpex.log import (
    LogLevel,
    set_log_level,
    # debug,
    info,
    # warning,
    error,
    warning,
    rule
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


@dataclass(frozen=True)
class Layer:
    layer: str
    purpose: Optional[str]
    gds_pair: GDSPair

    @property
    def lpp(self) -> str:
        if self.purpose:
            return f"{self.layer}.{self.purpose}"
        else:
            return self.layer


@dataclass(frozen=True)
class LayerList:
    layers: List[Layer]

    @cached_property
    def gds_pair_by_lpp(self) -> Dict[str, GDSPair]:
        return {l.lpp: l.gds_pair for l in self.layers}

    @cached_property
    def lpp_by_gds_pair(self) -> Dict[GDSPair, str]:
        return {l.gds_pair: l.lpp for l in self.layers}


def parse_args(arg_list: List[str] = None) -> argparse.Namespace:
    main_parser = argparse.ArgumentParser(description=f"{PROGRAM_NAME}: "
                                                      f"KLayout-based Layer Mapping Tool",
                                          epilog=f"See '{PROGRAM_NAME} <subcommand> -h' for help on subcommand",
                                          add_help=False)
    group_special = main_parser.add_argument_group("Special options")
    group_special.add_argument("--help", "-h", action='help', help="show this help message and exit")
    group_special.add_argument("--version", "-v", action='version', version=f'{PROGRAM_NAME} {__version__}')
    group_special.add_argument("--log_level", dest='log_level', default='SUBPROCESS',
                               help=render_enum_help(topic='log_level', enum_cls=LogLevel))

    group_info = main_parser.add_argument_group("Gather Information")
    group_info.add_argument("--layers", "-l", action='store_true', dest="dump_layers_and_quit",
                            help='Dump layers and quit')

    group_pex_input = main_parser.add_argument_group("Conversion")
    group_pex_input.add_argument("--in", "-i", dest="input_gds_path", default=None,
                                 help="Input GDS path")
    group_pex_input.add_argument("--out", "-o", dest="output_gds_path", default=None,
                                 help="Output GDS path")

    if arg_list is None:
        arg_list = sys.argv[1:]
    args = main_parser.parse_args(arg_list)
    return args


def validate_args(args: argparse.Namespace):
    found_errors = False

    try:
        args.log_level = LogLevel[args.log_level.upper()]
    except KeyError:
        error(f"Requested log level {args.log_level.lower()} does not exist, "
              f"{render_enum_help(topic='log_level', enum_cls=LogLevel, print_default=False)}")
        found_errors = True

    if args.dump_layers_and_quit:
        pass
    else:
        if not os.path.isfile(args.input_gds_path):
            error(f"Can't read GDS input file at path {args.input_gds_path}")
            found_errors = True

        try:
            dir = os.path.dirname(args.input_gds_path)
            is_dir = os.path.isdir(dir)
            if not is_dir:
                raise Exception(f"{dir} is no directory")
        except Exception:
            error(f"Can't write GDS output file at {args.output_gds_path}")
            found_errors = True

    if found_errors:
        raise Exception("Argument validation failed")


def setup_logging(args: argparse.Namespace):
    set_log_level(args.log_level)


def map_gds_layers(layout: kdb.Layout,
                   from_tech: str,
                   to_tech: str,
                   from_layers: LayerList,
                   to_layers: LayerList,
                   gds_layer_mapping: Dict[GDSPair, GDSPair]):
    layer_infos = [layout.layer_infos()[idx] for idx in layout.layer_indexes()]
    for li in layer_infos:
        gds_pair = GDSPair(li.layer, li.datatype)
        dest_gds_pair = gds_layer_mapping.get(gds_pair, None)
        if not dest_gds_pair:
            dest_gds_pair = GDSPair(1000 + li.layer, li.datatype)
            error(f"Unable to map layer {gds_pair} ({from_layers.lpp_by_gds_pair[gds_pair]}) "
                  f"from PDK {from_tech} to {to_tech}, "
                  f"mapping to dummy layer {dest_gds_pair}")
        else:
            info(f"Mapping layer {gds_pair} ({from_layers.lpp_by_gds_pair[gds_pair]}) -> "
                 f"{dest_gds_pair} ({to_layers.lpp_by_gds_pair[dest_gds_pair]})")
        lyr = layout.layer(li)
        layout.set_info(lyr, kdb.LayerInfo(dest_gds_pair.layer, dest_gds_pair.datatype))


def parse_layers(lyp_path: str) -> LayerList:
    lyp = ET.parse(lyp_path)
    lyp_root = lyp.getroot()
    layers = []
    layer_props = lyp_root.findall('./properties')
    for lp in layer_props:
        name = lp.find('./name').text
        source = lp.find('./source').text
        # print(f"name: {name}, source: {source}")
        layer_name: str = ""
        purpose: str = ""
        gds_layer: int = 0
        gds_datatype: int = 0

        try:
            name_match = re.match(r'^(?P<layer>\w+)(\.(?P<purpose>\w+))?(\s.*)?$', name)
            layer_name = name_match.group('layer')
            purpose = name_match.group('purpose')
        except Exception:
            error(f"Failed to parse layer name: {name} from {lyp_path}")

        try:
            source_match = re.match(r'^(?P<gds_layer>\d+)/(?P<gds_datatype>\d+).*$', source)
            gds_layer = int(source_match.group('gds_layer'))
            gds_datatype = int(source_match.group('gds_datatype'))
        except Exception:
            error(f"Failed to parse layer source: {source} from {lyp_path}")

        layer = Layer(layer=layer_name,
                      purpose=purpose,
                      gds_pair=GDSPair(gds_layer, gds_datatype))
        layers.append(layer)

    return LayerList(layers)


def main():
    info("Called with arguments:")
    info(' '.join(map(shlex.quote, sys.argv)))

    from_tech = "sky130A"
    to_tech = "sg13g2"

    dir = os.path.dirname(os.path.realpath(__file__))
    from_lyp_path = os.path.join(dir, "pdk", "sky130A", "kpex", "sky130A.lyp")
    to_lyp_path = os.path.join(dir, "pdk", "ihp_sg13g2", "kpex", "sg13g2.lyp")

    warning(f"At the moment, only conversion from PDK {from_tech} -> {to_tech} is supported!")

    args = parse_args()
    setup_logging(args)

    try:
        validate_args(args)
    except Exception:
        sys.exit(1)

    from_layers = parse_layers(from_lyp_path)
    to_layers = parse_layers(to_lyp_path)
    if args.dump_layers_and_quit:
        info("Dumping all available layers…")
        rule(from_lyp_path)
        info(sorted([layer.lpp for layer in from_layers.layers]))
        rule(to_lyp_path)
        info(sorted([layer.lpp for layer in to_layers.layers]))
        sys.exit(0)

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

    lpp_mapping: Dict[str, str] = {
        'boundary':             'prBoundary.boundary',
        'prBoundary.boundary':  'prBoundary.boundary',
        'diff.drawing':         'Activ.drawing',
        'nwell.drawing':        'NWell.drawing',
        'nwell.label':          'NWell.label',
        'pwell.drawing':        'PWell.drawing',
        'pwell.label':          'PWell.label',
        'pwell.pin':            'PWell.pin',
        'nsdm.drawing':         'nSD.drawing',
        'psdm.drawing':         'pSD.drawing',
        'poly.drawing':         'GatPoly.drawing',
        'licon1.drawing':       'Cont.drawing',
        'li1.drawing':          'Metal1.drawing',
        'li1.pin':              'Metal1.pin',
        'li1.label':            'Metal1.label',
        'mcon.drawing':         'Via1.drawing',
        'met1.drawing':         'Metal2.drawing',
        'met1.pin':             'Metal2.pin',
        'met1.label':           'Metal2.label',
        'via.drawing':          'Via2.drawing',
        'met2.drawing':         'Metal3.drawing',
        'met2.pin':             'Metal3.pin',
        'met2.label':           'Metal3.label',
        'via2.drawing':         'Via3.drawing',
        'met3.drawing':         'Metal4.drawing',
        'met3.pin':             'Metal4.pin',
        'met3.label':           'Metal4.label',
        'via3.drawing':         'Via4.drawing',
        'met4.drawing':         'Metal5.drawing',
        'met4.pin':             'Metal5.pin',
        'met4.label':           'Metal5.label',
        'via4.drawing':         'TopVia1.drawing',
        'met5.drawing':         'TopMetal1.drawing',
        'met5.pin':             'TopMetal1.pin',
        'met5.label':           'TopMetal1.label',
        'capacitor.drawing':    'Recog.mom',
        'capm2.drawing':        'MIM.drawing',
    }

    gds_mapping = {from_layers.gds_pair_by_lpp[from_lpp]: to_layers.gds_pair_by_lpp[to_lpp] \
                   for from_lpp, to_lpp in lpp_mapping.items()}
    rule("Map GDS layers")
    map_gds_layers(layout,
                   from_tech,
                   to_tech,
                   from_layers,
                   to_layers,
                   gds_mapping)

    rule()
    info(f"Writing layout to {args.output_gds_path}")
    layout.write(args.output_gds_path)


if __name__ == "__main__":
    main()
