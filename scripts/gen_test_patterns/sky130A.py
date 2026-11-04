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
TAP:      GDSPair = (65, 44)
NSDM:     GDSPair = (93, 44)
PSDM:     GDSPair = (94, 20)
POLY:     GDSPair = (66, 20)
POLY_PIN: GDSPair = (66, 16)
LICON:    GDSPair = (66, 44)
LI1:      GDSPair = (67, 20)
LI1_PIN:  GDSPair = (67, 16)
MCON:     GDSPair = (67, 44)
MET1:     GDSPair = (68, 20)
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


PATTERNS: Dict[str, Callable[[], Pattern]] = {
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
