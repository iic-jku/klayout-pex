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
This creates a technology definition example for IHP sg13g2 (and its variant sg13cmos5l):

See page5 of
https://github.com/IHP-GmbH/IHP-Open-PDK/blob/main/ihp-sg13g2/libs.doc/doc/SG13G2_os_process_spec.pdf
and https://github.com/IHP-GmbH/IHP-Open-PDK/blob/main/ihp-sg13g2/libs.tech/openems/testcase/SG13_Octagon_L2n0/OpenEMS_Python/Using%20OpenEMS%20Python%20with%20IHP%20SG13G2%20v1.1.pdf
"""
from __future__ import annotations

from enum import Enum

from tech_builder import *


class LayerStackVariant(Enum):
    # value: tech name
    SG13G2 = "ihp-sg13g2"
    SG13CMOS5L = "ihp-sg13cmos5l"


class TechBuilder:
    def __init__(self, variant: LayerStackVariant):
        self.variant = variant

    @property
    def is_g2(self) -> bool:
        return self.variant == LayerStackVariant.SG13G2

    def build_layers(self, tech: Technology):
        #               purpose   name         drw_gds,   pin_gds,   label_gds,  description
        add_layer(tech, DIFF,     "Activ",     (1, 0),    (1, 2),    None,       "Active (diffusion) area")  # ~ diff.drawing
        add_layer(tech, NWELL,    "NWell",     (31, 0),   (31, 2),   None,       "N-well region")
        add_layer(tech, PWELL,    "PWell",     (46, 0),   (46, 2),   None,       "P-well region")
        add_layer(tech, NIMP,     "nSD",       (7, 0),    None,      None,       "Defines areas to receive N+ S/D implant")
        add_layer(tech, PIMP,     "pSD",       (14, 0),   None,      None,       "Defines areas to receive P+ S/D implant")
        add_layer(tech, METAL,    "GatPoly",   (5, 0),    (5, 2),    (5, 25),    "Poly")  # ~ poly.drawing
        add_layer(tech, CONT,     "Cont",      (6, 0),    None,      None,       "Defines 1-st metal contacts to Activ, GatPoly")
        add_layer(tech, METAL,    "Metal1",    (8, 0),    (8, 2),    (8, 25),    "Defines 1-st metal interconnect")
        add_layer(tech, VIA,      "Via1",      (19, 0),   None,      None,       "Defines 1-st metal to 2-nd metal contact")
        add_layer(tech, METAL,    "Metal2",    (10, 0),   (10, 2),   (10, 25),   "Defines 2-nd metal interconnect")
        add_layer(tech, VIA,      "Via2",      (29, 0),   None,      None,       "Defines 2-nd metal to 3-rd metal contact")
        add_layer(tech, METAL,    "Metal3",    (30, 0),   (30, 2),   (30, 25),   "Defines 3-rd metal interconnect")
        add_layer(tech, VIA,      "Via3",      (49, 0),   None,      None,       "Defines 3-rd metal to 4-th metal contact")
        add_layer(tech, METAL,    "Metal4",    (50, 0),   (50, 2),   (50, 25),   "Defines 4-th metal interconnect")

        if self.is_g2:
            add_layer(tech, VIA,      "Via4",      (66, 0),   None,      None,       "Defines 4-th metal to 5-th metal contact")
            add_layer(tech, METAL,    "Metal5",    (67, 0),   (67, 2),   (67, 25),   "Defines 5-th metal interconnect")
            add_layer(tech, MIM,      "MIM",       (36, 0),   None,      None,       "MiM capacitor top plate over Metal5")

        add_layer(tech, VIA,      "TopVia1",   (125, 0),  None,      None,       "Defines 3-rd (or 5-th) metal to TopMetal1 contact")
        add_layer(tech, METAL,    "TopMetal1", (126, 0),  (126, 2),  (126, 25),  "Defines 1-st thick TopMetal layer")

        if self.is_g2:
            add_layer(tech, VIA,      "TopVia2",   (133, 0),  None,      None,       "Defines via between TopMetal1 and TopMetal2")
            add_layer(tech, METAL,    "TopMetal2", (134, 0),  (134, 2),  (134, 25),  "Defines 2-nd thick TopMetal layer")

    def build_lvs_computed_layers(self, tech: Technology):
        #                        purpose kind  lvs_name         lvs_gds_pair  orig. layer  description
        add_computed_layer(tech, PWELL, KREG, "pwell",          (46, 0),      "PWell",     "Computed layer for PWell")
        add_computed_layer(tech, PWELL, KREG, "pwell_sub",      (46, 0),      "PWell",     "Computed layer for PWell")
        add_computed_layer(tech, NWELL, KREG, "nwell_drw",      (31, 0),      "NWell",     "Computed layer for NWell")
        add_computed_layer(tech, NIMP,  KREG, "nsd_fet",        (7, 0),       "nSD",       "Computed layer for nSD")
        add_computed_layer(tech, PIMP,  KREG, "psd_fet",        (14, 0),      "pSD",       "Computed layer for pSD")
        add_computed_layer(tech, NTAP,  KREG, "ntap",           (65, 144),    "Activ",     "Computed layer for ntap")
        add_computed_layer(tech, PTAP,  KREG, "ptap",           (65, 244),    "Activ",     "Computed layer for ptap")

        add_computed_layer(tech, METAL, KREG, "poly_con",       (5, 0),       "GatPoly",   "Computed layer for GatPoly")
        add_computed_layer(tech, METAL, KREG, "metal1_con",     (8, 0),       "Metal1",    "Computed layer for Metal1")
        add_computed_layer(tech, METAL, KREG, "metal2_con",     (10, 0),      "Metal2",    "Computed layer for Metal2")
        add_computed_layer(tech, METAL, KREG, "metal3_con",     (30, 0),      "Metal3",    "Computed layer for Metal3")
        add_computed_layer(tech, METAL, KREG, "metal4_con",     (50, 0),      "Metal4",    "Computed layer for Metal4")

        if self.is_g2:
            add_computed_layer(tech, METAL, KREG, "metal5_n_cap",   (67, 0),      "Metal5",    "Computed layer for Metal5 (case where no MiM cap)")

        add_computed_layer(tech, METAL, KREG, "topmetal1_con",  (126, 0),     "TopMetal1", "Computed layer for TopMetal1")

        if self.is_g2:
            add_computed_layer(tech, METAL, KREG, "topmetal2_con",  (134, 0),     "TopMetal2", "Computed layer for TopMetal2")

        add_computed_layer(tech, CONT,  KREG, "cont_nsd_con",   (6, 4401),    "Cont",      "Computed layer for contact from nSD to Metal1")
        add_computed_layer(tech, CONT,  KREG, "cont_psd_con",   (6, 4402),    "Cont",      "Computed layer for contact from pSD to Metal1")
        add_computed_layer(tech, CONT,  KREG, "cont_poly_con",  (6, 4403),    "Cont",      "Computed layer for contact from GatPoly to Metal1")

        add_computed_layer(tech, VIA,   KREG, "via1_drw",       (19, 0),      "Via1",      "Computed layer for Via1")
        add_computed_layer(tech, VIA,   KREG, "via2_drw",       (29, 0),      "Via2",      "Computed layer for Via2")
        add_computed_layer(tech, VIA,   KREG, "via3_drw",       (49, 0),      "Via3",      "Computed layer for Via3")

        if self.is_g2:
            add_computed_layer(tech, VIA,   KREG, "via4_drw",       (66, 0),      "Via4",      "Computed layer for Via4")

        add_computed_layer(tech, VIA,   KREG, "topvia1_n_cap",  (125, 0),     "TopVia1",   "Original TopVia1 is 125/0 (case where no MiM cap)")

        if self.is_g2:
            add_computed_layer(tech, VIA,   KREG, "topvia2_drw",    (133, 0),     "TopVia2",   "Computed layer for TopVia2")

        # NOTE: for CC whiteboxing to work,
        #       we must ensure all VPP/MIM metal layers map to the same GDS pair as the non-cap versions,
        #       to ensure they are be merged
        #
        #       for R mode, MIM cap vias should point to a different GDS number than the regular via
        #       as they have different resistances

        if self.is_g2:
            add_computed_layer(tech, VIA,   KCAP, "mim_via",        (125, 10),    "TopVia1",   "Original TopVia1 is 125/0, case MiM cap")
            add_computed_layer(tech, MIM,   KCAP, "metal5_cap",     (67, 0),      "Metal5",    "Computed layer for Metal5, case MiM cap")
            add_computed_layer(tech, MIM,   KCAP, "cmim_top",       (36, 0),      "MIM",       "Computed layer for MiM cap above Metal5")

        # NOTE: there are no existing SPICE models for MOM caps (as was with sky130A)
        #       otherwise they should also be declared as ComputedLayerInfo.KIND_DEVICE_CAPACITOR
        #       and extracted accordingly in the LVS script, to allow blackboxing

        add_computed_layer(tech, METAL, KPIN, "poly_pin_con",       (5, 2),    "GatPoly.pin",    "Poly pin")
        add_computed_layer(tech, METAL, KPIN, "metal1_pin_con",     (8, 2),    "Metal1.pin",     "Metal1 pin")
        add_computed_layer(tech, METAL, KPIN, "metal2_pin_con",     (10, 2),   "Metal2.pin",     "Metal2 pin")
        add_computed_layer(tech, METAL, KPIN, "metal3_pin_con",     (30, 2),   "Metal3.pin",     "Metal3 pin")
        add_computed_layer(tech, METAL, KPIN, "metal4_pin_con",     (50, 2),   "Metal4.pin",     "Metal4 pin")

        if self.is_g2:
            add_computed_layer(tech, METAL, KPIN, "metal5_pin_con",     (67, 2),   "Metal5.pin",     "Metal5 pin")

        add_computed_layer(tech, METAL, KPIN, "topmetal1_pin_con",  (126, 2),  "TopMetal1.pin",  "TopMetal1 pin")

        if self.is_g2:
            add_computed_layer(tech, METAL, KPIN, "topmetal2_pin_con",  (134, 2),  "TopMetal2.pin",  "TopMetal2 pin")

        add_computed_layer(tech, METAL, KLBL, "poly_text",          (5, 25),   "GatPoly.text",   "Poly label")
        add_computed_layer(tech, METAL, KLBL, "metal1_text",        (8, 25),   "Metal1.text",    "Metal1 label")
        add_computed_layer(tech, METAL, KLBL, "metal2_text",        (10, 25),  "Metal2.text",    "Metal2 label")
        add_computed_layer(tech, METAL, KLBL, "metal3_text",        (30, 25),  "Metal3.text",    "Metal3 label")
        add_computed_layer(tech, METAL, KLBL, "metal4_text",        (50, 25),  "Metal4.text",    "Metal4 label")

        if self.is_g2:
            add_computed_layer(tech, METAL, KLBL, "metal5_text",        (67, 25),  "Metal5.text",    "Metal5 label")
        add_computed_layer(tech, METAL, KLBL, "topmetal1_text",     (126, 25), "TopMetal1.text", "TopMetal1 label")
        if self.is_g2:
            add_computed_layer(tech, METAL, KLBL, "topmetal2_text",     (134, 25), "TopMetal2.text", "TopMetal2 label")

    def build_process_stack_info(self, psi: ProcessStackInfo):
        # SUBSTRATE:              name    height   thickness         reference
        #                                          (below height 0)
        #-----------------------------------------------------------------------------------------------
        add_substrate_layer(psi, "subs",  0.0,     0.28,             "fox")

        # NWELL/DIFF:                    name     z        ref
        #                                         (TODO)
        #-----------------------------------------------------------------------------------------------
        add_nwell_layer(psi,             "ntap",  0.0,     "fox")

        ndiff = add_diffusion_layer(psi, "nSD",   0.0,     "fox")
        pdiff = add_diffusion_layer(psi, "pSD",   0.0,     "fox")

        # FOX:                      name     dielectric_k
        #-----------------------------------------------------------------------------------------------
        add_field_oxide_layer(psi,  "fox",   3.95)  # from SG13G2_os_process_spec.pdf p6

        capild_k = 6.7  # to match design sg13g2__pr.gds/cmim to 74.62fF
        capild_thickness = 0.04

        poly_z = 0.4

        poly_thickness = 0.16
        met1_thickness = 0.42
        met2_thickness = 0.49
        met3_thickness = 0.49
        met4_thickness = 0.49
        met5_thickness = 0.49
        cmim_cap_thickness = 0.15
        topmet1_thickness = 2.0
        topmet2_thickness = 3.0

        conp_thickness = 0.64 - poly_thickness
        via1_thickness = 0.54
        via2_thickness = 0.54
        via3_thickness = 0.54
        via4_thickness = 0.54
        topvia1_ncap_thickness = 0.85
        mim_via_thickness = topvia1_ncap_thickness - capild_thickness - cmim_cap_thickness
        topvia2_thickness = 2.8

        met1_z           = poly_z + poly_thickness + conp_thickness
        met2_z           = met1_z + met1_thickness + via1_thickness
        met3_z           = met2_z + met2_thickness + via2_thickness
        met4_z           = met3_z + met3_thickness + via3_thickness
        met5_z           = met4_z + met4_thickness + via4_thickness
        cmim_z           = met5_z + met5_thickness + capild_thickness
        topmet1_g2_z     = met5_z + met5_thickness + topvia1_ncap_thickness
        topmet1_cmos5l_z = met4_z + met4_thickness + topvia1_ncap_thickness
        topmet2_z        = topmet1_g2_z + topmet1_thickness + topvia2_thickness

        # METAL:                        name,      z,           thickness
        #-----------------------------------------------------------------------------------------------
        poly = add_metal_layer(psi,     "GatPoly", poly_z,      poly_thickness)
        # thickness: from SG13G2_os_process_spec.pdf p17

        # DIELECTRIC (conformal)        name,      dielectric_k, thickness,   thickness,      thickness, ref
        #                                                        over metal,  where no metal, sidewall
        #-----------------------------------------------------------------------------------------------
        add_conformal_dielectric(psi,   "nitride", 6.5,          0.05,        0.05,           0.05,      "GatPoly")

        # DIELECTRIC (simple)        name,     dielectric_k, ref
        #-----------------------------------------------------------------------------------------------
        add_simple_dielectric(psi,   "ild0",   4.1,          "fox")

        # METAL:                        name,     z,      thickness
        #-----------------------------------------------------------------------------------------------
        met1 = add_metal_layer(psi,     "Metal1", met1_z, met1_thickness)

        # DIELECTRIC (simple)        name,     dielectric_k, ref
        #-----------------------------------------------------------------------------------------------
        add_simple_dielectric(psi,   "ild1",   4.1,          "ild0")

        # METAL:                        name,     z,      thickness
        #-----------------------------------------------------------------------------------------------
        met2 = add_metal_layer(psi,     "Metal2", met2_z, met2_thickness)

        # DIELECTRIC (simple)        name,     dielectric_k, ref
        #-----------------------------------------------------------------------------------------------
        add_simple_dielectric(psi,   "ild2",   4.1,          "ild1")

        # METAL:                        name,     z,      thickness
        #-----------------------------------------------------------------------------------------------
        met3 = add_metal_layer(psi,     "Metal3", met3_z, met3_thickness)

        # DIELECTRIC (simple)        name,     dielectric_k, ref
        #-----------------------------------------------------------------------------------------------
        add_simple_dielectric(psi,   "ild3",   4.1,          "ild2")

        # METAL:                        name,     z,      thickness
        #-----------------------------------------------------------------------------------------------
        met4 = add_metal_layer(psi,     "Metal4", met4_z, met4_thickness)

        # DIELECTRIC (simple)        name,     dielectric_k, ref
        #-----------------------------------------------------------------------------------------------
        add_simple_dielectric(psi,   "ild4",   4.1,          "ild3")

        met5_ncap = None
        if self.is_g2:
            # METAL:                             name,           z,      thickness
            #-----------------------------------------------------------------------------------------------
            met5_ncap = add_metal_layer(psi,     "metal5_n_cap", met5_z, met5_thickness)

        # DIELECTRIC (simple)        name,       dielectric_k, ref
        #-----------------------------------------------------------------------------------------------
        add_simple_dielectric(psi,   "ildtm1",   4.1,          "ild4")

        cmim_cap = None
        if self.is_g2:
            # METAL:                         name,         z,      thickness
            #-----------------------------------------------------------------------------------------------------------
            add_metal_layer(psi,             "metal5_cap", met5_z, met5_thickness)

            # DIELECTRIC (conformal)        name,    dielectric_k, thickness,        thickness,      thickness, ref
            #                                                      over metal,       where no metal, sidewall
            #------------------------------------------------------------------------------------------------------------
            add_conformal_dielectric(psi,   "ismim", capild_k,     capild_thickness, 0.0,            0.0,       "metal5_cap")

            # DIELECTRIC (simple)        name,       dielectric_k, ref
            # A band of its own: same material as ildtm1, but it fills from
            # metal5_cap up to cmim_top, and a name may be declared only once.
            #------------------------------------------------------------------------------------------------------------
            add_simple_dielectric(psi,   "ildtm1b",  4.1,          "ild4")

            # METAL:                            name,       z,      thickness
            #----------------------------------------------------------------------------------------------------
            cmim_cap = add_metal_layer(psi,     "cmim_top", cmim_z, cmim_cap_thickness)

            # DIELECTRIC (simple)        name,       dielectric_k, ref
            #----------------------------------------------------------------------------------------------------
            add_simple_dielectric(psi,   "ildtm1c",  4.1,          "ild4")

        if self.is_g2:
            # METAL:                           name,        z,            thickness
            #----------------------------------------------------------------------------------------------------
            topmet1 = add_metal_layer(psi,     "TopMetal1", topmet1_g2_z, topmet1_thickness)

            # DIELECTRIC (simple)        name,       dielectric_k, ref
            #----------------------------------------------------------------------------------------------------
            add_simple_dielectric(psi,   "ildtm2",   4.1,          "ildtm1")

            # METAL:                           name,        z,            thickness
            #----------------------------------------------------------------------------------------------------
            add_metal_layer(psi,               "TopMetal2", topmet2_z,    topmet2_thickness)
            pass1_ref = "TopMetal2"
        else:
            # METAL:                           name,        z,                thickness
            #----------------------------------------------------------------------------------------------------
            topmet1 = add_metal_layer(psi,     "TopMetal1", topmet1_cmos5l_z, topmet1_thickness)
            pass1_ref = "TopMetal1"

        # DIELECTRIC (conformal)        name,    dielectric_k, thickness,   thickness,      thickness, ref
        #                                                      over metal,  where no metal, sidewall
        #-----------------------------------------------------------------------------------------------
        add_conformal_dielectric(psi,   "pass1", 4.1,          1.5,         1.5,            0.3,       pass1_ref)

        # DIELECTRIC (conformal)        name,    dielectric_k, thickness,   thickness,      thickness, ref
        #                                                      over metal,  where no metal, sidewall
        #-----------------------------------------------------------------------------------------------
        add_conformal_dielectric(psi,   "pass2", 6.6,          0.4,         0.4,            0.3,       "pass1")

        # DIELECTRIC (simple)        name,    dielectric_k, ref
        #-----------------------------------------------------------------------------------------------
        add_simple_dielectric(psi,   "air",   1.0,          "pass2")

        # TODO: cont over ptap/ntap/nwell!
        contn = ndiff.contact_above
        contd = pdiff.contact_above
        contp = poly.contact_above
        via1 = met1.contact_above
        via2 = met2.contact_above
        via3 = met3.contact_above
        if self.is_g2:
            via4 = met4.contact_above
            mim_via = cmim_cap.contact_above
            topvia1_n_cap = met5_ncap.contact_above
            topvia2 = topmet1.contact_above
        else:
            topvia1_n_cap = met4.contact_above

        # CONTACT:  contact,         name,            layer_below,     metal_above,     thickness,               width, spacing, border
        #                            (LVS)            (LVS)            (LVS)
        #--------------------------------------------------------------------------------------------------------------------------------
        set_contact(contn,           "cont_nsd_con",  "nsd_fet",       "metal1_con",    0.4 + 0.64,              0.16,  0.18,    0.0)    # TODO: spacing
        set_contact(contd,           "cont_psd_con",  "psd_fet",       "metal1_con",    0.4 + 0.64,              0.16,  0.18,    0.0)    # TODO: spacing
        set_contact(contp,           "cont_poly_con", "poly_con",      "metal1_con",    conp_thickness,          0.16,  0.18,    0.0)    # TODO: spacing
        set_contact(via1,            "via1_drw",      "metal1_con",    "metal2_con",    via1_thickness,          0.19,  0.22,    0.0)    # TODO: spacing
        set_contact(via2,            "via2_drw",      "metal2_con",    "metal3_con",    via2_thickness,          0.19,  0.22,    0.0)    # TODO: spacing
        set_contact(via3,            "via3_drw",      "metal3_con",    "metal4_con",    via3_thickness,          0.19,  0.22,    0.0)    # TODO: spacing
        if self.is_g2:
            set_contact(via4,          "via4_drw",      "metal4_con",    "metal5_n_cap",  via4_thickness,          0.19,  0.22,    0.0)    # TODO: spacing
            set_contact(topvia1_n_cap, "topvia1_n_cap", "metal5_n_cap",  "topmetal1_con", topvia1_ncap_thickness,  0.42,  0.42,    0.005)  # border: or 0.36
            set_contact(mim_via,       "mim_via",       "cmim_top",      "topmetal1_con", mim_via_thickness,       0.42,  0.42,    0.005)  # border: or 0.36
            set_contact(topvia2,       "topvia2_drw",   "topmetal1_con", "topmetal2_con", topvia2_thickness,       0.9,   1.06,    0.5)
        else:
            # CMOS5L has no Metal5, so TopVia1 lands on Metal4
            set_contact(topvia1_n_cap, "topvia1_n_cap", "metal4_con",    "topmetal1_con", topvia1_ncap_thickness,  0.42,  0.42,    0.005)  # border: or 0.36
        # TODO: refine via rules!

        # NOTE:  Contact arrays defined at 200 spacing for large array rule (5x5), otherwise spacing is 180.
        #        The smallest square which would be illegal at 180 spacing is
        #        (160 * 5) + (180 * 4) = 1520 (divided by 2 is 760)

        # NOTE:  Via1 arrays defined at 290 spacing for large array rule (4x4), otherwise spacing is 220.
        #        The smallest square which would be illegal at 220 spacing is
        #        (5 * 2) + (190 * 4) + (220 * 3) = 1430 (divided by 2 is 715)

        # NOTE: VIA2/VIA3/VIA4 same as VIA1!

        # TODO: depending if sealring or not the grid rules differ
        # TODO: if sealring is enabled, then no via restriction for TopVia2!

    def build_process_parasitics_info(self, ex: ProcessParasiticsInfo):
        # NOTE: coefficients according to
        #    - G2: https://github.com/IHP-GmbH/IHP-Open-PDK/blob/970a7688e7dcce2a6172797df9ef47bde2f60f9f/ihp-sg13g2/libs.tech/magic/ihp-sg13g2-extract.tech#L20
        #    - CMOS5L: https://github.com/IHP-GmbH/ihp-sg13cmos5l/blob/91e2a084bbc18960451532194727aef4ce533cdc/libs.tech/magic/ihp-sg13cmos5l-extract.tech#L20

        ex.side_halo = 8

        ri = ex.resistance

        # resistance values are in mΩ / square
        #                       layer, resistance, [corner_adjustment_fraction]
        add_layer_resistance(ri, "GatPoly",  7000)  # TODO: there is no value defined in the process spec!
        add_layer_resistance(ri, "Metal1",    110)
        add_layer_resistance(ri, "Metal2",     88)
        add_layer_resistance(ri, "Metal3",     88)
        add_layer_resistance(ri, "Metal4",     88)
        if self.is_g2:
            add_layer_resistance(ri, "Metal5",     88)
        add_layer_resistance(ri, "TopMetal1",  18)
        if self.is_g2:
            add_layer_resistance(ri, "TopMetal2",  11)

        # resistance values are in mΩ / CNT
        #                         contact_layer,   layer_below,  layer_above,     resistance
        #                         (LVS)            (LVS)         (LVS)
        add_contact_resistance(ri, "cont_nsd_con",  "nsd_fet",    "metal1_con",    17000)  # Cont over nSD-Activ
        add_contact_resistance(ri, "cont_psd_con",  "psd_fet",    "metal1_con",    17000)  # Cont over pSD-Activ
        add_contact_resistance(ri, "cont_poly_con", "poly_con",   "metal1_con",    15000)  # Cont over GatPoly

        # resistance values are in mΩ / CNT
        #                     via_layer,  resistance

        add_via_resistance(ri,     "Via1",       9000)
        add_via_resistance(ri,     "Via2",       9000)
        add_via_resistance(ri,     "Via3",       9000)
        if self.is_g2:
            add_via_resistance(ri,     "Via4",       9000)
        add_via_resistance(ri,     "TopVia1",    2200)
        if self.is_g2:
            add_via_resistance(ri,     "TopVia2",    1100)

        ci = ex.capacitance

        #                    layer,       area_cap,  perimeter_cap
        add_substrate_cap(ci, "GatPoly",  87.433,   44.537)
        add_substrate_cap(ci, "Metal1",   35.015,   39.585)
        add_substrate_cap(ci, "Metal2",   18.180,   34.798)
        add_substrate_cap(ci, "Metal3",   11.994,   31.352)
        add_substrate_cap(ci, "Metal4",    8.948,   29.083)
        if self.is_g2:
            add_substrate_cap(ci, "Metal5",    7.136,   27.527)
            add_substrate_cap(ci, "TopMetal1", 5.649,   37.383)
            add_substrate_cap(ci, "TopMetal2", 3.233,   31.175)
        else:
            add_substrate_cap(ci, "TopMetal1", 6.727,   34.527)

        # NOTE: magic distinguishes LV and HV (ThickGateOx) diffusion, which differ by up to 2 %,
        #       there is only one diffusion layer here, which uses the LV values
        diff_nonfet = "Activ"   # TODO: diff must be non-fet!

        #                  top_layer,    bottom_layer,   cap
        add_overlap_cap(ci, "GatPoly",    "NWell",        87.433)
        add_overlap_cap(ci, "GatPoly",    "PWell",        87.433)
        add_overlap_cap(ci, "Metal1",     "PWell",        35.015)
        add_overlap_cap(ci, "Metal1",     "NWell",        35.015)
        add_overlap_cap(ci, "Metal1",     diff_nonfet,    58.168)
        add_overlap_cap(ci, "Metal1",     "GatPoly",      78.653)
        add_overlap_cap(ci, "Metal2",     "PWell",        18.180)
        add_overlap_cap(ci, "Metal2",     "NWell",        18.180)
        add_overlap_cap(ci, "Metal2",     diff_nonfet,    22.916)
        add_overlap_cap(ci, "Metal2",     "GatPoly",      25.537)
        add_overlap_cap(ci, "Metal2",     "Metal1",       67.225)
        add_overlap_cap(ci, "Metal3",     "NWell",        11.994)
        add_overlap_cap(ci, "Metal3",     "PWell",        11.994)
        add_overlap_cap(ci, "Metal3",     diff_nonfet,    13.887)
        add_overlap_cap(ci, "Metal3",     "GatPoly",      14.808)
        add_overlap_cap(ci, "Metal3",     "Metal1",       23.122)
        add_overlap_cap(ci, "Metal3",     "Metal2",       67.225)
        add_overlap_cap(ci, "Metal4",     "NWell",         8.948)
        add_overlap_cap(ci, "Metal4",     "PWell",         8.948)
        add_overlap_cap(ci, "Metal4",     diff_nonfet,     9.962)
        add_overlap_cap(ci, "Metal4",     "GatPoly",      10.427)
        add_overlap_cap(ci, "Metal4",     "Metal1",       13.962)
        add_overlap_cap(ci, "Metal4",     "Metal2",       23.122)
        add_overlap_cap(ci, "Metal4",     "Metal3",       67.225)
        if self.is_g2:
            add_overlap_cap(ci, "Metal5",     "NWell",         7.136)
            add_overlap_cap(ci, "Metal5",     "PWell",         7.136)
            add_overlap_cap(ci, "Metal5",     diff_nonfet,     7.766)
            add_overlap_cap(ci, "Metal5",     "GatPoly",       8.046)
            add_overlap_cap(ci, "Metal5",     "Metal1",       10.000)
            add_overlap_cap(ci, "Metal5",     "Metal2",       13.962)
            add_overlap_cap(ci, "Metal5",     "Metal3",       23.122)
            add_overlap_cap(ci, "Metal5",     "Metal4",       67.225)
            add_overlap_cap(ci, "TopMetal1",  "NWell",         5.649)
            add_overlap_cap(ci, "TopMetal1",  "PWell",         5.649)
            add_overlap_cap(ci, "TopMetal1",  diff_nonfet,     6.036)
            add_overlap_cap(ci, "TopMetal1",  "GatPoly",       6.204)
            add_overlap_cap(ci, "TopMetal1",  "Metal1",        7.304)
            add_overlap_cap(ci, "TopMetal1",  "Metal2",        9.214)
            add_overlap_cap(ci, "TopMetal1",  "Metal3",       12.475)
            add_overlap_cap(ci, "TopMetal1",  "Metal4",       19.309)
            add_overlap_cap(ci, "TopMetal1",  "Metal5",       42.708)
            add_overlap_cap(ci, "TopMetal2",  "NWell",         3.233)
            add_overlap_cap(ci, "TopMetal2",  "PWell",         3.233)
            add_overlap_cap(ci, "TopMetal2",  diff_nonfet,     3.357)
            add_overlap_cap(ci, "TopMetal2",  "GatPoly",       3.408)
            add_overlap_cap(ci, "TopMetal2",  "Metal1",        3.716)
            add_overlap_cap(ci, "TopMetal2",  "Metal2",        4.154)
            add_overlap_cap(ci, "TopMetal2",  "Metal3",        4.708)
            add_overlap_cap(ci, "TopMetal2",  "Metal4",        5.434)
            add_overlap_cap(ci, "TopMetal2",  "Metal5",        6.425)
            add_overlap_cap(ci, "TopMetal2",  "TopMetal1",    12.965)
        else:  # CMOS5L: overlap situations differ as Metal5 and TopMetal2 are missing!
            add_overlap_cap(ci, "TopMetal1",  "NWell",         6.727)
            add_overlap_cap(ci, "TopMetal1",  "PWell",         6.727)
            add_overlap_cap(ci, "TopMetal1",  diff_nonfet,     7.284)
            add_overlap_cap(ci, "TopMetal1",  "GatPoly",       7.529)
            add_overlap_cap(ci, "TopMetal1",  "Metal1",        9.213)
            add_overlap_cap(ci, "TopMetal1",  "Metal2",       12.475)
            add_overlap_cap(ci, "TopMetal1",  "Metal3",       19.309)
            add_overlap_cap(ci, "TopMetal1",  "Metal4",       42.708)

        #                   layer_name,      cap,  offset
        add_sidewall_cap(ci, "GatPoly",    11.722, -0.023)
        add_sidewall_cap(ci, "Metal1",     28.735, -0.057)
        add_sidewall_cap(ci, "Metal2",     40.981, -0.033)
        add_sidewall_cap(ci, "Metal3",     37.679, -0.045)
        add_sidewall_cap(ci, "Metal4",     49.526,  0.004)
        if self.is_g2:
            add_sidewall_cap(ci, "Metal5",     53.129,  0.021)
        add_sidewall_cap(ci, "TopMetal1", 162.172,  0.343)
        if self.is_g2:
            add_sidewall_cap(ci, "TopMetal2", 227.323,  1.893)

        #                           in_layer,       out_layer,      cap
        add_sidewall_overlap_cap(ci, "GatPoly",      "NWell",        44.537)
        add_sidewall_overlap_cap(ci, "GatPoly",      "PWell",        44.537)
        add_sidewall_overlap_cap(ci, "Metal1",       "NWell",        39.585)
        add_sidewall_overlap_cap(ci, "Metal1",       "PWell",        39.585)
        add_sidewall_overlap_cap(ci, "Metal1",       diff_nonfet,    44.749)
        add_sidewall_overlap_cap(ci, "Metal1",       "GatPoly",      49.378)
        add_sidewall_overlap_cap(ci, "GatPoly",      "Metal1",       23.229)
        add_sidewall_overlap_cap(ci, "Metal2",       "NWell",        34.798)
        add_sidewall_overlap_cap(ci, "Metal2",       "PWell",        34.798)
        add_sidewall_overlap_cap(ci, "Metal2",       diff_nonfet,    36.950)
        add_sidewall_overlap_cap(ci, "Metal2",       "GatPoly",      37.616)
        add_sidewall_overlap_cap(ci, "GatPoly",      "Metal2",       10.801)
        add_sidewall_overlap_cap(ci, "Metal2",       "Metal1",       49.543)
        add_sidewall_overlap_cap(ci, "Metal1",       "Metal2",       31.073)
        add_sidewall_overlap_cap(ci, "Metal3",       "NWell",        31.352)
        add_sidewall_overlap_cap(ci, "Metal3",       "PWell",        31.352)
        add_sidewall_overlap_cap(ci, "Metal3",       diff_nonfet,    32.271)
        add_sidewall_overlap_cap(ci, "Metal3",       "GatPoly",      32.795)
        add_sidewall_overlap_cap(ci, "GatPoly",      "Metal3",       7.068)
        add_sidewall_overlap_cap(ci, "Metal3",       "Metal1",       37.009)
        add_sidewall_overlap_cap(ci, "Metal1",       "Metal3",       17.349)
        add_sidewall_overlap_cap(ci, "Metal3",       "Metal2",       49.537)
        add_sidewall_overlap_cap(ci, "Metal2",       "Metal3",       36.907)
        add_sidewall_overlap_cap(ci, "Metal4",       "NWell",        29.083)
        add_sidewall_overlap_cap(ci, "Metal4",       "PWell",        29.083)
        add_sidewall_overlap_cap(ci, "Metal4",       diff_nonfet,    29.755)
        add_sidewall_overlap_cap(ci, "Metal4",       "GatPoly",      30.101)
        add_sidewall_overlap_cap(ci, "GatPoly",      "Metal4",        5.240)
        add_sidewall_overlap_cap(ci, "Metal4",       "Metal1",       32.162)
        add_sidewall_overlap_cap(ci, "Metal1",       "Metal4",       12.398)
        add_sidewall_overlap_cap(ci, "Metal4",       "Metal2",       36.335)
        add_sidewall_overlap_cap(ci, "Metal2",       "Metal4",       22.327)
        add_sidewall_overlap_cap(ci, "Metal4",       "Metal3",       49.537)
        add_sidewall_overlap_cap(ci, "Metal3",       "Metal4",       40.019)
        if self.is_g2:
            add_sidewall_overlap_cap(ci, "Metal5",       "NWell",        27.527)
            add_sidewall_overlap_cap(ci, "Metal5",       "PWell",        27.527)
            add_sidewall_overlap_cap(ci, "Metal5",       diff_nonfet,    28.227)
            add_sidewall_overlap_cap(ci, "Metal5",       "GatPoly",      28.414)
            add_sidewall_overlap_cap(ci, "GatPoly",      "Metal5",        4.178)
            add_sidewall_overlap_cap(ci, "Metal5",       "Metal1",       29.935)
            add_sidewall_overlap_cap(ci, "Metal1",       "Metal5",        9.725)
            add_sidewall_overlap_cap(ci, "Metal5",       "Metal2",       32.116)
            add_sidewall_overlap_cap(ci, "Metal2",       "Metal5",       16.534)
            add_sidewall_overlap_cap(ci, "Metal5",       "Metal3",       36.971)
            add_sidewall_overlap_cap(ci, "Metal3",       "Metal5",       24.785)
            add_sidewall_overlap_cap(ci, "Metal5",       "Metal4",       49.517)
            add_sidewall_overlap_cap(ci, "Metal4",       "Metal5",       41.956)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "NWell",        37.383)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "PWell",        37.383)
            add_sidewall_overlap_cap(ci, "TopMetal1",    diff_nonfet,    38.084)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "GatPoly",      38.376)
            add_sidewall_overlap_cap(ci, "GatPoly",      "TopMetal1",     3.316)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "Metal1",       39.678)
            add_sidewall_overlap_cap(ci, "Metal1",       "TopMetal1",     7.669)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "Metal2",       42.268)
            add_sidewall_overlap_cap(ci, "Metal2",       "TopMetal1",    12.649)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "Metal3",       46.611)
            add_sidewall_overlap_cap(ci, "Metal3",       "TopMetal1",    17.848)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "Metal4",       52.657)
            add_sidewall_overlap_cap(ci, "Metal4",       "TopMetal1",    24.526)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "Metal5",       65.859)
            add_sidewall_overlap_cap(ci, "Metal5",       "TopMetal1",    36.377)

            add_sidewall_overlap_cap(ci, "TopMetal2",    "NWell",        31.175)
            add_sidewall_overlap_cap(ci, "TopMetal2",    "PWell",        31.175)
            add_sidewall_overlap_cap(ci, "TopMetal2",    diff_nonfet,    31.484)
            add_sidewall_overlap_cap(ci, "TopMetal2",    "GatPoly",      30.971)
            add_sidewall_overlap_cap(ci, "GatPoly",      "TopMetal2",     1.909)
            add_sidewall_overlap_cap(ci, "TopMetal2",    "Metal1",       32.318)
            add_sidewall_overlap_cap(ci, "Metal1",       "TopMetal2",     4.344)
            add_sidewall_overlap_cap(ci, "TopMetal2",    "Metal2",       33.245)
            add_sidewall_overlap_cap(ci, "Metal2",       "TopMetal2",     6.975)
            add_sidewall_overlap_cap(ci, "TopMetal2",    "Metal3",       34.339)
            add_sidewall_overlap_cap(ci, "Metal3",       "TopMetal2",     9.381)
            add_sidewall_overlap_cap(ci, "TopMetal2",    "Metal4",       35.630)
            add_sidewall_overlap_cap(ci, "Metal4",       "TopMetal2",    11.825)
            add_sidewall_overlap_cap(ci, "TopMetal2",    "Metal5",       37.206)
            add_sidewall_overlap_cap(ci, "Metal5",       "TopMetal2",    14.415)
            add_sidewall_overlap_cap(ci, "TopMetal2",    "TopMetal1",    44.735)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "TopMetal2",    33.071)
        else:  # CMOS5L: fringe situations differ as Metal5 and TopMetal2 are missing!
            add_sidewall_overlap_cap(ci, "TopMetal1",    "NWell",        34.527)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "PWell",        34.527)
            add_sidewall_overlap_cap(ci, "TopMetal1",    diff_nonfet,    35.162)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "GatPoly",      35.513)
            add_sidewall_overlap_cap(ci, "GatPoly",      "TopMetal1",     3.942)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "Metal1",       37.397)
            add_sidewall_overlap_cap(ci, "Metal1",       "TopMetal1",     9.198)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "Metal2",       40.400)
            add_sidewall_overlap_cap(ci, "Metal2",       "TopMetal1",    15.402)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "Metal3",       45.197)
            add_sidewall_overlap_cap(ci, "Metal3",       "TopMetal1",    22.609)
            add_sidewall_overlap_cap(ci, "TopMetal1",    "Metal4",       55.229)
            add_sidewall_overlap_cap(ci, "Metal4",       "TopMetal1",    35.146)

    def build_tech(self) -> Technology:
        tech = Technology(name=self.variant.value)

        self.build_layers(tech)

        self.build_lvs_computed_layers(tech)

        self.build_process_stack_info(tech.process_stack)

        self.build_process_parasitics_info(tech.process_parasitics)

        return tech


def build_tech(variant: LayerStackVariant) -> Technology:
    return TechBuilder(variant).build_tech()
