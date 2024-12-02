#! /usr/bin/env python3

import argparse
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property
import numpy
import os
import os.path
import re
import shlex
import sys
from typing import *
import xml.etree.ElementTree as ET

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
    def as_gds_list(self) -> List[GDSPair]:
        return [layer.gds_pair for layer in self.layers]

    @cached_property
    def layer_by_lpp(self) -> Dict[str, Layer]:
        return {l.lpp: l for l in self.layers}

    @cached_property
    def gds_pair_by_lpp(self) -> Dict[str, GDSPair]:
        return {l.lpp: l.gds_pair for l in self.layers}

    @cached_property
    def lpp_by_gds_pair(self) -> Dict[GDSPair, str]:
        return {l.gds_pair: l.lpp for l in self.layers}


class LayerMapping:
    def __init__(self,
                 lpp_mapping: Dict[str, Tuple[str]],
                 src_layers: LayerList,
                 dest_layers: LayerList):
        self.lpp_mapping = lpp_mapping
        self.src_layers = src_layers
        self.dest_layers = dest_layers

    @cached_property
    def layer_mapping(self) -> Dict[Layer, LayerList]:
        errors = []

        d = {}
        for src_lpp, dest_lpps in self.lpp_mapping.items():
            src_layer = self.src_layers.layer_by_lpp.get(src_lpp, None)
            if not src_layer:
                errors += f"Unknown source layer {src_lpp}"
                continue
            dest_layers: List[Layer] = []
            for dest_lpp in dest_lpps:
                lyr = self.dest_layers.layer_by_lpp.get(dest_lpp, None)
                if not lyr:
                    errors += f"Unknown source layer {dest_lpp}"
                    continue
                dest_layers.append(lyr)
            d[src_layer] = LayerList(dest_layers)

        if errors:
            raise Exception('\n'.join(errors))

        return d

    @cached_property
    def dest_layers_by_source_gds_pair(self) -> Dict[GDSPair, LayerList]:
        return {src_layer.gds_pair: dest_layers
                for src_layer, dest_layers in self.layer_mapping.items()}


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
            dir = os.path.dirname(os.path.realpath(args.input_gds_path))
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


def guess_technology(layout: kdb.Layout,
                     tech_layer_lists: List[LayerList]) -> int:
    layer_infos = [layout.layer_infos()[idx] for idx in layout.layer_indexes()]

    rank_by_tech = [0] * len(tech_layer_lists)
    for idx, tech_layers in enumerate(tech_layer_lists):
        tech_layer_set = set(tech_layers.as_gds_list)
        for li in layer_infos:
            gds_pair = GDSPair(li.layer, li.datatype)
            if gds_pair in tech_layer_set:
                rank_by_tech[idx] += 1

    return numpy.argmax(rank_by_tech)


def map_gds_layers(src_layout: kdb.Layout,
                   src_tech: str,
                   dest_tech: str,
                   layer_mapping: LayerMapping) -> kdb.Layout:
    dest_layout = src_layout.dup()

    layer_infos = [src_layout.layer_infos()[idx] for idx in src_layout.layer_indexes()]
    for li in layer_infos:
        gds_pair = GDSPair(li.layer, li.datatype)
        dest_layers = layer_mapping.dest_layers_by_source_gds_pair.get(gds_pair, None)
        dest_gds_pair_list: List[GDSPair]
        if dest_layers:
            dest_gds_pair_list = dest_layers.as_gds_list
            layers = [f"{gdp} ({layer_mapping.dest_layers.lpp_by_gds_pair[gdp]})" for gdp in dest_gds_pair_list]
            info(f"Mapping layer {gds_pair} ({layer_mapping.src_layers.lpp_by_gds_pair[gds_pair]}) "
                 f"-> {', '.join(layers)}")
        else:
            dest_gds_pair = GDSPair(1000 + li.layer, li.datatype)
            error(f"Unable to map layer {gds_pair} "
                  f"({layer_mapping.src_layers.lpp_by_gds_pair.get(gds_pair, None) or 'unknown'}) "
                  f"from PDK {src_tech} to {dest_tech}, "
                  f"mapping to dummy layer {dest_gds_pair}")
            dest_gds_pair_list = [dest_gds_pair]
        lyr = src_layout.layer(li)
        for idx, gdp in enumerate(dest_gds_pair_list):
            new_li = kdb.LayerInfo(gdp.layer, gdp.datatype)
            if idx == 0:
                dest_layout.set_info(lyr, new_li)
            else:
                dest_layer = dest_layout.insert_layer(new_li)
                dest_layout.copy_layer(lyr, dest_layer)

    return dest_layout


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


def invert_dict(d: Dict[str, Tuple[str]]) -> Dict[str, Tuple[str]]:
    n = defaultdict(list)
    for src_lpp, dest_lpps in d.items():
        for dest_lpp in dest_lpps:
            n[dest_lpp].append(src_lpp)
    n = {k: tuple(v) for k, v in n.items()}
    return n


