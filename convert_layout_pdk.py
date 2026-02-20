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

from __future__ import annotations
import argparse
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
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

from klayout_pex.log import (
    LogLevel,
    set_log_level,
    # debug,
    info,
    # warning,
    error,
    warning,
    rule
)
from klayout_pex.version import __version__
from klayout_pex.util.argparse_helpers import render_enum_help

# ------------------------------------------------------------------------------------

PROGRAM_NAME = "convert_layout_pdk"

LayerName = str
LayerPurpose = str
LayerPurposePair = str

@dataclass(frozen=True, order=True)
class GDSPair:
    layer: int
    datatype: int

    def __str__(self):
        return f"{self.layer}/{self.datatype}"


@dataclass(frozen=True)
class Layer:
    layer: LayerName
    purpose: Optional[LayerPurpose]
    gds_pair: GDSPair

    @property
    def lpp(self) -> LayerPurposePair:
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
    def layer_by_lpp(self) -> Dict[LayerPurposePair, Layer]:
        return {l.lpp: l for l in self.layers}

    @cached_property
    def gds_pair_by_lpp(self) -> Dict[LayerPurposePair, GDSPair]:
        return {l.lpp: l.gds_pair for l in self.layers}

    @cached_property
    def lpp_by_gds_pair(self) -> Dict[GDSPair, LayerPurposePair]:
        return {l.gds_pair: l.lpp for l in self.layers}

    @cached_property
    def layer_by_gds_pair(self) -> Dict[GDSPair, Layer]:
        return {l.gds_pair: l for l in self.layers}


class LayerMapping:
    def __init__(self,
                 lpp_mapping: Dict[LayerPurposePair, LayerPurposePair],
                 src_layers: LayerList,
                 dest_layers: LayerList):
        self.lpp_mapping = lpp_mapping
        self.src_layers = src_layers
        self.dest_layers = dest_layers

    @cached_property
    def layer_mapping(self) -> Dict[Layer, Layer]:
        errors = []

        d = {}
        for src_lpp, dest_lpp in self.lpp_mapping.items():
            src_layer = self.src_layers.layer_by_lpp.get(src_lpp, None)
            if not src_layer:
                errors += f"Unknown source layer {src_lpp}"
                continue
            dst_layer = self.dest_layers.layer_by_lpp.get(dest_lpp, None)
            if not dst_layer:
                errors += f"Unknown source layer {dest_lpp}"
                continue
            d[src_layer] = dst_layer

        if errors:
            raise Exception('\n'.join(errors))

        return d

    @cached_property
    def dest_layer_by_source_gds_pair(self) -> Dict[GDSPair, Layer]:
        return {src_layer.gds_pair: dest_layer
                for src_layer, dest_layer in self.layer_mapping.items()}


