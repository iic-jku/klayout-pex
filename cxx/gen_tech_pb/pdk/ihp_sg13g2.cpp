/*
 * --------------------------------------------------------------------------------
 * SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
 * Johannes Kepler University, Institute for Integrated Circuits.
 *
 * This file is part of KPEX 
 * (see https://github.com/iic-jku/klayout-pex).
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program. If not, see <http://www.gnu.org/licenses/>.
 * SPDX-License-Identifier: GPL-3.0-or-later
 * --------------------------------------------------------------------------------
 */

//
// This creates a technology definition example for IHP sg13g2:
//
// See page5 of
// https://github.com/IHP-GmbH/IHP-Open-PDK/blob/main/ihp-sg13g2/libs.doc/doc/SG13G2_os_process_spec.pdf
// and https://github.com/IHP-GmbH/IHP-Open-PDK/blob/main/ihp-sg13g2/libs.tech/openems/testcase/SG13_Octagon_L2n0/OpenEMS_Python/Using%20OpenEMS%20Python%20with%20IHP%20SG13G2%20v1.1.pdf
//
//

#include "protobuf.h"

namespace ihp_sg13g2 {

constexpr auto DNWELL = kpex::tech::LayerInfo_Purpose_PURPOSE_DNWELL;
constexpr auto NWELL = kpex::tech::LayerInfo_Purpose_PURPOSE_NWELL;
constexpr auto PWELL = kpex::tech::LayerInfo_Purpose_PURPOSE_PWELL;
constexpr auto DIFF = kpex::tech::LayerInfo_Purpose_PURPOSE_DIFF;
constexpr auto N_P_TAP = kpex::tech::LayerInfo_Purpose_PURPOSE_NTAP_OR_PTAP;
constexpr auto NTAP = kpex::tech::LayerInfo_Purpose_PURPOSE_NTAP;
constexpr auto PTAP = kpex::tech::LayerInfo_Purpose_PURPOSE_PTAP;
constexpr auto PIMP = kpex::tech::LayerInfo_Purpose_PURPOSE_P_IMPLANT;
constexpr auto NIMP = kpex::tech::LayerInfo_Purpose_PURPOSE_N_IMPLANT;
constexpr auto CONT = kpex::tech::LayerInfo_Purpose_PURPOSE_CONTACT;
constexpr auto METAL = kpex::tech::LayerInfo_Purpose_PURPOSE_METAL;
constexpr auto VIA = kpex::tech::LayerInfo_Purpose_PURPOSE_VIA;
constexpr auto MIM = kpex::tech::LayerInfo_Purpose_PURPOSE_MIM_CAP;

void buildLayers(kpex::tech::Technology *tech) {
    //             purpose   name       drw_gds, pin_gds, label_gds, description
    addLayer(tech, DIFF,     "Activ",       1,0,   1,2,  -1,-1, "Active (diffusion) area"); // ~ diff.drawing
    addLayer(tech, NWELL,    "NWell",      31,0,  31,2,  -1,-1, "N-well region");
    addLayer(tech, PWELL,    "PWell",      46,0,  46,2,  -1,-1, "P-well region");
    addLayer(tech, NIMP,     "nSD",         7,0, -1,-1,  -1,-1, "Defines areas to receive N+ S/D implant");
    addLayer(tech, PIMP,     "pSD",        14,0, -1,-1,  -1,-1, "Defines areas to receive P+ S/D implant");
    addLayer(tech, METAL,    "GatPoly",     5,0,   5,2,   5,25, "Poly"); // ~ poly.drawing
    addLayer(tech, CONT,     "Cont",        6,0, -1,-1,  -1,-1, "Defines 1-st metal contacts to Activ, GatPoly");
    addLayer(tech, METAL,    "Metal1",      8,0,   8,2,   8,25, "Defines 1-st metal interconnect");
    addLayer(tech, VIA,      "Via1",       19,0, -1,-1,  -1,-1, "Defines 1-st metal to 2-nd metal contact");
    addLayer(tech, METAL,    "Metal2",     10,0,  10,2,  10,25, "Defines 2-nd metal interconnect");
    addLayer(tech, VIA,      "Via2",       29,0, -1,-1,  -1,-1, "Defines 2-nd metal to 3-rd metal contact");
    addLayer(tech, METAL,    "Metal3",     30,0,  30,2,  30,25, "Defines 3-rd metal interconnect");
    addLayer(tech, VIA,      "Via3",       49,0, -1,-1,  -1,-1, "Defines 3-rd metal to 4-th metal contact");
    addLayer(tech, METAL,    "Metal4",     50,0,  50,2,  50,25, "Defines 4-th metal interconnect");
    addLayer(tech, VIA,      "Via4",       66,0, -1,-1,  -1,-1, "Defines 4-th metal to 5-th metal contact");
    addLayer(tech, METAL,    "Metal5",     67,0,  67,2,  67,25, "Defines 5-th metal interconnect");
    addLayer(tech, VIA,      "TopVia1",   125,0, -1,-1,  -1,-1, "Defines 3-rd (or 5-th) metal to TopMetal1 contact");
    addLayer(tech, METAL,    "TopMetal1", 126,0, 126,2, 126,25, "Defines 1-st thick TopMetal layer");
    addLayer(tech, VIA,      "TopVia2",   133,0, -1,-1,  -1,-1, "Defines via between TopMetal1 and TopMetal2");
    addLayer(tech, METAL,    "TopMetal2", 134,0, 134,2, 134,25, "Defines 2-nd thick TopMetal layer");
}

void buildLVSComputedLayers(kpex::tech::Technology *tech) {
    auto KREG = kpex::tech::ComputedLayerInfo_Kind_KIND_REGULAR;
    auto KCAP = kpex::tech::ComputedLayerInfo_Kind_KIND_DEVICE_CAPACITOR;
    auto KRES = kpex::tech::ComputedLayerInfo_Kind_KIND_DEVICE_RESISTOR;
    auto KPIN = kpex::tech::ComputedLayerInfo_Kind_KIND_PIN;
    auto KLBL = kpex::tech::ComputedLayerInfo_Kind_KIND_LABEL;

    //                     purpose kind  lvs_name lvs_gds_pair  orig. layer   description
    addComputedLayer(tech, PWELL, KREG, "pwell",        46, 0,   "PWell", "Computed layer for PWell");
    addComputedLayer(tech, PWELL, KREG, "pwell_sub",    46, 0,   "PWell", "Computed layer for PWell");
    addComputedLayer(tech, NWELL, KREG, "nwell_drw",    31, 0,   "NWell", "Computed layer for NWell");
    addComputedLayer(tech, NIMP,  KREG, "nsd_fet",       7, 0,   "nSD", "Computed layer for nSD");
    addComputedLayer(tech, PIMP,  KREG, "psd_fet",      14, 0,   "pSD", "Computed layer for pSD");
    addComputedLayer(tech, NTAP,  KREG, "ntap",         65, 144, "Activ", "Computed layer for ntap");
    addComputedLayer(tech, PTAP,  KREG, "ptap",         65, 244, "Activ", "Computed layer for ptap");

    addComputedLayer(tech, METAL, KREG, "poly_con",       5, 0,   "GatPoly", "Computed layer for GatPoly");
    addComputedLayer(tech, METAL, KREG, "metal1_con",     8, 0,   "Metal1", "Computed layer for Metal1");
    addComputedLayer(tech, METAL, KREG, "metal2_con",    10, 0,   "Metal2", "Computed layer for Metal2");
    addComputedLayer(tech, METAL, KREG, "metal3_con",    30, 0,   "Metal3", "Computed layer for Metal3");
    addComputedLayer(tech, METAL, KREG, "metal4_con",    50, 0,   "Metal4", "Computed layer for Metal4");
    addComputedLayer(tech, METAL, KREG, "metal5_n_cap",  67, 200, "Metal5", "Computed layer for Metal5 (case where no MiM cap)");
    addComputedLayer(tech, METAL, KREG, "topmetal1_con", 126, 0, "TopMetal1", "Computed layer for TopMetal1");
    addComputedLayer(tech, METAL, KREG, "topmetal2_con", 134, 0, "TopMetal2", "Computed layer for TopMetal2");

    addComputedLayer(tech, CONT,  KREG, "cont_nsd_con",   6, 4401,  "Cont", "Computed layer for contact from nSD to Metal1");
    addComputedLayer(tech, CONT,  KREG, "cont_psd_con",   6, 4402,  "Cont", "Computed layer for contact from pSD to Metal1");
    addComputedLayer(tech, CONT,  KREG, "cont_poly_con",  6, 4403,  "Cont", "Computed layer for contact from GatPoly to Metal1");
    
    addComputedLayer(tech, VIA,   KREG, "via1_drw",      19, 0,  "Via1", "Computed layer for Via1");
    addComputedLayer(tech, VIA,   KREG, "via2_drw",      29, 0,  "Via2", "Computed layer for Via2");
    addComputedLayer(tech, VIA,   KREG, "via3_drw",      49, 0,  "Via3", "Computed layer for Via3");
    addComputedLayer(tech, VIA,   KREG, "via4_drw",      66, 0,  "Via4", "Computed layer for Via4");
    
    addComputedLayer(tech, VIA,   KREG, "topvia1_n_cap", 125, 200, "TopVia1", "Original TopVia1 is 125/0 (case where no MiM cap)");
    addComputedLayer(tech, VIA,   KREG, "topvia2_drw",   133, 0, "TopVia2", "Computed layer for TopVia2");

    addComputedLayer(tech, VIA,   KCAP, "mim_via",       125, 10, "TopVia1", "Original TopVia1 is 125/0, case MiM cap");
    addComputedLayer(tech, MIM,   KCAP, "metal5_cap",    67, 100,  "Metal5", "Computed layer for Metal5, case MiM cap");
    addComputedLayer(tech, MIM,   KCAP, "cmim_top",      36, 0,  "<TODO>", "Computed layer for MiM cap above Metal5");

    // NOTE: there are no existing SPICE models for MOM caps (as was with sky130A)
    //       otherwise they should also be declared as ComputedLayerInfo_Kind_KIND_DEVICE_CAPACITOR
    //       and extracted accordingly in the LVS script, to allow blackboxing
    
    addComputedLayer(tech, METAL,   KPIN, "poly_pin_con",        5, 2,  "GatPoly.pin",   "Poly pin");
    addComputedLayer(tech, METAL,   KPIN, "metal1_pin_con",      8, 2,  "Metal1.pin",    "Metal1 pin");
    addComputedLayer(tech, METAL,   KPIN, "metal2_pin_con",     10, 2,  "Metal2.pin",    "Metal2 pin");
    addComputedLayer(tech, METAL,   KPIN, "metal3_pin_con",     30, 2,  "Metal3.pin",    "Metal3 pin");
    addComputedLayer(tech, METAL,   KPIN, "metal4_pin_con",     50, 2,  "Metal4.pin",    "Metal4 pin");
    addComputedLayer(tech, METAL,   KPIN, "metal5_pin_con",     67, 2,  "Metal5.pin",    "Metal5 pin");
    addComputedLayer(tech, METAL,   KPIN, "topmetal1_pin_con", 126, 2,  "TopMetal1.pin", "TopMetal1 pin");
    addComputedLayer(tech, METAL,   KPIN, "topmetal2_pin_con", 134, 2,  "TopMetal2.pin", "TopMetal2 pin");
    
    addComputedLayer(tech, METAL,   KLBL, "poly_text",        5, 25,  "GatPoly.text",   "Poly label");
    addComputedLayer(tech, METAL,   KLBL, "metal1_text",      8, 25,  "Metal1.text",    "Metal1 label");
    addComputedLayer(tech, METAL,   KLBL, "metal2_text",     10, 25,  "Metal2.text",    "Metal2 label");
    addComputedLayer(tech, METAL,   KLBL, "metal3_text",     30, 25,  "Metal3.text",    "Metal3 label");
    addComputedLayer(tech, METAL,   KLBL, "metal4_text",     50, 25,  "Metal4.text",    "Metal4 label");
    addComputedLayer(tech, METAL,   KLBL, "metal5_text",     67, 25,  "Metal5.text",    "Metal5 label");
    addComputedLayer(tech, METAL,   KLBL, "topmetal1_text", 126, 25,  "TopMetal1.text", "TopMetal1 label");
    addComputedLayer(tech, METAL,   KLBL, "topmetal2_text", 134, 25,  "TopMetal2.text", "TopMetal2 label");
}

void buildProcessStackInfo(kpex::tech::ProcessStackInfo *psi) {
    // SUBSTRATE:           name    height   thickness         reference
    //                                       (below height 0)
    //-----------------------------------------------------------------------------------------------
    addSubstrateLayer(psi, "subs",  0.0,     0.28,             "fox");
    
    // NWELL/DIFF:                     name     z        ref
    //                                          (TODO)
    //-----------------------------------------------------------------------------------------------
    auto nwell =    addNWellLayer(psi, "ntap",  0.0,    "fox");
    
    auto ndiff = addDiffusionLayer(psi, "nSD",  0.0,    "fox");
    auto pdiff = addDiffusionLayer(psi, "pSD",  0.0,    "fox");

    // FOX:                 name     dielectric_k
    //-----------------------------------------------------------------------------------------------
    addFieldOxideLayer(psi, "fox",   3.95); // from SG13G2_os_process_spec.pdf p6
    
    double capild_k = 6.7;  // to match design sg13g2__pr.gds/cmim to 74.62fF
    double capild_thickness = 0.04;
    
    auto poly_z = 0.4;
    
    auto poly_thickness = 0.16;
    auto met1_thickness = 0.42;
    auto met2_thickness = 0.36;
    auto met3_thickness = 0.49;
    auto met4_thickness = 0.49;
    auto met5_thickness = 0.49;
    auto cmim_cap_thickness = 0.15;
    auto topmet1_thickness = 2.0;
    auto topmet2_thickness = 3.0;
    
    auto conp_thickness = 0.64 - poly_thickness;
    auto via1_thickness = 0.54;
    auto via2_thickness = 0.54;
    auto via3_thickness = 0.54;
    auto via4_thickness = 0.54;
    auto topvia1_ncap_thickness = 0.85;
    auto mim_via_thickness = topvia1_ncap_thickness - capild_thickness - cmim_cap_thickness;
    auto topvia2_thickness = 2.8;
    
    auto met1_z      = poly_z + poly_thickness + conp_thickness;
    auto met2_z      = met1_z + met1_thickness + via1_thickness;
    auto met3_z      = met2_z + met2_thickness + via2_thickness;
    auto met4_z      = met3_z + met3_thickness + via3_thickness;
    auto met5_z      = met4_z + met4_thickness + via4_thickness;
    auto cmim_z      = met5_z + met5_thickness + capild_thickness;
    auto topmet1_z   = met5_z + met5_thickness + topvia1_ncap_thickness;
    auto topmet2_z   = topmet1_z + topmet1_thickness + topvia2_thickness;
    
    // METAL:                      name,      z,           thickness
    //-----------------------------------------------------------------------------------------------
    auto poly = addMetalLayer(psi, "GatPoly", poly_z, poly_thickness);
    // thickness: from SG13G2_os_process_spec.pdf p17
    
    // DIELECTRIC (conformal)   name,    dielectric_k,   thickness,   thickness,      thickness, ref
    //                                                   over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    addConformalDielectric(psi, "nitride",        6.5,         0.05,            0.05,      0.05,  "GatPoly");
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "ild0",   4.1,          "fox");
    
