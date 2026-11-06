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

The MOM cap and device patterns use the pcells of the PDK, so the ihp-sg13g2 PDK must be installed
(e.g. IIC-OSIC-TOOLS, with $PDK_ROOT/ihp-sg13g2).

Usage:
    python3 scripts/gen_test_patterns/ihp_sg13g2.py [--output-dir DIR] [PATTERN ...]
"""
from __future__ import annotations

import importlib
import os
import sys
from typing import *

import klayout.db as kdb

from pattern_builder import GDSPair, Pattern, main, pdk_root

ACTIV:        GDSPair = (1, 0)
GATPOLY:      GDSPair = (5, 0)
CONT:         GDSPair = (6, 0)
PSD:          GDSPair = (14, 0)
NWELL:        GDSPair = (31, 0)
NBULAY:       GDSPair = (32, 0)
METAL1:       GDSPair = (8, 0)
METAL1_PIN:   GDSPair = (8, 2)
METAL2:       GDSPair = (10, 0)
METAL2_PIN:   GDSPair = (10, 2)
VIA1:         GDSPair = (19, 0)
VIA2:         GDSPair = (29, 0)
METAL3:       GDSPair = (30, 0)
METAL3_PIN:   GDSPair = (30, 2)
VIA3:         GDSPair = (49, 0)
METAL4:       GDSPair = (50, 0)
METAL4_PIN:   GDSPair = (50, 2)
METAL5:       GDSPair = (67, 0)
METAL5_PIN:   GDSPair = (67, 2)
MIM:          GDSPair = (36, 0)
VMIM:         GDSPair = (129, 0)
TOPMETAL1:    GDSPair = (126, 0)
TOPMETAL1_PIN: GDSPair = (126, 2)
TOPMETAL2:    GDSPair = (134, 0)
TOPMETAL2_PIN: GDSPair = (134, 2)
TOPVIA2:      GDSPair = (133, 0)
DIGISUB:      GDSPair = (60, 0)
POLYRES:      GDSPair = (128, 0)
NORCX:        GDSPair = (148, 0)
PR_BOUNDARY:  GDSPair = (189, 4)
METAL3_NOQRC: GDSPair = (30, 28)
NORCX_M2M3:   GDSPair = (148, 41)
NORCX_M3SUB:  GDSPair = (148, 125)

LABEL_BY_LAYER: Dict[GDSPair, GDSPair] = {
    METAL1: (8, 25),
    METAL2: (10, 25),
    METAL3: (30, 25),
    METAL4: (50, 25),
    METAL5: (67, 25),
    TOPMETAL1: (126, 25),
    TOPMETAL2: (134, 25),
}


def pattern(name: str) -> Pattern:
    return Pattern(name, label_layer_by_layer=LABEL_BY_LAYER)


def load_pdk_pcells(technology: str = 'sg13g2') -> str:
    """
    :param technology: of the PDK, e.g. sg13cmos5l of ihp-sg13cmos5l
    :return: the technology of the pcell library SG13_dev
    """
    if kdb.Library.library_by_name('SG13_dev', technology) is None:
        klayout_dir = os.path.join(pdk_root(), f"ihp-{technology}", 'libs.tech', 'klayout')
        sys.path.insert(0, os.path.join(klayout_dir, 'python'))
        sys.path.insert(0, os.path.join(klayout_dir, 'python', 'pycell4klayout-api', 'source', 'python'))
        importlib.import_module(f"{technology}_pycell_lib")  # NOTE: registers the library SG13_dev
    return technology


#
# Capacitance patterns
#

def mom_cap(name: str,
            pcell_name: str,
            parameters: Dict[str, Any],
            technology: str = 'sg13g2',
            trans: kdb.Trans = kdb.Trans()) -> Pattern:
    """
    A pattern of a MOM cap of the pcells of the PDK, flattened
    """
    p = pattern(name)
    p.layout.technology_name = load_pdk_pcells(technology)
    pcell = p.layout.create_cell(pcell_name, 'SG13_dev', parameters)
    p.top.insert(kdb.CellInstArray(pcell.cell_index(), trans))
    p.top.flatten(-1, True)
    return p


def label_terminals_from_left(p: Pattern, metal: GDSPair, metal_pin: GDSPair):
    """
    The MOM caps of the pcells whose pins are on one metal, the left one is PLUS (the lower one, of two in a column),
    e.g. of cmomf, at its left edge, and MINUS at its top edge
    """
    pins = sorted(kdb.Region(p.top.begin_shapes_rec(p.layout.layer(*metal_pin))).merged().each(),
                  key=lambda pin: (pin.bbox().left, pin.bbox().bottom))
    for text, pin in zip(('PLUS', 'MINUS'), pins):
        center = pin.bbox().center()
        p.label(metal, text, center.x, center.y)


def wire_across(p: Pattern, metal: GDSPair, metal_pin: GDSPair, half_width: int = 500):
    """
    A wire X across the layout so far, with its pin beside it
    """
    bbox = p.top.bbox()
    y = bbox.center().y
    p.box(metal, bbox.left - 2000, y - half_width, bbox.right + 2000, y + half_width)
    p.box(metal_pin, bbox.left - 2000, y - half_width, bbox.left - 1000, y + half_width)
    p.label(metal, 'X', bbox.left - 1500, y)


def cap_cmomf_w10u_l25u_m2_m4_m5_wire() -> Pattern:
    # a MOM cap (cmomf pcell of the PDK) of 10 µm x 25 µm, with fingers on Metal2 … Metal4
    # (the model gives 0.915 fF/µm², 228.75 fF), its terminals labelled PLUS (left) and MINUS (top),
    # and a Metal5 wire X across it
    p = mom_cap('cap_cmomf_w10u_l25u_m2_m4_m5_wire', 'cmomf', {'w': '10u', 'l': '25u', 'mmin': 2, 'mmax': 4})
    label_terminals_from_left(p, METAL4, METAL4_PIN)
    wire_across(p, METAL5, METAL5_PIN)
    return p


def cap_cmomf_w5u_l5u_m2_m4_plus_from_m1() -> Pattern:
    # a MOM cap (cmomf pcell of the PDK) with fingers on Metal2 … Metal4, its terminal PLUS also connected
    # from below: a Metal1 wire through a Via1 within the marker onto the left bar of its Metal2,
    # so there are vias under the fingers, but no fingers on Metal1
    p = mom_cap('cap_cmomf_w5u_l5u_m2_m4_plus_from_m1', 'cmomf', {'w': '5u', 'l': '5u', 'mmin': 2, 'mmax': 4})
    label_terminals_from_left(p, METAL4, METAL4_PIN)
    bbox = p.top.bbox()
    y = bbox.center().y
    p.box(VIA1, bbox.left + 5, y - 95, bbox.left + 195, y + 95)
    p.box(METAL1, bbox.left - 2000, y - 150, bbox.left + 200, y + 150)
    return p


def cap_cmomi_w5u_l5u_m3_m5_same_m1_m2_wire() -> Pattern:
    # a MOM cap (cmomi pcell of the PDK) with fingers on Metal3 … Metal5 and its terminals on stacked pads
    # (feed same): PLUS on Metal5, MINUS on Metal4, and under it a wire X across it on Metal1 and Metal2,
    # both joined by a Via1 within the marker, so there are vias under the fingers, which don't belong to them
    p = mom_cap('cap_cmomi_w5u_l5u_m3_m5_same_m1_m2_wire', 'cmomi',
                {'w': '5u', 'l': '5u', 'mmin': 3, 'mmax': 5, 'feed': 'same'})
    for text, metal, metal_pin in (('PLUS', METAL5, METAL5_PIN), ('MINUS', METAL4, METAL4_PIN)):
        pin = kdb.Region(p.top.begin_shapes_rec(p.layout.layer(*metal_pin))).bbox()
        p.label(metal, text, pin.center().x, pin.center().y)
    bbox = p.top.bbox()
    center = bbox.center()
    p.box(METAL2, bbox.left - 500, center.y - 150, bbox.right + 500, center.y + 150)
    p.box(VIA1, center.x - 95, center.y - 95, center.x + 95, center.y + 95)
    wire_across(p, METAL1, METAL1_PIN, half_width=150)
    return p


def cap_cmomi_w5u_l5u_m4_m5_none() -> Pattern:
    # a MOM cap (cmomi pcell of the PDK) without feeds: its pins are on opposite corners of the array,
    # for the caller to connect the rows
    p = mom_cap('cap_cmomi_w5u_l5u_m4_m5_none', 'cmomi', {'w': '5u', 'l': '5u', 'mmin': 4, 'mmax': 5, 'feed': 'none'})
    label_terminals_from_left(p, METAL5, METAL5_PIN)
    return p


def cap_cmomi_w8u9_l3u36_m1_m5_r90() -> Pattern:
    # a MOM cap (cmomi pcell of the PDK) of 10 rows and 4 columns, turned by 90°, with opposite feeds, so its rows run
    # along y (the model gives 1.36 fF/µm² of 3.36 µm x 8.9 µm and 0.152 fF/µm of its pads, 42.086 fF)
    p = mom_cap('cap_cmomi_w8u9_l3u36_m1_m5_r90', 'cmomi', {'w': '8.9u', 'l': '3.36u', 'mmin': 1, 'mmax': 5},
                trans=kdb.Trans.R90)
    label_terminals_from_left(p, METAL5, METAL5_PIN)
    return p


def cap_cmomi_w3u_l2u_m4_m5_orientations() -> Pattern:
    # the MOM caps (cmomi pcell of the PDK) of the feeds, each in all 8 orientations, of 3 rows and 2 columns
    p = pattern('cap_cmomi_w3u_l2u_m4_m5_orientations')
    p.layout.technology_name = load_pdk_pcells()
    for row, feed in enumerate(('none', 'same', 'double')):
        pcell = p.layout.create_cell('cmomi', 'SG13_dev', {'w': '3u', 'l': '2u', 'mmin': 4, 'mmax': 5, 'feed': feed})
        for column, orientation in enumerate((kdb.Trans.R0, kdb.Trans.R90, kdb.Trans.R180, kdb.Trans.R270,
                                              kdb.Trans.M0, kdb.Trans.M45, kdb.Trans.M90, kdb.Trans.M135)):
            p.top.insert(kdb.CellInstArray(pcell.cell_index(), kdb.Trans(orientation, column * 10000, row * 10000)))
    p.top.flatten(-1, True)
    return p


def cap_cmim_over_m4_wire(name: str) -> Pattern:
    """
    A MIM cap of 20 µm x 20 µm: the MIM top plate on a Metal5 bottom plate of net A, which encloses it by 2 µm,
    joined by a Vmim in its middle to the TopMetal1 of net B over it (0.345 µm within it, as in the cmim pcell),
    over a Metal4 wire D of 2 µm width across it, which the bottom plate shields from the top plate
    """
    p = pattern(name)
    p.box(METAL5, 0, 0, 24000, 24000)
    p.box(METAL5_PIN, 0, 0, 2000, 2000)
    p.label(METAL5, 'A', 200, 200)
    p.box(MIM, 2000, 2000, 22000, 22000)
    p.box(VMIM, 11790, 11790, 12210, 12210)
    p.box(TOPMETAL1, 2345, 2345, 21655, 21655)
    p.box(TOPMETAL1_PIN, 19655, 19655, 21655, 21655)
    p.label(TOPMETAL1, 'B', 19855, 19855)
    p.box(METAL4, -10000, 11000, 34000, 13000)
    p.box(METAL4_PIN, -10000, 11000, -8000, 13000)
    p.label(METAL4, 'D', -9800, 11200)
    return p


def metal5_routes_in_cells(p: Pattern, left: int, right: int, *bottoms: int):
    """
    Metal5 routes of 1 µm width from left to right, each in a cell of its own, as generated layouts have them,
    over the bottom plate of a MIM cap: it stays apart from the Metal5 of the top cell in the LVS layers
    """
    for idx, bottom in enumerate(bottoms):
        cell = p.layout.create_cell(f"ROUTE{idx}")
        cell.shapes(p.layout.layer(*METAL5)).insert(kdb.Box(left, bottom, right, bottom + 1000))
        p.top.insert(kdb.CellInstArray(cell.cell_index(), kdb.Trans()))


def cap_cmim_20um_x_20um_metal5_routes_in_cells() -> Pattern:
    """
    The MIM cap of cap_cmim_20um_x_20um_over_m4_wire, with Metal5 routes across its top plate, within its bottom plate
    """
    p = cap_cmim_over_m4_wire('cap_cmim_20um_x_20um_metal5_routes_in_cells')
    metal5_routes_in_cells(p, 1000, 23000, 10000, 14000)
    return p


def rfcmim_w7u_l7u(name: str) -> Pattern:
    """
    The rfcmim of the test data (sg13g2_pr__rfcmim, 7 µm x 7 µm, wfeed 3 µm, its terminals PLUS and MINUS)
    """
    p = pattern(name)
    p.copy_design('ihp-sg13g2', 'sg13g2_pr__rfcmim', 'rfcmim.gds.gz')

    # NOTE: the cell labels its pins on the text layer only, label them as the terminals of the model
    for layer, pin_layer, text in ((TOPMETAL1, TOPMETAL1_PIN, 'PLUS'), (METAL5, METAL5_PIN, 'MINUS')):
        pin, = kdb.Region(p.top.begin_shapes_rec(p.layout.layer(*pin_layer))).merged().each()
        center = pin.bbox().center()
        p.label(layer, text, center.x, center.y)
    return p


def cap_rfcmim_w7u_l7u_over_m4_wire() -> Pattern:
    """
    The rfcmim of rfcmim_w7u_l7u, with a Metal4 wire D of 1 µm width under it, across the cap,
    which the bottom plate shields from the top plate
    """
    p = rfcmim_w7u_l7u('cap_rfcmim_w7u_l7u_over_m4_wire')
    p.box(METAL4, 3000, -8000, 4000, 15000)
    p.box(METAL4_PIN, 3000, -8000, 4000, -7000)
    p.label(METAL4, 'D', 3200, -7800)
    return p


def cap_rfcmim_w7u_l7u_metal5_routes_in_cells() -> Pattern:
    """
    The rfcmim of rfcmim_w7u_l7u, with Metal5 routes across its top plate, one of them over the start of its feed,
    both within its PWellBlock
    """
    p = rfcmim_w7u_l7u('cap_rfcmim_w7u_l7u_metal5_routes_in_cells')
    metal5_routes_in_cells(p, -1000, 8000, 1500, 5500)
    return p


def cap_rfcmim_w7u_l7u_two_feeds() -> Pattern:
    """
    The rfcmim of rfcmim_w7u_l7u, with a second Metal5 feed of 1 µm width out of its PWellBlock,
    so it has no single wfeed
    """
    p = rfcmim_w7u_l7u('cap_rfcmim_w7u_l7u_two_feeds')
    p.box(METAL5, -5000, 3000, 0, 4000)
    return p


def single_plate_6um_x_8um_m1_over_isolated_pwell() -> Pattern:
    """
    A Metal1 plate A of 6 µm x 8 µm over an isolated p-well: the hole of 12 µm x 10 µm of an NWell ring
    of 2 µm width over an nBuLay, which encloses the ring by 1 µm; a p-tap in the hole ties the p-well to W
    """
    p = pattern('single_plate_6um_x_8um_m1_over_isolated_pwell')
    p.box(NBULAY, -3000, -3000, 15000, 13000)
    for ring_part in ((-2000, -2000, 14000, 0), (-2000, 10000, 14000, 12000),
                      (-2000, 0, 0, 10000), (12000, 0, 14000, 10000)):
        p.box(NWELL, *ring_part)

    p.box(ACTIV, 9000, 4000, 11000, 6000)
    p.box(PSD, 8800, 3800, 11200, 6200)
    p.box(CONT, 9920, 4920, 10080, 5080)
    p.box(METAL1, 9700, 4700, 10300, 5300)
    p.box(METAL1_PIN, 9700, 4700, 10300, 5300)
    p.label(METAL1, 'W', 10000, 5000)

    p.box(METAL1, 1000, 1000, 7000, 9000)
    p.box(METAL1_PIN, 3500, 4500, 4500, 5500)
    p.label(METAL1, 'A', 4000, 5000)
    return p


def wires_no_pin() -> Pattern:
    """
    Two Metal3 wires of 50 µm x 0.5 µm, 1.5 µm apart, labelled A and B on the text layer only, without a pin,
    so that nothing drives them (#407)
    """
    p = pattern('wires_no_pin')
    for index, label in enumerate(('A', 'B')):
        y = index * 2000
        p.box(METAL3, 0, y, 50000, y + 500)
        p.label(METAL3, label, 1000, y + 250)
    return p


#
# Resistance patterns
#

def r_wire_over_nbulay_m1() -> Pattern:
    """
    A Metal1 wire of 10 µm x 0.5 µm from A to B, over an nBuLay (the deep n-well),
    which is no conductor of the resistance network
    """
    p = pattern('r_wire_over_nbulay_m1')
    p.box(NBULAY, -2000, -2000, 12000, 2500)
    p.box(METAL1, 0, 0, 10000, 500)
    p.box(METAL1_PIN, 0, 0, 500, 500)
    p.box(METAL1_PIN, 9500, 0, 10000, 500)
    p.label(METAL1, 'A', 250, 250)
    p.label(METAL1, 'B', 9750, 250)
    return p


#
# Exclusion marker patterns
#

def metal3_wire(p: Pattern, x1: int, y1: int, x2: int, y2: int, label: Optional[str] = None):
    """
    A Metal3 wire, with a pin at its left end, if it has a label
    """
    p.box(METAL3, x1, y1, x2, y2)
    if label is not None:
        p.box(METAL3_PIN, x1, y1, x1 + 1000, y2)
        p.label(METAL3, label, x1 + 500, (y1 + y2) // 2)


def metal2_pin(p: Pattern, label: str, x1: int, y1: int, x2: int, y2: int):
    p.box(METAL2_PIN, x1, y1, x2, y2)
    p.label(METAL2, label, (x1 + x2) // 2, (y1 + y2) // 2)


def exclusion_wire_through() -> Pattern:
    """
    A Metal3 wire of 60 µm x 2 µm from A to B, with its middle third within a marker
    """
    p = pattern('exclusion_wire_through')
    metal3_wire(p, -20000, 0, 40000, 2000, 'A')
    p.box(METAL3_PIN, 39000, 0, 40000, 2000)
    p.label(METAL3, 'B', 39500, 1000)
    p.box(NORCX, 0, -5000, 20000, 7000)
    return p


def exclusion_wire_through_octagon() -> Pattern:
    """
    A Metal3 wire from A to B, which bends by 45° through the sloped edges of an octagonal marker
    """
    p = pattern('exclusion_wire_through_octagon')
    p.path(METAL3, [(-20000, -15000), (-10000, -15000), (10000, 5000), (20000, 5000)], 2000)
    p.box(METAL3_PIN, -20000, -16000, -19000, -14000)
    p.label(METAL3, 'A', -19500, -15000)
    p.box(METAL3_PIN, 19000, 4000, 20000, 6000)
    p.label(METAL3, 'B', 19500, 5000)
    p.polygon(NORCX, [(-6000, -14000), (-14000, -6000), (-14000, 6000), (-6000, 14000),
                      (6000, 14000), (14000, 6000), (14000, -6000), (6000, -14000)])
    return p


def exclusion_wire_middle() -> Pattern:
    """
    The part of exclusion_wire_through within the marker, on its own, with the pins P and Q at its ends,
    as a model that goes between the ports at the cuts
    """
    p = pattern('exclusion_wire_middle')
    p.box(METAL3, 0, 0, 20000, 2000)
    p.box(METAL3_PIN, 0, 0, 2, 2000)
    p.box(METAL3_PIN, 19998, 0, 20000, 2000)
    p.label(METAL3, 'P', 1, 1000)
    p.label(METAL3, 'Q', 19999, 1000)
    return p


def exclusion_wire_end(name: str, label: Optional[str]) -> Pattern:
    """
    A Metal3 wire of 40 µm x 2 µm, whose half ends within a marker
    """
    p = pattern(name)
    metal3_wire(p, -20000, 0, 20000, 2000, label)
    p.box(NORCX, 0, -5000, 30000, 7000)
    return p


def exclusion_plate_neighbor(name: str, plate_label: Optional[str]) -> Pattern:
    """
    A Metal3 plate of 20 µm x 20 µm just within a marker, and a Metal3 wire N beside it outside the marker,
    0.3 µm from the plate
    """
    p = pattern(name)
    metal3_wire(p, 0, 0, 20000, 20000, plate_label)
    metal3_wire(p, -20000, 20300, 40000, 20800, 'N')
    p.box(NORCX, 0, 0, 20000, 20000)
    return p


def exclusion_plates_markers(name: str, marker_boxes: List[Tuple[int, int, int, int]]) -> Pattern:
    """
    Metal3 plates P and Q of 20 µm x 20 µm, 0.5 µm apart
    """
    p = pattern(name)
    metal3_wire(p, 0, 0, 20000, 20000, 'P')
    metal3_wire(p, 20500, 0, 40500, 20000, 'Q')
    for box in marker_boxes:
        p.box(NORCX, *box)
    return p


def metal2_wires_metal3_bridge(name: str, marker: bool, bridge_label: Optional[str] = None) -> Pattern:
    """
    A wire from A to B on Metal2, with a Metal3 bridge of its gap in the middle, with a marker around the bridge,
    and a pin on the left half of the bridge, if it has a label
    """
    p = pattern(name)
    p.box(METAL2, -10000, 0, 4000, 2000)
    p.box(METAL2, 7000, 0, 20000, 2000)
    p.box(METAL3, 3000, 0, 8000, 2000)
    p.box(VIA2, 3200, 500, 3600, 900)
    p.box(VIA2, 7200, 500, 7600, 900)
    metal2_pin(p, 'A', -10000, 0, -9000, 2000)
    metal2_pin(p, 'B', 19000, 0, 20000, 2000)
    if marker:
        p.box(NORCX, 0, -5000, 10000, 7000)
    if bridge_label is not None:
        p.box(METAL3_PIN, 4000, 0, 5000, 2000)
        p.label(METAL3, bridge_label, 4500, 1000)
    return p


def exclusion_via_across() -> Pattern:
    """
    A wire from A on Metal2 to B on Metal3, through a via across the edge of a marker
    """
    p = pattern('exclusion_via_across')
    p.box(METAL2, -10000, 0, 5000, 2000)
    p.box(METAL3, -1000, 0, 5000, 2000)
    p.box(VIA2, -200, 500, 200, 900)
    metal2_pin(p, 'A', -10000, 0, -9000, 2000)
    p.box(METAL3_PIN, 4000, 0, 5000, 2000)
    p.label(METAL3, 'B', 4500, 1000)
    p.box(NORCX, 0, -5000, 10000, 7000)
    return p


def exclusion_stubs() -> Pattern:
    """
    Two Metal3 stubs of a net, which only the metal outside the marker joins, with their pins S1 and S2 within it
    """
    p = pattern('exclusion_stubs')
    metal3_wire(p, -10000, 0, 3000, 1000)
    metal3_wire(p, -10000, 4000, 3000, 5000)
    metal3_wire(p, -10000, 0, -9000, 5000)
    p.box(METAL3_PIN, -10000, 2000, -9000, 3000)
    p.label(METAL3, 'A', -9500, 2500)
    for label, y in (('S1', 0), ('S2', 4000)):
        p.box(METAL3_PIN, 2000, y, 3000, y + 1000)
        p.label(METAL3, label, 2500, y + 500)
    p.box(NORCX, 0, -5000, 10000, 10000)
    return p


def exclusion_marker_in_cell() -> Pattern:
    """
    A wire of the top cell from A to a Metal3 stub in a rotated child cell, which has the marker
    """
    p = pattern('exclusion_marker_in_cell')
    block = p.layout.create_cell('block')
    block.shapes(p.layout.layer(*METAL3)).insert(kdb.Box(0, 0, 20000, 2000))
    block.shapes(p.layout.layer(*NORCX)).insert(kdb.Box(0, -5000, 20000, 7000))
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans(kdb.Trans.R90, 50000, 50000)))
    metal3_wire(p, 47000, 30000, 49000, 60000)
    p.box(METAL3, 47000, 49000, 53000, 51000)
    p.box(METAL3_PIN, 47000, 30000, 49000, 31000)
    p.label(METAL3, 'A', 48000, 30500)
    return p


def exclusion_coil_guard_ring() -> Pattern:
    """
    A hand-drawn coil of the tank of an LC oscillator, for an EM model:
      - a TopMetal2 loop within a marker, with its leads to OSCP and OSCN,
        and a center tap on TopMetal1 to VCT, labeled ind1, ind2 and ct within the marker, near where they leave it
      - a TopMetal1 guard ring VDD around the marker, so outside it, with a gap for the center tap
      - a Metal5 wire VC below the leads, outside the marker
    """
    p = pattern('exclusion_coil_guard_ring')
    for x1, y1, x2, y2 in ((-30000, 10000, -24000, 70000), (24000, 10000, 30000, 70000),
                           (-30000, 64000, 30000, 70000),
                           (-30000, 10000, -16000, 16000), (16000, 10000, 30000, 16000),
                           (-22000, -20000, -16000, 16000), (16000, -20000, 22000, 16000)):
        p.box(TOPMETAL2, x1, y1, x2, y2)
    p.box(TOPMETAL1, -2000, -20000, 2000, 69000)
    p.box(TOPVIA2, -1000, 65500, 1000, 68500)

    for layer, pin_layer, x, outer_label, inner_label in ((TOPMETAL2, TOPMETAL2_PIN, -19000, 'OSCP', 'ind1'),
                                                          (TOPMETAL2, TOPMETAL2_PIN, 19000, 'OSCN', 'ind2'),
                                                          (TOPMETAL1, TOPMETAL1_PIN, 0, 'VCT', 'ct')):
        for label, y in ((outer_label, -19000), (inner_label, 6000)):
            p.box(pin_layer, x - 1000, y - 1000, x + 1000, y + 1000)
            p.label(layer, label, x, y)

    for x1, y1, x2, y2 in ((-45000, -5000, -40000, 85000), (40000, -5000, 45000, 85000),
                           (-45000, 80000, 45000, 85000),
                           (-45000, -5000, -26000, 0), (26000, -5000, 45000, 0)):
        p.box(TOPMETAL1, x1, y1, x2, y2)
    p.box(TOPMETAL1_PIN, -45000, 40000, -40000, 42000)
    p.label(TOPMETAL1, 'VDD', -42500, 41000)

    p.box(METAL5, -60000, -14000, 60000, -12000)
    p.box(METAL5_PIN, -60000, -14000, -59000, -12000)
    p.label(METAL5, 'VC', -59500, -13000)

    p.box(NORCX, -36000, 4000, 36000, 76000)
    return p


def exclusion_inductor2_wire_under() -> Pattern:
    """
    The inductor of inductor2_w2u_d15u48_tm2_wires_50u,
    with a Metal5 wire from Y1 to Y2 across its marker, under its coil
    """
    p = pattern('exclusion_inductor2_wire_under')
    p.copy_design('ihp-sg13g2', 'test_patterns', 'inductor2_w2u_d15u48_tm2_wires_50u.gds.gz')
    p.box(METAL5, -50000, 28000, 50000, 30000)
    for label, x1 in (('Y1', -50000), ('Y2', 49000)):
        p.box(METAL5_PIN, x1, 28000, x1 + 1000, 30000)
        p.label(METAL5, label, x1 + 500, 29000)
    return p


def exclusion_hairpin(name: str, bridge_gap: int, bridge_layer: GDSPair) -> Pattern:
    """
    Metal3 wires from A and B, 2 µm apart, which end within a marker, joined there by a bridge,
    of Metal3, so one polygon with them, or of Metal2, through vias, with a gap for two nets
    """
    p = pattern(name)
    metal3_wire(p, -30000, 0, 5000, 2000, 'A')
    metal3_wire(p, -30000, 4000, 5000, 6000, 'B')
    p.box(bridge_layer, 3000, 0, 5000, 3000 - bridge_gap // 2)
    p.box(bridge_layer, 3000, 3000 + bridge_gap // 2, 5000, 6000)
    if bridge_layer != METAL3:
        p.box(VIA2, 3500, 500, 3900, 900)
        p.box(VIA2, 3500, 5100, 3900, 5500)
    p.box(NORCX, 0, -5000, 10000, 11000)
    return p


def exclusion_stacked_wires(name: str, via: bool) -> Pattern:
    """
    A Metal3 wire from A over a Metal2 wire from B, overlapping by half of their widths, which end within a marker,
    joined there by a via, or not, for two nets
    """
    p = pattern(name)
    metal3_wire(p, -30000, 0, 5000, 2000, 'A')
    p.box(METAL2, -30000, 1000, 5000, 3000)
    metal2_pin(p, 'B', -30000, 1000, -29000, 3000)
    if via:
        p.box(VIA2, 3000, 1300, 3400, 1700)
    p.box(NORCX, 0, -5000, 10000, 8000)
    return p


def exclusion_plate_between_wires(name: str, plate_marker: Optional[GDSPair]) -> Pattern:
    """
    A Metal3 plate P of 20 µm x 20 µm between a Metal2 wire A and a Metal4 wire B, with a marker of its size
    """
    p = pattern(name)
    for layer, pin_layer, label in ((METAL2, METAL2_PIN, 'A'), (METAL4, METAL4_PIN, 'B')):
        p.box(layer, -15000, 9000, 35000, 11000)
        p.box(pin_layer, -15000, 9000, -14000, 11000)
        p.label(layer, label, -14500, 10000)
    metal3_wire(p, 0, 0, 20000, 20000, 'P')
    if plate_marker is not None:
        p.box(plate_marker, 0, 0, 20000, 20000)
    return p


COIL_LOOP_BOXES = ((-30000, 10000, -24000, 70000), (24000, 10000, 30000, 70000),
                   (-30000, 64000, 30000, 70000),
                   (-30000, 10000, -16000, 16000), (16000, 10000, 30000, 16000),
                   (-22000, 0, -16000, 16000), (16000, 0, 22000, 16000))
COIL_CENTER_TAP_BOX = (-2000, 0, 2000, 69000)
COIL_VIA_BOX = (-1000, 65500, 1000, 68500)
COIL_LABELS = ((TOPMETAL2, 'LA', -19000, 2000), (TOPMETAL2, 'LB', 19000, 2000), (TOPMETAL1, 'CT', 0, 2000))


def cut_coil_model() -> Pattern:
    """
    The coil of cut_coil_pattern on its own, without its guard ring, with pins on its leads, as a model
    that goes between the ports of the cut
    """
    p = pattern('cut_coil_model')
    for box in COIL_LOOP_BOXES:
        p.box(TOPMETAL2, *box)
    p.box(TOPMETAL1, *COIL_CENTER_TAP_BOX)
    p.box(TOPVIA2, *COIL_VIA_BOX)
    for (layer, text, x, y), pin_layer, half_width in zip(COIL_LABELS, (TOPMETAL2_PIN, TOPMETAL2_PIN, TOPMETAL1_PIN),
                                                          (3000, 3000, 2000)):
        p.box(pin_layer, x - half_width, 0, x + half_width, 2)
        p.label(layer, text, x, 1)
    return p


def cut_coil_pattern(name: str, instance_count: int = 1) -> Pattern:
    """
    The tank of an LC oscillator with its coil in a child cell, to cut out for an EM model:
      - the child cell has a TopMetal2 loop with stubs of its leads, a center tap on TopMetal1 with a TopVia2,
        the labels LA, LB and CT on them, and a guard ring on TopMetal1 around all of it, labeled VDD, with a gap
      - the top cell has wires that go on from the stubs to OSCP, OSCN and VCT, and a Metal5 wire VC under the coil,
        which is no shape of the cell
    """
    p = pattern(name)
    coil = p.layout.create_cell('coil')

    def box(layer: GDSPair, x1: int, y1: int, x2: int, y2: int):
        coil.shapes(p.layout.layer(*layer)).insert(kdb.Box(x1, y1, x2, y2))

    def label(layer: GDSPair, text: str, x: int, y: int):
        coil.shapes(p.layout.layer(*p.label_layer_by_layer[layer])).insert(kdb.Text(text, kdb.Trans(x, y)))

    for loop_box in COIL_LOOP_BOXES:
        box(TOPMETAL2, *loop_box)
    box(TOPMETAL1, *COIL_CENTER_TAP_BOX)
    box(TOPVIA2, *COIL_VIA_BOX)
    for coil_label in COIL_LABELS:
        label(*coil_label)
    for x1, y1, x2, y2 in ((-45000, -5000, -40000, 85000), (40000, -5000, 45000, 85000),
                           (-45000, 80000, 45000, 85000),
                           (-45000, -5000, -26000, 0), (26000, -5000, 45000, 0)):
        box(TOPMETAL1, x1, y1, x2, y2)

    for index in range(instance_count):
        x = index * 150000
        p.top.insert(kdb.CellInstArray(coil.cell_index(), kdb.Trans(x, 0)))
        suffix = '' if instance_count == 1 else str(index)
        for layer, pin_layer, wire_x, text in ((TOPMETAL2, TOPMETAL2_PIN, -19000, f"OSCP{suffix}"),
                                               (TOPMETAL2, TOPMETAL2_PIN, 19000, f"OSCN{suffix}"),
                                               (TOPMETAL1, TOPMETAL1_PIN, 0, f"VCT{suffix}")):
            half_width = 3000 if layer == TOPMETAL2 else 2000
            p.box(layer, x + wire_x - half_width, -20000, x + wire_x + half_width, 1000)
            p.box(pin_layer, x + wire_x - 1000, -20000, x + wire_x + 1000, -18000)
            p.label(layer, text, x + wire_x, -19000)
        # NOTE: the guard ring joins the net by a stub of the top cell, which has its label
        p.box(TOPMETAL1, x - 45000, 40000, x - 50000, 42000)
        p.box(TOPMETAL1_PIN, x - 50000, 40000, x - 49000, 42000)
        p.label(TOPMETAL1, f"VDD{suffix}", x - 49500, 41000)
        p.box(METAL5, x - 60000, 30000, x + 60000, 32000)
        p.box(METAL5_PIN, x - 60000, 30000, x - 59000, 32000)
        p.label(METAL5, f"VC{suffix}", x - 59500, 31000)
    return p


def cut_coil_beside_marker() -> Pattern:
    """
    cut_coil with a marker over the half of the lead to OSCP next to the cell, which it abuts
    """
    p = cut_coil_pattern('cut_coil_beside_marker')
    p.box(NORCX, -25000, -10000, -13000, 0)
    return p


def cut_abutting_wires() -> Pattern:
    """
    A Metal3 wire through two instances of the cell seg, which abut, with wires of the top cell to the pins A and B
    """
    p = pattern('cut_abutting_wires')
    segment = p.layout.create_cell('seg')
    segment.shapes(p.layout.layer(*METAL3)).insert(kdb.Box(0, 0, 10000, 2000))
    for x in (0, 10000):
        p.top.insert(kdb.CellInstArray(segment.cell_index(), kdb.Trans(x, 0)))
    metal3_wire(p, -10000, 0, 0, 2000, 'A')
    metal3_wire(p, 20000, 0, 30000, 2000, 'B')
    return p


def cut_block_with_mos() -> Pattern:
    """
    A MOS of the design nmos_diode2 in a child cell, whose pins VDD and VSS on Metal3 the top cell wires on, and
    a Metal5 wire R over the cell, which is no shape of the cell
    """
    p = pattern('cut_block_with_mos')
    p.copy_design('ihp-sg13g2', 'nmos_diode2', 'nmos_diode2.gds.gz', subcell_name='block')
    block = p.layout.cell('block')
    bbox = block.bbox()
    metal3 = kdb.Region(block.begin_shapes_rec(p.layout.layer(*METAL3))).merged()
    pins = sorted(metal3.each(), key=lambda polygon: polygon.bbox().bottom)
    for text, polygon in zip(('A', 'B'), pins):
        box = polygon.bbox()
        p.box(METAL3, box.right - 100, box.bottom, box.right + 10000, box.bottom + 300)
        p.box(METAL3_PIN, box.right + 9500, box.bottom, box.right + 10000, box.bottom + 300)
        p.label(METAL3, text, box.right + 9750, box.bottom + 150)
    p.box(METAL5, bbox.left - 5000, bbox.center().y - 500, bbox.right + 15000, bbox.center().y + 500)
    p.box(METAL5_PIN, bbox.left - 5000, bbox.center().y - 500, bbox.left - 4000, bbox.center().y + 500)
    p.label(METAL5, 'R', bbox.left - 4500, bbox.center().y)
    return p


def child_cell_with_wire(p: Pattern, name: str, label: str) -> kdb.Cell:
    """
    A child cell with a Metal3 wire of 10 µm x 1 µm, with a pin at its left end
    """
    child = p.layout.create_cell(name)
    child.shapes(p.layout.layer(*METAL3)).insert(kdb.Box(0, 0, 10000, 1000))
    child.shapes(p.layout.layer(*METAL3_PIN)).insert(kdb.Box(0, 0, 1000, 1000))
    child.shapes(p.layout.layer(*p.label_layer_by_layer[METAL3])).insert(kdb.Text(label, kdb.Trans(500, 500)))
    return child


def label_in_child_cell_pattern(name: str) -> Pattern:
    """
    A wire in a child cell with the pin inner, and the pin outer of the top cell on the same wire
    """
    p = pattern(name)
    child = child_cell_with_wire(p, 'child', 'inner')
    p.top.insert(kdb.CellInstArray(child.cell_index(), kdb.Trans()))
    p.box(METAL3_PIN, 9000, 0, 10000, 1000)
    p.label(METAL3, 'outer', 9500, 500)
    return p


def label_only_in_child_cell() -> Pattern:
    """
    A wire in a child cell with the pin inner, without devices, and nothing of the top cell on it
    """
    p = pattern('label_only_in_child_cell')
    child = child_cell_with_wire(p, 'child', 'inner')
    p.top.insert(kdb.CellInstArray(child.cell_index(), kdb.Trans()))
    return p


def label_in_child_cell_within_marker() -> Pattern:
    """
    label_in_child_cell with a marker over the left half of the wire, with the pin inner of the child cell
    """
    p = label_in_child_cell_pattern('label_in_child_cell_within_marker')
    p.box(NORCX, -1000, -1000, 5000, 2000)
    return p


def labels_in_child_cells() -> Pattern:
    """
    Wires in two child cells with the pins a and b, joined by a wire of the top cell without a label
    """
    p = pattern('labels_in_child_cells')
    for index, label in enumerate(('a', 'b')):
        child = child_cell_with_wire(p, f"child_{label}", label)
        p.top.insert(kdb.CellInstArray(child.cell_index(), kdb.Trans(index * 20000, 0)))
    p.box(METAL3, 9000, 0, 21000, 1000)
    return p


def labels_without_pin_shapes() -> Pattern:
    """
    The design nmos_diode2 without its label VSS, with a Metal3 wire of 50 µm from the pin of VSS (the drain)
    to the label OUT, and beside it a Metal3 wire without devices with the label W, both without pin shapes.
    Below them, a Metal3 wire without devices with the pin P at its left end and the label Q at its right end,
    and the label VDD on the Metal3 between the pin VDD and its Via2, both without pin shapes
    """
    p = pattern('labels_without_pin_shapes')
    p.copy_design('ihp-sg13g2', 'nmos_diode2', 'nmos_diode2.gds.gz')
    for layer_index in p.layout.layer_indexes():
        for shape in list(p.top.shapes(layer_index).each(kdb.Shapes.STexts)):
            if shape.text_string == 'VSS':
                shape.delete()
    vss = min(kdb.Region(p.top.begin_shapes_rec(p.layout.layer(*METAL3))).merged().each(),
              key=lambda polygon: polygon.bbox().bottom).bbox()
    for text, bottom in (('OUT', vss.bottom), ('W', vss.bottom - 2000)):
        p.box(METAL3, vss.right - 100, bottom, vss.right + 50000, bottom + 300)
        p.label(METAL3, text, vss.right + 49900, bottom + 150)
    bottom = vss.bottom - 4000
    metal3_wire(p, vss.right - 100, bottom, vss.right + 50000, bottom + 300, 'P')
    p.label(METAL3, 'Q', vss.right + 49900, bottom + 150)
    p.label(METAL3, 'VDD', 800, 1000)
    return p


def cut_block_beside_mos() -> Pattern:
    """
    The design nmos_diode2 twice, in the child cells block and kept, side by side
    """
    p = pattern('cut_block_beside_mos')
    p.copy_design('ihp-sg13g2', 'nmos_diode2', 'nmos_diode2.gds.gz', subcell_name='block')
    block = p.layout.cell('block')
    kept = p.layout.create_cell('kept')
    kept.copy_tree(block)
    p.top.insert(kdb.CellInstArray(kept.cell_index(), kdb.Trans(block.bbox().width() + 5000, 0)))
    return p


def cut_inductor2_leads_in_top() -> Pattern:
    """
    The inductor of inductor2_w2u_d15u48_tm2_wires_50u in a child cell, without the wires outside its marker,
    which the top cell has, to the pins A and B, so that the terminals of the inductor are on the metal of the top cell
    """
    p = pattern('cut_inductor2_leads_in_top')
    p.copy_design('ihp-sg13g2', 'test_patterns', 'inductor2_w2u_d15u48_tm2_wires_50u.gds.gz', subcell_name='ind')
    ind = p.layout.cell('ind')
    metal_layer = p.layout.layer(*TOPMETAL2)
    metal = kdb.Region(ind.begin_shapes_rec(metal_layer)).merged()
    below_marker = kdb.Region(kdb.Box(-100000, -100000, 100000, 0))
    wires = metal & below_marker
    ind.shapes(metal_layer).clear()
    ind.shapes(metal_layer).insert(metal - below_marker)
    for layer in (TOPMETAL2_PIN, LABEL_BY_LAYER[TOPMETAL2]):
        ind.shapes(p.layout.layer(*layer)).clear()
    p.top.shapes(metal_layer).insert(wires)
    for text, wire in zip(('A', 'B'), sorted(wires.each(), key=lambda polygon: polygon.bbox().left)):
        box = wire.bbox()
        p.box(TOPMETAL2_PIN, box.left, box.bottom, box.right, box.bottom + 2000)
        p.label(TOPMETAL2, text, box.center().x, box.bottom + 1000)
    return p


def exclusion_hairpin_around_wire(name: str, bridge_gap: int) -> Pattern:
    """
    Metal3 wires from A and B, 6 µm apart, which end within a marker, joined there by a bridge (or two nets with a gap),
    and a Metal3 wire M between them, which shields them from each other
    """
    p = pattern(name)
    metal3_wire(p, -40000, 0, 5000, 2000, 'A')
    metal3_wire(p, -40000, 8000, 5000, 10000, 'B')
    p.box(METAL3, 3000, 0, 5000, 5000 - bridge_gap // 2)
    p.box(METAL3, 3000, 5000 + bridge_gap // 2, 5000, 10000)
    metal3_wire(p, -40000, 4000, -1000, 6000, 'M')
    p.box(NORCX, 0, -5000, 10000, 15000)
    return p


def exclusion_same_label_within() -> Pattern:
    """
    A Metal3 wire with a pin A outside a marker, and another pin A on its end within the marker
    """
    p = pattern('exclusion_same_label_within')
    metal3_wire(p, -20000, 0, 20000, 2000, 'A')
    p.box(METAL3_PIN, 9000, 0, 10000, 2000)
    p.label(METAL3, 'A', 9500, 1000)
    p.box(NORCX, 0, -5000, 30000, 7000)
    return p


def exclusion_tap_wire_through() -> Pattern:
    """
    A p-tap, whose Metal2 wire of the substrate net, without a label, goes through a marker, and a Metal3 wire W
    """
    p = pattern('exclusion_tap_wire_through')
    tap_m1_m2(p, 0, True, None)
    p.box(METAL2, 0, 0, 30000, 1000)
    p.box(NORCX, 10000, -3000, 20000, 4000)
    metal3_wire(p, -10000, 8000, 30000, 10000, 'W')
    return p


def exclusion_wire_over_nwell() -> Pattern:
    """
    A Metal3 wire W over an n-well, whose net is NW by a tap with a Metal1 pin
    """
    p = pattern('exclusion_wire_over_nwell')
    p.box(NWELL, 0, 0, 30000, 30000)
    metal3_wire(p, 5000, 5000, 25000, 10000, 'W')
    p.box(ACTIV, 1000, 20000, 4000, 23000)
    p.box(CONT, 2000, 21000, 2160, 21160)
    p.box(METAL1, 1000, 20000, 4000, 23000)
    p.box(METAL1_PIN, 1000, 20000, 2000, 23000)
    p.label(METAL1, 'NW', 1500, 21500)
    return p


def exclusion_slanted_wire() -> Pattern:
    """
    A Metal3 wire at an angle of 33 degrees from A to B through a marker
    """
    p = pattern('exclusion_slanted_wire')
    p.path(METAL3, [(-20000, -13000), (20000, 13000)], 2000)
    p.box(METAL3_PIN, -20000, -13200, -19800, -13000)
    p.label(METAL3, 'A', -19900, -13100)
    p.box(METAL3_PIN, 19800, 13000, 20000, 13200)
    p.label(METAL3, 'B', 19900, 13100)
    p.box(NORCX, -5000, -20000, 5000, 20000)
    return p


def cut_two_strips() -> Pattern:
    """
    The cell blk with two strips of Metal3, the label X on one of them, which only a wire of the top cell joins,
    with the pin T
    """
    p = pattern('cut_two_strips')
    block = p.layout.create_cell('blk')
    block.shapes(p.layout.layer(*METAL3)).insert(kdb.Box(0, 0, 2000, 2000))
    block.shapes(p.layout.layer(*METAL3)).insert(kdb.Box(0, 10000, 2000, 12000))
    block.shapes(p.layout.layer(*LABEL_BY_LAYER[METAL3])).insert(kdb.Text('X', kdb.Trans(1000, 1000)))
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    p.box(METAL3, -50000, 0, 0, 2000)
    p.box(METAL3, -50000, 10000, 0, 12000)
    p.box(METAL3, -52000, 0, -50000, 12000)
    p.box(METAL3_PIN, -52000, 5000, -51000, 6000)
    p.label(METAL3, 'T', -51500, 5500)
    return p


def cut_bend_beside_marker() -> Pattern:
    """
    Metal3 wires from A and B, which the cell bend joins, with a marker over 2 µm of the wire from A
    """
    p = pattern('cut_bend_beside_marker')
    bend = p.layout.create_cell('bend')
    bend.shapes(p.layout.layer(*METAL3)).insert(kdb.Box(0, 0, 5000, 8000))
    p.top.insert(kdb.CellInstArray(bend.cell_index(), kdb.Trans()))
    metal3_wire(p, -40000, 0, 0, 2000, 'A')
    metal3_wire(p, -40000, 6000, 0, 8000, 'B')
    p.box(NORCX, -5000, -1000, -3000, 3000)
    return p


def cut_rotated_cell() -> Pattern:
    """
    An instance of the cell seg with a Metal3 wire, rotated by 30 degrees, and a wire that goes on from it to the pin A
    """
    p = pattern('cut_rotated_cell')
    segment = p.layout.create_cell('seg')
    segment.shapes(p.layout.layer(*METAL3)).insert(kdb.Box(0, 0, 10000, 2000))
    p.top.insert(kdb.CellInstArray(segment.cell_index(), kdb.ICplxTrans(1.0, 30, False, 0, 0)))
    p.path(METAL3, [(8660, 5000), (20000, 11547)], 2000)
    p.box(METAL3_PIN, 19900, 11400, 20100, 11600)
    p.label(METAL3, 'A', 20000, 11500)
    return p


def exclusion_nmos_diode2_all() -> Pattern:
    """
    The design nmos_diode2 with a marker over all of it, so its nets, with their pins, are within the marker
    """
    p = pattern('exclusion_nmos_diode2_all')
    p.copy_design('ihp-sg13g2', 'nmos_diode2', 'nmos_diode2.gds.gz')
    p.box(NORCX, -20000, -20000, 20000, 20000)
    return p


def exclusion_nmos_diode2() -> Pattern:
    """
    The design nmos_diode2 with a marker over its MOS, whose terminals are on the conductors there,
    which leave the marker on Metal1 and Metal2
    """
    p = pattern('exclusion_nmos_diode2')
    p.copy_design('ihp-sg13g2', 'nmos_diode2', 'nmos_diode2.gds.gz')
    p.box(NORCX, -500, -700, 500, 700)
    return p


#
# Device patterns
#

def pcells_side_by_side(name: str, pcells: List[Tuple[str, Dict[str, Any]]], space: int = 10000) -> Pattern:
    """
    Pcells of the PDK, by name and parameters, side by side

    :param space: between their bounding boxes, in nm
    """
    technology = load_pdk_pcells()
    p = pattern(name)
    p.layout.technology_name = technology
    x = 0
    for pcell_name, parameters in pcells:
        pcell = p.layout.create_cell(pcell_name, 'SG13_dev', parameters)
        p.top.insert(kdb.CellInstArray(pcell.cell_index(), kdb.Trans(x - pcell.bbox().left, 0)))
        x += pcell.bbox().width() + space
    p.top.flatten(-1, True)
    return p


def bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa() -> Pattern:
    """
    The bipolar transistors (pcells of the PDK): an npn13G2 with 4 emitters, an npn13G2L, an npn13G2V and a pnpMPA,
    whose terminals are joined to the Metal1 over them by contacts (and the emitters of the npn13G2 and the npn13G2L
    by their emitter windows) within the devices
    """
    return pcells_side_by_side('bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa',
                               [('npn13G2', {'Nx': 4}), ('npn13G2L', {}), ('npn13G2V', {}), ('pnpMPA', {})])


def device_pcells() -> Pattern:
    """
    One each of the device pcells of the PDK, with their default parameters and no wires, but not
      - the ones with patterns of their own: the MOM caps, the MOS caps, the inductors, the ESD diodes,
        the antenna diodes
      - the ESD clamps nmoscl_2 and nmoscl_4, which take long
      - the npn13G2 with 1 emitter, whose collector overlaps no conductor without a wire (with 4 emitters, it does)
    """
    return pcells_side_by_side('device_pcells', [
        ('SVaricap', {}), ('cmim', {}), ('isolbox', {}), ('nmos', {}), ('nmosHV', {}), ('npn13G2L', {}),
        ('npn13G2V', {}), ('ntap1', {}), ('pmos', {}), ('pmosHV', {}), ('pnpMPA', {}), ('ptap1', {}), ('rfcmim', {}),
        ('rfnmos', {}), ('rfnmosHV', {}), ('rfpmos', {}), ('rfpmosHV', {}), ('rhigh', {}), ('rppd', {}), ('rsil', {}),
        ('schottky', {}),
    ])


def cap_moscap_n_moscap_p() -> Pattern:
    """
    The MOS caps sg13_moscap_n and sg13_moscap_p (moscap_n and moscap_p pcells of the PDK), side by side,
    with their default parameters and no wires
    """
    return pcells_side_by_side('cap_moscap_n_moscap_p', [('moscap_n', {}), ('moscap_p', {})])


def merged_shapes(p: Pattern, layer: GDSPair) -> kdb.Region:
    return kdb.Region(p.top.begin_shapes_rec(p.layout.layer(*layer))).merged()


def cap_moscap_n_x2_gatpoly_wire() -> Pattern:
    """
    Two MOS caps sg13_moscap_n of 5 µm x 5 µm (moscap_n pcells of the PDK), 0.5 µm apart, as in an array,
    with a Metal1 wire between their guard rings, as only the substrate would join them otherwise,
    which is no conductor of the resistance network,
    and a GatPoly wire outside the guard ring of the left one, 1.2 µm from its core
    """
    p = pcells_side_by_side('cap_moscap_n_x2_gatpoly_wire', [('moscap_n', {'w': '5u', 'l': '5u'})] * 2, space=500)
    cores = merged_shapes(p, ACTIV) & merged_shapes(p, GATPOLY)
    left_core = min(cores.each(), key=lambda core: core.bbox().left).bbox()
    guard_rings = sorted(merged_shapes(p, METAL1).each(), key=lambda metal: metal.bbox().height())[-2:]
    left_ring, right_ring = sorted((ring.bbox() for ring in guard_rings), key=lambda box: box.left)
    p.box(METAL1, left_ring.right - 100, left_core.center().y - 150, right_ring.left + 100, left_core.center().y + 150)
    p.box(GATPOLY, left_core.left - 1330, left_core.bottom, left_core.left - 1200, left_core.top)
    return p


def cap_moscap_p_x2_wells_apart() -> Pattern:
    """
    Two MOS caps sg13_moscap_p of 5 µm x 5 µm (moscap_p pcells of the PDK), each in an NWell of its own, 0.7 µm apart
    (NW.b1 wants 1.8 µm between wells of different nets), so each one's guard ring is within reach of the other's core
    """
    return pcells_side_by_side('cap_moscap_p_x2_wells_apart', [('moscap_p', {'w': '5u', 'l': '5u'})] * 2, space=700)


def cap_moscap_n_no_guard_ring() -> Pattern:
    """
    A MOS cap sg13_moscap_n (moscap_n pcell of the PDK) without the Metal1 of its guard ring, so it has no bulk port
    """
    p = pcells_side_by_side('cap_moscap_n_no_guard_ring', [('moscap_n', {})])
    metal1 = merged_shapes(p, METAL1)
    guard_ring = max(metal1.each(), key=lambda metal: metal.bbox().height())
    p.top.shapes(p.layout.layer(*METAL1)).clear()
    p.top.shapes(p.layout.layer(*METAL1)).insert(metal1 - kdb.Region(guard_ring))
    return p


def cap_svaricap_nwell_guard_ring() -> Pattern:
    """
    A varicap sg13_hv_svaricap (SVaricap pcell of the PDK) with its guard ring of NWell, so it's all in that well
    """
    return pcells_side_by_side('cap_svaricap_nwell_guard_ring', [('SVaricap', {'guardRingType': 'nwell'})])


def cap_svaricap_nwell_guard_ring_digisub() -> Pattern:
    """
    The varicap of cap_svaricap_nwell_guard_ring on a DigiSub, so it has no substrate below it for its terminal SUB
    """
    p = pcells_side_by_side('cap_svaricap_nwell_guard_ring_digisub', [('SVaricap', {'guardRingType': 'nwell'})])
    bbox = p.top.bbox().enlarged(2000, 2000)
    p.box(DIGISUB, bbox.left, bbox.bottom, bbox.right, bbox.top)
    return p


def res_rppd_x2_one_marker() -> Pattern:
    """
    Two rppd of 1 µm x 5 µm (pcells of the PDK), 0.18 µm apart, with a PolyRes bar that merges their markers
    """
    p = pcells_side_by_side('res_rppd_x2_one_marker', [('rppd', {'w': '1u', 'l': '5u'})] * 2, space=180)
    bbox = merged_shapes(p, POLYRES).bbox()
    p.box(POLYRES, bbox.left, bbox.center().y - 100, bbox.right, bbox.center().y + 100)
    return p


def inductor2_x2_markers_touching() -> Pattern:
    """
    Two inductors (inductor2 pcells of the PDK, 1 turn), whose markers touch
    """
    return pcells_side_by_side('inductor2_x2_markers_touching', [('inductor2', {})] * 2, space=0)


def esd_diode(model: str) -> Pattern:
    """
    An ESD diode (esd pcell of the PDK)
    """
    return pcells_side_by_side(f"esd_{model}", [('esd', {'model': model})])


def esd_diode_pair(model: str) -> Pattern:
    """
    Two ESD diodes (esd pcells of the PDK), unwired, so that only the substrate joins the Metal1 on their substrate net
    """
    return pcells_side_by_side(f"esd_{model}_pair", [('esd', {'model': model}), ('esd', {'model': model})])


def diode_dantenna_dpantenna() -> Pattern:
    """
    The antenna diodes (pcells of the PDK): the anode of the dantenna is on the substrate, the cathode of the dpantenna
    on an nwell, and the other terminals on the Metal1 over them
    """
    return pcells_side_by_side('diode_dantenna_dpantenna', [('dantenna', {}), ('dpantenna', {})])


def diode_schottky_nbl1() -> Pattern:
    """
    A Schottky diode schottky_nbl1 (schottky pcell of the PDK), its anode labelled A on the Metal2 over it
    and its cathode K on the Metal1 ring around the anode, both joined to the device by contacts within it
    """
    technology = load_pdk_pcells()
    p = pattern('diode_schottky_nbl1')
    p.layout.technology_name = technology
    pcell = p.layout.create_cell('schottky', 'SG13_dev', {})
    p.top.insert(kdb.CellInstArray(pcell.cell_index(), kdb.Trans()))
    p.top.flatten(-1, True)
    # NOTE: on the pins of the pcell, the anode's at the bottom of its Metal2, the cathode's at the top of its ring
    p.label(METAL2, 'A', 600, -1255)
    p.label(METAL1, 'K', 600, 2830)
    return p


def inductor2_w2u_d15u48_tm2_wires_50u() -> Pattern:
    """
    An inductor (inductor2 pcell of the PDK) of 1 turn of 2 µm width, 15.48 µm inner diameter,
    whose ports (on IND.pin, within its marker) abut its TopMetal2 leads, which wires of 50 µm
    continue to the pins LA and LB
    """
    technology = load_pdk_pcells()
    p = pattern('inductor2_w2u_d15u48_tm2_wires_50u')
    p.layout.technology_name = technology
    pcell = p.layout.create_cell('inductor2', 'SG13_dev', {'w': '2u', 's': '2.1u', 'd': '15.48u', 'nr_r': 1})
    p.top.insert(kdb.CellInstArray(pcell.cell_index(), kdb.Trans()))
    p.top.flatten(-1, True)

    # NOTE: the pcell paints the pins (TopMetal2.pin) on its leads, LA left and LB right, move them to the wires
    pin_layer = p.layout.layer(*TOPMETAL2_PIN)
    pins = sorted(kdb.Region(p.top.begin_shapes_rec(pin_layer)).merged().each(), key=lambda pin: pin.bbox().left)
    p.top.shapes(pin_layer).clear()
    for text, pin in zip(('LA', 'LB'), pins):
        box = pin.bbox()
        p.box(TOPMETAL2, box.left, box.bottom - 50000, box.right, box.bottom)
        p.box(TOPMETAL2_PIN, box.left, box.bottom - 50000, box.right, box.bottom - 48000)
        p.label(TOPMETAL2, text, box.center().x, box.bottom - 49000)
    return p


def inductor3_w2u_d25u84_2_turns() -> Pattern:
    """
    A center-tapped inductor (inductor3 pcell of the PDK) of 2 turns of 2 µm width, 25.84 µm inner diameter,
    whose TopVia2 within its marker join the windings (TopMetal2) to the underpass crossings (TopMetal1)
    """
    technology = load_pdk_pcells()
    p = pattern('inductor3_w2u_d25u84_2_turns')
    p.layout.technology_name = technology
    pcell = p.layout.create_cell('inductor3', 'SG13_dev', {'w': '2u', 's': '2.1u', 'd': '25.84u', 'nr_r': 2})
    p.top.insert(kdb.CellInstArray(pcell.cell_index(), kdb.Trans()))
    p.top.flatten(-1, True)
    return p


def tap_m1_m2(p: Pattern, x: int, ptap: bool, label: Optional[str] = None):
    """
    A tap of 0.5 µm x 5 µm at x, under a Metal1 wire of 0.3 µm width, joined by 5 contacts,
    and a Metal2 wire over that, joined by 2 vias, 4 µm apart

    :param ptap: a p-tap, otherwise an n-tap (for an NWell around it)
    :param label: of a pin in the middle of the Metal2 wire
    """
    if ptap:
        p.box(PSD, x - 180, -180, x + 680, 5180)
    p.box(ACTIV, x, 0, x + 500, 5000)
    for y in range(500, 5000, 1000):
        p.box(CONT, x + 170, y - 80, x + 330, y + 80)
    p.box(METAL1, x + 100, 0, x + 400, 5000)
    for y in (500, 4500):
        p.box(VIA1, x + 155, y - 95, x + 345, y + 95)
    p.box(METAL2, x + 100, 0, x + 400, 5000)
    if label is not None:
        p.box(METAL2_PIN, x + 100, 2350, x + 400, 2650)
        p.label(METAL2, label, x + 250, 2500)


def r_ptap_pair_m1_m2(name: str, labels: Tuple[Optional[str], Optional[str]]) -> Pattern:
    """
    Two p-taps 10 µm apart, with Metal1 and Metal2 wires over them (see tap_m1_m2), which only the substrate joins
    """
    p = pattern(name)
    tap_m1_m2(p, 0, ptap=True, label=labels[0])
    tap_m1_m2(p, 10000, ptap=True, label=labels[1])
    return p


def r_ntap_pair_nwell_m1_m2() -> Pattern:
    """
    Two n-taps 10 µm apart in one NWell, with Metal1 and Metal2 wires over them (see tap_m1_m2),
    which only the NWell joins, as it has no sheet resistance in the tech info
    """
    p = pattern('r_ntap_pair_nwell_m1_m2')
    p.box(NWELL, -1000, -1000, 11500, 6000)
    tap_m1_m2(p, 0, ptap=False)
    tap_m1_m2(p, 10000, ptap=False)
    return p


def nmos_pair_abutting_ptaps() -> Pattern:
    """
    Two nmos (pcells of the PDK) with their sources on the substrate net, as the salicide joins each source
    to a p-tap abutting it, so that only the substrate joins the Metal1 over the sources
    """
    p = pcells_side_by_side('nmos_pair_abutting_ptaps', [('nmos', {}), ('nmos', {})])
    for activ in kdb.Region(p.top.begin_shapes_rec(p.layout.layer(*ACTIV))).merged().each():
        box = activ.bbox()
        p.box(ACTIV, box.left - 500, box.bottom, box.left, box.top)
        p.box(PSD, box.left - 680, box.bottom - 180, box.left, box.top + 180)
    return p


CUT_CELL_PCELLS = [('dantenna', {}), ('dpantenna', {}), ('rppd', {}), ('nmos', {}), ('moscap_n', {}), ('isolbox', {}),
                   ('schottky', {})]


def with_boundary_of_child_cell(p: Pattern) -> Pattern:
    """
    Adds the child cell block, which only has its boundary over all of the top cell, and a wire beside that
    """
    bbox = p.top.bbox()
    block = p.layout.create_cell('block')
    block.shapes(p.layout.layer(*PR_BOUNDARY)).insert(bbox.enlarged(1000, 1000))
    block.shapes(p.layout.layer(*METAL3)).insert(kdb.Box(bbox.right + 2000, bbox.bottom,
                                                         bbox.right + 3000, bbox.bottom + 5000))
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    return p


def cut_boundary_over_devices() -> Pattern:
    """
    Devices (pcells of the PDK), whose terminals are on layers the tech info has or only LVS knows, in the top cell
    under the boundary of a child cell, which they aren't devices of
    """
    return with_boundary_of_child_cell(pcells_side_by_side('cut_boundary_over_devices', CUT_CELL_PCELLS))


def cut_boundary_over_inductor() -> Pattern:
    """
    The inductor of inductor2_w2u_d15u48_tm2_wires_50u, whose terminals only abut its leads, in the top cell
    under the boundary of a child cell, which it isn't a device of
    """
    p = pattern('cut_boundary_over_inductor')
    p.copy_design('ihp-sg13g2', 'test_patterns', 'inductor2_w2u_d15u48_tm2_wires_50u.gds.gz')
    return with_boundary_of_child_cell(p)


def cut_cell_of_devices() -> Pattern:
    """
    The devices of cut_boundary_over_devices within a child cell, with a wire beside it in the top cell
    """
    p = pcells_side_by_side('cut_cell_of_devices', CUT_CELL_PCELLS)
    block = p.layout.create_cell('block')
    block.copy_tree(p.top)
    p.top.clear()
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    bbox = p.top.bbox()
    p.box(METAL3, bbox.right + 2000, bbox.bottom, bbox.right + 3000, bbox.bottom + 5000)
    return p


def cut_abutting_std_cells() -> Pattern:
    """
    Three abutting cells of the standard cell sg13g2_a21o_1: left, middle and right, whose NWell and pSD go on
    over their neighbors
    """
    p = pattern('cut_abutting_std_cells')
    p.copy_design('ihp-sg13g2', 'sg13g2_a21o_1', 'sg13g2_a21o_1.gds.gz', subcell_name='middle')
    middle = p.layout.cell('middle')
    for name, x in (('left', -3360), ('right', 3360)):
        cell = p.layout.create_cell(name)
        cell.copy_tree(middle)
        p.top.insert(kdb.CellInstArray(cell.cell_index(), kdb.Trans(x, 0)))
    return p


def cut_pad_via_on_label(name: str = 'cut_pad_via_on_label') -> Pattern:
    """
    A child cell with a Metal3 pad of 5 µm x 5 µm and its pin P in the middle, on which a Via3 of the top cell lands,
    from a Metal4 wire to its pin W
    """
    p = pattern(name)
    block = p.layout.create_cell('block')
    block.shapes(p.layout.layer(*METAL3)).insert(kdb.Box(0, 0, 5000, 5000))
    block.shapes(p.layout.layer(*METAL3_PIN)).insert(kdb.Box(2400, 2400, 2600, 2600))
    block.shapes(p.layout.layer(*LABEL_BY_LAYER[METAL3])).insert(kdb.Text('P', kdb.Trans(2500, 2500)))
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    p.box(VIA3, 2400, 2400, 2600, 2600)
    p.box(METAL4, 2000, 1000, 3000, 20000)
    p.box(METAL4_PIN, 2000, 19000, 3000, 20000)
    p.label(METAL4, 'W', 2500, 19500)
    return p


def cut_pad_with_same_label_in_top() -> Pattern:
    """
    The child cell of cut_pad_via_on_label, whose pin P the top cell also has, at the same place
    """
    p = cut_pad_via_on_label('cut_pad_with_same_label_in_top')
    p.box(METAL3_PIN, 2400, 2400, 2600, 2600)
    p.label(METAL3, 'P', 2500, 2500)
    return p


def cut_rotated_child() -> Pattern:
    """
    A child cell with an instance of the cell seg with a Metal3 wire, rotated by 30 degrees,
    with a wire beside it in the top cell
    """
    p = pattern('cut_rotated_child')
    segment = p.layout.create_cell('seg')
    segment.shapes(p.layout.layer(*METAL3)).insert(kdb.Box(0, 0, 10000, 2000))
    block = p.layout.create_cell('block')
    block.insert(kdb.CellInstArray(segment.cell_index(), kdb.ICplxTrans(1.0, 30, False, 0, 0)))
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    p.box(METAL3, 30000, 0, 31000, 5000)
    return p


def cut_bjts_wire_on_collector() -> Pattern:
    """
    The BJTs of bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa within a child cell, with a Metal1 wire of the top cell
    over the whole collector terminal of the first one
    """
    p = pattern('cut_bjts_wire_on_collector')
    p.copy_design('ihp-sg13g2', 'test_patterns', 'bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa.gds.gz',
                  subcell_name='block')
    p.box(METAL1, 2375, -10430, 9875, 1280)
    return p


def cut_plate_with_fill() -> Pattern:
    """
    A child cell of a Metal3 plate of 10 µm x 10 µm, with fill below it on Metal2.filler, and a wire W beside it
    in the top cell
    """
    p = pattern('cut_plate_with_fill')
    block = p.layout.create_cell('block')
    block.shapes(p.layout.layer(*METAL3)).insert(kdb.Box(0, 0, 10000, 10000))
    for x in range(1000, 10000, 3000):
        for y in range(1000, 10000, 3000):
            block.shapes(p.layout.layer(10, 22)).insert(kdb.Box(x, y, x + 1500, y + 1500))
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    p.box(METAL3, 11000, 4000, 40000, 6000)
    p.box(METAL3_PIN, 39000, 4000, 40000, 6000)
    p.label(METAL3, 'W', 39500, 5000)
    return p


def cut_strip_along_wire() -> Pattern:
    """
    A Metal3 wire of 100 µm x 1 µm with the pins A and B, with a child cell with the Metal3 of the upper half of
    its width along 50 µm, and a marker over the same
    """
    p = pattern('cut_strip_along_wire')
    p.box(METAL3, 0, 0, 100000, 1000)
    p.box(METAL3_PIN, 0, 0, 200, 1000)
    p.label(METAL3, 'A', 100, 500)
    p.box(METAL3_PIN, 99800, 0, 100000, 1000)
    p.label(METAL3, 'B', 99900, 500)
    block = p.layout.create_cell('block')
    block.shapes(p.layout.layer(*METAL3)).insert(kdb.Box(25000, 500, 75000, 1000))
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    p.box(NORCX, 25000, 500, 75000, 2000)
    return p


def exclusion_substrate_pin_within() -> Pattern:
    """
    A p-tap with the pin VSS of the net of the substrate on it within a marker, and a Metal2 rail to another p-tap
    """
    p = pattern('exclusion_substrate_pin_within')
    tap_m1_m2(p, 0, True, 'VSS')
    tap_m1_m2(p, 30000, True)
    p.box(METAL2, 100, 2400, 30400, 2700)
    p.box(NORCX, -1000, 0, 1000, 5000)
    return p


def exclusion_wires_through_and_beside(name: str, label: str) -> Pattern:
    """
    A Metal3 wire with the pin A through a marker, and a Metal3 wire beside it and the marker with the pin of the label
    """
    p = pattern(name)
    p.box(METAL3, 0, 0, 20000, 1000)
    p.box(METAL3_PIN, 0, 0, 200, 1000)
    p.label(METAL3, 'A', 100, 500)
    p.box(METAL3, 0, 2000, 20000, 3000)
    p.box(METAL3_PIN, 0, 2000, 200, 3000)
    p.label(METAL3, label, 100, 2500)
    p.box(NORCX, 8000, -1000, 12000, 1500)
    return p


def exclusion_overlapping_markers() -> Pattern:
    """
    The wires and the plate of exclusion_plate_between_wires, with a marker of all layers and one of Metal2 and Metal3
    that overlap over the plate
    """
    p = exclusion_plate_between_wires('exclusion_overlapping_markers', None)
    p.box(NORCX, 0, -5000, 12000, 25000)
    p.box(NORCX_M2M3, 8000, -5000, 20000, 25000)
    return p


def exclusion_rail_between_taps() -> Pattern:
    """
    A Metal2 rail of 300 µm x 0.3 µm between two p-taps with the pins A and B (see tap_m1_m2),
    with 20 µm of it within a marker, so that the substrate is what joins its parts but a model
    """
    p = pattern('exclusion_rail_between_taps')
    tap_m1_m2(p, 0, True, 'A')
    tap_m1_m2(p, 300000, True, 'B')
    p.box(METAL2, 100, 2400, 300400, 2700)
    p.box(NORCX, 140000, 0, 160000, 5000)
    return p


def exclusion_ptap_within_marker() -> Pattern:
    """
    The p-taps of r_ptap_pair_m1_m2_pins_A_B, which only the substrate joins, with a marker over the one with the pin B
    """
    p = r_ptap_pair_m1_m2('exclusion_ptap_within_marker', ('A', 'B'))
    p.box(NORCX, 9000, -1000, 11500, 6000)
    return p


PATTERNS: Dict[str, Callable[[], Pattern]] = {
    'cap_cmomf_w10u_l25u_m2_m4_m5_wire': cap_cmomf_w10u_l25u_m2_m4_m5_wire,
    'cap_cmomf_w5u_l5u_m2_m4_plus_from_m1': cap_cmomf_w5u_l5u_m2_m4_plus_from_m1,
    'cap_cmomi_w5u_l5u_m3_m5_same_m1_m2_wire': cap_cmomi_w5u_l5u_m3_m5_same_m1_m2_wire,
    'cap_cmomi_w5u_l5u_m4_m5_none': cap_cmomi_w5u_l5u_m4_m5_none,
    'cap_cmomi_w8u9_l3u36_m1_m5_r90': cap_cmomi_w8u9_l3u36_m1_m5_r90,
    'cap_cmomi_w3u_l2u_m4_m5_orientations': cap_cmomi_w3u_l2u_m4_m5_orientations,
    'cap_cmim_20um_x_20um_over_m4_wire':
        lambda: cap_cmim_over_m4_wire('cap_cmim_20um_x_20um_over_m4_wire'),
    'cap_cmim_20um_x_20um_metal5_routes_in_cells': cap_cmim_20um_x_20um_metal5_routes_in_cells,
    'cap_moscap_n_moscap_p': cap_moscap_n_moscap_p,
    'cap_moscap_n_x2_gatpoly_wire': cap_moscap_n_x2_gatpoly_wire,
    'cap_moscap_p_x2_wells_apart': cap_moscap_p_x2_wells_apart,
    'cap_moscap_n_no_guard_ring': cap_moscap_n_no_guard_ring,
    'cap_svaricap_nwell_guard_ring': cap_svaricap_nwell_guard_ring,
    'cap_svaricap_nwell_guard_ring_digisub': cap_svaricap_nwell_guard_ring_digisub,
    'res_rppd_x2_one_marker': res_rppd_x2_one_marker,
    'inductor2_x2_markers_touching': inductor2_x2_markers_touching,
    'cap_rfcmim_w7u_l7u_over_m4_wire': cap_rfcmim_w7u_l7u_over_m4_wire,
    'cap_rfcmim_w7u_l7u_metal5_routes_in_cells': cap_rfcmim_w7u_l7u_metal5_routes_in_cells,
    'cap_rfcmim_w7u_l7u_two_feeds': cap_rfcmim_w7u_l7u_two_feeds,
    'single_plate_6um_x_8um_m1_over_isolated_pwell': single_plate_6um_x_8um_m1_over_isolated_pwell,
    'wires_no_pin': wires_no_pin,
    'r_wire_over_nbulay_m1': r_wire_over_nbulay_m1,
    'r_ptap_pair_m1_m2': lambda: r_ptap_pair_m1_m2('r_ptap_pair_m1_m2', (None, None)),
    'r_ptap_pair_m1_m2_pins_A_B': lambda: r_ptap_pair_m1_m2('r_ptap_pair_m1_m2_pins_A_B', ('A', 'B')),
    'r_ntap_pair_nwell_m1_m2': r_ntap_pair_nwell_m1_m2,
    'nmos_pair_abutting_ptaps': nmos_pair_abutting_ptaps,
    'bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa': bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa,
    'device_pcells': device_pcells,
    'esd_diodevdd_2kv': lambda: esd_diode('diodevdd_2kv'),
    'esd_diodevss_2kv': lambda: esd_diode('diodevss_2kv'),
    'esd_diodevss_2kv_pair': lambda: esd_diode_pair('diodevss_2kv'),
    'diode_dantenna_dpantenna': diode_dantenna_dpantenna,
    'diode_schottky_nbl1': diode_schottky_nbl1,
    'inductor2_w2u_d15u48_tm2_wires_50u': inductor2_w2u_d15u48_tm2_wires_50u,
    'inductor3_w2u_d25u84_2_turns': inductor3_w2u_d25u84_2_turns,
    'exclusion_wire_through': exclusion_wire_through,
    'exclusion_wire_through_octagon': exclusion_wire_through_octagon,
    'exclusion_wire_middle': exclusion_wire_middle,
    'exclusion_wire_end': lambda: exclusion_wire_end('exclusion_wire_end', 'W'),
    'exclusion_wire_end_no_label': lambda: exclusion_wire_end('exclusion_wire_end_no_label', None),
    'exclusion_plate_neighbor': lambda: exclusion_plate_neighbor('exclusion_plate_neighbor', 'P'),
    'exclusion_floating_plate_neighbor': lambda: exclusion_plate_neighbor('exclusion_floating_plate_neighbor', None),
    'exclusion_plates_2_markers': lambda: exclusion_plates_markers('exclusion_plates_2_markers',
                                                                   [(0, 0, 20000, 20000), (20500, 0, 40500, 20000)]),
    'exclusion_plates_1_marker': lambda: exclusion_plates_markers('exclusion_plates_1_marker',
                                                                  [(0, 0, 40500, 20000)]),
    'exclusion_via_stack': lambda: metal2_wires_metal3_bridge('exclusion_via_stack', marker=True),
    'exclusion_via_stack_no_marker': lambda: metal2_wires_metal3_bridge('exclusion_via_stack_no_marker', marker=False),
    'exclusion_via_stack_pin_on_bridge':
        lambda: metal2_wires_metal3_bridge('exclusion_via_stack_pin_on_bridge', marker=True, bridge_label='P'),
    'exclusion_via_across': exclusion_via_across,
    'exclusion_stubs': exclusion_stubs,
    'exclusion_marker_in_cell': exclusion_marker_in_cell,
    'exclusion_nmos_diode2': exclusion_nmos_diode2,
    'exclusion_nmos_diode2_all': exclusion_nmos_diode2_all,
    'exclusion_hairpin_around_wire': lambda: exclusion_hairpin_around_wire('exclusion_hairpin_around_wire', 0),
    'exclusion_hairpin_around_wire_open': lambda: exclusion_hairpin_around_wire('exclusion_hairpin_around_wire_open',
                                                                                2000),
    'exclusion_same_label_within': exclusion_same_label_within,
    'exclusion_tap_wire_through': exclusion_tap_wire_through,
    'exclusion_wire_over_nwell': exclusion_wire_over_nwell,
    'exclusion_slanted_wire': exclusion_slanted_wire,
    'exclusion_rail_between_taps': exclusion_rail_between_taps,
    'exclusion_ptap_within_marker': exclusion_ptap_within_marker,
    'exclusion_overlapping_markers': exclusion_overlapping_markers,
    'cut_boundary_over_devices': cut_boundary_over_devices,
    'cut_boundary_over_inductor': cut_boundary_over_inductor,
    'cut_cell_of_devices': cut_cell_of_devices,
    'cut_abutting_std_cells': cut_abutting_std_cells,
    'cut_pad_via_on_label': cut_pad_via_on_label,
    'cut_pad_with_same_label_in_top': cut_pad_with_same_label_in_top,
    'cut_rotated_child': cut_rotated_child,
    'cut_bjts_wire_on_collector': cut_bjts_wire_on_collector,
    'cut_strip_along_wire': cut_strip_along_wire,
    'cut_plate_with_fill': cut_plate_with_fill,
    'exclusion_substrate_pin_within': exclusion_substrate_pin_within,
    'exclusion_wire_beside_label_of_other_net':
        lambda: exclusion_wires_through_and_beside('exclusion_wire_beside_label_of_other_net', 'B'),
    'exclusion_wire_beside_label_of_piece':
        lambda: exclusion_wires_through_and_beside('exclusion_wire_beside_label_of_piece', 'A#marker0'),
    'cut_two_strips': cut_two_strips,
    'cut_bend_beside_marker': cut_bend_beside_marker,
    'cut_rotated_cell': cut_rotated_cell,
    'exclusion_coil_guard_ring': exclusion_coil_guard_ring,
    'exclusion_inductor2_wire_under': exclusion_inductor2_wire_under,
    'exclusion_plate_noqrc': lambda: exclusion_plate_between_wires('exclusion_plate_noqrc', METAL3_NOQRC),
    'exclusion_plate_pair_m2m3': lambda: exclusion_plate_between_wires('exclusion_plate_pair_m2m3', NORCX_M2M3),
    'exclusion_plate_pair_m3sub': lambda: exclusion_plate_between_wires('exclusion_plate_pair_m3sub', NORCX_M3SUB),
    'cut_coil': lambda: cut_coil_pattern('cut_coil'),
    'cut_coil_beside_marker': cut_coil_beside_marker,
    'cut_abutting_wires': cut_abutting_wires,
    'cut_coil_model': cut_coil_model,
    'cut_coil_x2': lambda: cut_coil_pattern('cut_coil_x2', instance_count=2),
    'cut_block_with_mos': cut_block_with_mos,
    'cut_block_beside_mos': cut_block_beside_mos,
    'label_in_child_cell': lambda: label_in_child_cell_pattern('label_in_child_cell'),
    'label_in_child_cell_within_marker': label_in_child_cell_within_marker,
    'label_only_in_child_cell': label_only_in_child_cell,
    'labels_in_child_cells': labels_in_child_cells,
    'labels_without_pin_shapes': labels_without_pin_shapes,
    'cut_inductor2_leads_in_top': cut_inductor2_leads_in_top,
    'exclusion_hairpin': lambda: exclusion_hairpin('exclusion_hairpin', 0, METAL3),
    'exclusion_hairpin_open': lambda: exclusion_hairpin('exclusion_hairpin_open', 1000, METAL3),
    'exclusion_hairpin_bridge_m2': lambda: exclusion_hairpin('exclusion_hairpin_bridge_m2', 0, METAL2),
    'exclusion_hairpin_bridge_m2_open': lambda: exclusion_hairpin('exclusion_hairpin_bridge_m2_open', 1000, METAL2),
    'exclusion_stacked_wires': lambda: exclusion_stacked_wires('exclusion_stacked_wires', True),
    'exclusion_stacked_wires_open': lambda: exclusion_stacked_wires('exclusion_stacked_wires_open', False),
}


if __name__ == '__main__':
    sys.exit(main('ihp-sg13g2', PATTERNS))
