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
Generate gf180mcuD test patterns (testdata/designs/gf180mcuD/test_patterns),
drawn to the gf180mcu DRC rules (variant D: 5 metals, 11K top metal):

  Metal1:            width 0.23, spacing 0.23, area 0.1444
  Metal2-Metal4:     width 0.28, area 0.1444
  Metal5 (top, 11K): width 0.44, area 0.5625
  Contact:           size 0.22, Poly2 enclosure 0.07, Metal1 enclosure >= 0.005
  Via1-Via4:         size 0.26, spacing 0.26, metal enclosure 0.06
  MIM (option B):    FuseTop area >= 25, enclosed by the bottom plate (Metal4) and CAP_MK by 0.6,
                     Via4 on FuseTop spacing 0.5, FuseTop enclosure 0.4, bottom plates 1.2 apart

The nfet patterns use the nfet pcell of the PDK, so the gf180mcuD PDK must be installed
(e.g. IIC-OSIC-TOOLS, with $PDK_ROOT/gf180mcuD).

Usage:
    python3 scripts/gen_test_patterns/gf180mcuD.py [--output-dir DIR] [PATTERN ...]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import *

import klayout.db as kdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / 'testdata' / 'designs' / 'gf180mcuD' / 'test_patterns'

GDSPair = Tuple[int, int]

POLY2:  GDSPair = (30, 0)
CONT:   GDSPair = (33, 0)
METAL1: GDSPair = (34, 0)
VIA1:   GDSPair = (35, 0)
METAL2: GDSPair = (36, 0)
VIA2:   GDSPair = (38, 0)
METAL3: GDSPair = (42, 0)
VIA3:   GDSPair = (40, 0)
METAL4: GDSPair = (46, 0)
VIA4:   GDSPair = (41, 0)
METAL5: GDSPair = (81, 0)
FUSETOP: GDSPair = (75, 0)
CAP_MK: GDSPair = (117, 5)
MIM_L_MK: GDSPair = (117, 10)

LABEL_BY_LAYER: Dict[GDSPair, GDSPair] = {
    POLY2: (30, 10),
    METAL1: (34, 10),
    METAL2: (36, 10),
    METAL3: (42, 10),
    METAL4: (46, 10),
    METAL5: (81, 10),
}


class Pattern:
    def __init__(self, name: str):
        self.layout = kdb.Layout()
        self.layout.dbu = 0.001
        self.top = self.layout.create_cell(name)

    def box(self, layer: GDSPair, x1: int, y1: int, x2: int, y2: int):
        self.top.shapes(self.layout.layer(*layer)).insert(kdb.Box(x1, y1, x2, y2))

    def square(self, layer: GDSPair, half_size: int):
        self.box(layer, -half_size, -half_size, half_size, half_size)

    def path(self, layer: GDSPair, points: List[Tuple[int, int]], width: int):
        self.top.shapes(self.layout.layer(*layer)).insert(kdb.Path([kdb.Point(*p) for p in points], width))

    def polygon(self, layer: GDSPair, points: List[Tuple[int, int]]):
        self.top.shapes(self.layout.layer(*layer)).insert(kdb.Polygon([kdb.Point(*p) for p in points]))

    def label(self, layer: GDSPair, text: str, x: int, y: int):
        self.top.shapes(self.layout.layer(*LABEL_BY_LAYER[layer])).insert(kdb.Text(text, kdb.Trans(x, y)))


#
# Resistance patterns
#

def metal1_wire(name: str,
                labels: List[Tuple[str, int, int]],
                stub: bool = False) -> Pattern:
    """
    A Metal1 wire of 10 µm (0.23 wide), optionally with a stub in the middle
    """
    p = Pattern(name)
    p.path(METAL1, [(0, 0), (10000, 0)], 230)
    if stub:
        p.box(METAL1, 4885, 115, 5115, 1115)
    for text, x, y in labels:
        p.label(METAL1, text, x, y)
    return p


def r_single_wire_m1() -> Pattern:
    return metal1_wire('r_single_wire_m1', [('A', 115, 0), ('B', 9885, 0)])


def r_wire_voltage_divider_m1() -> Pattern:
    return metal1_wire('r_wire_voltage_divider_m1', [('A', 115, 0), ('B', 9885, 0), ('C', 5000, 1000)], stub=True)


def r_wire_and_floating_branch_m1() -> Pattern:
    return metal1_wire('r_wire_and_floating_branch_m1', [('A', 115, 0), ('B', 9885, 0)], stub=True)


def r_meander_trace_m1() -> Pattern:
    p = Pattern('r_meander_trace_m1')
    p.path(METAL1, [(0, 6075), (12500, 6075), (12500, 4075), (0, 4075),
                    (0, 2075), (12500, 2075), (12500, 75), (0, 75)], 230)
    p.label(METAL1, 'A', 115, 6075)
    p.label(METAL1, 'B', 115, 75)
    return p