def main():
    info("Called with arguments:")
    info(' '.join(map(shlex.quote, sys.argv)))

    tech_names = ("sky130A", "sg13g2")

    dir = os.path.dirname(os.path.realpath(__file__))
    lyp_paths = (os.path.join(dir, "pdk", "sky130A", "kpex", "sky130A.lyp"),
                 os.path.join(dir, "pdk", "ihp_sg13g2", "kpex", "sg13g2.lyp"))

    warning(f"At the moment, only conversion between PDKs {tech_names} is supported!")

    args = parse_args()
    setup_logging(args)

    try:
        validate_args(args)
    except Exception:
        sys.exit(1)

    tech_layer_lists = [parse_layers(lyp_path) for lyp_path in lyp_paths]
    if args.dump_layers_and_quit:
        info("Dumping all available layers…")
        for lyp_path, layer_list in zip(lyp_paths, tech_layer_lists):
            rule(lyp_path)
            info(sorted([layer.lpp for layer in layer_list.layers]))
        sys.exit(0)

    layout = kdb.Layout()

    info(f"Reading layout from {args.input_gds_path}")
    layout.read(args.input_gds_path)

    for c in layout.top_cells():
        c: kdb.Cell
        layout.flatten(
            c.cell_index(),
            -1,   # all levels
            True  # prune orphan cells
        )

    src_tech_index = guess_technology(layout=layout, tech_layer_lists=tech_layer_lists)

    assert len(tech_names) == 2
    dest_tech_index = (src_tech_index + 1) % 2

    src_tech = tech_names[src_tech_index]
    dest_tech = tech_names[dest_tech_index]
    src_layers = tech_layer_lists[src_tech_index]
    dest_layers = tech_layer_lists[dest_tech_index]
    info(f"Guessing layout is of tech: {src_tech}")

    # from tech1 to tech2
    lpp_mapping: Dict[str, Tuple[str]] = {
        'boundary':             ('prBoundary.boundary',),
        'prBoundary.boundary':  ('prBoundary.boundary',),
        'tap.drawing':          ('Activ.drawing',),
        'diff.drawing':         ('Activ.drawing',),
        'nwell.drawing':        ('NWell.drawing',),
        'nwell.label':          ('NWell.pin', 'NWell.label'), # NOTE: EMX loves purpose .pin
        'pwell.drawing':        ('PWell.drawing',),
        'pwell.label':          ('PWell.pin', 'PWell.label'),  # NOTE: EMX loves purpose .pin
        'pwell.pin':            ('PWell.pin',),
        'nsdm.drawing':         ('nSD.drawing',),
        'psdm.drawing':         ('pSD.drawing',),
        'poly.drawing':         ('GatPoly.drawing',),
        'licon1.drawing':       ('Cont.drawing',),
        'li1.drawing':          ('Metal1.drawing',),
        'li1.pin':              ('Metal1.pin',),
        'li1.label':            ('Metal1.pin', 'Metal1.text'), # NOTE: OSS flow LVS needs .text (Virtuoso .pin)
        'mcon.drawing':         ('Via1.drawing',),
        'met1.drawing':         ('Metal2.drawing',),
        'met1.pin':             ('Metal2.pin',),
        'met1.label':           ('Metal2.pin', 'Metal2.text'),
        'via.drawing':          ('Via2.drawing',),
        'met2.drawing':         ('Metal3.drawing',),
        'met2.pin':             ('Metal3.pin',),
        'met2.label':           ('Metal3.pin', 'Metal3.text'),
        'via2.drawing':         ('Via3.drawing',),
        'met3.drawing':         ('Metal4.drawing',),
        'met3.pin':             ('Metal4.pin',),
        'met3.label':           ('Metal4.pin', 'Metal4.text'),
        'via3.drawing':         ('Via4.drawing',),
        'met4.drawing':         ('Metal5.drawing',),
        'met4.pin':             ('Metal5.pin',),
        'met4.label':           ('Metal5.pin', 'Metal5.text'),
        'via4.drawing':         ('TopVia1.drawing',),
        'met5.drawing':         ('TopMetal1.drawing',),
        'met5.pin':             ('TopMetal1.pin',),
        'met5.label':           ('TopMetal1.pin', 'TopMetal1.text'),
        'capacitor.drawing':    ('Recog.mom',),
        'capm2.drawing':        ('MIM.drawing',),
    }

    if src_tech_index == 1:
        lpp_mapping = invert_dict(lpp_mapping)

    layer_mapping = LayerMapping(lpp_mapping=lpp_mapping,
                                 src_layers=src_layers,
                                 dest_layers=dest_layers)

    rule("Map GDS layers")
    dest_layout = map_gds_layers(layout,
                                 src_tech,
                                 dest_tech,
                                 layer_mapping)

    rule()
    info(f"Writing layout to {args.output_gds_path}")
    dest_layout.write(args.output_gds_path)


if __name__ == "__main__":
    main()
