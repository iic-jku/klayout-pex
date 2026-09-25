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
This creates a technology definition example for sky130A:
https://skywater-pdk.readthedocs.io/en/main/_images/metal_stack.svg
"""
from __future__ import annotations

from tech_builder import *


def build_layers(tech: Technology):
    #               purpose, name,     drw_gds,  pin_gds,  label_gds, description
    add_layer(tech, DNWELL,  "dnwell", (64, 18), None,     None,      "Deep N-well")
    add_layer(tech, NWELL,   "nwell",  (64, 20), (64, 16), (64, 5),   "N-well region")
    add_layer(tech, DIFF,    "diff",   (65, 20), (65, 16), (65, 5),   "Active (diffusion) area")
    add_layer(tech, N_P_TAP, "tap",    (65, 44), None,     None,      "Active (diffusion) area (type equal to the well/substrate underneath) (i.e., N+ and P+)")
    add_layer(tech, PIMP,    "psdm",   (94, 20), None,     None,      "P+ source/drain implant")
    add_layer(tech, NIMP,    "nsdm",   (93, 44), None,     None,      "N+ source/drain implant")
    add_layer(tech, METAL,   "poly",   (66, 20), (66, 16), (66, 5),   "Polysilicon")
    add_layer(tech, CONT,    "licon1", (66, 44), None,     None,      "Contact to local interconnect")
    add_layer(tech, METAL,   "li1",    (67, 20), (67, 16), (67, 5),   "Local interconnect")
    add_layer(tech, VIA,     "mcon",   (67, 44), None,     None,      "Contact from local interconnect to met1")
    add_layer(tech, METAL,   "met1",   (68, 20), (68, 16), (68, 5),   "Metal 1")
    add_layer(tech, VIA,     "via",    (68, 44), None,     None,      "Contact from met1 to met2")
    add_layer(tech, METAL,   "met2",   (69, 20), (69, 16), (69, 5),   "Metal 2")
    add_layer(tech, VIA,     "via2",   (69, 44), None,     None,      "Contact from met2 to met3")
    add_layer(tech, METAL,   "met3",   (70, 20), (70, 16), (70, 5),   "Metal 3")
    add_layer(tech, VIA,     "via3",   (70, 44), None,     None,      "Contact from cap above met3 to met4")
    add_layer(tech, MIM,     "capm",   (89, 44), None,     None,      "MiM capacitor plate over metal 3")
    add_layer(tech, METAL,   "met4",   (71, 20), (71, 16), (71, 5),   "Metal 4")
    add_layer(tech, MIM,     "capm2",  (97, 44), None,     None,      "MiM capacitor plate over metal 4")
    add_layer(tech, VIA,     "via4",   (71, 44), None,     None,      "Contact from met4 to met5 (no MiM cap)")
    add_layer(tech, METAL,   "met5",   (72, 20), (72, 16), (72, 5),   "Metal 5")


def build_lvs_computed_layers(tech: Technology):
    #                        purpose  kind  lvs_name     lvs_gds_pair orig. layer  description
    add_computed_layer(tech, DNWELL,  KREG, "dnwell",    (64, 18),    "dnwell",    "Deep NWell")
    add_computed_layer(tech, NWELL,   KREG, "nwell",     (64, 20),    "nwell",     "NWell")
    add_computed_layer(tech, NIMP,    KREG, "nsd",       (93, 44),    "nsdm",      "borrow from nsdm")
    add_computed_layer(tech, PIMP,    KREG, "psd",       (94, 20),    "psdm",      "borrow from psdm")
    add_computed_layer(tech, NTAP,    KREG, "ntap_conn", (65, 144),   "tap",       "Separate ntap, original tap is 65,44, we need seperate ntap/ptap")
    add_computed_layer(tech, PTAP,    KREG, "ptap_conn", (65, 244),   "tap",       "Separate ptap, original tap is 65,44, we need seperate ntap/ptap")
    add_computed_layer(tech, METAL,   KREG, "poly_con",  (66, 20),    "poly",      "Computed layer for poly")
    add_computed_layer(tech, METAL,   KREG, "li_con",    (67, 20),    "li1",       "Computed layer for li1")
    add_computed_layer(tech, METAL,   KREG, "met1_con",  (68, 20),    "met1",      "Computed layer for met1")
    add_computed_layer(tech, METAL,   KREG, "met2_con",  (69, 20),    "met2",      "Computed layer for met2")
    add_computed_layer(tech, METAL,   KREG, "met3_ncap", (70, 20),    "met3",      "Computed layer for met3 (no cap)")
    add_computed_layer(tech, METAL,   KREG, "met4_ncap", (71, 20),    "met4",      "Computed layer for met4 (no cap)")
    add_computed_layer(tech, METAL,   KREG, "met5_con",  (72, 20),    "met5",      "Computed layer for met5")
    add_computed_layer(tech, CONT,    KREG, "licon_nsd_con",  (66, 4401), "licon1", "Computed layer for contact from nsdm to li1")
    add_computed_layer(tech, CONT,    KREG, "licon_psd_con",  (66, 4402), "licon1", "Computed layer for contact from psdm to li1")
    add_computed_layer(tech, CONT,    KREG, "licon_poly_con", (66, 4403), "licon1", "Computed layer for contact from poly to li1")
    add_computed_layer(tech, VIA,     KREG, "mcon_con",  (67, 44),    "mcon",      "Computed layer for contact between li1 and met1")
    add_computed_layer(tech, VIA,     KREG, "via1_con",  (68, 44),    "via",       "Computed layer for contact between met1 and met2")
    add_computed_layer(tech, VIA,     KREG, "via2_con",  (69, 44),    "via2",      "Computed layer for contact between met2 and met3")
    add_computed_layer(tech, VIA,     KREG, "via3_ncap", (70, 144),   "via3",      "Computed layer for via3 (no MIM cap)")
    add_computed_layer(tech, VIA,     KREG, "via4_ncap", (71, 144),   "via4",      "Computed layer for via4 (no MIM cap)")

    # NOTE: for CC whiteboxing to work,
    #       we must ensure all VPP/MIM metal layers map to the same GDS pair as the non-cap versions,
    #       to ensure they are be merged
    #
    #       for R mode, MIM cap vias should point to a different GDS number than the regular via
    #       as they have different resistances
    add_computed_layer(tech, VIA,     KCAP, "via3_cap",  (70, 244),   "via3",      "Computed layer for via3 (with MIM cap)")
    add_computed_layer(tech, VIA,     KCAP, "via4_cap",  (71, 244),   "via4",      "Computed layer for via4 (with MIM cap)")
    add_computed_layer(tech, METAL,   KCAP, "met3_cap",  (70, 20),    "met3",      "metal3 part of MiM cap")
    add_computed_layer(tech, METAL,   KCAP, "met4_cap",  (71, 20),    "met4",      "metal4 part of MiM cap")
    add_computed_layer(tech, MIM,     KCAP, "capm",      (89, 44),    "capm",      "MiM cap above metal3")
    add_computed_layer(tech, MIM,     KCAP, "capm2",     (97, 44),    "capm2",     "MiM cap above metal4")
    add_computed_layer(tech, METAL,   KCAP, "poly_vpp",  (66, 20),    "poly",      "Computed layer for poly (MOM cap)")
    add_computed_layer(tech, METAL,   KCAP, "li_vpp",    (67, 20),    "li1",       "Capacitor device metal (MOM cap)")
    add_computed_layer(tech, METAL,   KCAP, "met1_vpp",  (68, 20),    "met1",      "Capacitor device metal (MOM cap)")
    add_computed_layer(tech, METAL,   KCAP, "met2_vpp",  (69, 20),    "met2",      "Capacitor device metal (MOM cap)")
    add_computed_layer(tech, METAL,   KCAP, "met3_vpp",  (70, 20),    "met3",      "Capacitor device metal (MOM cap)")
    add_computed_layer(tech, METAL,   KCAP, "met4_vpp",  (71, 20),    "met4",      "Capacitor device metal (MOM cap)")
    add_computed_layer(tech, METAL,   KCAP, "met5_vpp",  (72, 20),    "met5",      "Capacitor device metal (MOM cap)")
    add_computed_layer(tech, CONT,    KCAP, "licon_vpp", (66, 44),    "licon1",    "Capacitor device contact (MOM cap)")
    add_computed_layer(tech, VIA,     KCAP, "mcon_vpp",  (67, 44),    "mcon",      "Capacitor device contact (MOM cap)")
    add_computed_layer(tech, VIA,     KCAP, "via1_vpp",  (68, 44),    "via",       "Capacitor device contact (MOM cap)")
    add_computed_layer(tech, VIA,     KCAP, "via2_vpp",  (69, 44),    "via2",      "Capacitor device contact (MOM cap)")
    add_computed_layer(tech, VIA,     KCAP, "via3_vpp",  (70, 44),    "via3",      "Capacitor device contact (MOM cap)")
    add_computed_layer(tech, VIA,     KCAP, "via4_vpp",  (71, 44),    "via4",      "Capacitor device contact (MOM cap)")

    add_computed_layer(tech, METAL,   KPIN, "poly_pin_con", (66, 16), "poly.pin",   "Poly pin")
    add_computed_layer(tech, METAL,   KPIN, "li_pin_con",   (67, 16), "li1.pin",    "li1 pin")
    add_computed_layer(tech, METAL,   KPIN, "met1_pin_con", (68, 16), "met1.pin",   "met1 pin")
    add_computed_layer(tech, METAL,   KPIN, "met2_pin_con", (69, 16), "met2.pin",   "met2 pin")
    add_computed_layer(tech, METAL,   KPIN, "met3_pin_con", (70, 16), "met3.pin",   "met3 pin")
    add_computed_layer(tech, METAL,   KPIN, "met4_pin_con", (71, 16), "met4.pin",   "met4 pin")
    add_computed_layer(tech, METAL,   KPIN, "met5_pin_con", (72, 16), "met5.pin",   "met5 pin")

    add_computed_layer(tech, METAL,   KLBL, "poly_label",   (66, 5),  "poly.label", "Poly label")
    add_computed_layer(tech, METAL,   KLBL, "li_label",     (67, 5),  "li1.label",  "li1 label")
    add_computed_layer(tech, METAL,   KLBL, "met1_label",   (68, 5),  "met1.label", "met1 label")
    add_computed_layer(tech, METAL,   KLBL, "met2_label",   (69, 5),  "met2.label", "met2 label")
    add_computed_layer(tech, METAL,   KLBL, "met3_label",   (70, 5),  "met3.label", "met3 label")
    add_computed_layer(tech, METAL,   KLBL, "met4_label",   (71, 5),  "met4.label", "met4 label")
    add_computed_layer(tech, METAL,   KLBL, "met5_label",   (72, 5),  "met5.label", "met5 label")


def build_process_stack_info(psi: ProcessStackInfo):
    # SUBSTRATE:              name    height   thickness   reference
    #                                 (TODO)   (TODO)
    #-----------------------------------------------------------------------------------------------
    add_substrate_layer(psi, "subs",  0.1,     0.33,       "fox")

    # NWELL/DIFF:                      name     z        ref
    #                                           (TODO)
    #-----------------------------------------------------------------------------------------------
    nwell =    add_nwell_layer(psi,     "nwell", 0.1,    "fox")

    ndiff = add_diffusion_layer(psi,    "nsd",   0.323,  "fox")
    pdiff = add_diffusion_layer(psi,    "psd",   0.323,  "fox")

    # FOX:                      name     dielectric_k
    #-----------------------------------------------------------------------------------------------
    add_field_oxide_layer(psi,  "fox",   4.632)
    # NOTE: fine-tuned dielectric_k for single_plate_100um_x_100um_li1_over_substrate to match foundry table data

    # METAL:                        name,   z,      thickness
    #-----------------------------------------------------------------------------------------------
    poly = add_metal_layer(psi,     "poly", 0.3262, 0.18)

    # DIELECTRIC (conformal)        name,    dielectric_k, thickness,   thickness,      thickness, ref
    #                                                      over metal,  where no metal, sidewall
    #-----------------------------------------------------------------------------------------------
    add_conformal_dielectric(psi,   "iox",   3.9,          0.0,         0.0,            0.006,     "poly")
    add_conformal_dielectric(psi,   "spnit", 7.5,          0.121,       0.0,            0.0431,    "iox")

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "psg",    3.9,          "fox")

    # METAL:                        name,  z,      thickness
    #-----------------------------------------------------------------------------------------------
    li1 = add_metal_layer(psi,      "li1", 0.9361, 0.1)

    # DIELECTRIC (conformal)        name,   dielectric_k, thickness,   thickness,      thickness  ref
    #                                                     over metal,  where no metal, sidewall
    #-----------------------------------------------------------------------------------------------
    add_conformal_dielectric(psi,   "lint", 7.3,          0.075,       0.075,          0.075,     "li1")

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "nild2",  4.05,         "lint")

    # METAL:                        name,   z,      thickness
    #-----------------------------------------------------------------------------------------------
    met1 = add_metal_layer(psi,     "met1", 1.3761, 0.36)

    # DIELECTRIC (conformal)        name,     dielectric_k, thickness,   thickness,      thickness, ref
    #                                                       over metal,  where no metal, sidewall
    #-----------------------------------------------------------------------------------------------
    add_conformal_dielectric(psi,   "nild3c", 3.5,          0.0,         0.0,            0.03,      "met1")

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "nild3",  4.5,          "nild2")

    # METAL:                        name,   z,      thickness
    #-----------------------------------------------------------------------------------------------
    met2 = add_metal_layer(psi,     "met2", 2.0061, 0.36)

    # DIELECTRIC (conformal)        name,     dielectric_k, thickness,   thickness,      thickness, ref
    #                                                       over metal,  where no metal, sidewall
    #-----------------------------------------------------------------------------------------------
    add_conformal_dielectric(psi,   "nild4c", 3.5,          0.0,         0.0,            0.03,      "met2")

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "nild4",  4.2,          "nild3")

    # METAL:                             name,        z,      thickness
    #-----------------------------------------------------------------------------------------------
    met3_ncap = add_metal_layer(psi,     "met3_ncap", 2.7861, 0.845)
    met3_cap  = add_metal_layer(psi,     "met3_cap",  2.7861, 0.845)

    capm_thickness = 0.1
    capild_k = 4.52  # to match design cap_mim_m3_w18p9_l5p1_no_interconnect to 200fF
    capild_thickness = 0.02

    # DIELECTRIC (conformal)        name,      dielectric_k, thickness,        thickness,      thickness, ref
    #                                                        over metal,       where no metal, sidewall
    #-----------------------------------------------------------------------------------------------
    add_conformal_dielectric(psi,   "capild3", capild_k,     capild_thickness, 0.0,            0.0,       "met3_cap")

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "nild5",  4.1,          "nild4")

    # METAL:                        name,   z,                                 thickness
    #-----------------------------------------------------------------------------------------------
    capm = add_metal_layer(psi,     "capm", 2.7861 + 0.845 + capild_thickness, capm_thickness)

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "nild5b", 4.1,          "nild4")  # same material as nild5, above capm

    # METAL:                             name,        z,      thickness
    #-----------------------------------------------------------------------------------------------
    met4_ncap = add_metal_layer(psi,     "met4_ncap", 4.0211, 0.845)

    # DIELECTRIC (conformal)        name,      dielectric_k, thickness,        thickness,      thickness, ref
    #                                                        over metal,       where no metal, sidewall
    #-----------------------------------------------------------------------------------------------
    add_conformal_dielectric(psi,   "capild4", capild_k,     capild_thickness, 0.0,            0.0,       "met4_cap")

    # METAL:                             name,        z,      thickness
    #-----------------------------------------------------------------------------------------------
    met4_cap  = add_metal_layer(psi,     "met4_cap",  4.0211, 0.845)

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "nild6",  4.0,          "nild5")

    # METAL:                         name,    z,                                 thickness
    #-----------------------------------------------------------------------------------------------
    capm2 = add_metal_layer(psi,     "capm2", 4.0211 + 0.845 + capild_thickness, capm_thickness)

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "nild6b", 4.0,          "nild5")  # same material as nild6, above capm2

    # METAL:                        name,   z,      thickness
    #-----------------------------------------------------------------------------------------------
    met5 = add_metal_layer(psi,     "met5", 5.3711, 1.26)

    # DIELECTRIC (conformal)        name,     dielectric_k, thickness,   thickness,      thickness, ref
    #                                                       over metal,  where no metal, sidewall
    #-----------------------------------------------------------------------------------------------
    add_conformal_dielectric(psi,   "topox",  3.9,          0.09,        0.0,            0.07,      "met5")

    # DIELECTRIC (conformal)        name,     dielectric_k, thickness,   thickness,      thickness, ref
    #                                                       over metal,  where no metal, sidewall
    #-----------------------------------------------------------------------------------------------
    add_conformal_dielectric(psi,   "topnit", 7.5,          0.54,        0.4223,         0.3777,    "topox")

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "air",    3.0,          "topnit")

    # NOTE: on its own, accessing contact_above declares no contact (unlike C++ mutable_contact_above()),
    #       it's declared by setting its fields in set_contact()
    # nwellc = nwell.contact_above  # licon over nwell / tap  # TODO!
    licon1n = ndiff.contact_above     # licon over nsdm
    licon1p = pdiff.contact_above     # licon over nsdm
    licon1poly = poly.contact_above   # licon over poly
    mcon = li1.contact_above
    via = met1.contact_above
    via2 = met2.contact_above
    via3_ncap = met3_ncap.contact_above
    via3_cap = capm.contact_above
    via4_ncap = met4_ncap.contact_above
    via4_cap = capm2.contact_above

    # CONTACT:  contact,     name,             layer_below, metal_above, thickness,               width, spacing, border
    #                        (LVS)             (LVS)        (LVS)
    #----------------------------------------------------------------------------------------------------------------------
    # set_contact(nwellc,    "TODO",           "nwell",     "li1",       0.9361,                  0.17,  0.17,    0.0)  # TODO
    set_contact(licon1n,     "licon_nsd_con",  "nsdm",      "li1",       0.9361,                  0.17,  0.17,    0.0)
    set_contact(licon1p,     "licon_psd_con",  "psdm",      "li1",       0.9361,                  0.17,  0.17,    0.0)
    set_contact(licon1poly,  "licon_poly_con", "poly",      "li1",       0.4299,                  0.17,  0.17,    0.0)
    set_contact(mcon,        "mcon_con",       "li1",       "met1",      1.3761 - (0.9361 + 0.1), 0.17,  0.19,    0.0)
    set_contact(via,         "via1_con",       "met1",      "met2",      0.27,                    0.15,  0.17,    0.055)
    set_contact(via2,        "via2_con",       "met2",      "met3",      0.42,                    0.20,  0.20,    0.04)
    set_contact(via3_ncap,   "via3_ncap",      "met3",      "met4",      0.39,                    0.20,  0.20,    0.06)
    set_contact(via4_ncap,   "via4_ncap",      "met4",      "met5",      0.505,                   0.80,  0.80,    0.19)

    # The MiM variants land on the capacitor top plate, not on the metal below it:
    # via3_cap and via4_cap are attached to capm / capm2 above. Their thickness is
    # derived rather than written out, because the gap they have to fill depends on
    # capild_thickness, which the two literals it replaces did not account for
    # (0.29 and 0.405 against actual gaps of 0.27 and 0.385).
    #
    # CONTACT:  contact,     name,             layer_below, metal_above, thickness,                                 width, spacing, border
    #                        (LVS)             (LVS)        (LVS)
    #-----------------------------------------------------------------------------------------------------------------------------------------------
    set_contact(via3_cap,    "via3_cap",       "capm",      "met4",      met4_ncap.z - (capm.z + capm.thickness),   0.20,  0.20,    0.06)
    set_contact(via4_cap,    "via4_cap",       "capm2",     "met5",      met5.z - (capm2.z + capm2.thickness),      0.80,  0.80,    0.19)


def build_process_parasitics_info(ex: ProcessParasiticsInfo):
    # See  https://docs.google.com/spreadsheets/d/1N9To-xTiA7FLfQ1SNzWKe-wMckFEXVE9WPkPPjYkaxE/edit?pli=1&gid=1654372372#gid=1654372372

    ex.side_halo = 8.0

    ri = ex.resistance

    # resistance values are in mΩ / square
    #                       layer, resistance, [corner_adjustment_fraction]
    add_layer_resistance(ri, "poly", 48200)  # allpolynonres
    add_layer_resistance(ri, "li1",  12800)
    add_layer_resistance(ri, "met1",   125)
    add_layer_resistance(ri, "met2",   125)
    add_layer_resistance(ri, "met3",    47)
    add_layer_resistance(ri, "met4",    47)
    add_layer_resistance(ri, "met5",    29)

    # resistance values are in mΩ / CNT
    #                         contact_layer,    layer_below,  layer_above, resistance
    add_contact_resistance(ri, "licon_nsd_con",  "nsdm",       "li1",        185000)  # licon over nsdm!
    add_contact_resistance(ri, "licon_psd_con",  "psdm",       "li1",        585000)  # licon over psdm!
    add_contact_resistance(ri, "licon_poly_con", "poly",       "li1",        152000)  # licon over poly!

    # resistance values are in mΩ / CNT
    #                     via_layer,  resistance
    add_via_resistance(ri, "mcon",          9300)
    add_via_resistance(ri, "via",           4500)
    add_via_resistance(ri, "via2",          3410)
    add_via_resistance(ri, "via3",          3410)
    add_via_resistance(ri, "via4",           380)

    ci = ex.capacitance

    #                    layer,  area_cap,  perimeter_cap
    # add_substrate_cap(ci, "dnwell", 120.0,   0.0)  # TODO
    add_substrate_cap(ci, "poly", 106.13,    55.27)
    add_substrate_cap(ci, "li1",  36.99,     40.7)
    add_substrate_cap(ci, "met1", 25.78,     40.57)
    add_substrate_cap(ci, "met2", 17.5,      37.76)
    add_substrate_cap(ci, "met3", 12.37,     40.99)
    add_substrate_cap(ci, "met4", 8.42,      36.68)
    add_substrate_cap(ci, "met5", 6.32,      38.85)

    diff_nonfet = "diff"  # TODO: diff must be non-fet!
    poly_nonres = "poly"  # TODO: poly must be non-res!
    all_active = "diff"   # TODO: must be allactive

    #                  top_layer,  bottom_layer,  cap
    # add_overlap_cap(ci, "pwell", "dnwell",     120.0)  # TODO
    add_overlap_cap(ci, "pwell",    "dnwell",     120.0)  # TODO
    add_overlap_cap(ci, "poly",     "nwell",      106.13)
    add_overlap_cap(ci, "poly",     "pwell",      106.13)
    add_overlap_cap(ci, "li1",      "pwell",      36.99)
    add_overlap_cap(ci, "li1",      "nwell",      36.99)
    add_overlap_cap(ci, "li1",      diff_nonfet,  55.3)
    add_overlap_cap(ci, "li1",      "poly",       94.16)
    add_overlap_cap(ci, "met1",     "pwell",      25.78)
    add_overlap_cap(ci, "met1",     "nwell",      25.78)
    add_overlap_cap(ci, "met1",     diff_nonfet,  33.6)
    add_overlap_cap(ci, "met1",     poly_nonres,  44.81)
    add_overlap_cap(ci, "met1",     "li1",        114.20)
    add_overlap_cap(ci, "met2",     "nwell",      17.5)
    add_overlap_cap(ci, "met2",     "pwell",      17.5)
    add_overlap_cap(ci, "met2",     diff_nonfet,  20.8)
    add_overlap_cap(ci, "met2",     poly_nonres,  24.50)
    add_overlap_cap(ci, "met2",     "li1",        37.56)
    add_overlap_cap(ci, "met2",     "met1",       133.86)
    add_overlap_cap(ci, "met3",     "nwell",      12.37)
    add_overlap_cap(ci, "met3",     "pwell",      12.37)
    add_overlap_cap(ci, "met3",     all_active,   14.2)
    add_overlap_cap(ci, "met3",     poly_nonres,  16.06)
    add_overlap_cap(ci, "met3",     "li1",        20.79)
    add_overlap_cap(ci, "met3",     "met1",       34.54)
    add_overlap_cap(ci, "met3",     "met2",       86.19)
    add_overlap_cap(ci, "met4",     "nwell",      8.42)
    add_overlap_cap(ci, "met4",     "pwell",      8.42)
    add_overlap_cap(ci, "met4",     all_active,   9.41)
    add_overlap_cap(ci, "met4",     poly_nonres,  10.01)
    add_overlap_cap(ci, "met4",     "li1",        11.67)
    add_overlap_cap(ci, "met4",     "met1",       15.03)
    add_overlap_cap(ci, "met4",     "met2",       20.33)
    add_overlap_cap(ci, "met4",     "met3",       84.03)
    add_overlap_cap(ci, "met5",     "nwell",      6.32)
    add_overlap_cap(ci, "met5",     "pwell",      6.32)
    add_overlap_cap(ci, "met5",     all_active,   6.88)
    add_overlap_cap(ci, "met5",     poly_nonres,  7.21)
    add_overlap_cap(ci, "met5",     "li1",        8.03)
    add_overlap_cap(ci, "met5",     "met1",       9.48)
    add_overlap_cap(ci, "met5",     "met2",       11.34)
    add_overlap_cap(ci, "met5",     "met3",       19.63)
    add_overlap_cap(ci, "met5",     "met4",       68.33)

    #                   layer_name, cap,  offset
    add_sidewall_cap(ci, "poly",     16.0, 0.0)
    add_sidewall_cap(ci, "li1",      25.5, 0.14)
    add_sidewall_cap(ci, "met1",     44,   0.25)
    add_sidewall_cap(ci, "met2",     50,   0.3)
    add_sidewall_cap(ci, "met3",     74.0, 0.4)
    add_sidewall_cap(ci, "met4",     94.0, 0.57)
    add_sidewall_cap(ci, "met5",     155,  0.5)

    #                           in_layer,    out_layer,   cap
    add_sidewall_overlap_cap(ci, "poly",      "nwell",     55.27)
    add_sidewall_overlap_cap(ci, "poly",      "pwell",     55.27)
    add_sidewall_overlap_cap(ci, "li1",       "nwell",     40.70)
    add_sidewall_overlap_cap(ci, "li1",       "pwell",     40.70)
    add_sidewall_overlap_cap(ci, "li1",       diff_nonfet, 44.27)
    add_sidewall_overlap_cap(ci, "li1",       poly_nonres, 51.85)
    add_sidewall_overlap_cap(ci, "poly",      "li1",       25.14)
    add_sidewall_overlap_cap(ci, "met1",      "nwell",     40.57)
    add_sidewall_overlap_cap(ci, "met1",      "pwell",     40.57)
    add_sidewall_overlap_cap(ci, "met1",      diff_nonfet, 43.10)
    add_sidewall_overlap_cap(ci, "met1",      poly_nonres, 46.72)
    add_sidewall_overlap_cap(ci, "poly",      "met1",      16.69)
    add_sidewall_overlap_cap(ci, "met1",      "li1",       59.50)
    add_sidewall_overlap_cap(ci, "li1",       "met1",      34.70)
    add_sidewall_overlap_cap(ci, "met2",      "nwell",     37.76)
    add_sidewall_overlap_cap(ci, "met2",      "pwell",     37.76)
    add_sidewall_overlap_cap(ci, "met2",      diff_nonfet, 39.54)
    add_sidewall_overlap_cap(ci, "met2",      poly_nonres, 41.22)
    add_sidewall_overlap_cap(ci, "poly",      "met2",      11.17)
    add_sidewall_overlap_cap(ci, "met2",      "li1",       46.28)
    add_sidewall_overlap_cap(ci, "li1",       "met2",      21.74)
    add_sidewall_overlap_cap(ci, "met2",      "met1",      67.05)
    add_sidewall_overlap_cap(ci, "met1",      "met2",      48.19)
    add_sidewall_overlap_cap(ci, "met3",      "nwell",     40.99)
    add_sidewall_overlap_cap(ci, "met3",      "pwell",     40.99)
    add_sidewall_overlap_cap(ci, "met3",      all_active,  42.25)
    add_sidewall_overlap_cap(ci, "met3",      poly_nonres, 43.53)
    add_sidewall_overlap_cap(ci, "poly",      "met3",      9.18)
    add_sidewall_overlap_cap(ci, "met3",      "li1",       46.71)
    add_sidewall_overlap_cap(ci, "li1",       "met3",      15.08)
    add_sidewall_overlap_cap(ci, "met3",      "met1",      54.81)
    add_sidewall_overlap_cap(ci, "met1",      "met3",      26.68)
    add_sidewall_overlap_cap(ci, "met3",      "met2",      69.85)
    add_sidewall_overlap_cap(ci, "met2",      "met3",      44.43)
    add_sidewall_overlap_cap(ci, "met4",      "nwell",     36.68)
    add_sidewall_overlap_cap(ci, "met4",      "pwell",     36.68)
    add_sidewall_overlap_cap(ci, "met4",      diff_nonfet, 37.57)
    add_sidewall_overlap_cap(ci, "met4",      poly_nonres, 38.11)
    add_sidewall_overlap_cap(ci, "poly",      "met4",      6.35)
    add_sidewall_overlap_cap(ci, "met4",      "li1",       39.71)
    add_sidewall_overlap_cap(ci, "li1",       "met4",      10.14)
    add_sidewall_overlap_cap(ci, "met4",      "met1",      42.56)
    add_sidewall_overlap_cap(ci, "met1",      "met4",      16.42)
    add_sidewall_overlap_cap(ci, "met4",      "met2",      46.38)
    add_sidewall_overlap_cap(ci, "met2",      "met4",      22.33)
    add_sidewall_overlap_cap(ci, "met4",      "met3",      70.52)
    add_sidewall_overlap_cap(ci, "met3",      "met4",      42.64)

    add_sidewall_overlap_cap(ci, "met5",      "nwell",     38.85)
    add_sidewall_overlap_cap(ci, "met5",      "pwell",     38.85)
    add_sidewall_overlap_cap(ci, "met5",      diff_nonfet, 39.52)
    add_sidewall_overlap_cap(ci, "met5",      poly_nonres, 39.91)
    add_sidewall_overlap_cap(ci, "poly",      "met5",      6.49)
    add_sidewall_overlap_cap(ci, "met5",      "li1",       41.15)
    add_sidewall_overlap_cap(ci, "li1",       "met5",      7.64)
    add_sidewall_overlap_cap(ci, "met5",      "met1",      43.19)
    add_sidewall_overlap_cap(ci, "met1",      "met5",      12.02)
    add_sidewall_overlap_cap(ci, "met5",      "met2",      45.59)
    add_sidewall_overlap_cap(ci, "met2",      "met5",      15.69)
    add_sidewall_overlap_cap(ci, "met5",      "met3",      54.15)
    add_sidewall_overlap_cap(ci, "met3",      "met5",      27.84)
    add_sidewall_overlap_cap(ci, "met5",      "met4",      82.82)
    add_sidewall_overlap_cap(ci, "met4",      "met5",      46.98)


def build_tech() -> Technology:
    tech = Technology(name="sky130A")

    build_layers(tech)

    build_lvs_computed_layers(tech)

    build_process_stack_info(tech.process_stack)

    build_process_parasitics_info(tech.process_parasitics)

    return tech
