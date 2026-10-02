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
Generate ihp-sg13g2 test patterns (testdata/designs/ihp-sg13g2/test_patterns).

The MOM cap patterns use the cmomf pcell of the PDK, so the ihp-sg13g2 PDK must be installed
(e.g. IIC-OSIC-TOOLS, with $PDK_ROOT/ihp-sg13g2).

Usage:
    python3 scripts/gen_test_patterns/ihp_sg13g2.py [--output-dir DIR] [PATTERN ...]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import *

import klayout.db as kdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / 'testdata' / 'designs' / 'ihp-sg13g2' / 'test_patterns'

GDSPair = Tuple[int, int]

METAL4_PIN:   GDSPair = (50, 2)
METAL4_TEXT:  GDSPair = (50, 25)
METAL5:       GDSPair = (67, 0)
METAL5_PIN:   GDSPair = (67, 2)
METAL5_TEXT:  GDSPair = (67, 25)


class Pattern:
    def __init__(self, name: str):
        self.layout = kdb.Layout()
        self.layout.dbu = 0.001
        self.top = self.layout.create_cell(name)

    def box(self, layer: GDSPair, x1: int, y1: int, x2: int, y2: int):
        self.top.shapes(self.layout.layer(*layer)).insert(kdb.Box(x1, y1, x2, y2))

    def label(self, layer: GDSPair, text: str, x: int, y: int):
        self.top.shapes(self.layout.layer(*layer)).insert(kdb.Text(text, kdb.Trans(x, y)))


def load_pdk_pcells() -> str:
    """
    :return: the technology of the pcell library SG13_dev
    """
    if kdb.Library.library_by_name('SG13_dev', 'sg13g2') is None:
        pdk_root = os.environ.get('PDK_ROOT', '/foss/pdks')
        klayout_dir = os.path.join(pdk_root, 'ihp-sg13g2', 'libs.tech', 'klayout')
        sys.path.insert(0, os.path.join(klayout_dir, 'python'))
        sys.path.insert(0, os.path.join(klayout_dir, 'python', 'pycell4klayout-api', 'source', 'python'))
        import sg13g2_pycell_lib  # noqa: F401, registers the library SG13_dev
    return 'sg13g2'


#
# Capacitance patterns
#

def cap_cmomf_w10u_l25u_m2_m4_m5_wire() -> Pattern:
    # a MOM cap (cmomf pcell of the PDK) of 10 µm x 25 µm, with fingers on Metal2 … Metal4
    # (the model gives 0.915 fF/µm², 228.75 fF), its terminals labelled PLUS (left) and MINUS (top),
    # and a Metal5 wire X across it
    technology = load_pdk_pcells()
    p = Pattern('cap_cmomf_w10u_l25u_m2_m4_m5_wire')
    p.layout.technology_name = technology
    pcell = p.layout.create_cell('cmomf', 'SG13_dev', {'w': '10u', 'l': '25u', 'mmin': 2, 'mmax': 4})
    p.top.insert(kdb.CellInstArray(pcell.cell_index(), kdb.Trans()))
    p.top.flatten(-1, True)

    # NOTE: the pcell paints the pins (Metal4.pin) at the left (PLUS) and the top edge (MINUS)
    pins = sorted(kdb.Region(p.top.begin_shapes_rec(p.layout.layer(*METAL4_PIN))).merged().each(),
                  key=lambda pin: pin.bbox().left)
    for text, pin in zip(('PLUS', 'MINUS'), pins):
        center = pin.bbox().center()
        p.label(METAL4_TEXT, text, center.x, center.y)

    bbox = p.top.bbox()
    y = bbox.center().y
    p.box(METAL5, bbox.left - 2000, y - 500, bbox.right + 2000, y + 500)
    p.box(METAL5_PIN, bbox.left - 2000, y - 500, bbox.left - 1000, y + 500)
    p.label(METAL5_TEXT, 'X', bbox.left - 1500, y)
    return p


PATTERNS: Dict[str, Callable[[], Pattern]] = {
    'cap_cmomf_w10u_l25u_m2_m4_m5_wire': cap_cmomf_w10u_l25u_m2_m4_m5_wire,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate ihp-sg13g2 test patterns (GDS)")
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR,
                        help="default is %(default)s")
    parser.add_argument('patterns', nargs='*', choices=list(PATTERNS), metavar='PATTERN',
                        help=f"patterns to generate (default is all): {', '.join(PATTERNS)}")
    args = parser.parse_args()

    # NOTE: without timestamps, unchanged patterns are written byte-identical
    options = kdb.SaveLayoutOptions()
    options.gds2_write_timestamps = False

    for name in args.patterns or PATTERNS:
        path = args.output_dir / f"{name}.gds.gz"
        PATTERNS[name]().layout.write(str(path), options)
        print(f"Wrote {path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
