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

import sys
from typing import *

from pattern_builder import GDSPair, Pattern, main

NWELL:    GDSPair = (64, 20)
TAP:      GDSPair = (65, 44)
NSDM:     GDSPair = (93, 44)
PSDM:     GDSPair = (94, 20)
LICON:    GDSPair = (66, 44)
LI1:      GDSPair = (67, 20)
LI1_PIN:  GDSPair = (67, 16)
MCON:     GDSPair = (67, 44)
MET1:     GDSPair = (68, 20)
MET2:     GDSPair = (69, 20)
MET2_PIN: GDSPair = (69, 16)
MET3:     GDSPair = (70, 20)
MET3_PIN: GDSPair = (70, 16)
CAPM:     GDSPair = (89, 44)
VIA3:     GDSPair = (70, 44)
MET4:     GDSPair = (71, 20)
MET4_PIN: GDSPair = (71, 16)

LABEL_BY_LAYER: Dict[GDSPair, GDSPair] = {
    NWELL: (64, 5),
    LI1: (67, 5),
    MET1: (68, 5),
    MET2: (69, 5),
    MET3: (70, 5),
    MET4: (71, 5),
}


def pattern(name: str) -> Pattern:
    return Pattern(name, label_layer_by_layer=LABEL_BY_LAYER)


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

    NOTE: the wire stays outside the marker of the cap, as the LVS deck tells the VPP caps apart
          by the layers that touch their marker (a wire across would make it another device)
    """
    p = pattern('cap_vpp_04p4x04p6_l1m1m2_noshield_m2_wire')
    p.copy_design('sky130A', 'cap_vpp_04p4x04p6_l1m1m2_noshield', 'cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz')

    p.box(MET2, 4680, -615, 5680, 4590)
    p.box(MET2_PIN, 4680, -615, 5680, 385)
    p.label(MET2, 'X', 4880, -415)
    return p


#
# Net name patterns
#

def net_names_A_and_a_m2() -> Pattern:
    """
    Two met2 wires of 20 µm x 0.5 µm, 1 µm apart, the nets A and a,
    which SPICE reads as one, as it reads names case-insensitively
    """
    p = pattern('net_names_A_and_a_m2')
    p.box(MET2, 0, 0, 20000, 500)
    p.label(MET2, 'A', 100, 100)
    p.box(MET2, 0, 1500, 20000, 2000)
    p.label(MET2, 'a', 100, 1600)
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
    'net_names_A_and_a_m2': net_names_A_and_a_m2,
}


if __name__ == '__main__':
    sys.exit(main('sky130A', PATTERNS))
