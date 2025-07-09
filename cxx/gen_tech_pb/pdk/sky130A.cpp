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
// This creates a technology definition example for sky130A:
// https://skywater-pdk.readthedocs.io/en/main/_images/metal_stack.svg
//

#include "proto.h"
#include <vector>
#include <capnp/orphan.h>

namespace sky130A {

void buildLayers(kpex::tech::Technology::Builder *tech) {
    setLayerInfos(tech, {
        // name,   drw_gds, pin_gds, label_gds, description
        {"dnwell", 64,18,   -1,-1,  -1,-1,  "Deep N-well"},
        {"nwell",  64,20,   64,16,   64,5,   "N-well region"},
        {"diff",   65,20,   65,16,   65,5,   "Active (diffusion) area"},
        {"tap",    65,44,   -1,-1,  -1,-1,  "Active (diffusion) area (type equal to the rate underneath) (i.e., N+ and P+)"},
        {"psdm",   94,20,   -1,-1,  -1,-1,  "P+ source/drain implant"},
        {"nsdm",   93,44,   -1,-1,  -1,-1,  "N+ source/drain implant"},
        {"poly",   66,20,   66,16,   66,5,   "Polysilicon"},
        {"licon1", 66,44,   -1,-1,  -1,-1,  "Contact to local interconnect"},
        {"li1",    67,20,   67,16,   67,5,   "Local interconnect"},
        {"mcon",   67,44,   -1,-1,  -1,-1,  "Contact from local interconnect to met1"},
        {"met1",   68,20,  68,16,   68,5,   "Metal 1"},
        {"via",    68,44,  -1,-1,  -1,-1,  "Contact from met1 to met2"},
        {"met2",   69,20,  69,16,   69,5,   "Metal 2"},
        {"via2",   69,44,  -1,-1,  -1,-1,  "Contact from met2 to met3"},
        {"met3",   70,20,  70,16,   70,5,   "Metal 3"},
        {"via3",   70,44,  -1,-1,  -1,-1,  "Contact from cap above met3 to met4"},
        {"capm",   89,44,  -1,-1,  -1,-1,  "MiM capacitor plate over metal 3"},
        {"met4",   71,20,  71,16,   71,5,   "Metal 4"},
        {"capm2",  97,44,  -1,-1,  -1,-1,  "MiM capacitor plate over metal 4"},
        {"via4",   71,44,  -1,-1,  -1,-1,  "Contact from met4 to met5 (no MiM cap)"},
        {"met5",   72,20,  72,16,  72,5,   "Metal 5"},
    });
}

void buildLVSComputedLayers(kpex::tech::Technology::Builder *tech) {
    kpex::tech::ComputedLayerInfo::Kind KREG = kpex::tech::ComputedLayerInfo::Kind::REGULAR;
    kpex::tech::ComputedLayerInfo::Kind KCAP = kpex::tech::ComputedLayerInfo::Kind::DEVICE_CAPACITOR;
    kpex::tech::ComputedLayerInfo::Kind KRES = kpex::tech::ComputedLayerInfo::Kind::DEVICE_RESISTOR;
    kpex::tech::ComputedLayerInfo::Kind KPIN = kpex::tech::ComputedLayerInfo::Kind::PIN;
    
    setLvsComputedLayerInfos(tech, {
        //                     kind  lvs_name lvs_gds_pair  orig. layer   description
        {KREG, "dnwell",    64, 18,  "dnwell",     "Deep NWell"},
        {KREG, "li_con",    67, 20,  "li1",    "Computed layer for li"},
        {KREG, "licon",     66, 44,  "licon1", "Computed layer for contact to li"},
        {KREG, "mcon_con",  67, 44,  "mcon", ""},
        {KREG, "met1_con",  68, 20,  "met1", ""},
        {KREG, "met2_con",  69, 20,  "met2", ""},
        {KREG, "met3_ncap", 70, 20,  "met3", ""},
        {KREG, "met4_ncap", 71, 20,  "met4", ""},
        {KREG, "met5_con",  72, 20,  "met5", ""},
        {KREG, "nsd",       93, 44,  "nsdm", "borrow from nsdm"},
        {KREG, "ntap_conn", 65, 144, "tap", "Separate ntap, original tap is 65,44, we need seperate ntap/ptap"},
        {KREG, "nwell",     64, 20,  "nwell", ""},
        {KREG, "poly_con",  66, 20,  "poly", ""},
        {KREG, "psd",       94, 20,  "psdm", "borrow from psdm"},
        {KREG, "ptap_conn", 65, 244, "tap", "Separate ptap, original tap is 65,44, we need seperate ntap/ptap"},
        {KREG, "via1_con",  68, 44,  "via1", ""},
        {KREG, "via2_con",  69, 44,  "via2", ""},
        {KREG, "via3_ncap", 70, 144, "via3", "Original via3 is 70,44, case where no MiM cap"},
        {KREG, "via4_ncap", 71, 144, "via4", "Original via4 is 71,44, case where no MiM cap"},
        {KREG, "via3_cap",  70, 244, "via3", "Original via3 is 70,44, via above metal 3 MIM cap"},
        {KREG, "via4_cap",  71, 244, "via4", "Original via3 is 71,44, via above metal 4 MIM cap"},

        {KCAP, "poly_vpp",  66, 20,  "poly", "Capacitor device metal"},
        {KCAP, "li_vpp",    67, 20,  "li1", "Capacitor device metal"},
        {KCAP, "met1_vpp",  68, 20,  "met1", "Capacitor device metal"},
        {KCAP, "met2_vpp",  69, 20,  "met2", "Capacitor device metal"},
        {KCAP, "met3_vpp",  70, 20,  "met3", "Capacitor device metal"},
        {KCAP, "met4_vpp",  71, 20,  "met4", "Capacitor device metal"},
        {KCAP, "met5_vpp",  72, 20,  "met5", "Capacitor device metal"},
        {KCAP, "licon_vpp", 66, 44,  "licon1", "Capacitor device contact"},
        {KCAP, "mcon_vpp",  67, 44,  "mcon", "Capacitor device contact"},
        {KCAP, "via1_vpp",  68, 44,  "via1", "Capacitor device contact"},
        {KCAP, "via2_vpp",  69, 44,  "via2", "Capacitor device contact"},
        {KCAP, "via3_vpp",  70, 44,  "via3", "Capacitor device contact"},
        {KCAP, "via4_vpp",  71, 44,  "via4", "Capacitor device contact"},
        {KCAP, "met3_cap",  70, 220, "met3", "metal3 part of MiM cap"},
        {KCAP, "met4_cap",  71, 220, "met4", "metal4 part of MiM cap"},
        {KCAP, "capm",      89, 44,  "capm", "MiM cap above metal3"},
        {KCAP, "capm2",     97, 44,  "capm2", "MiM cap above metal4"},

        {KPIN, "poly_pin_con", 66, 16,  "poly.pin", "Poly pin"},
        {KPIN, "li_pin_con",   67, 16,  "li1.pin",  "li1 pin"},
        {KPIN, "met1_pin_con", 68, 16,  "met1.pin", "met1 pin"},
        {KPIN, "met2_pin_con", 69, 16,  "met2.pin", "met2 pin"},
        {KPIN, "met3_pin_con", 70, 16,  "met3.pin", "met3 pin"},
        {KPIN, "met4_pin_con", 71, 16,  "met4.pin", "met4 pin"},
        {KPIN, "met5_pin_con", 72, 16,  "met5.pin", "met5 pin"}
    });
}

void buildProcessStackInfo(kpex::tech::ProcessStackInfo::Builder *psi) {
    ::capnp::List< ::kpex::tech::ProcessStackInfo::LayerInfo>::Builder layers = psi->initLayers(128); // truncate later
    uint i = 0; // next layer index

    // SUBSTRATE:                   name    height   thickness   reference
    //                                       (TODO)   (TODO)
    //-----------------------------------------------------------------------------------------------
    setSubstrateLayer(layers[i++], "subs",  0.1,     0.33,       "fox");
    
    auto nwell_idx = i++;
    auto diff_idx = i++;
    
    // NWELL/DIFF:                       name     z      ref
    //                                           (TODO)
    //-----------------------------------------------------------------------------------------------
    setNWellLayer(layers[nwell_idx],    "nwell", 0.1,    "fox");
    setDiffusionLayer(layers[diff_idx], "diff",  0.323,  "fox");
    
    // FOX:                         name     dielectric_k
    //-----------------------------------------------------------------------------------------------
    setFieldOxideLayer(layers[i++], "fox",   4.632);
    // NOTE: fine-tuned dielectric_k for single_plate_100um_x_100um_li1_over_substrate to match foundry table data
    
    auto poly_idx = i++;
    
    // METAL:                       name,   z,      thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[poly_idx], "poly", 0.3262, 0.18);
    
    // DIELECTRIC (sidewall)            name,    dielectric_k, height_above_metal, width_outside_sw, ref
    //-----------------------------------------------------------------------------------------------
    setSidewallDielectric(layers[i++], "iox",   0.39,         0.18,               0.006,            "poly");
    setSidewallDielectric(layers[i++], "spnit", 7.5,          0.121,              0.0431,           "iox");
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "psg",   3.9,           "fox");
    
