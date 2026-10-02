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
This creates a technology definition example for gf180mcu:
https://gf180mcu-pdk.readthedocs.io/en/latest/analog/layout/inter_specs/inter_specs_3_43.html
https://gf180mcu-pdk.readthedocs.io/en/latest/physical_verification/design_manual/drm_04_1.html
https://gf180mcu-pdk.readthedocs.io/en/latest/analog/layout/inter_specs/inter_specs_2.html
"""
from __future__ import annotations

from tech_builder import *


def build_layers(tech: Technology):
    # https://gf180mcu-pdk.readthedocs.io/en/latest/physical_verification/design_manual/drm_04_1.html

    # NOTE: gf180mcu has no pin layers, pins are labels (xx/10) on the drawn layer,
    #       so the drawn layer is the pin layer too
    #
    #               purpose, name,      drw_gds,  pin_gds,  label_gds, description
    add_layer(tech, DNWELL,  "DNWELL",  (12, 0),  None,     None,      "Deep N-well")
    add_layer(tech, NWELL,   "Nwell",   (21, 0),  None,     None,      "N-well region")
    add_layer(tech, DIFF,    "COMP",    (22, 0),  None,     (22, 10),  "Diffusion for device and interconnect")
    # add_layer(tech, N_P_TAP, "tap",   (65, 44), None,     None,      "Active (diffusion) area (type equal to the well/substrate underneath) (i.e., N+ and P+)")
    add_layer(tech, PIMP,    "Pplus",   (31, 0),  None,     None,      "P+ source/drain implant")
    add_layer(tech, NIMP,    "Nplus",   (32, 0),  None,     None,      "N+ source/drain implant")
    add_layer(tech, METAL,   "Poly2",   (30, 0),  (30, 0),  (30, 10),  "Polysilicon gate & interconnect")
    add_layer(tech, CONT,    "Contact", (33, 0),  None,     None,      "Contact to local interconnect")
    add_layer(tech, METAL,   "Metal1",  (34, 0),  (34, 0),  (34, 10),  "Metal 1 interconnect")
    add_layer(tech, VIA,     "Via1",    (35, 0),  None,     None,      "Contact from Metal1 to Metal2")
    add_layer(tech, METAL,   "Metal2",  (36, 0),  (36, 0),  (36, 10),  "Metal 2 interconnect")
    add_layer(tech, VIA,     "Via2",    (38, 0),  None,     None,      "Contact from Metal2 to Metal3")
    add_layer(tech, METAL,   "Metal3",  (42, 0),  (42, 0),  (42, 10),  "Metal 3 interconnect")
    add_layer(tech, VIA,     "Via3",    (40, 0),  None,     None,      "Contact from Metal3 to Metal4")
    add_layer(tech, METAL,   "Metal4",  (46, 0),  (46, 0),  (46, 10),  "Metal 4 interconnect")
    add_layer(tech, VIA,     "Via4",    (41, 0),  None,     None,      "Contact from Metal4 to Metal5")
    add_layer(tech, MIM,     "FuseTop", (75, 0),  None,     None,      "MiM capacitor top plate over Metal4")
    add_layer(tech, METAL,   "Metal5",  (81, 0),  (81, 0),  (81, 10),  "Metal 5 interconnect")


def build_lvs_computed_layers(tech: Technology):
    #                        purpose  kind  lvs_name       lvs_gds_pair orig. layer  description
    add_computed_layer(tech, DNWELL,  KREG, "dnwell",      (12, 0),     "DNWELL",    "Deep NWell")
    add_computed_layer(tech, NWELL,   KREG, "nwell_con",   (21, 0),     "Nwell",     "NWell")
    add_computed_layer(tech, NIMP,    KREG, "nsd",         (32, 0),     "Nplus",     "N+ source/drain")
    add_computed_layer(tech, PIMP,    KREG, "psd",         (31, 0),     "Pplus",     "P+ source/drain")
    add_computed_layer(tech, NTAP,    KREG, "ntap",        (22, 144),   "COMP",      "N+ tap (COMP within nwell)")
    add_computed_layer(tech, PTAP,    KREG, "ptap",        (22, 244),   "COMP",      "P+ tap (COMP outside nwell)")
    add_computed_layer(tech, METAL,   KREG, "poly2_con",   (30, 0),     "Poly2",     "Computed layer for poly")
    add_computed_layer(tech, METAL,   KREG, "metal1_con",  (34, 0),     "Metal1",    "Computed layer for met1")
    add_computed_layer(tech, METAL,   KREG, "metal2_con",  (36, 0),     "Metal2",    "Computed layer for met2")
    add_computed_layer(tech, METAL,   KREG, "metal3_con",  (42, 0),     "Metal3",    "Computed layer for met3 (no cap)")
    add_computed_layer(tech, METAL,   KREG, "metal4_con",  (46, 0),     "Metal4",    "Computed layer for met4 (no cap)")
    add_computed_layer(tech, METAL,   KREG, "metal5_con",  (81, 0),     "Metal5",    "Computed layer for met5")
    add_computed_layer(tech, CONT,    KREG, "contact_nsd_con",  (33, 4401),  "Contact", "Computed layer for contact from nsd to Metal1")
    add_computed_layer(tech, CONT,    KREG, "contact_psd_con",  (33, 4402),  "Contact", "Computed layer for contact from psd to Metal1")
    add_computed_layer(tech, CONT,    KREG, "contact_poly_con", (33, 4403),  "Contact", "Computed layer for contact from poly to Metal1")
    add_computed_layer(tech, VIA,     KREG, "via1",        (35, 0),     "Via1",      "Computed layer for via1")
    add_computed_layer(tech, VIA,     KREG, "via2_n_cap",  (38, 144),   "Via2",      "Computed layer for via2 (no MIM cap)")
    add_computed_layer(tech, VIA,     KREG, "via3_n_cap",  (40, 144),   "Via3",      "Computed layer for via3 (no MIM cap)")
    add_computed_layer(tech, VIA,     KREG, "via4_n_cap",  (41, 144),   "Via4",      "Computed layer for via4 (no MIM cap)")
    add_computed_layer(tech, VIA,     KCAP, "top_via_cap", (41, 244),   "Via4",      "Computed layer for via4 (with MIM cap)")
    add_computed_layer(tech, MIM,     KCAP, "fuse_cap",    (75, 0),     "FuseTop",   "MiM cap top plate over Metal4")

    # NOTE: for CC whiteboxing to work,
    #       we must ensure all VPP/MIM metal layers map to the same GDS pair as the non-cap versions,
    #       to ensure they are be merged
    #
    #       for R mode, MIM cap vias should point to a different GDS number than the regular via
    #       as they have different resistances
    # add_computed_layer(tech, METAL, KCAP, "poly_vpp",    (66, 20),    "Poly2",     "Computed layer for poly (MOM cap)")
    # add_computed_layer(tech, METAL, KCAP, "li_vpp",      (67, 20),    "Metal1",    "Capacitor device metal (MOM cap)")
    # add_computed_layer(tech, METAL, KCAP, "met1_vpp",    (68, 20),    "Metal2",    "Capacitor device metal (MOM cap)")
    # add_computed_layer(tech, METAL, KCAP, "met2_vpp",    (69, 20),    "Metal3",    "Capacitor device metal (MOM cap)")
    # add_computed_layer(tech, METAL, KCAP, "met3_vpp",    (70, 20),    "Metal4",    "Capacitor device metal (MOM cap)")
    # add_computed_layer(tech, METAL, KCAP, "met4_vpp",    (71, 20),    "Metal5",    "Capacitor device metal (MOM cap)")
    # add_computed_layer(tech, METAL, KCAP, "met5_vpp",    (72, 20),    "MetalTop",  "Capacitor device metal (MOM cap)")
    # add_computed_layer(tech, CONT,  KCAP, "licon_vpp",   (66, 44),    "licon1",    "Capacitor device contact (MOM cap)")
    # add_computed_layer(tech, VIA,   KCAP, "mcon_vpp",    (67, 44),    "mcon",      "Capacitor device contact (MOM cap)")
    # add_computed_layer(tech, VIA,   KCAP, "via1_vpp",    (68, 44),    "via",       "Capacitor device contact (MOM cap)")
    # add_computed_layer(tech, VIA,   KCAP, "via2_vpp",    (69, 44),    "via2",      "Capacitor device contact (MOM cap)")
    # add_computed_layer(tech, VIA,   KCAP, "via3_vpp",    (70, 44),    "via3",      "Capacitor device contact (MOM cap)")
    # add_computed_layer(tech, VIA,   KCAP, "via4_vpp",    (71, 44),    "via4",      "Capacitor device contact (MOM cap)")

    add_computed_layer(tech, METAL,   KLBL, "comp_label",   (22, 10),   "COMP_label",   "LABEL drawn at diffusion layer")
    add_computed_layer(tech, METAL,   KLBL, "poly2_label",  (30, 10),   "Poly2_label",  "LABEL drawn at poly2 layer")
    add_computed_layer(tech, METAL,   KLBL, "metal1_label", (34, 10),   "Metal1_label", "LABEL drawn at Metal1 layer")
    add_computed_layer(tech, METAL,   KLBL, "metal2_label", (36, 10),   "Metal2_label", "LABEL drawn at Metal2 layer")
    add_computed_layer(tech, METAL,   KLBL, "metal3_label", (42, 10),   "Metal3_label", "LABEL drawn at Metal3 layer")
    add_computed_layer(tech, METAL,   KLBL, "metal4_label", (46, 10),   "Metal4_label", "LABEL drawn at Metal4 layer")
    add_computed_layer(tech, METAL,   KLBL, "metal5_label", (81, 10),   "Metal5_label", "LABEL drawn at Metal5 layer")


def build_process_stack_info(psi: ProcessStackInfo):
    # https://gf180mcu-pdk.readthedocs.io/en/latest/_images/2_cross_section_43.png

    # SUBSTRATE:              name    height   thickness   reference
    #                                 (TODO)   (TODO)
    #-----------------------------------------------------------------------------------------------
    add_substrate_layer(psi, "subs",  0.0,     0.33,       "fox")

    # NWELL/DIFF:                   name     z        ref
    #                                        (TODO)
    #-----------------------------------------------------------------------------------------------
    add_nwell_layer(psi,            "Nwell", 0.0,     "fox")

    ndiff = add_diffusion_layer(psi, "Nplus", 0.312,  "fox")
    pdiff = add_diffusion_layer(psi, "Pplus", 0.312,  "fox")

    # FOX:                      name     dielectric_k
    #-----------------------------------------------------------------------------------------------
    add_field_oxide_layer(psi,  "fox",   4.0)

    # METAL:                        name,    z,      thickness
    #-----------------------------------------------------------------------------------------------
    poly = add_metal_layer(psi,     "Poly2", 0.32,   0.2)

    # DIELECTRIC (conformal)        name,   dielectric_k, thickness,   thickness,      thickness  ref
    #                                                     over metal,  where no metal, sidewall
    #-----------------------------------------------------------------------------------------------
    add_conformal_dielectric(psi,   "nit",  7.0,          0.05,        0.05,           0.05,      "Poly2")

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "ild",    4.0,          "nit")

    # METAL:                        name,     z,      thickness
    #-----------------------------------------------------------------------------------------------
    met1 = add_metal_layer(psi,     "Metal1", 1.23,   0.55)

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "imd1",   4.0,          "ild")

    # METAL:                        name,     z,      thickness
    #-----------------------------------------------------------------------------------------------
    met2 = add_metal_layer(psi,     "Metal2", 2.38,   0.55)

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "imd2",   4.0,          "imd1")

    # METAL:                        name,     z,      thickness
    #-----------------------------------------------------------------------------------------------
    met3 = add_metal_layer(psi,     "Metal3", 3.53,   0.55)

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "imd3",   4.0,          "imd2")

    # METAL:                        name,     z,      thickness
    #-----------------------------------------------------------------------------------------------
    met4 = add_metal_layer(psi,     "Metal4", 4.68,   0.55)

    # MIM cap (option B), with the heights of the PDK's KLayout 2.5D view (libs.tech/klayout/tech/d25/gf180mcu.lyd25)
    fusetop_thickness = 0.295
    capild_thickness = 0.042
    capild_k = 9.44  # 1.99 fF/µm² of cap_mim_2f0_m4m5_noshield (the deck's default mim_cap)

    # NOTE: the deck has no layer of its own for the Metal4 under FuseTop (like sky130A's met3_cap),
    #       so for FasterCap the MIM dielectric covers all of Metal4 (2.5D uses the capacitance tables)

    # DIELECTRIC (conformal)        name,     dielectric_k, thickness,        thickness,      thickness, ref
    #                                                       over metal,       where no metal, sidewall
    #-----------------------------------------------------------------------------------------------
    add_conformal_dielectric(psi,   "capild", capild_k,     capild_thickness, 0.0,            0.0,       "Metal4")

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "imd4",   4.0,          "imd3")

    # METAL:                          name,      z,                                         thickness
    #-----------------------------------------------------------------------------------------------
    fusetop = add_metal_layer(psi,    "FuseTop", met4.z + met4.thickness + capild_thickness, fusetop_thickness)

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "imd4b",  4.0,          "imd3")  # same material as imd4, above FuseTop

    # METAL:                        name,     z,      thickness
    #-----------------------------------------------------------------------------------------------
    met5 = add_metal_layer(psi,     "Metal5", 6.13,   1.1925)

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "pass",   4.0,          "imd4")

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "sin",    8.5225,       "pass")

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "air",    1.0,          "sin")

    m1np = ndiff.contact_above
    m1pp = pdiff.contact_above
    m1po = poly.contact_above
    via1 = met1.contact_above
    via2 = met2.contact_above
    via3 = met3.contact_above
    via4 = met4.contact_above
    via4_cap = fusetop.contact_above

    # NOTE: contacts to diffusion start at z = 0, all others at the top of the layer below
    #       width, spacing and border (metal enclosure) are the DRC rules CO.1, CO.2a, CO.6 and Vx.1, Vx.2a, Vx.3b/4a

    # CONTACT:  contact,  name,               layer_below, metal_above, thickness,                            width, spacing, border
    #                     (LVS)
    #--------------------------------------------------------------------------------------------------------------------------------
    set_contact(m1np,     "contact_nsd_con",  "Nplus",     "Metal1",    met1.z,                               0.22,  0.25,    0.005)
    set_contact(m1pp,     "contact_psd_con",  "Pplus",     "Metal1",    met1.z,                               0.22,  0.25,    0.005)
    set_contact(m1po,     "contact_poly_con", "Poly2",     "Metal1",    met1.z - (poly.z + poly.thickness),   0.22,  0.25,    0.005)
    set_contact(via1,     "via1",             "Metal1",    "Metal2",    met2.z - (met1.z + met1.thickness),   0.26,  0.26,    0.01)
    set_contact(via2,     "via2_n_cap",       "Metal2",    "Metal3",    met3.z - (met2.z + met2.thickness),   0.26,  0.26,    0.01)
    set_contact(via3,     "via3_n_cap",       "Metal3",    "Metal4",    met4.z - (met3.z + met3.thickness),   0.26,  0.26,    0.01)
    set_contact(via4,     "via4_n_cap",       "Metal4",    "Metal5",    met5.z - (met4.z + met4.thickness),   0.26,  0.26,    0.01)
    set_contact(via4_cap, "top_via_cap",      "FuseTop",   "Metal5",    met5.z - (fusetop.z + fusetop.thickness), 0.26,  0.26,    0.4)  # MIMTM.4


def build_process_parasitics_info(ex: ProcessParasiticsInfo):
    # See  https://gf180mcu-pdk.readthedocs.io/en/latest/analog/layout/inter_specs/inter_specs_2_1.html
    #      https://gf180mcu-pdk.readthedocs.io/en/latest/analog/spice/elec_specs/elec_specs_5_1.html

    ex.side_halo = 8.0

    ri = ex.resistance

    # https://gf180mcu-pdk.readthedocs.io/en/latest/analog/spice/elec_specs/elec_specs_5_1.html
    # resistance values are in mΩ / square
    #                       layer, resistance, [corner_adjustment_fraction]
    add_layer_resistance(ri, "Poly2",   7300)  # allpolynonres
    add_layer_resistance(ri, "Metal1",   90)
    add_layer_resistance(ri, "Metal2",   90)
    add_layer_resistance(ri, "Metal3",   90)
    add_layer_resistance(ri, "Metal4",   90)
    add_layer_resistance(ri, "Metal5",   40)  # top metal, 11K (gf180mcuD, 5LM)

    # https://gf180mcu-pdk.readthedocs.io/en/latest/analog/spice/elec_specs/elec_specs_5_2.html
    # resistance values are in mΩ / CNT
    #                         contact_layer,  layer_below,  layer_above, resistance
    add_contact_resistance(ri, "contact_nsd_con",  "Nplus",  "Metal1",    6300)
    add_contact_resistance(ri, "contact_psd_con",  "Pplus",  "Metal1",    5200)
    add_contact_resistance(ri, "contact_poly_con", "Poly2",  "Metal1",    5900)

    # https://gf180mcu-pdk.readthedocs.io/en/latest/analog/spice/elec_specs/elec_specs_5_2.html
    # resistance values are in mΩ / CNT
    #                     via_layer,  resistance
    add_via_resistance(ri, "Via1",          4500)
    add_via_resistance(ri, "Via2",          4500)
    add_via_resistance(ri, "Via3",          4500)
    add_via_resistance(ri, "Via4",          4500)

    ci = ex.capacitance

    #                    layer,      area_cap,  perimeter_cap
    # add_substrate_cap(ci, "dnwell", 120.0,     0.0)  # TODO
    add_substrate_cap(ci, "Poly2",    110.67,    50.72)
    add_substrate_cap(ci, "Metal1",   29.304,    39.431)
    add_substrate_cap(ci, "Metal2",   15.016,    33.298)
    add_substrate_cap(ci, "Metal3",   10.094,    30.021)
    add_substrate_cap(ci, "Metal4",   7.602,     28.153)
    add_substrate_cap(ci, "Metal5",   5.798,     30.386)

    diff_nonfet = "COMP"   # TODO: diff must be non-fet!
    poly_nonres = "Poly2"  # TODO: poly must be non-res!
    all_active = "COMP"    # TODO: must be allactive

    #                  top_layer,  bottom_layer,  cap
    # add_overlap_cap(ci, "LVPWELL", "dnwell",   120.0)  # TODO
    add_overlap_cap(ci, "Poly2",     "Nwell",        110.67)
    add_overlap_cap(ci, "Poly2",     "LVPWELL",      110.67)
    add_overlap_cap(ci, "Metal1",    "LVPWELL",      29.304)
    add_overlap_cap(ci, "Metal1",    "Nwell",        29.304)
    add_overlap_cap(ci, "Metal1",    diff_nonfet,    30.502)  # TODO: lv vs mv?
    add_overlap_cap(ci, "Metal1",    "Poly2",        51.434)
    add_overlap_cap(ci, "Metal2",    "LVPWELL",      15.016)
    add_overlap_cap(ci, "Metal2",    "Nwell",        15.016)
    add_overlap_cap(ci, "Metal2",    diff_nonfet,    17.305)  # TODO: lv vs mv?
    add_overlap_cap(ci, "Metal2",    poly_nonres,    19.263)
    add_overlap_cap(ci, "Metal2",    "Metal1",       59.027)
    add_overlap_cap(ci, "Metal3",    "Nwell",        10.094)
    add_overlap_cap(ci, "Metal3",    "LVPWELL",      10.094)
    add_overlap_cap(ci, "Metal3",    diff_nonfet,    11.079)  # TODO: lv vs mv?
    add_overlap_cap(ci, "Metal3",    poly_nonres,    11.85)
    add_overlap_cap(ci, "Metal3",    "Metal1",       20.238)
    add_overlap_cap(ci, "Metal3",    "Metal2",       59.027)
    add_overlap_cap(ci, "Metal4",    "Nwell",        7.602)
    add_overlap_cap(ci, "Metal4",    "LVPWELL",      7.602)
    add_overlap_cap(ci, "Metal4",    all_active,     8.148)
    add_overlap_cap(ci, "Metal4",    poly_nonres,    8.557)
    add_overlap_cap(ci, "Metal4",    "Metal1",       12.212)
    add_overlap_cap(ci, "Metal4",    "Metal2",       20.238)
    add_overlap_cap(ci, "Metal4",    "Metal3",       59.027)
    add_overlap_cap(ci, "Metal5",    "Nwell",        5.798)
    add_overlap_cap(ci, "Metal5",    "LVPWELL",      5.798)
    add_overlap_cap(ci, "Metal5",    all_active,     6.11)
    add_overlap_cap(ci, "Metal5",    poly_nonres,    6.337)
    add_overlap_cap(ci, "Metal5",    "Metal1",       8.142)
    add_overlap_cap(ci, "Metal5",    "Metal2",       11.067)
    add_overlap_cap(ci, "Metal5",    "Metal3",       17.276)
    add_overlap_cap(ci, "Metal5",    "Metal4",       39.351)

    #                   layer_name, cap,     offset
    add_sidewall_cap(ci, "Poly2",    11.098, -0.082)
    add_sidewall_cap(ci, "Metal1",   40.512, -0.053)
    add_sidewall_cap(ci, "Metal2",   46.736,  0.289)
    add_sidewall_cap(ci, "Metal3",   70.675,  0.534)
    add_sidewall_cap(ci, "Metal4",   77.388,  0.611)
    add_sidewall_cap(ci, "Metal5",   114.86,  0.025)

    #                           in_layer,    out_layer,   cap
    add_sidewall_overlap_cap(ci, "Poly2",     "Nwell",     50.72)
    add_sidewall_overlap_cap(ci, "Poly2",     "LVPWELL",   50.72)
    add_sidewall_overlap_cap(ci, "Metal1",    "Nwell",     39.431)
    add_sidewall_overlap_cap(ci, "Metal1",    "LVPWELL",   39.431)
    add_sidewall_overlap_cap(ci, "Metal1",    diff_nonfet, 43.406)  # TODO: lv vs mv?
    add_sidewall_overlap_cap(ci, "Metal1",    poly_nonres, 46.700)
    add_sidewall_overlap_cap(ci, "Poly2",     "Metal1",    17.946)
    add_sidewall_overlap_cap(ci, "Metal2",    "Nwell",     33.298)
    add_sidewall_overlap_cap(ci, "Metal2",    "LVPWELL",   33.298)
    add_sidewall_overlap_cap(ci, "Metal2",    diff_nonfet, 35.189)  # TODO: lv vs mv?
    add_sidewall_overlap_cap(ci, "Metal2",    poly_nonres, 36.169)
    add_sidewall_overlap_cap(ci, "Poly2",     "Metal2",    8.706)
    add_sidewall_overlap_cap(ci, "Metal2",    "Metal1",    47.566)
    add_sidewall_overlap_cap(ci, "Metal1",    "Metal2",    32.048)
    add_sidewall_overlap_cap(ci, "Metal3",    "Nwell",     30.021)
    add_sidewall_overlap_cap(ci, "Metal3",    "LVPWELL",   30.021)
    add_sidewall_overlap_cap(ci, "Metal3",    diff_nonfet, 31.40)  # TODO: lv vs mv?
    add_sidewall_overlap_cap(ci, "Metal3",    poly_nonres, 31.927)
    add_sidewall_overlap_cap(ci, "Poly2",     "Metal3",    5.895)
    add_sidewall_overlap_cap(ci, "Metal3",    "Metal1",    36.609)
    add_sidewall_overlap_cap(ci, "Metal1",    "Metal3",    18.135)
    add_sidewall_overlap_cap(ci, "Metal3",    "Metal2",    49.011)
    add_sidewall_overlap_cap(ci, "Metal2",    "Metal3",    36.626)
    add_sidewall_overlap_cap(ci, "Metal4",    "Nwell",     28.153)
    add_sidewall_overlap_cap(ci, "Metal4",    "LVPWELL",   28.153)
    add_sidewall_overlap_cap(ci, "Metal4",    diff_nonfet, 29.065)
    add_sidewall_overlap_cap(ci, "Metal4",    poly_nonres, 29.407)
    add_sidewall_overlap_cap(ci, "Poly2",     "Metal4",    8.557)
    add_sidewall_overlap_cap(ci, "Metal4",    "Metal1",    32.104)
    add_sidewall_overlap_cap(ci, "Metal1",    "Metal4",    13.159)
    add_sidewall_overlap_cap(ci, "Metal4",    "Metal2",    36.563)
    add_sidewall_overlap_cap(ci, "Metal2",    "Metal4",    22.405)
    add_sidewall_overlap_cap(ci, "Metal4",    "Metal3",    47.871)
    add_sidewall_overlap_cap(ci, "Metal3",    "Metal4",    39.964)
    add_sidewall_overlap_cap(ci, "Metal5",    "Nwell",     30.386)
    add_sidewall_overlap_cap(ci, "Metal5",    "LVPWELL",   30.386)
    add_sidewall_overlap_cap(ci, "Metal5",    diff_nonfet, 31.165)
    add_sidewall_overlap_cap(ci, "Metal5",    poly_nonres, 31.458)
    add_sidewall_overlap_cap(ci, "Poly2",     "Metal5",    3.365)
    add_sidewall_overlap_cap(ci, "Metal5",    "Metal1",    33.316)
    add_sidewall_overlap_cap(ci, "Metal1",    "Metal5",    9.825)
    add_sidewall_overlap_cap(ci, "Metal5",    "Metal2",    36.591)
    add_sidewall_overlap_cap(ci, "Metal2",    "Metal5",    15.764)
    add_sidewall_overlap_cap(ci, "Metal5",    "Metal3",    41.466)
    add_sidewall_overlap_cap(ci, "Metal3",    "Metal5",    22.988)
    add_sidewall_overlap_cap(ci, "Metal5",    "Metal4",    52.692)
    add_sidewall_overlap_cap(ci, "Metal4",    "Metal5",    34.954)

    # MIM cap, c_cox 1.99e-3 F/m² and c_capsw 2.383e-10 F/m of the device model
    # cap_mim_2f0_m4m5_noshield (sm141064_mim.ngspice), the deck's default mim_cap
    #
    #              top_plate, bottom_plate, area_cap, perimeter_cap
    add_mim_cap(ci, "FuseTop", "Metal4",     1990.0,   238.3)


def build_device_models_info(dmi: DeviceModelsInfo):
    # NOTE: the ngspice models (sm141064.ngspice) take parameters in SI units,
    #       while the LVS device classes store lengths in µm (and areas in µm²).
    #       The terminal order of each model is the one of the LVS netlist reader,
    #       i.e. KLayout's standard one (see rule_decks/custom_classes.lvs)
    um = 1e-6
    um2 = 1e-12

    # the corners (e.g. typical) define all MOS as subcircuits (section fets_mm)
    #
    #     NOTE: the 10V asymmetric MOS are in smbb000149.ngspice, a simulation needs to include it itself
    mos = [lvs_param('l', 'L', um), lvs_param('w', 'W', um),
           lvs_param('as', 'AS', um2), lvs_param('ad', 'AD', um2),
           lvs_param('ps', 'PS', um), lvs_param('pd', 'PD', um)]
    for fet in ('nfet_03v3', 'nfet_03v3_dss', 'nfet_05v0', 'nfet_06v0', 'nfet_06v0_dss', 'nfet_06v0_nvt', 'nfet_10v0_asym',
                'pfet_03v3', 'pfet_03v3_dss', 'pfet_05v0', 'pfet_06v0', 'pfet_06v0_dss', 'pfet_10v0_asym'):
        add_device_model_mapping(dmi, fet, "X", ["D", "G", "S", "B"], mos)

    for diode in ('diode_nd2ps_03v3', 'diode_nd2ps_06v0', 'diode_nw2ps_03v3', 'diode_nw2ps_06v0',
                  'diode_pd2nw_03v3', 'diode_pd2nw_06v0', 'sc_diode'):
        add_device_model_mapping(dmi, diode, "D", ["A", "C"],
                                 [lvs_param('area', 'A', um2), lvs_param('pj', 'P', um)])

    # BJTs of a fixed size, NE is the number of devices
    for npn in ('npn_00p54x02p00', 'npn_00p54x04p00', 'npn_00p54x08p00', 'npn_00p54x16p00',
                'npn_05p00x05p00', 'npn_10p00x10p00'):
        add_device_model_mapping(dmi, npn, "X", ["C", "B", "E", "S"], [lvs_param('m', 'NE')])
    for pnp in ('pnp_05p00x00p42', 'pnp_05p00x05p00', 'pnp_10p00x00p42', 'pnp_10p00x10p00'):
        add_device_model_mapping(dmi, pnp, "X", ["C", "B", "E"], [lvs_param('m', 'NE')])

    res = [lvs_param('r_width', 'W', um), lvs_param('r_length', 'L', um)]
    for resistor in ('nplus_s', 'nplus_u', 'pplus_s', 'pplus_u', 'npolyf_s', 'npolyf_u', 'ppolyf_s', 'ppolyf_u',
                     'ppolyf_u_1k', 'ppolyf_u_1k_6p0', 'nwell'):
        add_device_model_mapping(dmi, resistor, "X", ["A", "B", "W"], res)
    for resistor in ('rm1', 'rm2', 'rm3', 'rm4', 'tm11k'):
        add_device_model_mapping(dmi, resistor, "X", ["A", "B"], res)
    add_device_model_mapping(dmi, "efuse", "X", ["A", "B"], [])  # unblown

    # MIM caps, the top plate (B, FuseTop) first, and MOS caps, the gate (A) first
    #
    #     NOTE: LVS extracts the area and perimeter, the models take c_width and c_length,
    #           but depend on c_width*c_length and c_width+c_length only.
    #           gf180mcuD has its MIM caps between Metal4 and Metal5 (MIM option B, 5 metal layers)
    cap = lvs_area_perimeter_params('c_width', 'c_length', 'A', 'P', um)
    for mim in ('1f0', '1f5', '2f0'):
        add_device_model_mapping(dmi, f"cap_mim_{mim}fF", "X", ["B", "A"], cap, f"cap_mim_{mim}_m4m5_noshield")
    for mos_cap in ('cap_nmos_03v3', 'cap_nmos_03v3_b', 'cap_nmos_06v0', 'cap_nmos_06v0_b',
                    'cap_pmos_03v3', 'cap_pmos_03v3_b', 'cap_pmos_06v0', 'cap_pmos_06v0_b'):
        add_device_model_mapping(dmi, mos_cap, "X", ["A", "B"], cap)

    # NOTE: no device model mapping (yet), a netlist with these devices is an error:
    #       - nfet_05v0_dss, pfet_05v0_dss, diode_dw2ps_*, diode_pw2dw_*, pwell,
    #         cap_nmos_*_dn, cap_pmos_*_dn (only with CONSIDER_DN_DW_FEATURES): no ngspice models


def build_substrate_info(si: SubstrateInfo):
    # NOTE: substrate_connections.lvs connects the substrate and the p-taps outside the isolated substrate
    #       (ptap_regular) to the global net SUB
    si.net_names.append("SUB")
    si.lvs_layer_names.append("ptap_regular")


def build_tech() -> Technology:
    tech = Technology(name="gf180mcuD")

    build_layers(tech)

    build_lvs_computed_layers(tech)

    build_process_stack_info(tech.process_stack)

    build_process_parasitics_info(tech.process_parasitics)

    build_device_models_info(tech.device_models)

    build_substrate_info(tech.substrate)

    return tech
