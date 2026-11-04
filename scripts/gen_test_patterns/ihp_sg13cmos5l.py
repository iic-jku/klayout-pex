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
Generate ihp-sg13cmos5l test patterns (testdata/designs/ihp-sg13cmos5l/test_patterns).

They use the pcells of the PDK, so the ihp-sg13cmos5l PDK must be installed
(e.g. IIC-OSIC-TOOLS, with $PDK_ROOT/ihp-sg13cmos5l).

Usage:
    python3 scripts/gen_test_patterns/ihp_sg13cmos5l.py [--output-dir DIR] [PATTERN ...]
"""
from __future__ import annotations

import sys
from typing import *

import klayout.db as kdb

from ihp_sg13g2 import (
    METAL3,
    METAL3_PIN,
    METAL4,
    METAL4_PIN,
    label_terminals_from_left,
    mom_cap,
    wire_across,
)
from pattern_builder import Pattern, main


#
# Capacitance patterns
#

def cap_cmomf_w5u_l5u_m2_m3_m4_wire() -> Pattern:
    # a MOM cap (cap_cmomf pcell of the PDK) with fingers on Metal2 and Metal3
    # (the model gives 0.61 fF/µm², 15.25 fF), its terminals labelled PLUS (left) and MINUS (top),
    # and a Metal4 wire X across it, on the top metal of the MOM caps of this PDK
    p = mom_cap('cap_cmomf_w5u_l5u_m2_m3_m4_wire', 'cap_cmomf', {'w': '5u', 'l': '5u', 'mmin': 2, 'mmax': 3},
                technology='sg13cmos5l')
    label_terminals_from_left(p, METAL3, METAL3_PIN)
    wire_across(p, METAL4, METAL4_PIN)
    return p


def cap_cmomi_w8u9_l3u36_m2_m4_m45() -> Pattern:
    # a MOM cap (cap_cmomi pcell of the PDK) of 10 rows and 4 columns, mirrored at the diagonal, with opposite feeds,
    # so its rows run along y (the model gives 0.82 fF/µm² of 3.36 µm x 8.9 µm and 0.152 fF/µm of its pads, 25.938 fF)
    p = mom_cap('cap_cmomi_w8u9_l3u36_m2_m4_m45', 'cap_cmomi', {'w': '8.9u', 'l': '3.36u', 'mmin': 2, 'mmax': 4},
                technology='sg13cmos5l', trans=kdb.Trans.M45)
    label_terminals_from_left(p, METAL4, METAL4_PIN)
    return p


PATTERNS: Dict[str, Callable[[], Pattern]] = {
    'cap_cmomf_w5u_l5u_m2_m3_m4_wire': cap_cmomf_w5u_l5u_m2_m3_m4_wire,
    'cap_cmomi_w8u9_l3u36_m2_m4_m45': cap_cmomi_w8u9_l3u36_m2_m4_m45,
}


if __name__ == '__main__':
    sys.exit(main('ihp-sg13cmos5l', PATTERNS))
