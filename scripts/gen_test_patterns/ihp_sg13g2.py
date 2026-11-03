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
VIA1:         GDSPair = (19, 0)
METAL3:       GDSPair = (30, 0)
METAL3_PIN:   GDSPair = (30, 2)
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
DIGISUB:      GDSPair = (60, 0)
POLYRES:      GDSPair = (128, 0)

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

def mom_cap(name: str, pcell_name: str, parameters: Dict[str, Any], technology: str = 'sg13g2') -> Pattern:
    """
    A pattern of a MOM cap of the pcells of the PDK, flattened
    """
    p = pattern(name)
    p.layout.technology_name = load_pdk_pcells(technology)
    pcell = p.layout.create_cell(pcell_name, 'SG13_dev', parameters)
    p.top.insert(kdb.CellInstArray(pcell.cell_index(), kdb.Trans()))
    p.top.flatten(-1, True)
    return p


def label_terminals_from_left(p: Pattern, metal: GDSPair, metal_pin: GDSPair):
    """
    The MOM caps of the pcells whose pins are on one metal, the left one is PLUS, e.g. of cmomf, at its left edge,
    and MINUS at its top edge
    """
    pins = sorted(kdb.Region(p.top.begin_shapes_rec(p.layout.layer(*metal_pin))).merged().each(),
                  key=lambda pin: pin.bbox().left)
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
    An ESD diode (esd pcell of the PDK), alone, as only the substrate would join the Metal1 on the substrate net
    of two of them, which is no conductor of the resistance network
    """
    return pcells_side_by_side(f"esd_{model}", [('esd', {'model': model})])


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


PATTERNS: Dict[str, Callable[[], Pattern]] = {
    'cap_cmomf_w10u_l25u_m2_m4_m5_wire': cap_cmomf_w10u_l25u_m2_m4_m5_wire,
    'cap_cmomf_w5u_l5u_m2_m4_plus_from_m1': cap_cmomf_w5u_l5u_m2_m4_plus_from_m1,
    'cap_cmomi_w5u_l5u_m3_m5_same_m1_m2_wire': cap_cmomi_w5u_l5u_m3_m5_same_m1_m2_wire,
    'cap_cmomi_w5u_l5u_m4_m5_none': cap_cmomi_w5u_l5u_m4_m5_none,
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
    'r_wire_over_nbulay_m1': r_wire_over_nbulay_m1,
    'bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa': bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa,
    'device_pcells': device_pcells,
    'esd_diodevdd_2kv': lambda: esd_diode('diodevdd_2kv'),
    'esd_diodevss_2kv': lambda: esd_diode('diodevss_2kv'),
    'diode_dantenna_dpantenna': diode_dantenna_dpantenna,
    'diode_schottky_nbl1': diode_schottky_nbl1,
    'inductor2_w2u_d15u48_tm2_wires_50u': inductor2_w2u_d15u48_tm2_wires_50u,
    'inductor3_w2u_d25u84_2_turns': inductor3_w2u_d25u84_2_turns,
}


if __name__ == '__main__':
    sys.exit(main('ihp-sg13g2', PATTERNS))
