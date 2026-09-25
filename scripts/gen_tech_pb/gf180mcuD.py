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

    #               purpose, name,      drw_gds,  pin_gds,  label_gds, description
    add_layer(tech, DNWELL,  "DNWELL",  (12, 0),  None,     None,      "Deep N-well")
    add_layer(tech, NWELL,   "Nwell",   (21, 0),  None,     None,      "N-well region")
    add_layer(tech, DIFF,    "COMP",    (22, 0),  None,     (22, 10),  "Diffusion for device and interconnect")
    # add_layer(tech, N_P_TAP, "tap",   (65, 44), None,     None,      "Active (diffusion) area (type equal to the well/substrate underneath) (i.e., N+ and P+)")
    add_layer(tech, PIMP,    "Pplus",   (31, 0),  None,     None,      "P+ source/drain implant")
    add_layer(tech, NIMP,    "Nplus",   (32, 0),  None,     None,      "N+ source/drain implant")
    add_layer(tech, METAL,   "Poly2",   (30, 0),  None,     (30, 10),  "Polysilicon gate & interconnect")
    add_layer(tech, CONT,    "Contact", (33, 0),  None,     None,      "Contact to local interconnect")
    add_layer(tech, METAL,   "Metal1",  (34, 0),  None,     (34, 10),  "Metal 1 interconnect")
    add_layer(tech, VIA,     "Via1",    (35, 0),  None,     None,      "Contact from Metal1 to Metal2")
    add_layer(tech, METAL,   "Metal2",  (36, 0),  None,     (36, 10),  "Metal 2 interconnect")
    add_layer(tech, VIA,     "Via2",    (38, 0),  None,     None,      "Contact from Metal2 to Metal3")
    add_layer(tech, METAL,   "Metal3",  (42, 0),  None,     (42, 10),  "Metal 3 interconnect")
    add_layer(tech, VIA,     "Via3",    (40, 0),  None,     None,      "Contact from Metal3 to Metal4")
    add_layer(tech, METAL,   "Metal4",  (46, 0),  None,     (46, 10),  "Metal 4 interconnect")
    add_layer(tech, VIA,     "Via4",    (41, 0),  None,     None,      "Contact from Metal4 to Metal5")
    add_layer(tech, MIM,     "FuseTop", (75, 0),  None,     None,      "MiM capacitor plate over Metal5")
    add_layer(tech, METAL,   "Metal5",  (81, 0),  None,     (81, 10),  "Metal 5 interconnect")