class PDK(StrEnum):
    GF180MCU = 'gf180mcu'
    IHP_SG13G2 = 'ihp-sg13g2'
    SKY130A = 'sky130A'

    @classmethod
    def tech_names(cls) -> List[str]:
        return [str(p.value) for p in cls]

    @property
    def pdk_index(self) -> int:
        match self:
            case PDK.GF180MCU: return 0
            case PDK.IHP_SG13G2: return 1
            case PDK.SKY130A: return 2
            case _:
                raise NotImplementedError(f"Unhandled enum case {self}")

    @property
    def lyp_path(self) -> str:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        match self:
            case PDK.GF180MCU:
                return os.path.join(script_dir, "pdk", "gf180mcuD",   "libs.tech", "kpex", "gf180mcu.lyp")
            case PDK.IHP_SG13G2:
                return os.path.join(script_dir, "pdk", "ihp_sg13g2", "libs.tech", "kpex", "sg13g2.lyp")
            case PDK.SKY130A:
                return os.path.join(script_dir, "pdk", "sky130A",    "libs.tech", "kpex", "sky130A.lyp")
            case _:
                raise NotImplementedError(f"Unhandled enum case {self}")

    @cached_property
    def layer_list(self) -> LayerList:
        return parse_layers(self.lyp_path)

    def layer_mapping(self,
                      dest_pdk: PDK) -> LayerMapping:
        pdks = list(PDK)
        own_index = pdks.index(self)
        dst_index = pdks.index(dest_pdk)
        t = PDK.corresponding_layer_table()
        lpp_mapping: Dict[LayerPurposePair, LayerPurposePair] = {r[own_index]: r[dst_index] \
                                                                 for r in t\
                                                                 if r[own_index] != '' and r[dst_index] != ''}

        lm = LayerMapping(lpp_mapping=lpp_mapping, src_layers=self.layer_list, dest_layers=dest_pdk.layer_list)
        return lm

    def corresponding_layer(self,
                            layer_name: LayerName,
                            dest_pdk: PDK) -> Optional[LayerName]:
        d = self._corresponding_layers.get(layer_name)
        if d is None:
            return None
        return d[dest_pdk]

    @cached_property
    def _corresponding_layers(self) -> Dict[LayerName, Dict[PDK, LayerName]]:
        d = {}
        pdks = list(PDK)
        own_index = pdks.index(self)
        t = self.corresponding_layer_table()
        for idx, m in enumerate(t):
            d[m[own_index]] = {pdks[j]: ln for j, ln in enumerate(m)}
        return d

    @classmethod
    def corresponding_layer_table(cls) -> List[List[str]]:
        l = [
            # GF180MCU                IHP-SG13G2                  SKY130A
            ['',                      'prBoundary.boundary',      'boundary'],
            ['COMP',                  'Activ.drawing',            'diff.drawing'],
            ['Nwell',                 'NWell.drawing',            'nwell.drawing'],
            ['',                      'NWell.label',              'nwell.label'],
            ['',                      'NWell.pin',                'nwell.pin'],
            ['LVPWELL',               'PWell.drawing',            'pwell.drawing'],
            ['',                      'PWell.label',              'pwell.label'],
            ['',                      'PWell.pin',                'pwell.pin'],
            ['Nplus',                 'nSD.drawing',              'nsdm.drawing'],
            ['Pplus',                 'pSD.drawing',              'psdm.drawing'],
            ['Poly2',                 'GatPoly.drawing',          'poly.drawing'],
            ['Poly2_Label',           'GatPoly.label',            'poly.label'],
            ['Contact',               'Cont.drawing',             'licon1.drawing'],
            ['Metal1',                'Metal1.drawing',           'li1.drawing'],
            ['',                      'Metal1.pin',               'li1.pin'],
            ['Metal1_Label',          'Metal1.text',              'li1.label'],
            ['Via1',                  'Via1.drawing',             'mcon.drawing'],
            ['Metal2',                'Metal2.drawing',           'met1.drawing'],
            ['',                      'Metal2.pin',               'met1.pin'],
            ['Metal2_Label',          'Metal2.text',              'met1.label'],
            ['Via2',                  'Via2.drawing',             'via.drawing'],
            ['Metal3',                'Metal3.drawing',           'met2.drawing'],
            ['',                      'Metal3.pin',               'met2.pin'],
            ['Metal3_Label',          'Metal3.text',              'met2.label'],
            ['Via3',                  'Via3.drawing',             'via2.drawing'],
            ['Metal4',                'Metal4.drawing',           'met3.drawing'],
            ['',                      'Metal4.pin',               'met3.pin'],
            ['Metal4_Label',          'Metal4.text',              'met3.label'],
            ['Via4',                  'Via4.drawing',             'via3.drawing'],
            ['Metal5',                'Metal5.drawing',           'met4.drawing'],
            ['',                      'Metal5.pin',               'met4.pin'],
            ['Metal5_Label',          'Metal5.text',              'met4.label'],
            ['Via5',                  'TopVia1.drawing',          'via4.drawing'],
            ['MetalTop',              'TopMetal1.drawing',        'met5.drawing'],
            ['',                      'TopMetal1.pin',            'met5.pin'],
            ['MetalTop_Label',        'TopMetal1.text',           'met5.label'],
            ['',                      'Recog.mom',                'capacitor.drawing'],
            ['',                      'MIM.drawing',              'capm2.drawing'],
        ]

        # 'tap.drawing':          ('Activ.drawing',),
        # 'nwell.label':          ('NWell.pin', 'NWell.label'), # NOTE: EMX loves purpose .pin
        # 'pwell.label':          ('PWell.pin', 'PWell.label'),  # NOTE: EMX loves purpose .pin
        # 'pwell.pin':            ('PWell.pin',),
        # 'li1.label':            ('Metal1.pin', 'Metal1.text'), # NOTE: OSS flow LVS needs .text (Virtuoso .pin)
        return l




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
    group_pex_input.add_argument("--in", "-i", dest="input_gds_path", required=True,
                                 help="Input GDS path")
    group_pex_input.add_argument("--out", "-o", dest="output_gds_path", required=True,
                                 help="Output GDS path")

    group_pex_input.add_argument("--src", "-s", dest="src_pdk", required=False, default=None,
                                 help=f"Source PDK, {render_enum_help(topic='source_pdk', enum_cls=PDK)}")
    group_pex_input.add_argument("--dest", "-d", dest="dest_pdk", required=True,
                                 help=f"Destination PDK, {render_enum_help(topic='dest_pdk', enum_cls=PDK)}")

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