def r_contact_1x1_minsize_via1() -> Pattern:
    p = Pattern('r_contact_1x1_minsize_via1')
    p.square(VIA1, 130)
    p.square(METAL1, 190)
    p.square(METAL2, 190)
    p.label(METAL1, 'BOT', 0, 0)
    p.label(METAL2, 'TOP', 0, 0)
    return p


def r_contact_2x2_minsize_via1() -> Pattern:
    p = Pattern('r_contact_2x2_minsize_via1')
    for cx in (-260, 260):
        for cy in (-260, 260):
            p.box(VIA1, cx - 130, cy - 130, cx + 130, cy + 130)
    p.square(METAL1, 450)
    p.square(METAL2, 450)
    p.label(METAL1, 'BOT', 0, 0)
    p.label(METAL2, 'TOP', 0, 0)
    return p


def r_via_stack_1x1_minsize_poly_to_metal5() -> Pattern:
    # NOTE: gf180mcuD has 5 metals, Metal5 is the top metal (there is no Via5/MetalTop)
    p = Pattern('r_via_stack_1x1_minsize_poly_to_metal5')
    p.square(POLY2, 180)
    p.square(CONT, 110)
    for via, metal in ((VIA1, METAL1), (VIA2, METAL2), (VIA3, METAL3), (VIA4, METAL4)):
        p.square(via, 130)
        p.square(metal, 190)
    p.square(METAL5, 375)
    for layer, text in ((POLY2, 'poly'), (METAL1, 'met1'), (METAL2, 'met2'),
                        (METAL3, 'met3'), (METAL4, 'met4'), (METAL5, 'met5')):
        p.label(layer, text, 0, 0)
    return p


#
# nfet (nfet pcell of the PDK, gate contact on top),
# source/drain routed down, gate routed up
#

def load_pdk_pcells():
    if kdb.Library.library_by_name('gf180mcu') is not None:
        return
    pdk_root = os.environ.get('PDK_ROOT', '/foss/pdks')
    sys.path.insert(0, os.path.join(pdk_root, 'gf180mcuD', 'libs.tech', 'klayout', 'tech', 'pymacros'))
    from cells import gf180mcu
    gf180mcu()


def nfet_m1(name: str, labels: str) -> Pattern:
    load_pdk_pcells()
    p = Pattern(name)
    pcell = p.layout.create_cell('nfet', 'gf180mcu', {
        'w_gate': 0.36, 'l_gate': 0.28, 'nf': 1, 'gate_con_pos': 'top', 'bulk': 'None', 'volt': '3.3V'
    })
    device = p.layout.cell(p.layout.convert_cell_to_static(pcell.cell_index()))
    device.name = 'nfet'
    p.layout.delete_cell(pcell.cell_index())
    p.top.insert(kdb.CellInstArray(device.cell_index(), kdb.Trans()))
    p.path(METAL1, [(-210, 180), (-210, -800)], 380)  # source
    p.path(METAL1, [(870, 180), (870, -800)], 380)    # drain
    p.path(METAL1, [(330, 840), (330, 1600)], 380)    # gate
    for text, x, y in (('S', -210, -700), ('D', 870, -700), ('G', 330, 1500)):
        if text in labels:
            p.label(METAL1, text, x, y)
    return p


#
# Capacitance patterns
#

def sidewall_cap_vpp_04p4x04p6_m1_redux() -> Pattern:
    # interdigitated fingers, 0.23 wide, 0.23 apart
    p = Pattern('sidewall_cap_vpp_04p4x04p6_m1_redux')
    p.polygon(METAL1, [(0, 0), (0, 1370), (3150, 1370), (3150, 920), (450, 920),
                       (450, 230), (2470, 230), (2470, 0)])
    p.polygon(METAL1, [(2700, -250), (2700, 460), (680, 460), (680, 690),
                       (3150, 690), (3150, -250)])
    p.label(METAL1, 'C0', 0, 0)
    p.label(METAL1, 'C1', 680, 460)
    return p


def sidewall_non_parallel_m1() -> Pattern:
    # the slanted edge of A is at 45°, not parallel to B
    p = Pattern('sidewall_non_parallel_m1')
    p.polygon(METAL1, [(-2000, 5000), (-2000, 15000), (0, 15000), (5000, 10000), (5000, 5000)])
    p.path(METAL1, [(0, 2000), (8000, 2000), (8000, 10000)], 2000)
    p.box(METAL1, 10000, 3000, 14000, 8000)
    p.label(METAL1, 'A', -1900, 5100)
    p.label(METAL1, 'B', 105, 1090)
    p.label(METAL1, 'C', 10090, 3115)
    return p


