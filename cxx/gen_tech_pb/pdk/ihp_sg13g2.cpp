/*
 * --------------------------------------------------------------------------------
 * SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
 * Johannes Kepler University, Institute for Integrated Circuits.
 *
 * This file is part of KPEX 
 * (see https://github.com/martinjankoehler/klayout-pex).
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

#include "proto.h"
#include <vector>

namespace ihp_sg13g2 {

void buildLayers(kpex::tech::Technology::Builder *tech) {
    setLayerInfos(tech, {
        // name,   drw_gds, pin_gds, label_gds, description
        {"Activ",       1,0,   1,2,  -1,-1, "Active (diffusion) area"}, // ~ diff.drawing
        {"NWell",      31,0,  31,2,  -1,-1, "N-well region"},
        {"PWell",      46,0,  46,2,  -1,-1, "P-well region"},
        {"nSD",         7,0, -1,-1,  -1,-1, "Defines areas to receive N+ S/D implant"},
        {"pSD",        14,0, -1,-1,  -1,-1, "Defines areas to receive P+ S/D implant"},
        {"GatPoly",     5,0,   5,2,  -1,-1, "Poly"}, // ~ poly.drawing
        {"Cont",        6,0, -1,-1,  -1,-1, "Defines 1-st metal contacts to Activ, GatPoly"},
        {"Metal1",      8,0,   8,2,   8,25, "Defines 1-st metal interconnect"},
        {"Via1",       19,0, -1,-1,  -1,-1, "Defines 1-st metal to 2-nd metal contact"},
        {"Metal2",     10,0,  10,2,  10,25, "Defines 2-nd metal interconnect"},
        {"Via2",       29,0, -1,-1,  -1,-1, "Defines 2-nd metal to 3-rd metal contact"},
        {"Metal3",     30,0,  30,2,  30,25, "Defines 3-rd metal interconnect"},
        {"Via3",       49,0, -1,-1,  -1,-1, "Defines 3-rd metal to 4-th metal contact"},
        {"Metal4",     50,0,  50,2,  50,25, "Defines 4-th metal interconnect"},
        {"Via4",       66,0, -1,-1,  -1,-1, "Defines 4-th metal to 5-th metal contact"},
        {"Metal5",     67,0,  67,2,  67,25, "Defines 5-th metal interconnect"},
        {"TopVia1",   125,0, -1,-1,  -1,-1, "Defines 3-rd (or 5-th) metal to TopMetal1 contact"},
        {"TopMetal1", 126,0, 126,2, 126,25, "Defines 1-st thick TopMetal layer"},
        {"TopVia2",   133,0, -1,-1,  -1,-1, "Defines via between TopMetal1 and TopMetal2"},
        {"TopMetal2", 134,0, 134,2, 134,25, "Defines 2-nd thick TopMetal layer"}
    });
}

void buildLVSComputedLayers(kpex::tech::Technology::Builder *tech) {
    kpex::tech::ComputedLayerInfo::Kind KREG = kpex::tech::ComputedLayerInfo::Kind::REGULAR;
    kpex::tech::ComputedLayerInfo::Kind KCAP = kpex::tech::ComputedLayerInfo::Kind::DEVICE_CAPACITOR;
    kpex::tech::ComputedLayerInfo::Kind KRES = kpex::tech::ComputedLayerInfo::Kind::DEVICE_RESISTOR;
    kpex::tech::ComputedLayerInfo::Kind KPIN = kpex::tech::ComputedLayerInfo::Kind::PIN;

    setLvsComputedLayerInfos(tech, {
        // kind  lvs_name     lvs_gds_pair  orig. layer   description
        {KREG, "cont_drw",        6, 0,    "Cont", "Computed layer for contact to Metal1"},
        {KREG, "metal1_con",      8, 0,    "Metal1", "Computed layer for Metal1"},
        {KREG, "metal2_con",     10, 0,    "Metal2", "Computed layer for Metal2"},
        {KREG, "metal3_con",     30, 0,    "Metal3", "Computed layer for Metal3"},
        {KREG, "metal4_con",     50, 0,    "Metal4", "Computed layer for Metal4"},
        {KREG, "metal5_n_cap",   67, 200,  "Metal5", "Computed layer for Metal5, case where no MiM cap"},
        {KREG, "topmetal1_con", 126, 0,    "TopMetal1", "Computed layer for TopMetal1"},
        {KREG, "topmetal2_con", 134, 0,    "TopMetal2", "Computed layer for TopMetal2"},
        {KREG, "nsd_fet",         7, 0,   "nSD", "Computed layer for nSD"},
        {KREG, "psd_fet",        14, 0,  "pSD", "Computed layer for pSD"},
        {KREG, "ntap",           65, 144, "Activ", "Computed layer for ntap"},
        {KREG, "ptap",           65, 244, "Activ", "Computed layer for ptap"},
        {KREG, "pwell",          46, 0,   "PWell", "Computed layer for PWell"},
        {KREG, "pwell_sub",      46, 0,   "PWell", "Computed layer for PWell"},
        {KREG, "nwell_drw",      31, 0,   "NWell", "Computed layer for NWell"},
        {KREG, "poly_con",        5, 0,    "GatPoly", "Computed layer for GatPoly"},
        {KREG, "via1_drw", 19, 0, "Via1", "Computed layer for Via1"},
        {KREG, "via2_drw", 29, 0, "Via2", "Computed layer for Via2"},
        {KREG, "via3_drw", 49, 0, "Via3", "Computed layer for Via3"},
        {KREG, "via4_drw", 66, 0, "Via4", "Computed layer for Via4"},
        {KREG, "topvia1_n_cap", 125, 200, "TopVia1", "Original TopVia1 is 125/0, case where no MiM cap"},
        {KREG, "topvia2_drw", 133, 0, "TopVia2", "Computed layer for TopVia2"},
        {KCAP, "mim_via",  125, 10, "TopVia1", "Original TopVia1 is 125/0, case MiM cap"},
        {KCAP, "metal5_cap",   67, 100,  "Metal5", "Computed layer for Metal5, case MiM cap"},
        {KCAP, "cmim_top",   36, 0,  "<TODO>", "Computed layer for MiM cap above Metal5"}
    });
    // NOTE: there are no existing SPICE models for MOM caps (as was with sky130A)
    //       otherwise they should also be declared as ComputedLayerInfo::Kind::DEVICE_CAPACITOR
    //       and extracted accordingly in the LVS script, to allow blackboxing
    
    // TODO: add KPIN pin layers!
}

void buildProcessStackInfo(kpex::tech::ProcessStackInfo::Builder *psi) {
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
    

    ::capnp::List< ::kpex::tech::ProcessStackInfo::LayerInfo>::Builder layers = psi->initLayers(128); // truncate later
    uint i = 0; // next layer index

    // SUBSTRATE:                   name    height   thickness         reference
    //                                       (below height 0)
    //-----------------------------------------------------------------------------------------------
    setSubstrateLayer(layers[i++], "subs",  0.0,     0.28,             "fox");
    
    auto nwell_idx = i++;
    auto diff_idx = i++;

    // NWELL/DIFF:                       name     z      ref
    //                                           (TODO)
    //-----------------------------------------------------------------------------------------------
    setNWellLayer(layers[nwell_idx],    "ntap",  0.0,    "fox");
    setDiffusionLayer(layers[diff_idx], "ptap",  0.0,    "fox");
    
    // FOX:                         name     dielectric_k
    //-----------------------------------------------------------------------------------------------
    setFieldOxideLayer(layers[i++], "fox",   3.95); // from SG13G2_os_process_spec.pdf p6
    
    auto poly_idx = i++;

    // METAL:                       name,      z,           thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[poly_idx], "GatPoly", poly_z, poly_thickness);
    // thickness: from SG13G2_os_process_spec.pdf p17
    
    // DIELECTRIC (conformal)           name,    dielectric_k,   thickness,   thickness,      thickness, ref
    //                                                   over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    setConformalDielectric(layers[i++], "nitride",        6.5,         0.05,            0.05,      0.05,  "GatPoly");
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "ild0",   4.1,          "fox");
    
    auto met1_idx = i++;

    // METAL:                       name,     z,      thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[met1_idx], "Metal1", met1_z, met1_thickness);
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "ild1",   4.1,          "ild0");
    
    auto met2_idx = i++;

    // METAL:                       name,     z,      thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[met2_idx], "Metal2", met2_z, met2_thickness);
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "ild2",   4.1,          "ild1");
    
    auto met3_idx = i++;

    // METAL:                      name,     z,      thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[met3_idx], "Metal3", met3_z, met3_thickness);
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "ild3",   4.1,          "ild2");
    
    auto met4_idx = i++;
    
    // METAL:                       name,     z,      thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[met4_idx], "Metal4", met4_z, met4_thickness);
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "ild4",   4.1,          "ild3");
    
    auto met5_ncap_idx = i++;
    
    // METAL:                            name,           z,           thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[met5_ncap_idx], "metal5_n_cap", met5_z, met5_thickness);
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "ildtm1",   4.1,        "ild4");
    
    auto met5_cap_idx = i++;
    
    // METAL:                           name,        z,      thickness
    //-----------------------------------------------------------------------------------------------------------
    setMetalLayer(layers[met5_cap_idx], "metal5_cap", met5_z, met5_thickness);
    
    // DIELECTRIC (conformal)          name,    dielectric_k, thickness,        thickness,      thickness, ref
    //                                                        over metal,       where no metal, sidewall
    //------------------------------------------------------------------------------------------------------------
    setConformalDielectric(layers[i++], "ismim", capild_k,     capild_thickness, 0.0,            0.0,       "metal5_cap");
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //----------------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "ildtm1",   4.1,        "ild4");
    
    auto cmim_cap_idx = i++;

    // METAL:                           name,      z,      thickness
    //----------------------------------------------------------------------------------------------------
    setMetalLayer(layers[cmim_cap_idx], "cmim_top", cmim_z, cmim_cap_thickness);
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //----------------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "ildtm1",   4.1,        "ild4");

    auto topmet1_idx = i++;

    // METAL:                           name,      z,         thickness
    //----------------------------------------------------------------------------------------------------
    setMetalLayer(layers[topmet1_idx], "TopMetal1", topmet1_z, topmet1_thickness);
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //----------------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "ildtm2",   4.1,        "ildtm1");
    
    auto topmet2_idx = i++;
    
    // METAL:                           name,      z,         thickness
    //----------------------------------------------------------------------------------------------------
    setMetalLayer(layers[topmet2_idx], "TopMetal2", topmet2_z, topmet2_thickness);
    
    // DIELECTRIC (conformal)          name,    dielectric_k, thickness,        thickness,      thickness, ref
    //                                                        over metal,       where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    setConformalDielectric(layers[i++], "pass1",          4.1,         1.5,            1.5,      0.3,    "TopMetal2");
    
    // DIELECTRIC (conformal)          name,    dielectric_k, thickness,        thickness,      thickness, ref
    //                                                        over metal,       where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    setConformalDielectric(layers[i++], "pass2",          6.6,         0.4,            0.4,      0.3,    "pass1");
    
    // DIELECTRIC (simple)   name,    dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "air",   1.0,          "pass2");
    
    auto contn = layers[nwell_idx].getNwellLayer().initContactAbove();
    auto contd = layers[diff_idx].getDiffusionLayer().initContactAbove();
    auto contp = layers[poly_idx].getMetalLayer().initContactAbove();
    auto via1 = layers[met1_idx].getMetalLayer().initContactAbove();
    auto via2 = layers[met2_idx].getMetalLayer().initContactAbove();
    auto via3 = layers[met3_idx].getMetalLayer().initContactAbove();
    auto via4 = layers[met4_idx].getMetalLayer().initContactAbove();
    auto topvia1_n_cap = layers[met5_ncap_idx].getMetalLayer().initContactAbove();
    auto mim_via = layers[cmim_cap_idx].getMetalLayer().initContactAbove();
    auto topvia2 = layers[topmet1_idx].getMetalLayer().initContactAbove();
    
    // CONTACT:                contact,         layer_below, metal_above,   thickness,               width, spacing,         border
    //----------------------------------------------------------------------------------------------------------------------------
    setContact(&contn,         "Cont",          "",          "Metal1",      0.4 + 0.64,              0.16,   0.18 /*TODO*/,  0.0);
    setContact(&contd,         "Cont",          "",          "Metal1",      0.4 + 0.64,              0.16,   0.18 /*TODO*/,  0.0);
    setContact(&contp,         "Cont",          "GatPoly",   "Metal1",      conp_thickness,          0.19,   0.22 /*TODO*/,  0.0);
    setContact(&via1,          "Via1",          "Metal1",    "Metal2",      via1_thickness,          0.19,   0.22 /*TODO*/,  0.0);
    setContact(&via2,          "Via2",          "Metal2",    "Metal3",      via1_thickness,          0.19,   0.22 /*TODO*/,  0.0);
    setContact(&via3,          "Via3",          "Metal3",    "Metal4",      via1_thickness,          0.19,   0.22 /*TODO*/,  0.0);
    setContact(&via4,          "Via4",          "Metal4",    "Metal5",      via1_thickness,          0.19,   0.22 /*TODO*/,  0.0);
    setContact(&topvia1_n_cap, "topvia1_n_cap", "Metal5",    "TopMetal1",   topvia1_ncap_thickness,  0.42,   0.42,           0.005 /* or 0.36*/);
    setContact(&mim_via,       "mim_via",       "cmim_top",  "TopMetal1",   mim_via_thickness,       0.42,   0.42,           0.005 /* or 0.36*/);
    setContact(&topvia2,       "TopVia2",       "TopMetal1", "TopMetal2",   topvia2_thickness,       0.9,    1.06,           0.5);
    
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