def build_lvs_computed_layers(tech: Technology):
    #                        purpose  kind  lvs_name       lvs_gds_pair orig. layer  description
    add_computed_layer(tech, DNWELL,  KREG, "dnwell",      (12, 0),     "DNWELL",    "Deep NWell")
    add_computed_layer(tech, NWELL,   KREG, "Nwell",       (21, 0),     "Nwell",     "NWell")
    add_computed_layer(tech, NIMP,    KREG, "nsd",         (32, 44),    "Nplus",     "borrow from nsdm")
    add_computed_layer(tech, PIMP,    KREG, "psd",         (31, 20),    "Pplus",     "borrow from psdm")
    add_computed_layer(tech, NTAP,    KREG, "ntap_conn",   (65, 144),   "tap",       "Separate ntap, original tap is 65,44, we need seperate ntap/ptap")
    add_computed_layer(tech, PTAP,    KREG, "ptap_conn",   (65, 244),   "tap",       "Separate ptap, original tap is 65,44, we need seperate ntap/ptap")
    add_computed_layer(tech, METAL,   KREG, "poly_con",    (30, 0),     "Poly2",     "Computed layer for poly")
    add_computed_layer(tech, METAL,   KREG, "metal1_con",  (34, 0),     "Metal1",    "Computed layer for met1")
    add_computed_layer(tech, METAL,   KREG, "metal2_con",  (36, 0),     "Metal2",    "Computed layer for met2")
    add_computed_layer(tech, METAL,   KREG, "metal3_con",  (42, 0),     "Metal3",    "Computed layer for met3 (no cap)")
    add_computed_layer(tech, METAL,   KREG, "metal4_con",  (46, 0),     "Metal4",    "Computed layer for met4 (no cap)")
    add_computed_layer(tech, METAL,   KREG, "metal5_con",  (81, 0),     "MetalTop",  "Computed layer for met5")
    add_computed_layer(tech, CONT,    KREG, "m1_nsd_con",  (66, 4401),  "Contact",   "Computed layer for contact from nsdm to Metal1")
    add_computed_layer(tech, CONT,    KREG, "m1_psd_con",  (66, 4402),  "Contact",   "Computed layer for contact from psdm to Metal1")
    add_computed_layer(tech, CONT,    KREG, "m1_poly_con", (66, 4403),  "Contact",   "Computed layer for contact from poly to Metal1")
    # add_computed_layer(tech, VIA,   KREG, "via1_con",    (35, 44),    "Via1",      "Computed layer for contact between met1 and met2")
    # add_computed_layer(tech, VIA,   KREG, "via2_con",    (38, 44),    "Via2",      "Computed layer for contact between met2 and met3")
    add_computed_layer(tech, VIA,     KREG, "via3_n_cap",  (40, 144),   "Via3",      "Computed layer for via3 (no MIM cap)")
    add_computed_layer(tech, VIA,     KREG, "via4_n_cap",  (41, 144),   "Via4",      "Computed layer for via4 (no MIM cap)")

    # NOTE: for CC whiteboxing to work,
    #       we must ensure all VPP/MIM metal layers map to the same GDS pair as the non-cap versions,
    #       to ensure they are be merged
    #
    #       for R mode, MIM cap vias should point to a different GDS number than the regular via
    #       as they have different resistances
    # add_computed_layer(tech, VIA,   KCAP, "via3_cap",    (70, 244),   "via3",      "Computed layer for via3 (with MIM cap)")
    # add_computed_layer(tech, VIA,   KCAP, "via4_cap",    (71, 244),   "via4",      "Computed layer for via4 (with MIM cap)")
    # add_computed_layer(tech, METAL, KCAP, "met3_cap",    (70, 20),    "Metal4",    "metal3 part of MiM cap")
    # add_computed_layer(tech, METAL, KCAP, "met4_cap",    (71, 20),    "Metal5",    "metal4 part of MiM cap")
    # add_computed_layer(tech, MIM,   KCAP, "capm",        (89, 44),    "capm",      "MiM cap above metal3")
    # add_computed_layer(tech, MIM,   KCAP, "capm2",       (97, 44),    "capm2",     "MiM cap above metal4")
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

    add_computed_layer(tech, METAL,   KLBL, "comp_label",   (30, 10),   "COMP_label",   "LABEL drawn at diffusion layer")
    add_computed_layer(tech, METAL,   KLBL, "Poly2_Label",  (30, 10),   "Poly2_label",  "LABEL drawn at poly2 layer")
    add_computed_layer(tech, METAL,   KLBL, "metal1_Label", (34, 10),   "Metal1_label", "LABEL drawn at Metal1 layer")
    add_computed_layer(tech, METAL,   KLBL, "metal2_Label", (36, 10),   "Metal2_label", "LABEL drawn at Metal2 layer")
    add_computed_layer(tech, METAL,   KLBL, "metal3_Label", (42, 10),   "Metal3_label", "LABEL drawn at Metal3 layer")
    add_computed_layer(tech, METAL,   KLBL, "metal4_Label", (46, 10),   "Metal4_label", "LABEL drawn at Metal4 layer")
    add_computed_layer(tech, METAL,   KLBL, "metal5_Label", (81, 10),   "Metal5_label", "LABEL drawn at Metal5 layer")


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

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "imd4",   4.0,          "imd3")

    # METAL:                        name,     z,      thickness
    #-----------------------------------------------------------------------------------------------
    add_metal_layer(psi,            "Metal5", 6.13,   1.1925)

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "pass",   4.0,          "imd4")

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "sin",    8.5225,       "pass")

    # DIELECTRIC (simple)        name,     dielectric_k, ref
    #-----------------------------------------------------------------------------------------------
    add_simple_dielectric(psi,   "air",    8.5225,       "sin")

    m1np = ndiff.contact_above
    m1pp = pdiff.contact_above
    m1po = poly.contact_above
    via1 = met1.contact_above
    via2 = met2.contact_above
    via3 = met3.contact_above
    via4 = met4.contact_above

    # TODO! via sizes and thicknesses!!!

    # CONTACT:  contact,  name,         layer_below, metal_above, thickness,               width, spacing, border
    #                     (LVS)         (LVS)        (LVS)
    #-------------------------------------------------------------------------------------------------------------
    set_contact(m1np,     "M1-Nplus",   "Nplus",     "Metal1",    0.9361,                  0.22,  0.17,    0.0)
    set_contact(m1pp,     "M1-Pplus",   "Pplus",     "Metal1",    0.9361,                  0.22,  0.17,    0.0)
    set_contact(m1po,     "M1-Poly",    "Poly2",     "Metal1",    0.4299,                  0.22,  0.17,    0.0)
    set_contact(via1,     "Via1_con",   "Metal1",    "Metal2",    1.3761 - (0.9361 + 0.1), 0.26,  0.19,    0.0)
    set_contact(via2,     "Via2_con",   "Metal2",    "Metal3",    0.27,                    0.26,  0.17,    0.055)
    set_contact(via3,     "Via3_con",   "Metal3",    "Metal4",    0.42,                    0.26,  0.20,    0.04)
    set_contact(via4,     "Via4_ncap",  "Metal4",    "Metal5",    0.505,                   0.26,  0.80,    0.19)


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
    add_layer_resistance(ri, "Metal5",   90)
    add_layer_resistance(ri, "MetalTop", 40)  # TODO: there are options 9kA/6kA/11kA/30kA

    # https://gf180mcu-pdk.readthedocs.io/en/latest/analog/spice/elec_specs/elec_specs_5_2.html
    # resistance values are in mΩ / CNT
    #                         contact_layer,  layer_below,  layer_above, resistance
    add_contact_resistance(ri, "M1-Nplus",     "Nplus",      "Metal1",    6300)
    add_contact_resistance(ri, "M1-Pplus",     "Pplus",      "Metal1",    5200)
    add_contact_resistance(ri, "M1-Poly",      "Poly2",      "Metal1",    5900)

    # https://gf180mcu-pdk.readthedocs.io/en/latest/analog/spice/elec_specs/elec_specs_5_2.html
    # resistance values are in mΩ / CNT
    #                     via_layer,  resistance
    add_via_resistance(ri, "M1-Poly",       5900)
    add_via_resistance(ri, "Via1",          4500)
    add_via_resistance(ri, "Via2",          4500)
    add_via_resistance(ri, "Via3",          4500)
    add_via_resistance(ri, "Via4",          4500)
    add_via_resistance(ri, "Via5",          4500)

    ci = ex.capacitance

    #                    layer,      area_cap,  perimeter_cap
    # add_substrate_cap(ci, "dnwell", 120.0,     0.0)  # TODO
    add_substrate_cap(ci, "Poly2",    110.67,    50.72)
    add_substrate_cap(ci, "Metal1",   29.304,    39.431)
    add_substrate_cap(ci, "Metal2",   15.016,    33.298)
    add_substrate_cap(ci, "Metal3",   10.094,    30.021)
    add_substrate_cap(ci, "Metal4",   7.602,     28.153)
    add_substrate_cap(ci, "Metal5",   5.798,     30.386)
    add_substrate_cap(ci, "MetalTop", 6.32,      38.85)

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
    add_sidewall_overlap_cap(ci, "Metal4",    "LVPWELL",   40.99)
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


def build_tech() -> Technology:
    tech = Technology(name="gf180mcuD")

    build_layers(tech)

    build_lvs_computed_layers(tech)

    build_process_stack_info(tech.process_stack)

    build_process_parasitics_info(tech.process_parasitics)

    return tech