    // METAL:                      name, z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto li1_idx = i++;
    setMetalLayer(layers[li1_idx], "li1", 0.9361, 0.1);
    
    // DIELECTRIC (conformal)           name,   dielectric_k, thickness,   thickness,      thickness  ref
    //                                                over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    setConformalDielectric(layers[i++], "lint", 7.3,          0.075,       0.075,          0.075,     "li1");
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "nild2",  4.05,         "lint");

    auto met1_idx = i++;

    // METAL:                       name,   z,      thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[met1_idx], "met1", 1.3761, 0.36);
    
    // DIELECTRIC (sidewall)           name,     dielectric_k, height_above_metal, width_outside_sw, ref
    //-----------------------------------------------------------------------------------------------
    setSidewallDielectric(layers[i++], "nild3c", 3.5,          0.0,                0.03,            "met1");
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "nild3",  4.5,         "nild2");
    
    // METAL:                       name,   z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met2_idx = i++;
    setMetalLayer(layers[met2_idx], "met2", 2.0061, 0.36);
    
    // DIELECTRIC (sidewall)           name,     dielectric_k, height_above_metal, width_outside_sw, ref
    //-----------------------------------------------------------------------------------------------
    setSidewallDielectric(layers[i++], "nild4c", 3.5,          0.0,                0.03,            "met2");
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "nild4",  4.2,         "nild3");
    
    auto met3_ncap_idx = i++;
    auto met3_cap_idx = i++;

    // METAL:                            name,        z,      thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[met3_ncap_idx], "met3_ncap", 2.7861, 0.845);
    setMetalLayer(layers[met3_cap_idx],  "met3_cap",  2.7861, 0.845);
    
    double capm_thickness = 0.1;
    double capild_k = 4.52;  // to match design cap_mim_m3_w18p9_l5p1_no_interconnect to 200fF
    double capild_thickness = 0.02;
    
    // DIELECTRIC (conformal)           name,    dielectric_k,   thickness,   thickness,      thickness,  ref
    //                                                   over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    setConformalDielectric(layers[i++], "capild", capild_k, capild_thickness,          0.0,        0.0,   "met3_cap");
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "nild5",  4.1,         "nild4");

    auto capm_idx = i++;

    // METAL:                       name,   z,                                 thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[capm_idx], "capm", 2.7861 + 0.845 + capild_thickness, capm_thickness);
    
    // DIELECTRIC (simple)           name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "nild5",  4.1,         "nild4");

    auto met4_ncap_idx = i++;

    // METAL:                            name,        z,      thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[met4_ncap_idx], "met4_ncap", 4.0211, 0.845);
    
    // DIELECTRIC (conformal)   name,    dielectric_k,   thickness,   thickness,      thickness,  ref
    //                                                   over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    setConformalDielectric(layers[i++], "capild", capild_k, capild_thickness,          0.0,        0.0,   "met4_cap");
    
    auto met4_cap_idx = i++;

    // METAL:                           name,        z,      thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[met4_cap_idx], "met4_cap",  4.0211, 0.845);
    
    // DIELECTRIC (simple)    name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "nild6",  4.0,         "nild5");

    auto capm2_idx = i++;

    // METAL:                       name,    z,                                 thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[capm2_idx], "capm2", 4.0211 + 0.845 + capild_thickness, capm_thickness);
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "nild6",  4.0,          "nild5");
    
    auto met5_idx = i++;
    
    // METAL:                      name,   z,      thickness
    //-----------------------------------------------------------------------------------------------
    setMetalLayer(layers[met5_idx], "met5", 5.3711, 1.26);
    
    // DIELECTRIC (sidewall)   name,    dielectric_k, height_above_metal, width_outside_sw, ref
    //-----------------------------------------------------------------------------------------------
    setSidewallDielectric(layers[i++], "topox", 3.9,          0.09,               0.07,            "met5");
    
    // DIELECTRIC (conformal)   name,    dielectric_k, thickness,   thickness,      thickness, ref
    //                                                 over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    setConformalDielectric(layers[i++], "topnit", 7.5,         0.54,        0.4223,         0.3777,    "topox");
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    setSimpleDielectric(layers[i++], "air",  3.0,          "topnit");
    
    auto licon1n = layers[nwell_idx].getNwellLayer().initContactAbove();
    auto licon1d = layers[diff_idx].getDiffusionLayer().initContactAbove();
    auto licon1p = layers[poly_idx].getMetalLayer().initContactAbove();
    auto mcon = layers[li1_idx].getMetalLayer().initContactAbove();
    auto via = layers[met1_idx].getMetalLayer().initContactAbove();
    auto via2 = layers[met2_idx].getMetalLayer().initContactAbove();
    auto via3_ncap = layers[met3_ncap_idx].getMetalLayer().initContactAbove();
    auto via3_cap = layers[capm_idx].getMetalLayer().initContactAbove();
    auto via4_ncap = layers[met4_ncap_idx].getMetalLayer().initContactAbove();
    auto via4_cap = layers[capm2_idx].getMetalLayer().initContactAbove();
    
    // CONTACT:           contact,     layer_below, metal_above, thickness,              width, spacing,  border
    //----------------------------------------------------------------------------------------------------------
    setContact(&licon1n,   "licon1",    "nsdm",      "li1",       0.9361,                  0.17,    0.17,  0.0);
    setContact(&licon1d,   "licon1",    "psdm",      "li1",       0.9361,                  0.17,    0.17,  0.0);
    setContact(&licon1p,   "licon1",    "poly",      "li1",       0.4299,                  0.17,    0.17,  0.0);
    setContact(&mcon,      "mcon",      "li1",       "met1",      1.3761 - (0.9361 + 0.1), 0.17,    0.19,  0.0);
    setContact(&via,       "via",       "met1",      "met2",      0.27,                    0.15,    0.17,  0.055);
    setContact(&via2,      "via2",      "met2",      "met3",      0.42,                    0.20,    0.20,  0.04);
    setContact(&via3_ncap, "via3_ncap", "met3",      "met4",      0.39,                    0.20,    0.20,  0.06);
    setContact(&via3_cap,  "via3_cap",  "met3",      "met4",      0.29,                    0.20,    0.20,  0.06);
    setContact(&via4_ncap, "via4_ncap", "met4",      "met5",      0.505,                   0.80,    0.80,  0.19);
    setContact(&via4_cap,  "via4_cap",  "met4",      "met5",      0.505 - 0.1,             0.80,    0.80,  0.19);
}

