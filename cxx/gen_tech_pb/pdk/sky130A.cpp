/*
 * --------------------------------------------------------------------------------
 * SPDX-FileCopyrightText: 2024 Martin Jan Köhler and Harald Pretl
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

#include "protobuf.h"

namespace sky130A {

void buildLayers(kpex::tech::Technology *tech) {
    //             name      gds_pair  description
    addLayer(tech, "dnwell", 64, 18,   "Deep N-well");
    addLayer(tech, "nwell",  64, 20,   "N-well region");
    addLayer(tech, "diff",   65, 20,   "Active (diffusion) area");
    addLayer(tech, "tap",    65, 44,   "Active (diffusion) area (type equal to the well/substrate underneath) (i.e., N+ and P+)");
    addLayer(tech, "psdm",   94, 20,   "");
    addLayer(tech, "nsdm",   93, 44,   "");
    addLayer(tech, "poly",   66, 20,   "Poly");
    addLayer(tech, "licon1", 66, 44,   "Contact to local interconnect");
    addLayer(tech, "li1",    67, 20,   "Local interconnect");
    addLayer(tech, "mcon",   67, 44,   "Contact from local interconnect to met1");
    addLayer(tech, "met1",   68, 20,   "Metal 1");
    addLayer(tech, "via",    68, 44,   "Contact from met1 to met2");
    addLayer(tech, "met2",   69, 20,   "Metal 2");
    addLayer(tech, "via2",   69, 44,   "Contact from met2 to met3");
    addLayer(tech, "met3",   70, 20,   "Metal 3");
    addLayer(tech, "via3",   70, 44,   "Contact from cap above met3 to met4");
    addLayer(tech, "capm",   89, 44,   "MiM capacitor plate over metal 3");
    addLayer(tech, "met4",   71, 20,   "Metal 4");
    addLayer(tech, "capm2",  97, 44,   "MiM capacitor plate over metal 4");
    addLayer(tech, "via4",   71, 44,   "Contact from met4 to met5 (no MiM cap)");
    addLayer(tech, "met5",   72, 20,   "Metal 5");
}

void buildPinLayerMappings(kpex::tech::Technology *tech) {
    //                       description   pin_gds_pair   drw_gds_pair
    addPinLayerMapping(tech, "poly.pin",   66, 16,        66, 20);
    addPinLayerMapping(tech, "li1.pin",    67, 16,        67, 20);
    addPinLayerMapping(tech, "met1.pin",   68, 16,        68, 20);
    addPinLayerMapping(tech, "met2.pin",   69, 16,        69, 20);
    addPinLayerMapping(tech, "met3.pin",   70, 16,        70, 20);
    addPinLayerMapping(tech, "met4.pin",   71, 16,        71, 20);
    addPinLayerMapping(tech, "met5.pin",   72, 16,        72, 20);
}

void buildLVSComputedLayers(kpex::tech::Technology *tech) {
    kpex::tech::ComputedLayerInfo::Kind KREG = kpex::tech::ComputedLayerInfo_Kind_KIND_REGULAR;
    kpex::tech::ComputedLayerInfo::Kind KCAP = kpex::tech::ComputedLayerInfo_Kind_KIND_DEVICE_CAPACITOR;
    kpex::tech::ComputedLayerInfo::Kind KRES = kpex::tech::ComputedLayerInfo_Kind_KIND_DEVICE_RESISTOR;
    kpex::tech::ComputedLayerInfo::Kind KPIN = kpex::tech::ComputedLayerInfo_Kind_KIND_PIN;
    
    //                     kind  lvs_name lvs_gds_pair  orig. layer   description
    addComputedLayer(tech, KREG, "dnwell",    64, 18,  "dnwell",     "Deep NWell");
    addComputedLayer(tech, KREG, "li_con",    67, 20,  "li1",    "Computed layer for li");
    addComputedLayer(tech, KREG, "licon",     66, 44,  "licon1", "Computed layer for contact to li");
    addComputedLayer(tech, KREG, "mcon_con",  67, 44,  "mcon", "");
    addComputedLayer(tech, KREG, "met1_con",  68, 20,  "met1", "");
    addComputedLayer(tech, KREG, "met2_con",  69, 20,  "met2", "");
    addComputedLayer(tech, KREG, "met3_ncap", 70, 20,  "met3", "");
    addComputedLayer(tech, KREG, "met4_ncap", 71, 20,  "met4", "");
    addComputedLayer(tech, KREG, "met5_con",  72, 20,  "met5", "");
    addComputedLayer(tech, KREG, "nsd",       93, 44,  "nsdm", "borrow from nsdm");
    addComputedLayer(tech, KREG, "ntap_conn", 65, 144, "tap", "Separate ntap, original tap is 65,44, we need seperate ntap/ptap");
    addComputedLayer(tech, KREG, "nwell",     64, 20,  "nwell", "");
    addComputedLayer(tech, KREG, "poly_con",  66, 20,  "poly", "");
    addComputedLayer(tech, KREG, "psd",       94, 20,  "psdm", "borrow from psdm");
    addComputedLayer(tech, KREG, "ptap_conn", 65, 244, "tap", "Separate ptap, original tap is 65,44, we need seperate ntap/ptap");
    addComputedLayer(tech, KREG, "via1_con",  68, 44,  "via1", "");
    addComputedLayer(tech, KREG, "via2_con",  69, 44,  "via2", "");
    addComputedLayer(tech, KREG, "via3_ncap", 70, 144, "via3", "Original via3 is 70,44, case where no MiM cap");
    addComputedLayer(tech, KREG, "via4_ncap", 71, 144, "via4", "Original via4 is 71,44, case where no MiM cap");
    addComputedLayer(tech, KREG, "via3_cap",  70, 244, "via3", "Original via3 is 70,44, via above metal 3 MIM cap");
    addComputedLayer(tech, KREG, "via4_cap",  71, 244, "via4", "Original via3 is 71,44, via above metal 4 MIM cap");
    
    addComputedLayer(tech, KCAP, "poly_vpp",  66, 20,  "poly", "Capacitor device metal");
    addComputedLayer(tech, KCAP, "li_vpp",    67, 20,  "li1", "Capacitor device metal");
    addComputedLayer(tech, KCAP, "met1_vpp",  68, 20,  "met1", "Capacitor device metal");
    addComputedLayer(tech, KCAP, "met2_vpp",  69, 20,  "met2", "Capacitor device metal");
    addComputedLayer(tech, KCAP, "met3_vpp",  70, 20,  "met3", "Capacitor device metal");
    addComputedLayer(tech, KCAP, "met4_vpp",  71, 20,  "met4", "Capacitor device metal");
    addComputedLayer(tech, KCAP, "met5_vpp",  72, 20,  "met5", "Capacitor device metal");
    addComputedLayer(tech, KCAP, "licon_vpp", 66, 44,  "licon", "Capacitor device contact");
    addComputedLayer(tech, KCAP, "mcon_vpp",  67, 44,  "mcon", "Capacitor device contact");
    addComputedLayer(tech, KCAP, "via1_vpp",  68, 44,  "via1", "Capacitor device contact");
    addComputedLayer(tech, KCAP, "via2_vpp",  69, 44,  "via2", "Capacitor device contact");
    addComputedLayer(tech, KCAP, "via3_vpp",  70, 44,  "via3", "Capacitor device contact");
    addComputedLayer(tech, KCAP, "via4_vpp",  71, 44,  "via4", "Capacitor device contact");
    addComputedLayer(tech, KCAP, "met3_cap",  70, 220, "met3", "metal3 part of MiM cap");
    addComputedLayer(tech, KCAP, "met4_cap",  71, 220, "met4", "metal4 part of MiM cap");
    addComputedLayer(tech, KCAP, "capm",      89, 44,  "capm", "MiM cap above metal3");
    addComputedLayer(tech, KCAP, "capm2",     97, 44,  "capm2", "MiM cap above metal4");
    
    addComputedLayer(tech, KPIN, "poly_pin_con", 66, 16,  "poly.pin", "Poly pin");
    addComputedLayer(tech, KPIN, "li_pin_con",   67, 16,  "li1.pin",   "li1 pin");
    addComputedLayer(tech, KPIN, "met1_pin_con", 68, 16,  "met1.pin", "met1 pin");
    addComputedLayer(tech, KPIN, "met2_pin_con", 69, 16,  "met2.pin", "met2 pin");
    addComputedLayer(tech, KPIN, "met3_pin_con", 70, 16,  "met3.pin", "met3 pin");
    addComputedLayer(tech, KPIN, "met4_pin_con", 71, 16,  "met4.pin", "met4 pin");
    addComputedLayer(tech, KPIN, "met5_pin_con", 72, 16,  "met5.pin", "met5 pin");
}

void buildProcessStackInfo(kpex::tech::ProcessStackInfo *psi) {
    // SUBSTRATE:           name    height   thickness   reference
    //                              (TODO)   (TODO)
    //-----------------------------------------------------------------------------------------------
    addSubstrateLayer(psi, "subs",  0.1,     0.33,       "fox");

    // NWELL/DIFF:                     name     height  ref
    //                                          (TODO)
    //-----------------------------------------------------------------------------------------------
    auto nwell =    addNWellLayer(psi, "nwell", 0.1,    "fox");
    auto diff = addDiffusionLayer(psi, "diff",  0.323,  "fox");
    
    // FOX:                 name     dielectric_k
    //-----------------------------------------------------------------------------------------------
    addFieldOxideLayer(psi, "fox",   4.632);
    // NOTE: fine-tuned dielectric_k for single_plate_100um_x_100um_li1_over_substrate to match foundry table data

    // METAL:                      name,   height, thickness, ref_below, ref_above
    //-----------------------------------------------------------------------------------------------
    auto poly = addMetalLayer(psi, "poly", 0.3262, 0.18,      "fox",     "psg");
    
    // DIELECTRIC (sidewall)   name,    dielectric_k, height_above_metal, width_outside_sw, ref
    //-----------------------------------------------------------------------------------------------
    addSidewallDielectric(psi, "iox",   0.39,         0.18,               0.006,            "poly");
    addSidewallDielectric(psi, "spnit", 7.5,          0.121,              0.0431,           "iox");

    // DIELECTRIC (simple)    name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "psg",   3.9,           "fox");

    // METAL:                      name, height, thickness, ref_below, ref_above
    //-----------------------------------------------------------------------------------------------
    auto li1 = addMetalLayer(psi, "li1", 0.9361, 0.1,      "psg",      "lint");

    // DIELECTRIC (conformal)   name,   dielectric_k, thickness,   thickness,      thickness  ref
    //                                                over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    addConformalDielectric(psi, "lint", 7.3,          0.075,       0.075,          0.075,     "li1");
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "nild2",  4.05,         "lint");

    // METAL:                      name,   height, thickness, ref_below, ref_above
    //-----------------------------------------------------------------------------------------------
    auto met1 = addMetalLayer(psi, "met1", 1.3761, 0.36,     "nild2",   "nild3");

    // DIELECTRIC (sidewall)   name,     dielectric_k, height_above_metal, width_outside_sw, ref
    //-----------------------------------------------------------------------------------------------
    addSidewallDielectric(psi, "nild3c", 3.5,          0.0,                0.03,            "met1");

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "nild3",  4.5,         "nild2");

    // METAL:                      name,   height, thickness, ref_below, ref_above
    //-----------------------------------------------------------------------------------------------
    auto met2 = addMetalLayer(psi, "met2", 2.0061, 0.36,     "nild3",   "nild4");

    // DIELECTRIC (sidewall)   name,     dielectric_k, height_above_metal, width_outside_sw, ref
    //-----------------------------------------------------------------------------------------------
    addSidewallDielectric(psi, "nild4c", 3.5,          0.0,                0.03,            "met2");

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "nild4",  4.2,         "nild3");

    // METAL:                           name,        height, thickness, ref_below, ref_above
    //-----------------------------------------------------------------------------------------------
    auto met3_ncap = addMetalLayer(psi, "met3_ncap", 2.7861, 0.845,     "nild4",   "nild5");
    auto met3_cap  = addMetalLayer(psi, "met3_cap",  2.7861, 0.845,     "nild4",   "nild5");

    double capm_thickness = 0.1;
    double capild_k = 4.52;  // to match design cap_mim_m3_w18p9_l5p1_no_interconnect to 200fF
    double capild_thickness = 0.02;

    // DIELECTRIC (conformal)   name,    dielectric_k,   thickness,   thickness,      thickness,  ref
    //                                                   over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    addConformalDielectric(psi, "capild", capild_k, capild_thickness,          0.0,        0.0,   "met3_cap");

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "nild5",  4.1,         "nild4");

    // METAL:                      name,   height,                            thickness,      ref_below, ref_above
    //-----------------------------------------------------------------------------------------------
    auto capm = addMetalLayer(psi, "capm", 2.7861 + 0.845 + capild_thickness, capm_thickness, "nild5",   "nild5");

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "nild5",  4.1,         "nild4");

    // METAL:                           name,        height, thickness, ref_below, ref_above
    //-----------------------------------------------------------------------------------------------
    auto met4_ncap = addMetalLayer(psi, "met4_ncap", 4.0211, 0.845,     "nild5",   "nild6");
    // TODO:   ->set_reference_below("nild5"); // PDK mim cap section says capild

    // DIELECTRIC (conformal)   name,    dielectric_k,   thickness,   thickness,      thickness,  ref
    //                                                   over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    addConformalDielectric(psi, "capild", capild_k, capild_thickness,          0.0,        0.0,   "met4_cap");

    // METAL:                           name,        height, thickness, ref_below, ref_above
    //-----------------------------------------------------------------------------------------------
    auto met4_cap  = addMetalLayer(psi, "met4_cap",  4.0211, 0.845,     "nild5",   "nild6");
    
    // DIELECTRIC (simple)    name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "nild6",  4.0,         "nild5");

    // METAL:                       name,    height,                            thickness,      ref_below, ref_above
    //-----------------------------------------------------------------------------------------------
    auto capm2 = addMetalLayer(psi, "capm2", 4.0211 + 0.845 + capild_thickness, capm_thickness, "nild6",   "nild6");
    // TODO:   ->set_reference_below("nild6"); // PDK mim cap section says capild

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "nild6",  4.0,          "nild5");

    // METAL:                      name,   height, thickness, ref_below, ref_above
    //-----------------------------------------------------------------------------------------------
    auto met5 = addMetalLayer(psi, "met5", 5.3711, 1.26,     "nild6",   "topox");

    // DIELECTRIC (sidewall)   name,    dielectric_k, height_above_metal, width_outside_sw, ref
    //-----------------------------------------------------------------------------------------------
    addSidewallDielectric(psi, "topox", 3.9,          0.09,               0.07,            "met5");

    // DIELECTRIC (conformal)   name,    dielectric_k, thickness,   thickness,      thickness, ref
    //                                                 over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    addConformalDielectric(psi, "topnit", 7.5,         0.54,        0.4223,         0.3777,    "topox");

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "air",  3.0,          "topnit");

    auto licon1n = nwell->mutable_contact_above();
    auto licon1d = diff->mutable_contact_above();
    auto licon1p = poly->mutable_contact_above();
    auto mcon = li1->mutable_contact_above();
    auto via = met1->mutable_contact_above();
    auto via2 = met2->mutable_contact_above();
    auto via3_ncap = met3_ncap->mutable_contact_above();
    auto via3_cap = capm->mutable_contact_above();
    auto via4_ncap = met4_ncap->mutable_contact_above();
    auto via4_cap = capm2->mutable_contact_above();
    
    // CONTACT:           contact,     metal_above, thickness,              width, spacing,  border
    //-----------------------------------------------------------------------------------------------
    setContact(licon1n,   "licon1",    "li1",       0.9361,                  0.17,    0.17,  0.0);
    setContact(licon1d,   "licon1",    "li1",       0.9361,                  0.17,    0.17,  0.0);
    setContact(licon1p,   "licon1",    "li1",       0.4299,                  0.17,    0.17,  0.0);
    setContact(mcon,      "mcon",      "met1",      1.3761 - (0.9361 + 0.1), 0.17,    0.19,  0.0);
    setContact(via,       "via",       "met2",      0.27,                    0.15,    0.17,  0.055);
    setContact(via2,      "via2",      "met3",      0.42,                    0.20,    0.20,  0.04);
    setContact(via3_ncap, "via3_ncap", "met4",      0.39,                    0.20,    0.20,  0.06);
    setContact(via3_cap,  "via3_cap",  "met4",      0.29,                    0.20,    0.20,  0.06);
    setContact(via4_ncap, "via4_ncap", "met5",      0.505,                   0.80,    0.80,  0.19);
    setContact(via4_cap,  "via4_cap",  "met5",      0.505 - 0.1,             0.80,    0.80,  0.19);
}

void buildProcessParasiticsInfo(kpex::tech::ProcessParasiticsInfo *ex) {
    // See  https://docs.google.com/spreadsheets/d/1N9To-xTiA7FLfQ1SNzWKe-wMckFEXVE9WPkPPjYkaxE/edit?pli=1&gid=1654372372#gid=1654372372
    
    ex->set_side_halo(8.0);
    
    kpex::tech::ResistanceInfo *ri = ex->mutable_resistance();

    // resistance values are in mΩ / square
    //                     layer, resistance, [corner_adjustment_fraction]
    addLayerResistance(ri, "poly", 48200);  // allpolynonres
    addLayerResistance(ri, "li1",  12800);
    addLayerResistance(ri, "met1",   125);
    addLayerResistance(ri, "met2",   125);
    addLayerResistance(ri, "met3",    47);
    addLayerResistance(ri, "met4",    47);
    addLayerResistance(ri, "met5",    29);
    
    // resistance values are in mΩ / square
    //                   layer,         resistance
    addViaResistance(ri, "licon_poly",  152000);
    addViaResistance(ri, "licon_ndiff", 185000);
    addViaResistance(ri, "licon_pdiff", 585000);
    addViaResistance(ri, "mcon",          9300);
    addViaResistance(ri, "via",           4500);
    addViaResistance(ri, "via2",          3410);
    addViaResistance(ri, "via3",          3410);
    addViaResistance(ri, "via4",           380);

    kpex::tech::CapacitanceInfo *ci = ex->mutable_capacitance();
    
    //                  layer,  area_cap,  perimeter_cap
    // addSubstrateCap(ci, "dnwell", 120.0,   0.0); // TODO
    addSubstrateCap(ci, "poly", 106.13,    55.27);
    addSubstrateCap(ci, "li1",  36.99,     40.7);
    addSubstrateCap(ci, "met1", 25.78,     40.57);
    addSubstrateCap(ci, "met2", 17.5,      37.76);
    addSubstrateCap(ci, "met3", 12.37,     40.99);
    addSubstrateCap(ci, "met4", 8.42,      36.68);
    addSubstrateCap(ci, "met5", 6.32,      38.85);
    
    const std::string diff_nonfet = "diff"; // TODO: diff must be non-fet!
    const std::string poly_nonres = "poly"; // TODO: poly must be non-res!
    const std::string all_active = "diff";   // TODO: must be allactive
    
    //                top_layer,  bottom_layer,  cap
    // addOverlapCap(ci, "pwell", "dnwell",     120.0); // TODO
    addOverlapCap(ci, "pwell",    "dnwell",     120.0); // TODO
    addOverlapCap(ci, "poly",     "nwell",      106.13);
    addOverlapCap(ci, "poly",     "pwell",      106.13);
    addOverlapCap(ci, "li1",      "pwell",      36.99);
    addOverlapCap(ci, "li1",      "nwell",      36.99);
    addOverlapCap(ci, "li1",      "nwell",      36.99);
    addOverlapCap(ci, "li1",      diff_nonfet,  55.3);
    addOverlapCap(ci, "li1",      "poly",       94.16);
    addOverlapCap(ci, "met1",     "pwell",      25.78);
    addOverlapCap(ci, "met1",     "nwell",      25.78);
    addOverlapCap(ci, "met1",     diff_nonfet,  33.6);
    addOverlapCap(ci, "met1",     poly_nonres,  44.81);
    addOverlapCap(ci, "met1",     "li1",        114.20);
    addOverlapCap(ci, "met2",     "nwell",      17.5);
    addOverlapCap(ci, "met2",     "pwell",      17.5);
    addOverlapCap(ci, "met2",     diff_nonfet,  20.8);
    addOverlapCap(ci, "met2",     poly_nonres,  24.50);
    addOverlapCap(ci, "met2",     "li1",        37.56);
    addOverlapCap(ci, "met2",     "met1",       133.86);
    addOverlapCap(ci, "met3",     "nwell",      12.37);
    addOverlapCap(ci, "met3",     "pwell",      12.37);
    addOverlapCap(ci, "met3",     all_active,   14.2);
    addOverlapCap(ci, "met3",     poly_nonres,  16.06);
    addOverlapCap(ci, "met3",     "li1",        20.79);
    addOverlapCap(ci, "met3",     "met1",       34.54);
    addOverlapCap(ci, "met3",     "met2",       86.19);
    addOverlapCap(ci, "met4",     "nwell",      8.42);
    addOverlapCap(ci, "met4",     "pwell",      8.42);
    addOverlapCap(ci, "met4",     all_active,   9.41);
    addOverlapCap(ci, "met4",     poly_nonres,  10.01);
    addOverlapCap(ci, "met4",     "li1",        11.67);
    addOverlapCap(ci, "met4",     "met1",       15.03);
    addOverlapCap(ci, "met4",     "met2",       20.33);
    addOverlapCap(ci, "met4",     "met3",       84.03);
    addOverlapCap(ci, "met5",     "nwell",      6.32);
    addOverlapCap(ci, "met5",     "pwell",      6.32);
    addOverlapCap(ci, "met5",     all_active,   6.88);
    addOverlapCap(ci, "met5",     poly_nonres,  7.21);
    addOverlapCap(ci, "met5",     "li1",        8.03);
    addOverlapCap(ci, "met5",     "met1",       9.48);
    addOverlapCap(ci, "met5",     "met2",       11.34);
    addOverlapCap(ci, "met5",     "met3",       19.63);
    addOverlapCap(ci, "met5",     "met4",       68.33);
    
    //                 layer_name, cap,  offset
    addSidewallCap(ci, "poly",     16.0, 0.0);
    addSidewallCap(ci, "li1",      25.5, 0.14);
    addSidewallCap(ci, "met1",     44,   0.25);
    addSidewallCap(ci, "met2",     50,   0.3);
    addSidewallCap(ci, "met3",     74.0, 0.4);
    addSidewallCap(ci, "met4",     94.0, 0.57);
    addSidewallCap(ci, "met5",     155,  0.5);
    
    //                        in_layer,    out_layer,   cap
    addSidewallOverlapCap(ci, "poly",      "nwell",     55.27);
    addSidewallOverlapCap(ci, "poly",      "pwell",     55.27);
    addSidewallOverlapCap(ci, "li1",       "nwell",     40.70);
    addSidewallOverlapCap(ci, "li1",       "pwell",     40.70);
    addSidewallOverlapCap(ci, "li1",       diff_nonfet, 44.27);
    addSidewallOverlapCap(ci, "li1",       poly_nonres, 51.85);
    addSidewallOverlapCap(ci, "poly",      "li1",       25.14);
    addSidewallOverlapCap(ci, "met1",      "nwell",     40.57);
    addSidewallOverlapCap(ci, "met1",      "pwell",     40.57);
    addSidewallOverlapCap(ci, "met1",      diff_nonfet, 43.10);
    addSidewallOverlapCap(ci, "met1",      poly_nonres, 46.72);
    addSidewallOverlapCap(ci, "poly",      "met1",      16.69);
    addSidewallOverlapCap(ci, "met1",      "li1",       59.50);
    addSidewallOverlapCap(ci, "li1",       "met1",      34.70);
    addSidewallOverlapCap(ci, "met2",      "nwell",     37.76);
    addSidewallOverlapCap(ci, "met2",      "pwell",     37.76);
    addSidewallOverlapCap(ci, "met2",      diff_nonfet, 39.54);
    addSidewallOverlapCap(ci, "met2",      poly_nonres, 41.22);
    addSidewallOverlapCap(ci, "poly",      "met2",      11.17);
    addSidewallOverlapCap(ci, "met2",      "li1",       46.28);
    addSidewallOverlapCap(ci, "li1",       "met2",      21.74);
    addSidewallOverlapCap(ci, "met2",      "met1",      67.05);
    addSidewallOverlapCap(ci, "met1",      "met2",      48.19);
    addSidewallOverlapCap(ci, "met3",      "nwell",     40.99);
    addSidewallOverlapCap(ci, "met3",      "pwell",     40.99);
    addSidewallOverlapCap(ci, "met3",      all_active,  42.25);
    addSidewallOverlapCap(ci, "met3",      poly_nonres, 43.53);
    addSidewallOverlapCap(ci, "poly",      "met3",      9.18);
    addSidewallOverlapCap(ci, "met3",      "li1",       46.71);
    addSidewallOverlapCap(ci, "li1",       "met3",      15.08);
    addSidewallOverlapCap(ci, "met3",      "met1",      54.81);
    addSidewallOverlapCap(ci, "met1",      "met3",      26.68);
    addSidewallOverlapCap(ci, "met3",      "met2",      69.85);
    addSidewallOverlapCap(ci, "met2",      "met3",      44.43);
    addSidewallOverlapCap(ci, "met4",      "nwell",     36.68);
    addSidewallOverlapCap(ci, "met4",      "pwell",     36.68);
    addSidewallOverlapCap(ci, "met4",      diff_nonfet, 37.57);
    addSidewallOverlapCap(ci, "met4",      poly_nonres, 38.11);
    addSidewallOverlapCap(ci, "poly",      "met4",      6.35);
    addSidewallOverlapCap(ci, "met4",      "li1",       39.71);
    addSidewallOverlapCap(ci, "li1",       "met4",      10.14);
    addSidewallOverlapCap(ci, "met4",      "met1",      42.56);
    addSidewallOverlapCap(ci, "met1",      "met4",      16.42);
    addSidewallOverlapCap(ci, "met4",      "met2",      46.38);
    addSidewallOverlapCap(ci, "met2",      "met4",      22.33);
    addSidewallOverlapCap(ci, "met4",      "met3",      70.52);
    addSidewallOverlapCap(ci, "met3",      "met4",      42.64);
    
    addSidewallOverlapCap(ci, "met5",      "nwell",     38.85);
    addSidewallOverlapCap(ci, "met5",      "pwell",     38.85);
    addSidewallOverlapCap(ci, "met5",      diff_nonfet, 39.52);
    addSidewallOverlapCap(ci, "met5",      poly_nonres, 39.91);
    addSidewallOverlapCap(ci, "poly",      "met5",      6.49);
    addSidewallOverlapCap(ci, "met5",      "li1",       41.15);
    addSidewallOverlapCap(ci, "li1",       "met5",      7.64);
    addSidewallOverlapCap(ci, "met5",      "met1",      43.19);
    addSidewallOverlapCap(ci, "met1",      "met5",      12.02);
    addSidewallOverlapCap(ci, "met5",      "met2",      45.59);
    addSidewallOverlapCap(ci, "met2",      "met5",      15.69);
    addSidewallOverlapCap(ci, "met5",      "met3",      54.15);
    addSidewallOverlapCap(ci, "met3",      "met5",      27.84);
    addSidewallOverlapCap(ci, "met5",      "met4",      82.82);
    addSidewallOverlapCap(ci, "met4",      "met5",      46.98);
}

void buildTech(kpex::tech::Technology &tech) {
    tech.set_name("sky130A");

    buildLayers(&tech);
    buildPinLayerMappings(&tech);
    
    buildLVSComputedLayers(&tech);

    kpex::tech::ProcessStackInfo *psi = tech.mutable_process_stack();
    buildProcessStackInfo(psi);

    kpex::tech::ProcessParasiticsInfo *ex = tech.mutable_process_parasitics();
    buildProcessParasiticsInfo(ex);
}

}