    // METAL:                      name,     z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met1 = addMetalLayer(psi, "Metal1", met1_z, met1_thickness);
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "ild1",   4.1,          "ild0");
    
    // METAL:                      name,     z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met2 = addMetalLayer(psi, "Metal2", met2_z, met2_thickness);
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "ild2",   4.1,          "ild1");
    
    // METAL:                      name,     z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met3 = addMetalLayer(psi, "Metal3", met3_z, met3_thickness);
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "ild3",   4.1,          "ild2");
    
    // METAL:                      name,     z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met4 = addMetalLayer(psi, "Metal4", met4_z, met4_thickness);
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "ild4",   4.1,          "ild3");
    
    // METAL:                           name,           z,           thickness
    //-----------------------------------------------------------------------------------------------
    auto met5_ncap = addMetalLayer(psi, "metal5_n_cap", met5_z, met5_thickness);
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "ildtm1",   4.1,        "ild4");
    
    // METAL:                           name,        z,      thickness
    //-----------------------------------------------------------------------------------------------------------
    auto met5_cap = addMetalLayer(psi, "metal5_cap", met5_z, met5_thickness);
    
    // DIELECTRIC (conformal)   name,    dielectric_k, thickness,        thickness,      thickness, ref
    //                                                 over metal,       where no metal, sidewall
    //------------------------------------------------------------------------------------------------------------
    addConformalDielectric(psi, "ismim", capild_k,     capild_thickness, 0.0,            0.0,       "metal5_cap");
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //----------------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "ildtm1",   4.1,        "ild4");
    
    // METAL:                           name,      z,      thickness
    //----------------------------------------------------------------------------------------------------
    auto cmim_cap = addMetalLayer(psi, "cmim_top", cmim_z, cmim_cap_thickness);
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //----------------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "ildtm1",   4.1,        "ild4");
    
    // METAL:                           name,      z,         thickness
    //----------------------------------------------------------------------------------------------------
    auto topmet1 = addMetalLayer(psi, "TopMetal1", topmet1_z, topmet1_thickness);
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //----------------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "ildtm2",   4.1,        "ildtm1");
    
    // METAL:                           name,      z,         thickness
    //----------------------------------------------------------------------------------------------------
    auto topmet2 = addMetalLayer(psi, "TopMetal2", topmet2_z, topmet2_thickness);
    
    // DIELECTRIC (conformal)   name,    dielectric_k,   thickness,   thickness,      thickness, ref
    //                                                   over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    addConformalDielectric(psi, "pass1",          4.1,         1.5,            1.5,      0.3,    "TopMetal2");
    
    // DIELECTRIC (conformal)   name,    dielectric_k,   thickness,   thickness,      thickness, ref
    //                                                   over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    addConformalDielectric(psi, "pass2",          6.6,         0.4,            0.4,      0.3,    "pass1");
    
    // DIELECTRIC (simple)   name,    dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "air",   1.0,          "pass2");
    
    // TODO: cont over ptap/ntap/nwell!
    auto contn = ndiff->mutable_contact_above();
    auto contd = pdiff->mutable_contact_above();
    auto contp = poly->mutable_contact_above();
    auto via1 = met1->mutable_contact_above();
    auto via2 = met2->mutable_contact_above();
    auto via3 = met3->mutable_contact_above();
    auto via4 = met4->mutable_contact_above();
    auto topvia1_n_cap = met5_ncap->mutable_contact_above();
    auto mim_via = cmim_cap->mutable_contact_above();
    auto topvia2 = topmet1->mutable_contact_above();
    
    // CONTACT:               contact,         layer_below,     metal_above,     thickness,               width, spacing,         border
    //                        (LVS)            (LVS)            (LVS)
    //----------------------------------------------------------------------------------------------------------------------------
    setContact(contn,         "cont_nsd_con",  "nsd_fet",       "metal1_con",    0.4 + 0.64,              0.16,   0.18 /*TODO*/,  0.0);
    setContact(contd,         "cont_psd_con",  "psd_fet",       "metal1_con",    0.4 + 0.64,              0.16,   0.18 /*TODO*/,  0.0);
    setContact(contp,         "cont_poly_con", "poly_con",      "metal1_con",    conp_thickness,          0.16,   0.18 /*TODO*/,  0.0);
    setContact(via1,          "via1_drw",      "metal1_con",    "metal2_con",    via1_thickness,          0.19,   0.22 /*TODO*/,  0.0);
    setContact(via2,          "via2_drw",      "metal2_con",    "metal3_con",    via1_thickness,          0.19,   0.22 /*TODO*/,  0.0);
    setContact(via3,          "via3_drw",      "metal3_con",    "metal4_con",    via1_thickness,          0.19,   0.22 /*TODO*/,  0.0);
    setContact(via4,          "via4_drw",      "metal4_con",    "metal5_n_cap",  via1_thickness,          0.19,   0.22 /*TODO*/,  0.0);
    setContact(topvia1_n_cap, "topvia1_n_cap", "metal5_n_cap",  "topmetal1_con", topvia1_ncap_thickness,  0.42,   0.42,           0.005 /* or 0.36*/);
    setContact(mim_via,       "mim_via",       "cmim_top",      "topmetal1_con", mim_via_thickness,       0.42,   0.42,           0.005 /* or 0.36*/);
    setContact(topvia2,       "topvia2_drw",   "topmetal1_con", "topmetal2_con", topvia2_thickness,       0.9,    1.06,           0.5);
    
    // TODO: refine via rules!
    
    // NOTE:  Contact arrays defined at 200 spacing for large array rule (5x5), otherwise spacing is 180.
    //        The smallest square which would be illegal at 180 spacing is
    //        (160 * 5) + (180 * 4) = 1520 (divided by 2 is 760)
    
    // NOTE:  Via1 arrays defined at 290 spacing for large array rule (4x4), otherwise spacing is 220.
    //        The smallest square which would be illegal at 220 spacing is
    //        (5 * 2) + (190 * 4) + (220 * 3) = 1430 (divided by 2 is 715)

    // NOTE: VIA2/VIA3/VIA4 same as VIA1!
    
    // TODO: depending if sealring or not the grid rules differ
    // TODO: if sealring is enabled, then no via restriction for TopVia2!
    
}