void buildProcessParasiticsInfo(kpex::tech::ProcessParasiticsInfo::Builder *ex) {
    // See  https://docs.google.com/spreadsheets/d/1N9To-xTiA7FLfQ1SNzWKe-wMckFEXVE9WPkPPjYkaxE/edit?pli=1&gid=1654372372#gid=1654372372
    
    ex->setSideHalo(8.0);
    
    
    kpex::tech::ResistanceInfo::Builder ri = ex->initResistance();
    
    // resistance values are in mΩ / square
    //                          layer, resistance
    setLayerResistances(&ri, { {"poly", 48200},  // allpolynonres
                               {"li1",  12800},
                               {"met1",   125},
                               {"met2",   125},
                               {"met3",    47},
                               {"met4",    47},
                               {"met5",    29} });
    
    // resistance values are in mΩ / square
    //                           contact_layer, layer_below,  resistance
    setContactResistance(&ri, { {"licon1",      "nsdm",       185000},    // licon over nsdm
                                {"licon1",      "psdm",       585000},    // licon over psdm
                                {"licon1",      "poly",       152000} }); // licon over poly!
    
    // resistance values are in mΩ / square
    //                       via_layer,  resistance
    setViaResistance(&ri, { {"poly",        152000},  // licon over poly!
                            {"mcon",          9300},
                            {"via",           4500},
                            {"via2",          3410},
                            {"via3",          3410},
                            {"via4",           380} });

    kpex::tech::CapacitanceInfo::Builder ci = ex->initCapacitance();
    
    //                       layer,  area_cap,  perimeter_cap
                        //  {"dnwell", 120.0,   0.0},  // TODO
    setSubstrateCaps(&ci, { {"poly", 106.13,    55.27},
                            {"li1",  36.99,     40.7},
                            {"met1", 25.78,     40.57},
                            {"met2", 17.5,      37.76},
                            {"met3", 12.37,     40.99},
                            {"met4", 8.42,      36.68},
                            {"met5", 6.32,      38.85} });
    
    const std::string diff_nonfet = "diff"; // TODO: diff must be non-fet!
    const std::string poly_nonres = "poly"; // TODO: poly must be non-res!
    const std::string all_active = "diff";   // TODO: must be allactive
    
    //                     top_layer,  bottom_layer,  cap
    //                    { "pwell", "dnwell",     120.0); // TODO
    setOverlapCaps(&ci, { {"pwell",    "dnwell",     120.0}, // TODO
                          {"poly",     "nwell",      106.13},
                          {"poly",     "pwell",      106.13},
                          {"li1",      "pwell",      36.99},
                          {"li1",      "nwell",      36.99},
                          {"li1",      "nwell",      36.99},
                          {"li1",      diff_nonfet,  55.3},
                          {"li1",      "poly",       94.16},
                          {"met1",     "pwell",      25.78},
                          {"met1",     "nwell",      25.78},
                          {"met1",     diff_nonfet,  33.6},
                          {"met1",     poly_nonres,  44.81},
                          {"met1",     "li1",        114.20},
                          {"met2",     "nwell",      17.5},
                          {"met2",     "pwell",      17.5},
                          {"met2",     diff_nonfet,  20.8},
                          {"met2",     poly_nonres,  24.50},
                          {"met2",     "li1",        37.56},
                          {"met2",     "met1",       133.86},
                          {"met3",     "nwell",      12.37},
                          {"met3",     "pwell",      12.37},
                          {"met3",     all_active,   14.2},
                          {"met3",     poly_nonres,  16.06},
                          {"met3",     "li1",        20.79},
                          {"met3",     "met1",       34.54},
                          {"met3",     "met2",       86.19},
                          {"met4",     "nwell",      8.42},
                          {"met4",     "pwell",      8.42},
                          {"met4",     all_active,   9.41},
                          {"met4",     poly_nonres,  10.01},
                          {"met4",     "li1",        11.67},
                          {"met4",     "met1",       15.03},
                          {"met4",     "met2",       20.33},
                          {"met4",     "met3",       84.03},
                          {"met5",     "nwell",      6.32},
                          {"met5",     "pwell",      6.32},
                          {"met5",     all_active,   6.88},
                          {"met5",     poly_nonres,  7.21},
                          {"met5",     "li1",        8.03},
                          {"met5",     "met1",       9.48},
                          {"met5",     "met2",       11.34},
                          {"met5",     "met3",       19.63},
                          {"met5",     "met4",       68.33} });
    
    //                   layer_name, cap,  offset
    setSidewallCaps(&ci, { {"poly",  16.0, 0.0},
                           {"li1",   25.5, 0.14},
                           {"met1",  44.0, 0.25},
                           {"met2",  50.0, 0.3},
                           {"met3",  74.0, 0.4},
                           {"met4",  94.0, 0.57},
                           {"met5", 155.0, 0.5} });
    
    //                    in_layer,    out_layer,   cap
    setFringeCaps(&ci, { {"poly",      "nwell",     55.27},
                         {"poly",      "pwell",     55.27},
                         {"li1",       "nwell",     40.70},
                         {"li1",       "pwell",     40.70},
                         {"li1",       diff_nonfet, 44.27},
                         {"li1",       poly_nonres, 51.85},
                         {"poly",      "li1",       25.14},
                         {"met1",      "nwell",     40.57},
                         {"met1",      "pwell",     40.57},
                         {"met1",      diff_nonfet, 43.10},
                         {"met1",      poly_nonres, 46.72},
                         {"poly",      "met1",      16.69},
                         {"met1",      "li1",       59.50},
                         {"li1",       "met1",      34.70},
                         {"met2",      "nwell",     37.76},
                         {"met2",      "pwell",     37.76},
                         {"met2",      diff_nonfet, 39.54},
                         {"met2",      poly_nonres, 41.22},
                         {"poly",      "met2",      11.17},
                         {"met2",      "li1",       46.28},
                         {"li1",       "met2",      21.74},
                         {"met2",      "met1",      67.05},
                         {"met1",      "met2",      48.19},
                         {"met3",      "nwell",     40.99},
                         {"met3",      "pwell",     40.99},
                         {"met3",      all_active,  42.25},
                         {"met3",      poly_nonres, 43.53},
                         {"poly",      "met3",       9.18},
                         {"met3",      "li1",       46.71},
                         {"li1",       "met3",      15.08},
                         {"met3",      "met1",      54.81},
                         {"met1",      "met3",      26.68},
                         {"met3",      "met2",      69.85},
                         {"met2",      "met3",      44.43},
                         {"met4",      "nwell",     36.68},
                         {"met4",      "pwell",     36.68},
                         {"met4",      diff_nonfet, 37.57},
                         {"met4",      poly_nonres, 38.11},
                         {"poly",      "met4",       6.35},
                         {"met4",      "li1",       39.71},
                         {"li1",       "met4",      10.14},
                         {"met4",      "met1",      42.56},
                         {"met1",      "met4",      16.42},
                         {"met4",      "met2",      46.38},
                         {"met2",      "met4",      22.33},
                         {"met4",      "met3",      70.52},
                         {"met3",      "met4",      42.64},
                         {"met5",      "nwell",     38.85},
                         {"met5",      "pwell",     38.85},
                         {"met5",      diff_nonfet, 39.52},
                         {"met5",      poly_nonres, 39.91},
                         {"poly",      "met5",       6.49},
                         {"met5",      "li1",       41.15},
                         {"li1",       "met5",       7.64},
                         {"met5",      "met1",      43.19},
                         {"met1",      "met5",      12.02},
                         {"met5",      "met2",      45.59},
                         {"met2",      "met5",      15.69},
                         {"met5",      "met3",      54.15},
                         {"met3",      "met5",      27.84},
                         {"met5",      "met4",      82.82},
                         {"met4",      "met5",      46.98}} );
}

void buildTech(kpex::tech::Technology::Builder &tech) {
    tech.setName("sky130A");

    buildLayers(&tech);
    
    buildLVSComputedLayers(&tech);

    auto psi = tech.initProcessStack();
    buildProcessStackInfo(&psi);

    auto ex = tech.initProcessParasitics();
    buildProcessParasiticsInfo(&ex);
}

}