COMPLEX_SHAPE = [
    (23000, 13000), (23000, 14000), (23500, 14000), (23500, 16500), (22785, 16500), (22785, 15405),
    (21860, 15405), (21860, 16000), (20000, 16000), (20000, 16500), (21860, 16500), (21860, 17950),
    (22770, 17950), (22770, 17000), (23500, 17000), (23500, 17500), (24000, 17500), (24000, 17000),
    (25000, 17000), (25000, 19000), (24000, 19000), (24000, 18000), (23000, 18000), (23000, 19000),
    (22000, 19000), (22000, 20000), (21000, 20000), (21000, 21000), (26000, 21000), (26000, 20000),
    (30000, 20000), (30000, 18645), (28000, 18645), (28000, 18000), (27000, 18000), (27000, 18645),
    (26360, 18645), (26360, 17165), (30000, 17165), (30000, 16000), (25000, 16000), (25000, 16500),
    (24000, 16500), (24000, 14000), (25000, 14000), (25000, 13000),
]


def sideoverlap_complex_m1_m2() -> Pattern:
    # a complex Metal1 shape at each side of a Metal2 plate (20 µm x 20 µm)
    p = Pattern('sideoverlap_complex_m1_m2')
    p.box(METAL2, 0, 0, 20000, 20000)
    p.label(METAL2, 'UPPER', 0, 18000)
    for text, dx, dy in (('Complex_Shape_R', 0, 0), ('Complex_Shape_T', -10000, 8000),
                         ('Complex_Shape_B', -20000, -20000), ('Complex_Shape_L', -30000, -12000)):
        p.polygon(METAL1, [(x + dx, y + dy) for x, y in COMPLEX_SHAPE])
        p.label(METAL1, text, COMPLEX_SHAPE[0][0] + dx, COMPLEX_SHAPE[0][1] + dy)
    return p


def mim_cap(p: Pattern, x: int, y: int, w: int, l: int, top: str, bottom: str):
    """
    A MIM cap (option B) like the PDK's cap_mim_2f0_m4m5_noshield, with its top plate (FuseTop) at x, y
    """
    p.box(FUSETOP, x, y, x + w, y + l)
    p.box(MIM_L_MK, x, y, x + w, y + 100)
    p.box(CAP_MK, x - 600, y - 600, x + w + 600, y + l + 600)
    p.box(METAL4, x - 600, y - 600, x + w + 600, y + l + 600)
    p.box(METAL5, x, y, x + w, y + l)
    nx, ny = ((size - 800 + 500) // 760 for size in (w, l))  # 0.26 vias, 0.5 apart, enclosed by 0.4
    x0, y0 = x + (w - (nx * 760 - 500)) // 2, y + (l - (ny * 760 - 500)) // 2
    for i in range(nx):
        for j in range(ny):
            p.box(VIA4, x0 + i * 760, y0 + j * 760, x0 + i * 760 + 260, y0 + j * 760 + 260)
    p.label(METAL4, bottom, x - 575, y - 575)
    p.label(METAL5, top, x + 25, y + 25)


def cap_mim_m4m5() -> Pattern:
    # 2 MIM caps, 5 µm x 5 µm and 20 µm x 10 µm
    p = Pattern('cap_mim_m4m5')
    mim_cap(p, 0, 0, 5000, 5000, 'TOP1', 'BOT1')
    mim_cap(p, 7400, 0, 20000, 10000, 'TOP2', 'BOT2')
    return p


PATTERNS: Dict[str, Callable[[], Pattern]] = {
    'r_single_wire_m1': r_single_wire_m1,
    'r_wire_voltage_divider_m1': r_wire_voltage_divider_m1,
    'r_wire_and_floating_branch_m1': r_wire_and_floating_branch_m1,
    'r_meander_trace_m1': r_meander_trace_m1,
    'r_contact_1x1_minsize_via1': r_contact_1x1_minsize_via1,
    'r_contact_2x2_minsize_via1': r_contact_2x2_minsize_via1,
    'r_via_stack_1x1_minsize_poly_to_metal5': r_via_stack_1x1_minsize_poly_to_metal5,
    'nfet_m1': lambda: nfet_m1('nfet_m1', 'DGS'),
    'nfet_m1_redux': lambda: nfet_m1('nfet_m1_redux', 'DS'),
    'nfet_m1_redux_only_G': lambda: nfet_m1('nfet_m1_redux_only_G', 'G'),
    'sidewall_cap_vpp_04p4x04p6_m1_redux': sidewall_cap_vpp_04p4x04p6_m1_redux,
    'sidewall_non_parallel_m1': sidewall_non_parallel_m1,
    'sideoverlap_complex_m1_m2': sideoverlap_complex_m1_m2,
    'cap_mim_m4m5': cap_mim_m4m5,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate gf180mcuD test patterns (GDS)")
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
