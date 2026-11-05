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
Generate sky130A test patterns (testdata/designs/sky130A/test_patterns),
drawn like the hand-drawn ones (e.g. overlap_plates_100um_x_100um_li1_m1_m2_m3):
each net has its label on the label layer and a pin square of 20 µm in a corner.

Usage:
    python3 scripts/gen_test_patterns/sky130A.py [--output-dir DIR] [PATTERN ...]
"""
from __future__ import annotations

import os
import sys
from typing import *

import klayout.db as kdb

from pattern_builder import GDSPair, Pattern, main, pdk_root

DNWELL:   GDSPair = (64, 18)
NWELL:    GDSPair = (64, 20)
DIFF:     GDSPair = (65, 20)
TAP:      GDSPair = (65, 44)
NSDM:     GDSPair = (93, 44)
PSDM:     GDSPair = (94, 20)
POLY:     GDSPair = (66, 20)
POLY_PIN: GDSPair = (66, 16)
NPC:      GDSPair = (95, 20)
LICON:    GDSPair = (66, 44)
LI1:      GDSPair = (67, 20)
LI1_PIN:  GDSPair = (67, 16)
MCON:     GDSPair = (67, 44)
MET1:     GDSPair = (68, 20)
MET1_PIN: GDSPair = (68, 16)
MET1_RES: GDSPair = (68, 13)
VIA1:     GDSPair = (68, 44)
MET2:     GDSPair = (69, 20)
MET2_PIN: GDSPair = (69, 16)
MET3:     GDSPair = (70, 20)
MET3_PIN: GDSPair = (70, 16)
CAPM:     GDSPair = (89, 44)
VIA3:     GDSPair = (70, 44)
MET4:     GDSPair = (71, 20)
MET4_PIN: GDSPair = (71, 16)
MET5:     GDSPair = (72, 20)
MET5_PIN: GDSPair = (72, 16)
INDUCTOR: GDSPair = (82, 24)
VPP:      GDSPair = (82, 64)

LABEL_BY_LAYER: Dict[GDSPair, GDSPair] = {
    NWELL: (64, 5),
    POLY: (66, 5),
    LI1: (67, 5),
    MET1: (68, 5),
    MET2: (69, 5),
    MET3: (70, 5),
    MET4: (71, 5),
    MET5: (72, 5),
}


def pattern(name: str) -> Pattern:
    return Pattern(name, label_layer_by_layer=LABEL_BY_LAYER)


def pdk_library() -> kdb.Layout:
    """
    The cells of the PDK's primitives, needs the sky130A PDK (e.g. IIC-OSIC-TOOLS, with $PDK_ROOT/sky130A)
    """
    library = kdb.Layout()
    library.read(os.path.join(pdk_root(), 'sky130A', 'libs.ref', 'sky130_fd_pr', 'gds', 'sky130_fd_pr.gds'))
    return library


def place_pdk_cell(p: Pattern, library: kdb.Layout, name: str, x: int) -> Tuple[kdb.Cell, kdb.Trans]:
    """
    An instance of a cell of the PDK in the top cell, with the left of its bounding box at x

    :return: the cell, and the transformation of its instance
    """
    cell = p.layout.create_cell(name)
    cell.copy_tree(library.cell(name))
    trans = kdb.Trans(x - cell.bbox().left, 0)
    p.top.insert(kdb.CellInstArray(cell.cell_index(), trans))
    return cell, trans


#
# Capacitance patterns
#

def overlap_shield_same_net(name: str, met1_width: int) -> Pattern:
    """
    Plates of 100 µm x 100 µm: li1 and met1 of net A, joined by an mcon in a corner, under met2 of net B,
    met1 covering li1 over its width from the left, so that it shields li1 from met2 there
    """
    p = pattern(name)
    p.box(LI1, 0, 0, 100000, 100000)
    p.box(LI1_PIN, 0, 0, 20000, 20000)
    p.label(LI1, 'A', 200, 200)
    p.box(MCON, 1000, 1000, 1170, 1170)
    p.box(MET1, 0, 0, met1_width, 100000)
    p.box(MET2, 0, 0, 100000, 100000)
    p.box(MET2_PIN, 80000, 80000, 100000, 100000)
    p.label(MET2, 'B', 80200, 80200)
    return p


def plate_li1_over_tap(name: str, ntap: bool) -> Pattern:
    """
    A li1 plate of 20 µm x 20 µm of net A over the middle of a tap of 40 µm x 40 µm,
    an n-tap in an nwell W, or a p-tap tied to VSS by a licon under a li1 pad in its corner
    (like in the standard cells, as only the licon joins a p-tap to a net)
    """
    p = pattern(name)
    if ntap:
        p.box(NWELL, -2000, -2000, 42000, 42000)
        p.label(NWELL, 'W', -1800, -1800)
    else:
        p.box(LICON, 1000, 1000, 1170, 1170)
        p.box(LI1, 500, 500, 2500, 2500)
        p.box(LI1_PIN, 500, 500, 2500, 2500)
        p.label(LI1, 'VSS', 700, 700)
    p.box(TAP, 0, 0, 40000, 40000)
    p.box(NSDM if ntap else PSDM, -200, -200, 40200, 40200)
    p.box(LI1, 10000, 10000, 30000, 30000)
    p.box(LI1_PIN, 10000, 10000, 15000, 15000)
    p.label(LI1, 'A', 10200, 10200)
    return p


def cap_mim_m3_over_m2_wire(name: str) -> Pattern:
    """
    A MIM cap of 20 µm x 20 µm: the capm top plate on a met3 bottom plate of net A, which encloses it by 2 µm,
    joined by a via3 in its middle to the met4 of net B over it,
    over a met2 wire D of 2 µm width across it, which the bottom plate shields from the top plate
    """
    p = pattern(name)
    p.box(MET3, 0, 0, 24000, 24000)
    p.box(MET3_PIN, 0, 0, 2000, 2000)
    p.label(MET3, 'A', 200, 200)
    p.box(CAPM, 2000, 2000, 22000, 22000)
    p.box(VIA3, 11900, 11900, 12100, 12100)
    p.box(MET4, 2000, 2000, 22000, 22000)
    p.box(MET4_PIN, 20000, 20000, 22000, 22000)
    p.label(MET4, 'B', 20200, 20200)
    p.box(MET2, -10000, 11000, 34000, 13000)
    p.box(MET2_PIN, -10000, 11000, -8000, 13000)
    p.label(MET2, 'D', -9800, 11200)
    return p


def cap_vpp_04p4x04p6_l1m1m2_noshield_m2_wire() -> Pattern:
    """
    The VPP cap of the test data (cap_vpp_04p4x04p6_l1m1m2_noshield, fingers on li1, met1 and met2,
    its terminals C0 and C1), with a met2 wire X of 1 µm width beside it, 0.3 µm away
    """
    p = pattern('cap_vpp_04p4x04p6_l1m1m2_noshield_m2_wire')
    p.copy_design('sky130A', 'cap_vpp_04p4x04p6_l1m1m2_noshield', 'cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz')

    p.box(MET2, 4680, -615, 5680, 4590)
    p.box(MET2_PIN, 4680, -615, 5680, 385)
    p.label(MET2, 'X', 4880, -415)
    return p


def cap_vpp_routing_across() -> Pattern:
    """
    VPP caps, 15 µm apart, with metal across their markers that is no part of them, each wire and lead
    with a label and a pin outside the marker: X1, …

    Instances of the PDK's cells:
    - cap_vpp_04p4x04p6_l1m1m2_noshield, fingers on li1, met1 and met2:
      a straight met3 wire, an L of met4, and a straight met5 wire
    - cap_vpp_06p8x06p1_m1m2m3_shieldl1m4, with plates on li1 and met4: a met5 wire
    - cap_vpp_04p4x04p6_m1m2_noshield twice, with fingers on met1 and met2: a li1 wire, and a poly wire

    Drawn flat, with only what the LVS deck looks at, as the cells of this size take minutes to extract,
    their terminals met2 leads, also X…:
    - cap_vpp_11p5x11p7_m1m2m3m4_shieldm5, with holes in its met5 plate
    - cap_vpp_11p5x11p7_l1m1m2m3m4_shieldpom5_x, its met5 plate within the marker, with a met5 lead
    """
    p = pattern('cap_vpp_routing_across')
    library = pdk_library()
    wires = 0

    def wire(layer: GDSPair, pin_layer: GDSPair, points: List[Tuple[int, int]], width: int):
        nonlocal wires
        wires += 1
        p.path(layer, points, width)
        x, y = points[0]
        for pin_or_wire in (layer, pin_layer):
            p.box(pin_or_wire, x - width // 2, y - width // 2, x + width // 2, y + width // 2)
        p.label(layer, f"X{wires}", x, y)

    def place_cap(name: str, x: int) -> kdb.Box:
        cell, trans = place_pdk_cell(p, library, f"sky130_fd_pr__cap_vpp_{name}", x)
        return kdb.Region(cell.begin_shapes_rec(p.layout.layer(*VPP))).merged().bbox().transformed(trans)

    def across(marker: kdb.Box, x: int) -> List[Tuple[int, int]]:
        return [(marker.left + x, marker.bottom - 2000), (marker.left + x, marker.top + 2000)]

    marker = place_cap('04p4x04p6_l1m1m2_noshield', 0)
    wire(MET3, MET3_PIN, across(marker, 1000), 400)
    wire(MET4, MET4_PIN, [(marker.left + 3000, marker.bottom - 2000),
                          (marker.left + 3000, marker.center().y),
                          (marker.right + 2000, marker.center().y)], 400)
    wire(MET5, MET5_PIN, across(marker, 2000), 1600)

    marker = place_cap('06p8x06p1_m1m2m3_shieldl1m4', marker.right + 15000)
    wire(MET5, MET5_PIN, across(marker, 2000), 1600)

    def draw_cap_11p5x11p7(x: int, *inner_layers: GDSPair) -> kdb.Box:
        marker = kdb.Box(x, 0, x + 11070, 11350)
        p.box(VPP, marker.left, marker.bottom, marker.right, marker.top)
        for layer in inner_layers:
            p.box(layer, x + 4000, 4000, x + 7000, 7000)
        wire(MET2, MET2_PIN, [(x - 2000, 1500), (x + 1000, 1500)], 1000)
        wire(MET2, MET2_PIN, [(x + 13070, 1500), (x + 10070, 1500)], 1000)
        return marker

    marker = draw_cap_11p5x11p7(marker.right + 15000, MET3, MET4)
    plate = kdb.Region(marker.enlarged(170))
    for hole_x, hole_y in ((1935, 2075), (6835, 2075), (1935, 6975), (6835, 6975)):
        plate -= kdb.Region(kdb.Box(0, 0, 2300, 2300).moved(marker.left + hole_x, marker.bottom + hole_y))
    p.top.shapes(p.layout.layer(*MET5)).insert(plate)

    marker = draw_cap_11p5x11p7(marker.right + 15000, LI1, MET3, MET4)
    p.box(POLY, marker.left, marker.bottom, marker.right, marker.top)
    p.top.shapes(p.layout.layer(*MET5)).insert(marker.enlarged(-230))
    wire(MET5, MET5_PIN, [(marker.center().x, marker.bottom - 2000), (marker.center().x, marker.bottom + 1000)], 1600)

    for layer, pin_layer in ((LI1, LI1_PIN), (POLY, POLY_PIN)):
        marker = place_cap('04p4x04p6_m1m2_noshield', marker.right + 15000)
        wire(layer, pin_layer, across(marker, 2000), 400)
    return p


def cap_vpp_licon_within_marker() -> Pattern:
    """
    A licon all within the marker of a VPP cap, like those of the nhv cells of the PDK, between poly P going
    out to the left and li1 L going out to the right
    """
    p = pattern('cap_vpp_licon_within_marker')
    p.box(VPP, 0, 0, 2000, 2000)
    p.box(POLY, -2000, 800, 1270, 1200)
    p.box(POLY_PIN, -2000, 800, -1800, 1200)
    p.label(POLY, 'P', -1900, 1000)
    p.box(LICON, 1000, 915, 1170, 1085)
    p.box(LI1, 900, 800, 4000, 1200)
    p.box(LI1_PIN, 3800, 800, 4000, 1200)
    p.label(LI1, 'L', 3900, 1000)
    return p


def cap_vpp_of_pdk(name: str) -> Pattern:
    """
    The cell of a VPP cap of the PDK, e.g. the smallest ones with licon within their markers:
    - cap_vpp_04p4x04p6_l1m1m2_shieldpo_floatm3: 44 licons between its li1 fingers and its poly shield
    - cap_vpp_02p7x06p1_m1m2m3m4_shieldl1_fingercap: 28 licons between its li1 shields and the taps below,
      no poly
    """
    p = pattern(name)
    place_pdk_cell(p, pdk_library(), f"sky130_fd_pr__{name}", 0)
    p.top.flatten(-1, True)
    return p


#
# Resistance patterns
#

def tap_li1_m1(p: Pattern, x: int, ptap: bool, y: int = 0):
    """
    A tap of 0.5 µm x 5 µm at (x, y), under li1 and met1 wires of 0.34 µm width, joined by 5 licons and 5 mcons

    :param ptap: a p-tap, otherwise an n-tap (for an nwell around it)
    """
    p.box(PSDM if ptap else NSDM, x - 130, y - 130, x + 630, y + 5130)
    p.box(TAP, x, y, x + 500, y + 5000)
    for contact_y in range(y + 500, y + 5000, 1000):
        p.box(LICON, x + 165, contact_y - 85, x + 335, contact_y + 85)
        p.box(MCON, x + 165, contact_y - 85, x + 335, contact_y + 85)
    p.box(LI1, x + 80, y, x + 420, y + 5000)
    p.box(MET1, x + 80, y, x + 420, y + 5000)


def r_ptap_pair_li1_m1() -> Pattern:
    """
    Two p-taps 10 µm apart, with li1 and met1 wires over them, which are nets of their own,
    as the deck has no substrate around the p-taps that would join them
    """
    p = pattern('r_ptap_pair_li1_m1')
    tap_li1_m1(p, 0, ptap=True)
    tap_li1_m1(p, 10000, ptap=True)
    return p


def r_ptap_li1_m1_two_wires() -> Pattern:
    """
    A p-tap of 0.5 µm x 12 µm with two li1 and met1 wires over it, 2 µm apart, which only the tap joins
    """
    p = pattern('r_ptap_li1_m1_two_wires')
    tap_li1_m1(p, 0, ptap=True)
    tap_li1_m1(p, 0, ptap=True, y=7000)
    p.box(TAP, 0, 5000, 500, 7000)
    p.box(PSDM, -130, 5000, 630, 7000)
    return p


def r_ntap_pair_nwell_li1_m1() -> Pattern:
    """
    Two n-taps 10 µm apart in one nwell, with li1 and met1 wires over them, which the nwell joins,
    a conductor of the resistance network
    """
    p = pattern('r_ntap_pair_nwell_li1_m1')
    p.box(NWELL, -1000, -1000, 11500, 6000)
    tap_li1_m1(p, 0, ptap=False)
    tap_li1_m1(p, 10000, ptap=False)
    return p


def r_ntap_pair_two_nwells_over_dnwell_li1_m1() -> Pattern:
    """
    Two n-taps 10 µm apart, each in an nwell of its own, with li1 and met1 wires over them,
    which only the deep nwell below both nwells joins, no conductor of the resistance network
    """
    p = pattern('r_ntap_pair_two_nwells_over_dnwell_li1_m1')
    p.box(DNWELL, -3000, -3000, 13500, 8000)
    p.box(NWELL, -1000, -1000, 1500, 6000)
    p.box(NWELL, 9000, -1000, 11500, 6000)
    tap_li1_m1(p, 0, ptap=False)
    tap_li1_m1(p, 10000, ptap=False)
    return p


def r_ptap_li1_m1_and_floating_m1_m2() -> Pattern:
    """
    Wires of the net A that the resistance network can't join: li1 and met1 wires over a p-tap, and, 10 µm apart
    and on no tap, met1 and met2 wires joined by a via, which only the labels A (without pins) join in the deck
    """
    p = pattern('r_ptap_li1_m1_and_floating_m1_m2')
    tap_li1_m1(p, 10000, ptap=True)
    p.label(LI1, 'A', 10250, 2500)
    p.box(MET1, 0, 0, 340, 5000)
    p.box(VIA1, 90, 2420, 250, 2580)
    p.box(MET2, 0, 0, 340, 5000)
    p.label(MET2, 'A', 170, 2500)
    return p


#
# Net name patterns
#

def net_names_A_and_a_m2() -> Pattern:
    """
    Two met2 wires of 20 µm x 0.5 µm, 1 µm apart, the nets A and a with a pin each,
    which SPICE reads as one, as it reads names case-insensitively
    """
    p = pattern('net_names_A_and_a_m2')
    p.box(MET2, 0, 0, 20000, 500)
    p.box(MET2_PIN, 0, 0, 500, 500)
    p.label(MET2, 'A', 100, 100)
    p.box(MET2, 0, 1500, 20000, 2000)
    p.box(MET2_PIN, 0, 1500, 500, 2000)
    p.label(MET2, 'a', 100, 1600)
    return p


#
# Hierarchy patterns
#

def nfet_li1_in_subcell() -> Pattern:
    """
    The nfet of the test pattern nfet_li1 (its nets labelled D, G and S on li1) in a subcell SUBNFET,
    which the schematic nfet_li1_in_subcell.spice has as a subcircuit too
    """
    p = pattern('nfet_li1_in_subcell')
    p.copy_design('sky130A', 'test_patterns', 'nfet_li1.gds.gz', subcell_name='SUBNFET')
    return p


#
# Device patterns
#

def rf_inductors_03_90_05_125_05_220() -> Pattern:
    """
    The RF inductors of the PDK (its cells sky130_fd_pr__rf_test_coil1, 2 and 3, of the models
    sky130_fd_pr__ind_03_90, _05_125 and _05_220) side by side, 10 µm apart, the leads of each coil
    outside its marker as pins: its ends (met3) A1, B1, A2, …, from the bottom, and its center tap (met2) CT1, …
    """
    library = pdk_library()
    p = pattern('rf_inductors_03_90_05_125_05_220')
    x = 0
    for i in (1, 2, 3):
        cell, trans = place_pdk_cell(p, library, f"sky130_fd_pr__rf_test_coil{i}", x)
        x += cell.bbox().width() + 10000

        def leads(layer: GDSPair) -> List[kdb.Box]:
            def region(gds_pair: GDSPair) -> kdb.Region:
                return kdb.Region(cell.begin_shapes_rec(p.layout.layer(*gds_pair))).transformed(trans)
            return sorted((polygon.bbox() for polygon in (region(layer) - region(INDUCTOR)).merged().each()),
                          key=lambda box: box.bottom)

        for (layer, pin_layer), names in (((MET3, MET3_PIN), (f"A{i}", f"B{i}")), ((MET2, MET2_PIN), (f"CT{i}",))):
            for box, name in zip(leads(layer), names, strict=True):
                p.box(pin_layer, box.left, box.bottom, box.right, box.top)
                p.label(layer, name, box.center().x, box.center().y)
    p.top.flatten(-1, True)
    return p


def exclusion_user_marker_wire() -> Pattern:
    """
    A met2 wire of 60 µm x 2 µm from A to B, with its middle third within a layer no PDK layer is on,
    for a marker given by the user, as the PDK has none
    """
    p = pattern('exclusion_user_marker_wire')
    p.box(MET2, -20000, 0, 40000, 2000)
    p.box(MET2_PIN, -20000, 0, -19000, 2000)
    p.label(MET2, 'A', -19500, 1000)
    p.box(MET2_PIN, 39000, 0, 40000, 2000)
    p.label(MET2, 'B', 39500, 1000)
    p.box((200, 0), 0, -5000, 20000, 7000)
    return p


def exclusion_nwell_between_pfet_and_tap(name: str = 'exclusion_nwell_between_pfet_and_tap') -> Pattern:
    """
    The pfet and the n-tap of r_nwell_pfet_ntap_li1, in one nwell, with the middle of the nwell within a layer
    no PDK layer is on, for a marker given by the user, so that nothing but a model joins the part with the pfet
    """
    p = pattern(name)
    p.copy_design('sky130A', 'test_patterns', 'r_nwell_pfet_ntap_li1.gds.gz')
    p.box((200, 0), 5000, -1000, 7000, 4000)
    return p


def exclusion_wire_beside_marker_over_nwell() -> Pattern:
    """
    exclusion_nwell_between_pfet_and_tap with a met1 wire N over the nwell beside the marker, on the side of the n-tap
    """
    p = exclusion_nwell_between_pfet_and_tap('exclusion_wire_beside_marker_over_nwell')
    p.box(MET1, 7200, 500, 9000, 2500)
    p.box(MET1_PIN, 7200, 500, 7400, 700)
    p.label(MET1, 'N', 7300, 600)
    return p


def exclusion_pfet_between_taps() -> Pattern:
    """
    The pfet and the n-tap of r_nwell_pfet_ntap_li1, with another n-tap on the other side of the pfet, labelled A,
    all in one nwell, with the pfet within a layer no PDK layer is on, for a marker given by the user,
    so that only a model joins the taps and the bulk of the pfet
    """
    p = pattern('exclusion_pfet_between_taps')
    p.copy_design('sky130A', 'test_patterns', 'r_nwell_pfet_ntap_li1.gds.gz')
    p.box(NWELL, -6000, 0, 0, 3000)
    p.box(TAP, -4500, 1000, -3500, 2000)
    p.box(NSDM, -4625, 875, -3375, 2125)
    p.box(LICON, -4085, 1415, -3915, 1585)
    p.box(LI1, -4165, 1335, -3835, 1665)
    p.box(LI1_PIN, -4165, 1335, -3835, 1665)
    p.label(LI1, 'A', -4000, 1500)
    p.box((200, 0), 500, -1000, 3000, 4000)
    return p


def cut_ntaps_in_one_nwell() -> Pattern:
    """
    The n-taps of r_ntap_pair_nwell_li1_m1 with their nwell in a child cell, with the pins VL and VR in the top cell,
    like a guard ring within a cell
    """
    p = pattern('cut_ntaps_in_one_nwell')
    block = p.layout.create_cell('block')
    source = r_ntap_pair_nwell_li1_m1()
    block.copy_tree(source.top)
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    for x, text in ((0, 'VL'), (10000, 'VR')):
        p.box(MET1_PIN, x + 100, 2350, x + 400, 2650)
        p.label(MET1, text, x + 250, 2500)
    return p


def exclusion_rail_between_taps() -> Pattern:
    """
    A met1 rail of 300 µm x 0.4 µm between two n-taps, in a nwell each, with the pins A and B on them,
    with 20 µm of it within a layer no PDK layer is on, for a marker given by the user
    """
    p = pattern('exclusion_rail_between_taps')
    for x, text in ((0, 'A'), (300000, 'B')):
        p.box(NWELL, x - 1000, -1000, x + 1500, 6000)
        tap_li1_m1(p, x, ptap=False)
        p.box(MET1_PIN, x + 100, 2350, x + 400, 2650)
        p.label(MET1, text, x + 250, 2500)
    p.box(MET1, 80, 2300, 300420, 2700)
    p.box((200, 0), 140000, 0, 160000, 5000)
    return p


def pfet_in_child_cell(p: Pattern, x_end: int):
    """
    A child cell of a pfet in an nwell, with its source on li1 and its gate on poly, labelled S and G,
    and its diffusion and nwell up to x_end. In the top cell, the source goes on as the pin ST, on li1
    """
    block = p.layout.create_cell('block')

    def draw(layer: GDSPair, x1: int, y1: int, x2: int, y2: int):
        block.shapes(p.layout.layer(*layer)).insert(kdb.Box(x1, y1, x2, y2))

    draw(NWELL, 0, 0, x_end, 3000)
    draw(DIFF, 1000, 500, x_end, 2500)
    draw(PSDM, 875, 375, x_end, 2625)
    draw(POLY, 1675, 370, 1825, 2630)
    draw(POLY, 1500, 2630, 1900, 2900)
    draw(POLY_PIN, 1500, 2630, 1900, 2900)
    block.shapes(p.layout.layer(*LABEL_BY_LAYER[POLY])).insert(kdb.Text('G', kdb.Trans(1750, 2750)))
    draw(LICON, 1200, 1415, 1370, 1585)
    draw(LI1, 1120, 1335, 1450, 1665)
    draw(LI1_PIN, 1120, 1335, 1450, 1665)
    block.shapes(p.layout.layer(*LABEL_BY_LAYER[LI1])).insert(kdb.Text('S', kdb.Trans(1285, 1500)))
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    p.box(LI1, 1120, 1665, 1450, 3500)
    p.box(LI1_PIN, 1120, 3300, 1450, 3500)
    p.label(LI1, 'ST', 1285, 3400)


def ntap_with_pin_vpwr(p: Pattern, x: int):
    """
    An n-tap with a contact and the pin VPWR on li1, for an nwell around it
    """
    p.box(TAP, x, 1000, x + 1000, 2000)
    p.box(NSDM, x - 125, 875, x + 1125, 2125)
    p.box(LICON, x + 415, 1415, x + 585, 1585)
    p.box(LI1, x + 335, 1335, x + 665, 1665)
    p.box(LI1_PIN, x + 335, 1335, x + 665, 1665)
    p.label(LI1, 'VPWR', x + 500, 1500)


def cut_pfets_sharing_diffusion() -> Pattern:
    """
    Two pfets on one diffusion: the left one in a child cell, which ends on the diffusion that they share,
    the rest of it, its contact with the pin D, and the right pfet in the top cell
    """
    p = pattern('cut_pfets_sharing_diffusion')
    pfet_in_child_cell(p, x_end=1900)
    p.box(NWELL, 1900, 0, 12000, 3000)
    p.box(DIFF, 1900, 500, 4000, 2500)
    p.box(PSDM, 1900, 375, 4125, 2625)
    p.box(POLY, 2675, 370, 2825, 2630)
    p.box(POLY, 2500, 2630, 3000, 2900)
    p.box(POLY_PIN, 2500, 2630, 3000, 2900)
    p.label(POLY, 'G2', 2750, 2750)
    p.box(LICON, 2130, 1415, 2300, 1585)
    p.box(LI1, 2050, 1335, 2380, 3500)
    p.box(LI1_PIN, 2050, 3300, 2380, 3500)
    p.label(LI1, 'D', 2215, 3400)
    p.box(LICON, 3200, 1415, 3370, 1585)
    p.box(LI1, 3120, 1335, 3450, 1665)
    p.box(LI1_PIN, 3120, 1335, 3450, 1665)
    p.label(LI1, 'S2', 3285, 1500)
    ntap_with_pin_vpwr(p, 10500)
    return p


def cut_pfet_drain_with_contacts_in_top() -> Pattern:
    """
    A pfet in a child cell, whose drain goes on in the top cell, beyond the box of the cell, to the pin D,
    with a contact beside the cell, and a contact there
    """
    p = pattern('cut_pfet_drain_with_contacts_in_top')
    pfet_in_child_cell(p, x_end=2300)
    p.box(NWELL, 2300, 0, 12000, 3000)
    p.box(DIFF, 2300, 500, 6000, 2500)
    p.box(PSDM, 2300, 375, 6125, 2625)
    for x in (2500, 5500):
        p.box(LICON, x, 1415, x + 170, 1585)
    p.box(LI1, 2420, 1335, 5750, 1665)
    p.box(LI1_PIN, 5420, 1335, 5750, 1665)
    p.label(LI1, 'D', 5585, 1500)
    ntap_with_pin_vpwr(p, 10500)
    return p


def cut_well_under_wire() -> Pattern:
    """
    An n-tap with its nwell in a child cell, with no node on the nwell, as the net VDD enters the cell on met1,
    and a met3 wire W over the nwell, in the top cell
    """
    p = pattern('cut_well_under_wire')
    source = pattern('nwell_and_tap')
    source.box(NWELL, -1000, -1000, 1500, 6000)
    tap_li1_m1(source, 0, ptap=False)
    block = p.layout.create_cell('block')
    block.copy_tree(source.top)
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    p.box(MET1, 80, 5000, 420, 12000)
    p.box(MET1_PIN, 100, 11000, 400, 11900)
    p.label(MET1, 'VDD', 250, 11500)
    p.box(MET3, -5000, 2000, 5000, 3000)
    p.box(MET3_PIN, -5000, 2000, -4000, 3000)
    p.label(MET3, 'W', -4500, 2500)
    return p


def cut_nfets_wired_in_top() -> Pattern:
    """
    Two nfets 60 µm apart in a child cell, whose contacts and wiring are all in the top cell:
    the sources on one long li1 wire with the pin VSS, near the left one, the drains and gates on pins of their own
    """
    p = pattern('cut_nfets_wired_in_top')
    block = p.layout.create_cell('block')

    def draw(layer: GDSPair, x1: int, y1: int, x2: int, y2: int):
        block.shapes(p.layout.layer(*layer)).insert(kdb.Box(x1, y1, x2, y2))

    for x, drain, gate in ((0, 'D1', 'G1'), (60000, 'D2', 'G2')):
        draw(DIFF, x, 0, x + 1500, 2000)
        draw(NSDM, x - 125, -125, x + 1625, 2125)
        draw(POLY, x + 675, -130, x + 825, 2130)
        draw(POLY, x + 500, 2130, x + 1000, 2400)
        p.box(LICON, x + 200, 915, x + 370, 1085)
        p.box(LI1, x + 120, 835, x + 450, 1165)
        p.box(LICON, x + 1130, 915, x + 1300, 1085)
        p.box(LI1, x + 1050, 835, x + 1380, 1165)
        p.box(LI1_PIN, x + 1050, 835, x + 1380, 1165)
        p.label(LI1, drain, x + 1215, 1000)
        p.box(POLY_PIN, x + 500, 2130, x + 1000, 2400)
        p.label(POLY, gate, x + 750, 2250)
        p.box(LI1, x + 120, -500, x + 450, 835)
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    p.box(LI1, 120, -800, 60450, -500)
    p.box(LI1, 120, -3000, 450, -800)
    p.box(LI1_PIN, 120, -3000, 450, -2800)
    p.label(LI1, 'VSS', 285, -2900)
    return p


def cut_resistors_in_series() -> Pattern:
    """
    Three met1 resistors in series between the pins A and B: the first and the last one in a child cell,
    the middle one and the wires between them in the top cell
    """
    p = pattern('cut_resistors_in_series')
    block = p.layout.create_cell('block')
    for x in (2000, 12000):
        block.shapes(p.layout.layer(*MET1)).insert(kdb.Box(x, 0, x + 2000, 500))
        block.shapes(p.layout.layer(*MET1_RES)).insert(kdb.Box(x, 0, x + 2000, 500))
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    p.box(MET1_RES, 7000, 0, 9000, 500)
    p.box(MET1, 0, 0, 2000, 500)
    p.box(MET1, 4000, 0, 12000, 500)
    p.box(MET1, 14000, 0, 16000, 500)
    for x, text in ((0, 'A'), (15800, 'B')):
        p.box(MET1_PIN, x, 0, x + 200, 500)
        p.label(MET1, text, x + 100, 250)
    return p


def cut_nfet_fingers(name: str, in_sibling: bool) -> Pattern:
    """
    Two nfet fingers on one diffusion, sharing the pin S, and one gate pin G: each is a polygon of poly with its half
    of the strap over them, as tools write merged polygons, one in a child cell, the other in the top cell or a sibling
    """
    p = pattern(name)
    block = p.layout.create_cell('block')
    other = p.layout.create_cell('sibling') if in_sibling else p.top

    def finger(cell: kdb.Cell, x: int):
        cell.shapes(p.layout.layer(*DIFF)).insert(kdb.Box(x, 0, x + 1000, 800))
        cell.shapes(p.layout.layer(*NSDM)).insert(kdb.Box(x, -200, x + 1000, 1000))
        cell.shapes(p.layout.layer(*POLY)).insert(kdb.Polygon([
            kdb.Point(x + px, py) for px, py in ((350, -300), (350, 1100), (0, 1100), (0, 1400), (1000, 1400),
                                                 (1000, 1100), (650, 1100), (650, -300))]))

    finger(block, 0)
    finger(other, 1000)
    for cell in {block.cell_index(), other.cell_index()} - {p.top.cell_index()}:
        p.top.insert(kdb.CellInstArray(cell, kdb.Trans()))
    for x, y, text in ((150, 400, 'D1'), (1000, 400, 'S'), (1850, 400, 'D2'), (1000, 1250, 'G')):
        p.box(LICON, x - 85, y - 85, x + 85, y + 85)
        p.box(LI1, x - 150, y - 150, x + 150, y + 150)
        p.box(LI1_PIN, x - 150, y - 150, x + 150, y + 150)
        p.label(LI1, text, x, y)
    p.box(NPC, 900, 1100, 1100, 1400)
    return p


def cut_instances_sharing_diffusion_in_top() -> Pattern:
    """
    Three instances of a child cell of an nfet, with the diffusion between them and the contacts in the top cell,
    with the pins L, M0, M1 and R
    """
    p = pattern('cut_instances_sharing_diffusion_in_top')
    unit = p.layout.create_cell('unit')

    def draw(cell: kdb.Cell, layer: GDSPair, x1: int, y1: int, x2: int, y2: int):
        cell.shapes(p.layout.layer(*layer)).insert(kdb.Box(x1, y1, x2, y2))

    def pin(x: int, text: str):
        p.box(LICON, x - 85, 315, x + 85, 485)
        p.box(LI1, x - 150, 250, x + 150, 550)
        p.box(LI1_PIN, x - 50, 350, x + 50, 450)
        p.label(LI1, text, x, 400)

    draw(unit, DIFF, 0, 0, 1000, 800)
    draw(unit, NSDM, 0, -200, 1000, 1000)
    draw(unit, POLY, 350, -300, 650, 1100)
    for index in range(3):
        p.top.insert(kdb.CellInstArray(unit.cell_index(), kdb.Trans(index * 2000, 0)))
    for index in range(2):
        x = 1000 + 2000 * index
        draw(p.top, DIFF, x, 0, x + 1000, 800)
        draw(p.top, NSDM, x, -200, x + 1000, 1000)
        pin(x + 500, f"M{index}")
    pin(150, 'L')
    pin(4850, 'R')
    return p


def cut_wires_with_label_like_numbered_port() -> Pattern:
    """
    Two met1 wires of a child cell, one with the label VDD_0, the other without a label, which the top cell joins
    to the pin VDD
    """
    p = pattern('cut_wires_with_label_like_numbered_port')
    block = p.layout.create_cell('block')
    for y in (0, 2000):
        block.shapes(p.layout.layer(*MET1)).insert(kdb.Box(0, y, 3000, y + 500))
        p.box(MET1, 3000, y, 5000, y + 500)
    block.shapes(p.layout.layer(*MET1_PIN)).insert(kdb.Box(500, 100, 700, 300))
    block.shapes(p.layout.layer(*LABEL_BY_LAYER[MET1])).insert(kdb.Text('VDD_0', kdb.Trans(600, 200)))
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    p.box(MET1, 5000, 0, 5500, 2500)
    p.box(MET1_PIN, 5100, 1000, 5400, 1200)
    p.label(MET1, 'VDD', 5250, 1100)
    return p


def cut_wire_with_label_without_pin() -> Pattern:
    """
    A met1 wire with its start in a child cell and the label A in the top cell, without a pin shape,
    and an nfet of the top cell on it
    """
    p = pattern('cut_wire_with_label_without_pin')
    block = p.layout.create_cell('block')
    block.shapes(p.layout.layer(*MET1)).insert(kdb.Box(0, 0, 3000, 1000))
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    p.box(MET1, 3000, 0, 10000, 1000)
    p.label(MET1, 'A', 9500, 500)
    p.box(DIFF, 12000, 0, 13500, 800)
    p.box(NSDM, 11800, -200, 13700, 1000)
    p.box(POLY, 12600, -300, 12900, 1100)
    for x in (12150, 13350):
        p.box(LICON, x - 85, 315, x + 85, 485)
        p.box(LI1, x - 150, 250, x + 150, 550)
    p.box(MCON, 12065, 315, 12235, 485)
    p.box(MET1, 10000, 200, 12300, 600)
    return p


def cut_half_of_gate() -> Pattern:
    """
    An nfet of the top cell, whose gate is half of a child cell, with the pin G on the poly of the top cell
    """
    p = pattern('cut_half_of_gate')
    block = p.layout.create_cell('block')
    block.shapes(p.layout.layer(*POLY)).insert(kdb.Box(675, -130, 825, 400))
    p.top.insert(kdb.CellInstArray(block.cell_index(), kdb.Trans()))
    p.box(DIFF, 0, 0, 1500, 800)
    p.box(NSDM, -125, -125, 1625, 925)
    p.box(POLY, 675, 400, 825, 3000)
    p.box(POLY, 500, 3000, 1000, 3400)
    p.box(POLY_PIN, 500, 3000, 1000, 3400)
    p.label(POLY, 'G', 750, 3200)
    return p


PATTERNS: Dict[str, Callable[[], Pattern]] = {
    'cut_half_of_gate': cut_half_of_gate,
    'cut_nfet_finger_beside_top': lambda: cut_nfet_fingers('cut_nfet_finger_beside_top', in_sibling=False),
    'cut_nfet_finger_beside_sibling': lambda: cut_nfet_fingers('cut_nfet_finger_beside_sibling', in_sibling=True),
    'cut_instances_sharing_diffusion_in_top': cut_instances_sharing_diffusion_in_top,
    'cut_wires_with_label_like_numbered_port': cut_wires_with_label_like_numbered_port,
    'cut_wire_with_label_without_pin': cut_wire_with_label_without_pin,
    'cut_resistors_in_series': cut_resistors_in_series,
    'cut_pfets_sharing_diffusion': cut_pfets_sharing_diffusion,
    'cut_pfet_drain_with_contacts_in_top': cut_pfet_drain_with_contacts_in_top,
    'cut_well_under_wire': cut_well_under_wire,
    'cut_nfets_wired_in_top': cut_nfets_wired_in_top,
    'cut_ntaps_in_one_nwell': cut_ntaps_in_one_nwell,
    'exclusion_nwell_between_pfet_and_tap': exclusion_nwell_between_pfet_and_tap,
    'exclusion_pfet_between_taps': exclusion_pfet_between_taps,
    'exclusion_wire_beside_marker_over_nwell': exclusion_wire_beside_marker_over_nwell,
    'exclusion_rail_between_taps': exclusion_rail_between_taps,
    'exclusion_user_marker_wire': exclusion_user_marker_wire,
    'overlap_shield_same_net_100um_x_100um_li1_m1_m2':
        lambda: overlap_shield_same_net('overlap_shield_same_net_100um_x_100um_li1_m1_m2', 100000),
    'overlap_shield_same_net_half_100um_x_100um_li1_m1_m2':
        lambda: overlap_shield_same_net('overlap_shield_same_net_half_100um_x_100um_li1_m1_m2', 50000),
    'plate_20um_x_20um_li1_over_ptap':
        lambda: plate_li1_over_tap('plate_20um_x_20um_li1_over_ptap', ntap=False),
    'plate_20um_x_20um_li1_over_ntap':
        lambda: plate_li1_over_tap('plate_20um_x_20um_li1_over_ntap', ntap=True),
    'cap_mim_m3_20um_x_20um_over_m2_wire':
        lambda: cap_mim_m3_over_m2_wire('cap_mim_m3_20um_x_20um_over_m2_wire'),
    'cap_vpp_04p4x04p6_l1m1m2_noshield_m2_wire': cap_vpp_04p4x04p6_l1m1m2_noshield_m2_wire,
    'cap_vpp_02p7x06p1_m1m2m3m4_shieldl1_fingercap':
        lambda: cap_vpp_of_pdk('cap_vpp_02p7x06p1_m1m2m3m4_shieldl1_fingercap'),
    'cap_vpp_04p4x04p6_l1m1m2_shieldpo_floatm3':
        lambda: cap_vpp_of_pdk('cap_vpp_04p4x04p6_l1m1m2_shieldpo_floatm3'),
    'cap_vpp_licon_within_marker': cap_vpp_licon_within_marker,
    'cap_vpp_routing_across': cap_vpp_routing_across,
    'r_ptap_pair_li1_m1': r_ptap_pair_li1_m1,
    'r_ptap_li1_m1_two_wires': r_ptap_li1_m1_two_wires,
    'r_ntap_pair_nwell_li1_m1': r_ntap_pair_nwell_li1_m1,
    'r_ntap_pair_two_nwells_over_dnwell_li1_m1': r_ntap_pair_two_nwells_over_dnwell_li1_m1,
    'r_ptap_li1_m1_and_floating_m1_m2': r_ptap_li1_m1_and_floating_m1_m2,
    'net_names_A_and_a_m2': net_names_A_and_a_m2,
    'nfet_li1_in_subcell': nfet_li1_in_subcell,
    'rf_inductors_03_90_05_125_05_220': rf_inductors_03_90_05_125_05_220,
}


if __name__ == '__main__':
    sys.exit(main('sky130A', PATTERNS))