def convert_layout(src_layout: kdb.Layout,
                   src_pdk: PDK,
                   dest_pdk: PDK) -> kdb.Layout:
    dest_layout = src_layout.dup()

    layer_mapping = src_pdk.layer_mapping(dest_pdk)

    layer_infos = [src_layout.layer_infos()[idx] for idx in src_layout.layer_indexes()]
    for li in layer_infos:
        src_gds_pair = GDSPair(li.layer, li.datatype)
        src_layer = src_pdk.layer_list.layer_by_gds_pair[src_gds_pair]
        if src_layer is None:
            src_layer = Layer('unknown', None, src_gds_pair)
        dest_layer = layer_mapping.dest_layer_by_source_gds_pair.get(src_gds_pair, None)
        if dest_layer:
            info(f"Mapping layer "
                 f"{src_layer.gds_pair} ({src_layer.lpp}) "
                 f"-> "
                 f"{dest_layer.gds_pair} ({dest_layer.lpp})")
        else:
            dest_gds_pair = GDSPair(1000 + li.layer, li.datatype)
            dest_layer = Layer('unknown', None, dest_gds_pair)
            error(f"Unable to map layer {src_gds_pair} ({src_layer.lpp}) "
                  f"from PDK {src_pdk} to {dest_pdk}, "
                  f"mapping to dummy layer {dest_gds_pair}")
        lyr = src_layout.layer(li)
        new_li = kdb.LayerInfo(dest_layer.gds_pair.layer, dest_layer.gds_pair.datatype)
        dest_layout.set_info(lyr, new_li)

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

        if name is None:
            try:
                source_match = re.match(r'^((?P<layer>\w+) )?(?P<gds_layer>\d+)/(?P<gds_datatype>\d+).*$', source)
                layer_name = source_match.group('layer')
                gds_layer = int(source_match.group('gds_layer'))
                gds_datatype = int(source_match.group('gds_datatype'))
            except Exception:
                error(f"Failed to parse layer source: {source} from {lyp_path}")
        else:
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

        if layer_name is not None:
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
    args = parse_args()
    setup_logging(args)

    info("Called with arguments:")
    info(' '.join(map(shlex.quote, sys.argv)))

    tech_names = PDK.tech_names()

    warning(f"At the moment, only conversion between PDKs {tech_names} is supported!")

    try:
        validate_args(args)
    except Exception:
        sys.exit(1)



    if args.dump_layers_and_quit:
        info("Dumping all available layers…")
        for pdk in PDK:
            rule(pdk.lyp_path)
            info(sorted([(layer.lpp, str(layer.gds_pair)) for layer in pdk.layer_list.layers]))
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

    src_pdk = PDK(args.src_pdk)
    dest_pdk = PDK(args.dest_pdk)

    if src_pdk is None:
        error("Source PDK is missing, please pass -s")
        sys.exit(1)

    if dest_pdk is None:
        error("Destination PDK is missing, please pass -d")
        sys.exit(1)

    rule("Convert GDS layout")
    dest_layout = convert_layout(layout, src_pdk, dest_pdk)

    rule()
    info(f"Writing layout to {args.output_gds_path}")
    dest_layout.write(args.output_gds_path)


if __name__ == "__main__":
    main()