void buildProcessParasiticsInfo(kpex::tech::ProcessParasiticsInfo::Builder *ex) {
    // NOTE: coefficients according to https://github.com/IHP-GmbH/IHP-Open-PDK/blob/7897c7f99fe5538656b4c08e300cfe4d2c8a5503/ihp-sg13g2/libs.tech/magic/ihp-sg13g2.tech#L4515
    
    ex->setSideHalo(8.0);
    
    kpex::tech::ResistanceInfo::Builder ri = ex->initResistance();
    
    // resistance values are in mΩ / square
    //                          layer,     resistance
    setLayerResistances(&ri, { {"GatPoly", 48200}, // TODO: there is no value defined in the process spec!
        {"Metal1",    110},
        {"Metal2",     88},
        {"Metal3",     88},
        {"Metal4",     88},
        {"Metal5",     88},
        {"TopMetal1",  18},
        {"TopMetal2",  11} });
    
    // resistance values are in mΩ / square
    //                           contact_layer, layer_below,  resistance
    
    setContactResistance(&ri, { {"Cont",        "nSD",        17000},  // Cont over nSD-Activ
        {"Cont",        "pSD",        17000},  // Cont over pSD-Activ
        {"Cont",        "GatPoly",    15000} });  // Cont over pSD-Activ
    
    // resistance values are in mΩ / square
    //                      via_layer,  resistance
    
    setViaResistance(&ri, { {"Via1",    9000},
        {"Via2",    9000},
        {"Via3",    9000},
        {"Via4",    9000},
        {"TopVia1", 2200},
        {"TopVia2", 1100} });
    
    kpex::tech::CapacitanceInfo::Builder ci = ex->initCapacitance();
    
    //                      layer  ,    area_cap,  perimeter_cap
    setSubstrateCaps(&ci, { {"GatPoly",  87.433,   44.537},
        {"Metal1",   35.015,   39.585},
        {"Metal2",   18.180,   34.798},
        {"Metal3",   11.994,   31.352},
        {"Metal4",    8.948,   29.083},
        {"Metal5",    7.136,   27.527},
        {"TopMetal1", 5.649,   37.383},
        {"TopMetal2", 3.233,   31.175} });
    
    const std::string diff_lv_nonfet = "Activ";   // TODO: diff must be non-fet!
    const std::string diff_hv_nonfet = "Activ";   // TODO: diff must be non-fet!
    
    //                top_layer,    bottom_layer,   cap
    setOverlapCaps(&ci, { {"GatPoly",    "NWell",        87.433},
        {"GatPoly",    "PWell",        87.433},
        {"Metal1",     "PWell",        35.015},
        {"Metal1",     "NWell",        35.015},
        {"Metal1",     diff_lv_nonfet, 58.168},
        {"Metal1",     diff_hv_nonfet, 57.702},
        {"Metal1",     "GatPoly",      78.653},
        {"Metal2",     "PWell",        18.180},
        {"Metal2",     "NWell",        18.180},
        {"Metal2",     diff_lv_nonfet, 22.916},
        {"Metal2",     diff_hv_nonfet, 22.844},
        {"Metal2",     "GatPoly",      25.537},
        {"Metal2",     "Metal1",       67.225},
        {"Metal3",     "NWell",        11.994},
        {"Metal3",     "PWell",        11.994},
        {"Metal3",     diff_lv_nonfet, 13.887},
        {"Metal3",     diff_hv_nonfet, 13.860},
        {"Metal3",     "GatPoly",      14.808},
        {"Metal3",     "Metal1",       23.122},
        {"Metal3",     "Metal2",       67.225},
        {"Metal4",     "NWell",         8.948},
        {"Metal4",     "PWell",         8.948},
        {"Metal4",     diff_lv_nonfet,  9.962},
        {"Metal4",     diff_hv_nonfet,  9.948},
        {"Metal4",     "GatPoly",      10.427},
        {"Metal4",     "Metal1",       13.962},
        {"Metal4",     "Metal2",       23.122},
        {"Metal4",     "Metal3",       67.225},
        {"Metal5",     "NWell",         7.136},
        {"Metal5",     "PWell",         7.136},
        {"Metal5",     diff_lv_nonfet,  7.766},
        {"Metal5",     diff_hv_nonfet,  7.758},
        {"Metal5",     "GatPoly",       8.046},
        {"Metal5",     "Metal1",       10.000},
        {"Metal5",     "Metal2",       13.962},
        {"Metal5",     "Metal3",       23.122},
        {"Metal5",     "Metal4",       67.225},
        {"TopMetal1",  "NWell",         5.649},
        {"TopMetal1",  "PWell",         5.649},
        {"TopMetal1",  diff_lv_nonfet,  6.036},
        {"TopMetal1",  diff_hv_nonfet,  6.031},
        {"TopMetal1",  "GatPoly",       6.204},
        {"TopMetal1",  "Metal1",        7.304},
        {"TopMetal1",  "Metal2",        9.214},
        {"TopMetal1",  "Metal3",       12.475},
        {"TopMetal1",  "Metal4",       19.309},
        {"TopMetal1",  "Metal5",       42.708},
        {"TopMetal2",  "NWell",         3.233},
        {"TopMetal2",  "PWell",         3.233},
        {"TopMetal2",  diff_lv_nonfet,  3.357},
        {"TopMetal2",  diff_hv_nonfet,  3.355},
        {"TopMetal2",  "GatPoly",       3.408},
        {"TopMetal2",  "Metal1",        3.716},
        {"TopMetal2",  "Metal2",        4.154},
        {"TopMetal2",  "Metal3",        4.708},
        {"TopMetal2",  "Metal4",        5.434},
        {"TopMetal2",  "Metal5",        6.425},
        {"TopMetal2",  "TopMetal1",    12.965} });
    
    //                 layer_name,      cap,  offset
    setSidewallCaps(&ci, { {"GatPoly",    11.722, -0.023},
        {"Metal1",     28.735, -0.057},
        {"Metal2",     40.981, -0.033},
        {"Metal3",     37.679, -0.045},
        {"Metal4",     49.526,  0.004},
        {"Metal5",     53.129,  0.021},
        {"TopMetal1", 162.172,  0.343},
        {"TopMetal2", 227.323,  1.893} });
    
    //                   in_layer,       out_layer,      cap
    setFringeCaps(&ci, { {"GatPoly",      "NWell",        44.537},
                         {"GatPoly",      "PWell",        44.537},
                         {"Metal1",       "NWell",        39.585},
                         {"Metal1",       "PWell",        39.585},
                         {"Metal1",       diff_lv_nonfet, 44.749},
                         {"Metal1",       diff_hv_nonfet, 45.041},
                         {"Metal1",       "GatPoly",      49.378},
                         {"GatPoly",      "Metal1",       23.229},
                         {"Metal2",       "NWell",        34.798},
                         {"Metal2",       "PWell",        34.798},
                         {"Metal2",       diff_lv_nonfet, 36.950},
                         {"Metal2",       diff_hv_nonfet, 36.919},
                         {"Metal2",       "GatPoly",      37.616},
                         {"GatPoly",      "Metal2",       10.801},
                         {"Metal2",       "Metal1",       49.543},
                         {"Metal1",       "Metal2",       31.073},
                         {"Metal3",       "NWell",        31.352},
                         {"Metal3",       "PWell",        31.352},
                         {"Metal3",       diff_lv_nonfet, 32.271},
                         {"Metal3",       diff_hv_nonfet, 32.495},
                         {"Metal3",       "GatPoly",      32.795},
                         {"GatPoly",      "Metal3",        7.068},
                         {"Metal3",       "Metal1",       37.009},
                         {"Metal1",       "Metal3",       17.349},
                         {"Metal3",       "Metal2",       49.537},
                         {"Metal2",       "Metal3",       36.907},
                         {"Metal4",       "NWell",        29.083},
                         {"Metal4",       "PWell",        29.083},
                         {"Metal4",       diff_lv_nonfet, 29.755},
                         {"Metal4",       diff_hv_nonfet, 29.942},
                         {"Metal4",       "GatPoly",      30.101},
                         {"GatPoly",      "Metal4",        5.240},
                         {"Metal4",       "Metal1",       32.162},
                         {"Metal1",       "Metal4",       12.398},
                         {"Metal4",       "Metal2",       36.335},
                         {"Metal2",       "Metal4",       22.327},
                         {"Metal4",       "Metal3",       49.537},
                         {"Metal3",       "Metal4",       40.019},
                         {"Metal5",       "NWell",        27.527},
                         {"Metal5",       "PWell",        27.527},
                         {"Metal5",       diff_lv_nonfet, 28.227},
                         {"Metal5",       diff_hv_nonfet, 28.221},
                         {"Metal5",       "GatPoly",      28.414},
                         {"GatPoly",      "Metal5",        4.178},
                         {"Metal5",       "Metal1",       29.935},
                         {"Metal1",       "Metal5",        9.725},
                         {"Metal5",       "Metal2",       32.116},
                         {"Metal2",       "Metal5",       16.534},
                         {"Metal5",       "Metal3",       36.971},
                         {"Metal3",       "Metal5",       24.785},
                         {"Metal5",       "Metal4",       49.517},
                         {"Metal4",       "Metal5",       41.956},
                         {"TopMetal1",    "NWell",        37.383},
                         {"TopMetal1",    "PWell",        37.383},
                         {"TopMetal1",    diff_lv_nonfet, 38.084},
                         {"TopMetal1",    diff_hv_nonfet, 38.085},
                         {"TopMetal1",    "GatPoly",      38.376},
                         {"GatPoly",      "TopMetal1",     3.316},
                         {"TopMetal1",    "Metal1",       39.678},
                         {"Metal1",       "TopMetal1",     7.669},
                         {"TopMetal1",    "Metal2",       42.268},
                         {"Metal2",       "TopMetal1",    12.649},
                         {"TopMetal1",    "Metal3",       46.611},
                         {"Metal3",       "TopMetal1",    17.848},
                         {"TopMetal1",    "Metal4",       52.657},
                         {"Metal4",       "TopMetal1",    24.526},
                         {"TopMetal1",    "Metal5",       65.859},
                         {"Metal5",       "TopMetal1",    36.377},
                         {"TopMetal2",    "NWell",        31.175},
                         {"TopMetal2",    "PWell",        31.175},
                         {"TopMetal2",    diff_lv_nonfet, 31.484},
                         {"TopMetal2",    diff_hv_nonfet, 30.835},
                         {"TopMetal2",    "GatPoly",      30.971},
                         {"GatPoly",      "TopMetal2",     1.909},
                         {"TopMetal2",    "Metal1",       32.318},
                         {"Metal1",       "TopMetal2",     4.344},
                         {"TopMetal2",    "Metal2",       33.245},
                         {"Metal2",       "TopMetal2",     6.975},
                         {"TopMetal2",    "Metal3",       34.339},
                         {"Metal3",       "TopMetal2",     9.381},
                         {"TopMetal2",    "Metal4",       35.630},
                         {"Metal4",       "TopMetal2",    11.825},
                         {"TopMetal2",    "Metal5",       37.206},
                         {"Metal5",       "TopMetal2",    14.415},
                         {"TopMetal2",    "TopMetal1",    44.735},
                         {"TopMetal1",    "TopMetal2",    33.071} } );
}

void buildTech(kpex::tech::Technology::Builder &tech) {
    tech.setName("ihp_sg13g2");
    
    buildLayers(&tech);

    buildLVSComputedLayers(&tech);
    
    auto psi = tech.initProcessStack();
    buildProcessStackInfo(&psi);
    
    auto ex = tech.initProcessParasitics();
    buildProcessParasiticsInfo(&ex);
}

}
