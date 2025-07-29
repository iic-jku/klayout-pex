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

#include "protobuf.h"

namespace sky130A {

constexpr auto DNWELL = kpex::tech::LayerInfo_Purpose_PURPOSE_DNWELL;
constexpr auto NWELL = kpex::tech::LayerInfo_Purpose_PURPOSE_NWELL;
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
    //             purpose, name,    drw_gds, pin_gds, label_gds, description
    addLayer(tech, DNWELL,  "dnwell", 64,18,  -1,-1,  -1,-1,   "Deep N-well");
    addLayer(tech, NWELL,   "nwell",  64,20,  64,16,   64,5,   "N-well region");
    addLayer(tech, DIFF,    "diff",   65,20,  65,16,   65,5,   "Active (diffusion) area");
    addLayer(tech, N_P_TAP, "tap",    65,44,  -1,-1,  -1,-1,   "Active (diffusion) area (type equal to the well/substrate underneath) (i.e., N+ and P+)");
    addLayer(tech, PIMP,    "psdm",   94,20,  -1,-1,  -1,-1,   "P+ source/drain implant");
    addLayer(tech, NIMP,    "nsdm",   93,44,  -1,-1,  -1,-1,   "N+ source/drain implant");
    addLayer(tech, METAL,   "poly",   66,20,  66,16,   66,5,   "Polysilicon");
    addLayer(tech, CONT,    "licon1", 66,44,  -1,-1,  -1,-1,   "Contact to local interconnect");
    addLayer(tech, METAL,   "li1",    67,20,  67,16,   67,5,   "Local interconnect");
    addLayer(tech, VIA,     "mcon",   67,44,  -1,-1,  -1,-1,   "Contact from local interconnect to met1");
    addLayer(tech, METAL,   "met1",   68,20,  68,16,   68,5,   "Metal 1");
    addLayer(tech, VIA,     "via",    68,44,  -1,-1,  -1,-1,   "Contact from met1 to met2");
    addLayer(tech, METAL,   "met2",   69,20,  69,16,   69,5,   "Metal 2");
    addLayer(tech, VIA,     "via2",   69,44,  -1,-1,  -1,-1,   "Contact from met2 to met3");
    addLayer(tech, METAL,   "met3",   70,20,  70,16,   70,5,   "Metal 3");
    addLayer(tech, VIA,     "via3",   70,44,  -1,-1,  -1,-1,   "Contact from cap above met3 to met4");
    addLayer(tech, MIM,     "capm",   89,44,  -1,-1,  -1,-1,   "MiM capacitor plate over metal 3");
    addLayer(tech, METAL,   "met4",   71,20,  71,16,   71,5,   "Metal 4");
    addLayer(tech, MIM,     "capm2",  97,44,  -1,-1,  -1,-1,   "MiM capacitor plate over metal 4");
    addLayer(tech, VIA,     "via4",   71,44,  -1,-1,  -1,-1,   "Contact from met4 to met5 (no MiM cap)");
    addLayer(tech, METAL,   "met5",   72,20,  72,16,  72,5,    "Metal 5");

}

