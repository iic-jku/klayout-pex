#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
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
"""
The shared parts of the test pattern generators, one module per PDK (e.g. gf180mcuD.py)
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import *

import klayout.db as kdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]

GDSPair = Tuple[int, int]


def pdk_root() -> str:
    """
    The directory of the installed PDKs (e.g. IIC-OSIC-TOOLS), for the pcells of a PDK
    """
    return os.environ.get('PDK_ROOT', '/foss/pdks')


class Pattern:
    """
    A test pattern, a layout with its top cell
    """
    def __init__(self, name: str, label_layer_by_layer: Dict[GDSPair, GDSPair]):
        """
        :param label_layer_by_layer: the label layer of each drawing layer of the PDK, see label()
        """
        self.layout = kdb.Layout()
        self.layout.dbu = 0.001
        self.top = self.layout.create_cell(name)
        self.label_layer_by_layer = label_layer_by_layer

    def box(self, layer: GDSPair, x1: int, y1: int, x2: int, y2: int):
        self.top.shapes(self.layout.layer(*layer)).insert(kdb.Box(x1, y1, x2, y2))

    def square(self, layer: GDSPair, half_size: int):
        self.box(layer, -half_size, -half_size, half_size, half_size)

    def path(self, layer: GDSPair, points: List[Tuple[int, int]], width: int):
        self.top.shapes(self.layout.layer(*layer)).insert(kdb.Path([kdb.Point(*p) for p in points], width))

    def polygon(self, layer: GDSPair, points: List[Tuple[int, int]]):
        self.top.shapes(self.layout.layer(*layer)).insert(kdb.Polygon([kdb.Point(*p) for p in points]))

    def label(self, layer: GDSPair, text: str, x: int, y: int):
        """
        A label on the label layer of the drawing layer
        """
        label_layer = self.label_layer_by_layer[layer]
        self.top.shapes(self.layout.layer(*label_layer)).insert(kdb.Text(text, kdb.Trans(x, y)))


def main(pdk_name: str, patterns: Dict[str, Callable[[], Pattern]]) -> int:
    """
    The command line of the generator of a PDK, which writes into testdata/designs/<pdk_name>/test_patterns
    """
    parser = argparse.ArgumentParser(description=f"Generate {pdk_name} test patterns (GDS)")
    parser.add_argument('--output-dir', type=Path,
                        default=PROJECT_ROOT / 'testdata' / 'designs' / pdk_name / 'test_patterns',
                        help="default is %(default)s")
    parser.add_argument('patterns', nargs='*', choices=list(patterns), metavar='PATTERN',
                        help=f"patterns to generate (default is all): {', '.join(patterns)}")
    args = parser.parse_args()

    # NOTE: without timestamps, unchanged patterns are written byte-identical
    options = kdb.SaveLayoutOptions()
    options.gds2_write_timestamps = False

    for name in args.patterns or patterns:
        path = args.output_dir / f"{name}.gds.gz"
        patterns[name]().layout.write(str(path), options)
        print(f"Wrote {path}")
    return 0
