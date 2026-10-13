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

import os
import sys
from typing import *

import klayout.db as kdb

from pattern_builder import GDSPair, Pattern, main, pdk_root

METAL4:       GDSPair = (50, 0)
METAL4_PIN:   GDSPair = (50, 2)
METAL5:       GDSPair = (67, 0)
METAL5_PIN:   GDSPair = (67, 2)

LABEL_BY_LAYER: Dict[GDSPair, GDSPair] = {
    METAL4: (50, 25),
    METAL5: (67, 25),
}


def pattern(name: str) -> Pattern:
    return Pattern(name, label_layer_by_layer=LABEL_BY_LAYER)


def load_pdk_pcells() -> str:
    """
    :return: the technology of the pcell library SG13_dev
    """
    if kdb.Library.library_by_name('SG13_dev', 'sg13g2') is None:
        klayout_dir = os.path.join(pdk_root(), 'ihp-sg13g2', 'libs.tech', 'klayout')
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
    p = pattern('cap_cmomf_w10u_l25u_m2_m4_m5_wire')
    p.layout.technology_name = technology
    pcell = p.layout.create_cell('cmomf', 'SG13_dev', {'w': '10u', 'l': '25u', 'mmin': 2, 'mmax': 4})
    p.top.insert(kdb.CellInstArray(pcell.cell_index(), kdb.Trans()))
    p.top.flatten(-1, True)

    # NOTE: the pcell paints the pins (Metal4.pin) at the left (PLUS) and the top edge (MINUS)
    pins = sorted(kdb.Region(p.top.begin_shapes_rec(p.layout.layer(*METAL4_PIN))).merged().each(),
                  key=lambda pin: pin.bbox().left)
    for text, pin in zip(('PLUS', 'MINUS'), pins):
        center = pin.bbox().center()
        p.label(METAL4, text, center.x, center.y)

    bbox = p.top.bbox()
    y = bbox.center().y
    p.box(METAL5, bbox.left - 2000, y - 500, bbox.right + 2000, y + 500)
    p.box(METAL5_PIN, bbox.left - 2000, y - 500, bbox.left - 1000, y + 500)
    p.label(METAL5, 'X', bbox.left - 1500, y)
    return p


PATTERNS: Dict[str, Callable[[], Pattern]] = {
    'cap_cmomf_w10u_l25u_m2_m4_m5_wire': cap_cmomf_w10u_l25u_m2_m4_m5_wire,
}


if __name__ == '__main__':
    sys.exit(main('ihp-sg13g2', PATTERNS))