void buildLVSComputedLayers(kpex::tech::Technology *tech) {
    auto KREG = kpex::tech::ComputedLayerInfo_Kind_KIND_REGULAR;
    auto KCAP = kpex::tech::ComputedLayerInfo_Kind_KIND_DEVICE_CAPACITOR;
    auto KRES = kpex::tech::ComputedLayerInfo_Kind_KIND_DEVICE_RESISTOR;
    auto KPIN = kpex::tech::ComputedLayerInfo_Kind_KIND_PIN;
    
    //                     purpose  kind  lvs_name lvs_gds_pair orig. layer  description
    addComputedLayer(tech, DNWELL,  KREG, "dnwell",    64, 18,  "dnwell",     "Deep NWell");
    addComputedLayer(tech, NWELL,   KREG, "nwell",     64, 20,  "nwell",      "NWell");
    addComputedLayer(tech, NIMP,    KREG, "nsd",       93, 44,  "nsdm",       "borrow from nsdm");
    addComputedLayer(tech, PIMP,    KREG, "psd",       94, 20,  "psdm",       "borrow from psdm");
    addComputedLayer(tech, NTAP,    KREG, "ntap_conn", 65, 144, "tap",        "Separate ntap, original tap is 65,44, we need seperate ntap/ptap");
    addComputedLayer(tech, PTAP,    KREG, "ptap_conn", 65, 244, "tap",        "Separate ptap, original tap is 65,44, we need seperate ntap/ptap");
    addComputedLayer(tech, METAL,   KREG, "poly_con",  66, 20,  "poly",       "Computed layer for poly");
    addComputedLayer(tech, METAL,   KREG, "li_con",    67, 20,  "li1",        "Computed layer for li1");
    addComputedLayer(tech, METAL,   KREG, "met1_con",  68, 20,  "met1",       "Computed layer for met1");
    addComputedLayer(tech, METAL,   KREG, "met2_con",  69, 20,  "met2",       "Computed layer for met2");
    addComputedLayer(tech, METAL,   KREG, "met3_ncap", 70, 20,  "met3",       "Computed layer for met3 (no cap)");
    addComputedLayer(tech, METAL,   KREG, "met4_ncap", 71, 20,  "met4",       "Computed layer for met4 (no cap)");
    addComputedLayer(tech, METAL,   KREG, "met5_con",  72, 20,  "met5",       "Computed layer for met5");
    addComputedLayer(tech, CONT,    KREG, "licon_nsd_con",  66, 4401,  "licon1", "Computed layer for contact from nsdm to li1");
    addComputedLayer(tech, CONT,    KREG, "licon_psd_con",  66, 4402,  "licon1", "Computed layer for contact from psdm to li1");
    addComputedLayer(tech, CONT,    KREG, "licon_poly_con", 66, 4403,  "licon1", "Computed layer for contact from poly to li1");
    addComputedLayer(tech, VIA,     KREG, "mcon_con",  67, 44,  "mcon",       "Computed layer for contact between li1 and met1");
    addComputedLayer(tech, VIA,     KREG, "via1_con",  68, 44,  "via1",       "Computed layer for contact between met1 and met2");
    addComputedLayer(tech, VIA,     KREG, "via2_con",  69, 44,  "via2",       "Computed layer for contact between met2 and met3");
    addComputedLayer(tech, VIA,     KREG, "via3_ncap", 70, 144, "via3",       "Computed layer for via3 (no MIM cap)");
    addComputedLayer(tech, VIA,     KREG, "via4_ncap", 71, 144, "via4",       "Computed layer for via4 (no MIM cap)");
    
    addComputedLayer(tech, VIA,     KCAP, "via3_cap",  70, 244, "via3",       "Computed layer for via3 (with MIM cap)");
    addComputedLayer(tech, VIA,     KCAP, "via4_cap",  71, 244, "via4",       "Computed layer for via4 (with MIM cap)");
    addComputedLayer(tech, METAL,   KCAP, "met3_cap",  70, 220, "met3",       "metal3 part of MiM cap");
    addComputedLayer(tech, METAL,   KCAP, "met4_cap",  71, 220, "met4",       "metal4 part of MiM cap");
    addComputedLayer(tech, MIM,     KCAP, "capm",      89, 44,  "capm",       "MiM cap above metal3");
    addComputedLayer(tech, MIM,     KCAP, "capm2",     97, 44,  "capm2",      "MiM cap above metal4");

    addComputedLayer(tech, METAL,   KCAP, "poly_vpp",  66, 200,  "poly",       "Computed layer for poly (MOM cap)");
    addComputedLayer(tech, METAL,   KCAP, "li_vpp",    67, 200,  "li1",        "Capacitor device metal (MOM cap)");
    addComputedLayer(tech, METAL,   KCAP, "met1_vpp",  68, 200,  "met1",       "Capacitor device metal (MOM cap)");
    addComputedLayer(tech, METAL,   KCAP, "met2_vpp",  69, 200,  "met2",       "Capacitor device metal (MOM cap)");
    addComputedLayer(tech, METAL,   KCAP, "met3_vpp",  70, 200,  "met3",       "Capacitor device metal (MOM cap)");
    addComputedLayer(tech, METAL,   KCAP, "met4_vpp",  71, 200,  "met4",       "Capacitor device metal (MOM cap)");
    addComputedLayer(tech, METAL,   KCAP, "met5_vpp",  72, 200,  "met5",       "Capacitor device metal (MOM cap)");
    addComputedLayer(tech, CONT,    KCAP, "licon_vpp", 66, 440,  "licon1",     "Capacitor device contact (MOM cap)");
    addComputedLayer(tech, VIA,     KCAP, "mcon_vpp",  67, 440,  "mcon",       "Capacitor device contact (MOM cap)");
    addComputedLayer(tech, VIA,     KCAP, "via1_vpp",  68, 440,  "via",        "Capacitor device contact (MOM cap)");
    addComputedLayer(tech, VIA,     KCAP, "via2_vpp",  69, 440,  "via2",       "Capacitor device contact (MOM cap)");
    addComputedLayer(tech, VIA,     KCAP, "via3_vpp",  70, 440,  "via3",       "Capacitor device contact (MOM cap)");
    addComputedLayer(tech, VIA,     KCAP, "via4_vpp",  71, 440,  "via4",       "Capacitor device contact (MOM cap)");
    
    addComputedLayer(tech, METAL,   KPIN, "poly_pin_con", 66, 16,  "poly.pin", "Poly pin");
    addComputedLayer(tech, METAL,   KPIN, "li_pin_con",   67, 16,  "li1.pin",  "li1 pin");
    addComputedLayer(tech, METAL,   KPIN, "met1_pin_con", 68, 16,  "met1.pin", "met1 pin");
    addComputedLayer(tech, METAL,   KPIN, "met2_pin_con", 69, 16,  "met2.pin", "met2 pin");
    addComputedLayer(tech, METAL,   KPIN, "met3_pin_con", 70, 16,  "met3.pin", "met3 pin");
    addComputedLayer(tech, METAL,   KPIN, "met4_pin_con", 71, 16,  "met4.pin", "met4 pin");
    addComputedLayer(tech, METAL,   KPIN, "met5_pin_con", 72, 16,  "met5.pin", "met5 pin");
}

