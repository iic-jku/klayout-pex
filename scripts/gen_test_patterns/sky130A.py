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

LI1:      GDSPair = (67, 20)
LI1_PIN:  GDSPair = (67, 16)
MCON:     GDSPair = (67, 44)
MET1:     GDSPair = (68, 20)
MET2:     GDSPair = (69, 20)
MET2_PIN: GDSPair = (69, 16)

LABEL_BY_LAYER: Dict[GDSPair, GDSPair] = {
    LI1: (67, 5),
    MET1: (68, 5),
    MET2: (69, 5),
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


PATTERNS: Dict[str, Callable[[], Pattern]] = {
    'overlap_shield_same_net_100um_x_100um_li1_m1_m2':
        lambda: overlap_shield_same_net('overlap_shield_same_net_100um_x_100um_li1_m1_m2', 100000),
    'overlap_shield_same_net_half_100um_x_100um_li1_m1_m2':
        lambda: overlap_shield_same_net('overlap_shield_same_net_half_100um_x_100um_li1_m1_m2', 50000),
}


if __name__ == '__main__':
    sys.exit(main('sky130A', PATTERNS))