void buildProcessParasiticsInfo(kpex::tech::ProcessParasiticsInfo *ex) {
    // NOTE: coefficients according to https://github.com/IHP-GmbH/IHP-Open-PDK/blob/7897c7f99fe5538656b4c08e300cfe4d2c8a5503/ihp-sg13g2/libs.tech/magic/ihp-sg13g2.tech#L4515

    ex->set_side_halo(8);
    
    kpex::tech::ResistanceInfo *ri = ex->mutable_resistance();

    // resistance values are in mΩ / square
    //                     layer, resistance, [corner_adjustment_fraction]
    addLayerResistance(ri, "GatPoly",  7000); // TODO: there is no value defined in the process spec!
    addLayerResistance(ri, "Metal1",    110);
    addLayerResistance(ri, "Metal2",     88);
    addLayerResistance(ri, "Metal3",     88);
    addLayerResistance(ri, "Metal4",     88);
    addLayerResistance(ri, "Metal5",     88);
    addLayerResistance(ri, "TopMetal1",  18);
    addLayerResistance(ri, "TopMetal2",  11);

    // resistance values are in mΩ / CNT
    //                       contact_layer,   layer_below,  layer_above,     resistance
    //                       (LVS)            (LVS)         (LVS)
    addContactResistance(ri, "cont_nsd_con",  "nsd_fet",    "metal1_con",    17000);  // Cont over nSD-Activ
    addContactResistance(ri, "cont_psd_con",  "psd_fet",    "metal1_con",    17000);  // Cont over pSD-Activ
    addContactResistance(ri, "cont_poly_con", "poly_con",   "metal1_con",    15000);  // Cont over GatPoly

    // resistance values are in mΩ / CNT
    //                       via_layer,  resistance

    addViaResistance(ri,     "Via1",       9000);
    addViaResistance(ri,     "Via2",       9000);
    addViaResistance(ri,     "Via3",       9000);
    addViaResistance(ri,     "Via4",       9000);
    addViaResistance(ri,     "TopVia1",    2200);
    addViaResistance(ri,     "TopVia2",    1100);
    
    kpex::tech::CapacitanceInfo *ci = ex->mutable_capacitance();

    //                  layer,    area_cap,  perimeter_cap
    addSubstrateCap(ci, "GatPoly",  87.433,   44.537);
    addSubstrateCap(ci, "Metal1",   35.015,   39.585);
    addSubstrateCap(ci, "Metal2",   18.180,   34.798);
    addSubstrateCap(ci, "Metal3",   11.994,   31.352);
    addSubstrateCap(ci, "Metal4",    8.948,   29.083);
    addSubstrateCap(ci, "Metal5",    7.136,   27.527);
    addSubstrateCap(ci, "TopMetal1", 5.649,   37.383);
    addSubstrateCap(ci, "TopMetal2", 3.233,   31.175);
    
    const std::string diff_lv_nonfet = "Activ";   // TODO: diff must be non-fet!
    const std::string diff_hv_nonfet = "Activ";   // TODO: diff must be non-fet!

    //                top_layer,    bottom_layer,   cap
    addOverlapCap(ci, "GatPoly",    "NWell",        87.433);
    addOverlapCap(ci, "GatPoly",    "PWell",        87.433);
    addOverlapCap(ci, "Metal1",     "PWell",        35.015);
    addOverlapCap(ci, "Metal1",     "NWell",        35.015);
    addOverlapCap(ci, "Metal1",     diff_lv_nonfet, 58.168);
    addOverlapCap(ci, "Metal1",     diff_hv_nonfet, 57.702);
    addOverlapCap(ci, "Metal1",     "GatPoly",      78.653);
    addOverlapCap(ci, "Metal2",     "PWell",        18.180);
    addOverlapCap(ci, "Metal2",     "NWell",        18.180);
    addOverlapCap(ci, "Metal2",     diff_lv_nonfet, 22.916);
    addOverlapCap(ci, "Metal2",     diff_hv_nonfet, 22.844);
    addOverlapCap(ci, "Metal2",     "GatPoly",      25.537);
    addOverlapCap(ci, "Metal2",     "Metal1",       67.225);
    addOverlapCap(ci, "Metal3",     "NWell",        11.994);
    addOverlapCap(ci, "Metal3",     "PWell",        11.994);
    addOverlapCap(ci, "Metal3",     diff_lv_nonfet, 13.887);
    addOverlapCap(ci, "Metal3",     diff_hv_nonfet, 13.860);
    addOverlapCap(ci, "Metal3",     "GatPoly",      14.808);
    addOverlapCap(ci, "Metal3",     "Metal1",       23.122);
    addOverlapCap(ci, "Metal3",     "Metal2",       67.225);
    addOverlapCap(ci, "Metal4",     "NWell",         8.948);
    addOverlapCap(ci, "Metal4",     "PWell",         8.948);
    addOverlapCap(ci, "Metal4",     diff_lv_nonfet,  9.962);
    addOverlapCap(ci, "Metal4",     diff_hv_nonfet,  9.948);
    addOverlapCap(ci, "Metal4",     "GatPoly",      10.427);
    addOverlapCap(ci, "Metal4",     "Metal1",       13.962);
    addOverlapCap(ci, "Metal4",     "Metal2",       23.122);
    addOverlapCap(ci, "Metal4",     "Metal3",       67.225);
    addOverlapCap(ci, "Metal5",     "NWell",         7.136);
    addOverlapCap(ci, "Metal5",     "PWell",         7.136);
    addOverlapCap(ci, "Metal5",     diff_lv_nonfet,  7.766);
    addOverlapCap(ci, "Metal5",     diff_hv_nonfet,  7.758);
    addOverlapCap(ci, "Metal5",     "GatPoly",       8.046);
    addOverlapCap(ci, "Metal5",     "Metal1",       10.000);
    addOverlapCap(ci, "Metal5",     "Metal2",       13.962);
    addOverlapCap(ci, "Metal5",     "Metal3",       23.122);
    addOverlapCap(ci, "Metal5",     "Metal4",       67.225);
    addOverlapCap(ci, "TopMetal1",  "NWell",         5.649);
    addOverlapCap(ci, "TopMetal1",  "PWell",         5.649);
    addOverlapCap(ci, "TopMetal1",  diff_lv_nonfet,  6.036);
    addOverlapCap(ci, "TopMetal1",  diff_hv_nonfet,  6.031);
    addOverlapCap(ci, "TopMetal1",  "GatPoly",       6.204);
    addOverlapCap(ci, "TopMetal1",  "Metal1",        7.304);
    addOverlapCap(ci, "TopMetal1",  "Metal2",        9.214);
    addOverlapCap(ci, "TopMetal1",  "Metal3",       12.475);
    addOverlapCap(ci, "TopMetal1",  "Metal4",       19.309);
    addOverlapCap(ci, "TopMetal1",  "Metal5",       42.708);
    addOverlapCap(ci, "TopMetal2",  "NWell",         3.233);
    addOverlapCap(ci, "TopMetal2",  "PWell",         3.233);
    addOverlapCap(ci, "TopMetal2",  diff_lv_nonfet,  3.357);
    addOverlapCap(ci, "TopMetal2",  diff_hv_nonfet,  3.355);
    addOverlapCap(ci, "TopMetal2",  "GatPoly",       3.408);
    addOverlapCap(ci, "TopMetal2",  "Metal1",        3.716);
    addOverlapCap(ci, "TopMetal2",  "Metal2",        4.154);
    addOverlapCap(ci, "TopMetal2",  "Metal3",        4.708);
    addOverlapCap(ci, "TopMetal2",  "Metal4",        5.434);
    addOverlapCap(ci, "TopMetal2",  "Metal5",        6.425);
    addOverlapCap(ci, "TopMetal2",  "TopMetal1",    12.965);

    //                 layer_name,      cap,  offset
    addSidewallCap(ci, "GatPoly",    11.722, -0.023);
    addSidewallCap(ci, "Metal1",     28.735, -0.057);
    addSidewallCap(ci, "Metal2",     40.981, -0.033);
    addSidewallCap(ci, "Metal3",     37.679, -0.045);
    addSidewallCap(ci, "Metal4",     49.526,  0.004);
    addSidewallCap(ci, "Metal5",     53.129,  0.021);
    addSidewallCap(ci, "TopMetal1", 162.172,  0.343);
    addSidewallCap(ci, "TopMetal2", 227.323,  1.893);

    //                        in_layer,       out_layer,      cap
    addSidewallOverlapCap(ci, "GatPoly",      "NWell",        44.537);
    addSidewallOverlapCap(ci, "GatPoly",      "PWell",        44.537);
    addSidewallOverlapCap(ci, "Metal1",       "NWell",        39.585);
    addSidewallOverlapCap(ci, "Metal1",       "PWell",        39.585);
    addSidewallOverlapCap(ci, "Metal1",       diff_lv_nonfet, 44.749);
    addSidewallOverlapCap(ci, "Metal1",       diff_hv_nonfet, 45.041);
    addSidewallOverlapCap(ci, "Metal1",       "GatPoly",      49.378);
    addSidewallOverlapCap(ci, "GatPoly",      "Metal1",       23.229);
    addSidewallOverlapCap(ci, "Metal2",       "NWell",        34.798);
    addSidewallOverlapCap(ci, "Metal2",       "PWell",        34.798);
    addSidewallOverlapCap(ci, "Metal2",       diff_lv_nonfet, 36.950);
    addSidewallOverlapCap(ci, "Metal2",       diff_hv_nonfet, 36.919);
    addSidewallOverlapCap(ci, "Metal2",       "GatPoly",      37.616);
    addSidewallOverlapCap(ci, "GatPoly",      "Metal2",       10.801);
    addSidewallOverlapCap(ci, "Metal2",       "Metal1",       49.543);
    addSidewallOverlapCap(ci, "Metal1",       "Metal2",       31.073);
    addSidewallOverlapCap(ci, "Metal3",       "NWell",        31.352);
    addSidewallOverlapCap(ci, "Metal3",       "PWell",        31.352);
    addSidewallOverlapCap(ci, "Metal3",       diff_lv_nonfet, 32.271);
    addSidewallOverlapCap(ci, "Metal3",       diff_hv_nonfet, 32.495);
    addSidewallOverlapCap(ci, "Metal3",       "GatPoly",      32.795);
    addSidewallOverlapCap(ci, "GatPoly",      "Metal3",       7.068);
    addSidewallOverlapCap(ci, "Metal3",       "Metal1",       37.009);
    addSidewallOverlapCap(ci, "Metal1",       "Metal3",       17.349);
    addSidewallOverlapCap(ci, "Metal3",       "Metal2",       49.537);
    addSidewallOverlapCap(ci, "Metal2",       "Metal3",       36.907);
    addSidewallOverlapCap(ci, "Metal4",       "NWell",        29.083);
    addSidewallOverlapCap(ci, "Metal4",       "PWell",        29.083);
    addSidewallOverlapCap(ci, "Metal4",       diff_lv_nonfet, 29.755);
    addSidewallOverlapCap(ci, "Metal4",       diff_hv_nonfet, 29.942);
    addSidewallOverlapCap(ci, "Metal4",       "GatPoly",      30.101);
    addSidewallOverlapCap(ci, "GatPoly",      "Metal4",        5.240);
    addSidewallOverlapCap(ci, "Metal4",       "Metal1",       32.162);
    addSidewallOverlapCap(ci, "Metal1",       "Metal4",       12.398);
    addSidewallOverlapCap(ci, "Metal4",       "Metal2",       36.335);
    addSidewallOverlapCap(ci, "Metal2",       "Metal4",       22.327);
    addSidewallOverlapCap(ci, "Metal4",       "Metal3",       49.537);
    addSidewallOverlapCap(ci, "Metal3",       "Metal4",       40.019);
    addSidewallOverlapCap(ci, "Metal5",       "NWell",        27.527);
    addSidewallOverlapCap(ci, "Metal5",       "PWell",        27.527);
    addSidewallOverlapCap(ci, "Metal5",       diff_lv_nonfet, 28.227);
    addSidewallOverlapCap(ci, "Metal5",       diff_hv_nonfet, 28.221);
    addSidewallOverlapCap(ci, "Metal5",       "GatPoly",      28.414);
    addSidewallOverlapCap(ci, "GatPoly",      "Metal5",        4.178);
    addSidewallOverlapCap(ci, "Metal5",       "Metal1",       29.935);
    addSidewallOverlapCap(ci, "Metal1",       "Metal5",        9.725);
    addSidewallOverlapCap(ci, "Metal5",       "Metal2",       32.116);
    addSidewallOverlapCap(ci, "Metal2",       "Metal5",       16.534);
    addSidewallOverlapCap(ci, "Metal5",       "Metal3",       36.971);
    addSidewallOverlapCap(ci, "Metal3",       "Metal5",       24.785);
    addSidewallOverlapCap(ci, "Metal5",       "Metal4",       49.517);
    addSidewallOverlapCap(ci, "Metal4",       "Metal5",       41.956);
    
    addSidewallOverlapCap(ci, "TopMetal1",    "NWell",        37.383);
    addSidewallOverlapCap(ci, "TopMetal1",    "PWell",        37.383);
    addSidewallOverlapCap(ci, "TopMetal1",    diff_lv_nonfet, 38.084);
    addSidewallOverlapCap(ci, "TopMetal1",    diff_hv_nonfet, 38.085);
    addSidewallOverlapCap(ci, "TopMetal1",    "GatPoly",      38.376);
    addSidewallOverlapCap(ci, "GatPoly",      "TopMetal1",     3.316);
    addSidewallOverlapCap(ci, "TopMetal1",    "Metal1",       39.678);
    addSidewallOverlapCap(ci, "Metal1",       "TopMetal1",     7.669);
    addSidewallOverlapCap(ci, "TopMetal1",    "Metal2",       42.268);
    addSidewallOverlapCap(ci, "Metal2",       "TopMetal1",    12.649);
    addSidewallOverlapCap(ci, "TopMetal1",    "Metal3",       46.611);
    addSidewallOverlapCap(ci, "Metal3",       "TopMetal1",    17.848);
    addSidewallOverlapCap(ci, "TopMetal1",    "Metal4",       52.657);
    addSidewallOverlapCap(ci, "Metal4",       "TopMetal1",    24.526);
    addSidewallOverlapCap(ci, "TopMetal1",    "Metal5",       65.859);
    addSidewallOverlapCap(ci, "Metal5",       "TopMetal1",    36.377);
    
    addSidewallOverlapCap(ci, "TopMetal2",    "NWell",        31.175);
    addSidewallOverlapCap(ci, "TopMetal2",    "PWell",        31.175);
    addSidewallOverlapCap(ci, "TopMetal2",    diff_lv_nonfet, 31.484);
    addSidewallOverlapCap(ci, "TopMetal2",    diff_hv_nonfet, 30.835);
    addSidewallOverlapCap(ci, "TopMetal2",    "GatPoly",      30.971);
    addSidewallOverlapCap(ci, "GatPoly",      "TopMetal2",     1.909);
    addSidewallOverlapCap(ci, "TopMetal2",    "Metal1",       32.318);
    addSidewallOverlapCap(ci, "Metal1",       "TopMetal2",     4.344);
    addSidewallOverlapCap(ci, "TopMetal2",    "Metal2",       33.245);
    addSidewallOverlapCap(ci, "Metal2",       "TopMetal2",     6.975);
    addSidewallOverlapCap(ci, "TopMetal2",    "Metal3",       34.339);
    addSidewallOverlapCap(ci, "Metal3",       "TopMetal2",     9.381);
    addSidewallOverlapCap(ci, "TopMetal2",    "Metal4",       35.630);
    addSidewallOverlapCap(ci, "Metal4",       "TopMetal2",    11.825);
    addSidewallOverlapCap(ci, "TopMetal2",    "Metal5",       37.206);
    addSidewallOverlapCap(ci, "Metal5",       "TopMetal2",    14.415);
    addSidewallOverlapCap(ci, "TopMetal2",    "TopMetal1",    44.735);
    addSidewallOverlapCap(ci, "TopMetal1",    "TopMetal2",    33.071);
}

void buildTech(kpex::tech::Technology &tech) {
    tech.set_name("ihp_sg13g2");
    
    buildLayers(&tech);

    buildLVSComputedLayers(&tech);
    
    kpex::tech::ProcessStackInfo *psi = tech.mutable_process_stack();
    buildProcessStackInfo(psi);
    
    kpex::tech::ProcessParasiticsInfo *ex = tech.mutable_process_parasitics();
    buildProcessParasiticsInfo(ex);
}

}