void buildProcessStackInfo(kpex::tech::ProcessStackInfo *psi) {
    // SUBSTRATE:           name    height   thickness   reference
    //                              (TODO)   (TODO)
    //-----------------------------------------------------------------------------------------------
    addSubstrateLayer(psi, "subs",  0.1,     0.33,       "fox");

    // NWELL/DIFF:                     name     z        ref
    //                                          (TODO)
    //-----------------------------------------------------------------------------------------------
    auto nwell =    addNWellLayer(psi, "nwell", 0.1,    "fox");
    
    auto ndiff = addDiffusionLayer(psi, "nsd",  0.323,  "fox");
    auto pdiff = addDiffusionLayer(psi, "psd",  0.323,  "fox");

    // FOX:                 name     dielectric_k
    //-----------------------------------------------------------------------------------------------
    addFieldOxideLayer(psi, "fox",   4.632);
    // NOTE: fine-tuned dielectric_k for single_plate_100um_x_100um_li1_over_substrate to match foundry table data

    // METAL:                      name,   z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto poly = addMetalLayer(psi, "poly", 0.3262, 0.18);
    
    // DIELECTRIC (sidewall)   name,    dielectric_k, height_above_metal, width_outside_sw, ref
    //-----------------------------------------------------------------------------------------------
    addSidewallDielectric(psi, "iox",   0.39,         0.18,               0.006,            "poly");
    addSidewallDielectric(psi, "spnit", 7.5,          0.121,              0.0431,           "iox");

    // DIELECTRIC (simple)    name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "psg",   3.9,           "fox");

    // METAL:                      name, z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto li1 = addMetalLayer(psi, "li1", 0.9361, 0.1);

    // DIELECTRIC (conformal)   name,   dielectric_k, thickness,   thickness,      thickness  ref
    //                                                over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    addConformalDielectric(psi, "lint", 7.3,          0.075,       0.075,          0.075,     "li1");
    
    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "nild2",  4.05,         "lint");

    // METAL:                      name,   z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met1 = addMetalLayer(psi, "met1", 1.3761, 0.36);

    // DIELECTRIC (sidewall)   name,     dielectric_k, height_above_metal, width_outside_sw, ref
    //-----------------------------------------------------------------------------------------------
    addSidewallDielectric(psi, "nild3c", 3.5,          0.0,                0.03,            "met1");

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "nild3",  4.5,         "nild2");

    // METAL:                      name,   z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met2 = addMetalLayer(psi, "met2", 2.0061, 0.36);

    // DIELECTRIC (sidewall)   name,     dielectric_k, height_above_metal, width_outside_sw, ref
    //-----------------------------------------------------------------------------------------------
    addSidewallDielectric(psi, "nild4c", 3.5,          0.0,                0.03,            "met2");

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "nild4",  4.2,         "nild3");

    // METAL:                           name,        z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met3_ncap = addMetalLayer(psi, "met3_ncap", 2.7861, 0.845);
    auto met3_cap  = addMetalLayer(psi, "met3_cap",  2.7861, 0.845);

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

    // METAL:                      name,   z,                                 thickness
    //-----------------------------------------------------------------------------------------------
    auto capm = addMetalLayer(psi, "capm", 2.7861 + 0.845 + capild_thickness, capm_thickness);

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "nild5",  4.1,         "nild4");

    // METAL:                           name,        z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met4_ncap = addMetalLayer(psi, "met4_ncap", 4.0211, 0.845);

    // DIELECTRIC (conformal)   name,    dielectric_k,   thickness,   thickness,      thickness,  ref
    //                                                   over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    addConformalDielectric(psi, "capild", capild_k, capild_thickness,          0.0,        0.0,   "met4_cap");

    // METAL:                           name,        z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met4_cap  = addMetalLayer(psi, "met4_cap",  4.0211, 0.845);
    
    // DIELECTRIC (simple)    name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "nild6",  4.0,         "nild5");

    // METAL:                       name,    z,                                 thickness
    //-----------------------------------------------------------------------------------------------
    auto capm2 = addMetalLayer(psi, "capm2", 4.0211 + 0.845 + capild_thickness, capm_thickness);

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "nild6",  4.0,          "nild5");

    // METAL:                      name,   z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met5 = addMetalLayer(psi, "met5", 5.3711, 1.26);

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

    auto nwellc = nwell->mutable_contact_above(); // licon over nwell / tap // TODO!
    auto licon1n = ndiff->mutable_contact_above(); // licon over nsdm
    auto licon1p = pdiff->mutable_contact_above(); // licon over nsdm
    auto licon1poly = poly->mutable_contact_above(); // licon over poly
    auto mcon = li1->mutable_contact_above();
    auto via = met1->mutable_contact_above();
    auto via2 = met2->mutable_contact_above();
    auto via3_ncap = met3_ncap->mutable_contact_above();
    auto via3_cap = capm->mutable_contact_above();
    auto via4_ncap = met4_ncap->mutable_contact_above();
    auto via4_cap = capm2->mutable_contact_above();
    
    // CONTACT:             contact,         layer_below, metal_above, thickness,              width, spacing,  border
    //-----------------------------------------------------------------------------------------------------------------
    // setContact(nwellc,  "TODO",           "nwell",      "li1",       0.9361,                  0.17,    0.17,  0.0); // TODO
    setContact(licon1n,    "licon_nsd_con",  "nsdm",       "li1",       0.9361,                  0.17,    0.17,  0.0);
    setContact(licon1p,    "licon_psd_con",  "psdm",       "li1",       0.9361,                  0.17,    0.17,  0.0);
    setContact(licon1poly, "licon_poly_con", "poly",      "li1",       0.4299,                  0.17,    0.17,  0.0);
    setContact(mcon,       "mcon_con",       "li1",       "met1",      1.3761 - (0.9361 + 0.1), 0.17,    0.19,  0.0);
    setContact(via,        "via1_con",       "met1",      "met2",      0.27,                    0.15,    0.17,  0.055);
    setContact(via2,       "via2_con",       "met2",      "met3",      0.42,                    0.20,    0.20,  0.04);
    setContact(via3_ncap,  "via3_ncap",      "met3",      "met4",      0.39,                    0.20,    0.20,  0.06);
    setContact(via3_cap,   "via3_cap",       "met3",      "met4",      0.29,                    0.20,    0.20,  0.06);
    setContact(via4_ncap,  "via4_ncap",      "met4",      "met5",      0.505,                   0.80,    0.80,  0.19);
    setContact(via4_cap,   "via4_cap",       "met4",      "met5",      0.505 - 0.1,             0.80,    0.80,  0.19);
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
    //                       contact_layer,    layer_below,  layer_above, resistance
    addContactResistance(ri, "licon_nsd_con",  "nsdm",       "li1",        185000); // licon over nsdm!
    addContactResistance(ri, "licon_psd_con",  "psdm",       "li1",        585000); // licon over psdm!
    addContactResistance(ri, "licon_poly_con", "poly",       "li1",        152000); // licon over poly!

    // resistance values are in mΩ / square
    //                   via_layer,  resistance
    addViaResistance(ri, "poly",        152000); // licon over poly!
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
    
    buildLVSComputedLayers(&tech);

    kpex::tech::ProcessStackInfo *psi = tech.mutable_process_stack();
    buildProcessStackInfo(psi);

    kpex::tech::ProcessParasiticsInfo *ex = tech.mutable_process_parasitics();
    buildProcessParasiticsInfo(ex);
}

}
