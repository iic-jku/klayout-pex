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

import os
import sys
from typing import *

import klayout.db as kdb

from pattern_builder import GDSPair, Pattern, main, pdk_root

ACTIV:        GDSPair = (1, 0)
CONT:         GDSPair = (6, 0)
PSD:          GDSPair = (14, 0)
NWELL:        GDSPair = (31, 0)
NBULAY:       GDSPair = (32, 0)
METAL1:       GDSPair = (8, 0)
METAL1_PIN:   GDSPair = (8, 2)
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

LABEL_BY_LAYER: Dict[GDSPair, GDSPair] = {
    METAL1: (8, 25),
    METAL4: (50, 25),
    METAL5: (67, 25),
    TOPMETAL1: (126, 25),
    TOPMETAL2: (134, 25),
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


def cap_rfcmim_w7u_l7u_over_m4_wire() -> Pattern:
    """
    The rfcmim of the test data (sg13g2_pr__rfcmim, 7 µm x 7 µm, wfeed 3 µm, its terminals PLUS and MINUS),
    with a Metal4 wire D of 1 µm width under it, across the cap, which the bottom plate shields from the top plate
    """
    p = pattern('cap_rfcmim_w7u_l7u_over_m4_wire')
    p.copy_design('ihp-sg13g2', 'sg13g2_pr__rfcmim', 'rfcmim.gds.gz')

    # NOTE: the cell labels its pins on the text layer only, label them as the terminals of the model
    for layer, pin_layer, text in ((TOPMETAL1, TOPMETAL1_PIN, 'PLUS'), (METAL5, METAL5_PIN, 'MINUS')):
        pin, = kdb.Region(p.top.begin_shapes_rec(p.layout.layer(*pin_layer))).merged().each()
        center = pin.bbox().center()
        p.label(layer, text, center.x, center.y)

    p.box(METAL4, 3000, -8000, 4000, 15000)
    p.box(METAL4_PIN, 3000, -8000, 4000, -7000)
    p.label(METAL4, 'D', 3200, -7800)
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
# Device patterns
#

def bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa() -> Pattern:
    """
    The bipolar transistors (pcells of the PDK) side by side, 10 µm apart: an npn13G2 with 4 emitters,
    an npn13G2L, an npn13G2V and a pnpMPA, whose terminals are joined to the Metal1 over them by contacts
    (and the emitters of the npn13G2 and the npn13G2L by their emitter windows) within the devices
    """
    technology = load_pdk_pcells()
    p = pattern('bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa')
    p.layout.technology_name = technology
    x = 0
    for pcell_name, parameters in (('npn13G2', {'Nx': 4}), ('npn13G2L', {}), ('npn13G2V', {}), ('pnpMPA', {})):
        pcell = p.layout.create_cell(pcell_name, 'SG13_dev', parameters)
        p.top.insert(kdb.CellInstArray(pcell.cell_index(), kdb.Trans(x - pcell.bbox().left, 0)))
        x += pcell.bbox().width() + 10000
    p.top.flatten(-1, True)
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


PATTERNS: Dict[str, Callable[[], Pattern]] = {
    'cap_cmomf_w10u_l25u_m2_m4_m5_wire': cap_cmomf_w10u_l25u_m2_m4_m5_wire,
    'cap_cmim_20um_x_20um_over_m4_wire':
        lambda: cap_cmim_over_m4_wire('cap_cmim_20um_x_20um_over_m4_wire'),
    'cap_rfcmim_w7u_l7u_over_m4_wire': cap_rfcmim_w7u_l7u_over_m4_wire,
    'single_plate_6um_x_8um_m1_over_isolated_pwell': single_plate_6um_x_8um_m1_over_isolated_pwell,
    'r_wire_over_nbulay_m1': r_wire_over_nbulay_m1,
    'bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa': bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa,
    'inductor2_w2u_d15u48_tm2_wires_50u': inductor2_w2u_d15u48_tm2_wires_50u,
    'inductor3_w2u_d25u84_2_turns': inductor3_w2u_d25u84_2_turns,
}


if __name__ == '__main__':
    sys.exit(main('ihp-sg13g2', PATTERNS))
