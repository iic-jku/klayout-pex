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
// This creates a technology definition example for gf180mcu:
// https://gf180mcu-pdk.readthedocs.io/en/latest/analog/layout/inter_specs/inter_specs_3_43.html
// https://gf180mcu-pdk.readthedocs.io/en/latest/physical_verification/design_manual/drm_04_1.html
// https://gf180mcu-pdk.readthedocs.io/en/latest/analog/layout/inter_specs/inter_specs_2.html
//

#include "protobuf.h"

namespace gf180mcuD {

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
    // https://gf180mcu-pdk.readthedocs.io/en/latest/physical_verification/design_manual/drm_04_1.html
    
    //             purpose, name,    drw_gds, pin_gds, label_gds, description
    addLayer(tech, DNWELL,  "DNWELL",   12,0,   -1,-1,  -1,-1,   "Deep N-well");
    addLayer(tech, NWELL,   "Nwell",    21,0,   -1,-1,  -1,-1,   "N-well region");
    addLayer(tech, DIFF,    "COMP",     22,0,   -1,-1,  22,10,   "Diffusion for device and interconnect");
    // addLayer(tech, N_P_TAP, "tap",    65,44,  -1,-1,  -1,-1,   "Active (diffusion) area (type equal to the well/substrate underneath) (i.e., N+ and P+)");
    addLayer(tech, PIMP,    "Pplus",    31,0,   -1,-1,  -1,-1,   "P+ source/drain implant");
    addLayer(tech, NIMP,    "Nplus",    32,0,   -1,-1,  -1,-1,   "N+ source/drain implant");
    addLayer(tech, METAL,   "Poly2",    30,0,   -1,-1,  30,10,   "Polysilicon gate & interconnect");
    addLayer(tech, CONT,    "Contact",  33,0,   -1,-1,  -1,-1,   "Contact to local interconnect");
    addLayer(tech, METAL,   "Metal1",   34,0,   -1,-1,  34,10,   "Metal 1 interconnect");
    addLayer(tech, VIA,     "Via1",     35,0,   -1,-1,  -1,-1,   "Contact from Metal1 to Metal2");
    addLayer(tech, METAL,   "Metal2",   36,0,   -1,-1,  36,10,   "Metal 2 interconnect");
    addLayer(tech, VIA,     "Via2",     38,0,   -1,-1,  -1,-1,   "Contact from Metal2 to Metal3");
    addLayer(tech, METAL,   "Metal3",   42,0,   -1,-1,  42,10,   "Metal 3 interconnect");
    addLayer(tech, VIA,     "Via3",     40,0,   -1,-1,  -1,-1,   "Contact from Metal3 to Metal4");
    addLayer(tech, METAL,   "Metal4",   46,0,   -1,-1,  46,10,   "Metal 4 interconnect");
    addLayer(tech, VIA,     "Via4",     41,0,   -1,-1,  -1,-1,   "Contact from Metal4 to Metal5");
    addLayer(tech, MIM,     "FuseTop",  75,0,   -1,-1,  -1,-1,   "MiM capacitor plate over Metal5");
    addLayer(tech, METAL,   "Metal5",   81,0,   -1,-1,  81,10,   "Metal 5 interconnect");
}

void buildLVSComputedLayers(kpex::tech::Technology *tech) {
    auto KREG = kpex::tech::ComputedLayerInfo_Kind_KIND_REGULAR;
    auto KCAP = kpex::tech::ComputedLayerInfo_Kind_KIND_DEVICE_CAPACITOR;
    auto KRES = kpex::tech::ComputedLayerInfo_Kind_KIND_DEVICE_RESISTOR;
    auto KPIN = kpex::tech::ComputedLayerInfo_Kind_KIND_PIN;
    auto KLBL = kpex::tech::ComputedLayerInfo_Kind_KIND_LABEL;
    
    //                     purpose  kind  lvs_name lvs_gds_pair orig. layer  description
    addComputedLayer(tech, DNWELL,  KREG, "dnwell",    12, 0,  "DNWELL",     "Deep NWell");
    addComputedLayer(tech, NWELL,   KREG, "Nwell",     21, 0,  "Nwell",      "NWell");
    addComputedLayer(tech, NIMP,    KREG, "nsd",       32, 44,  "Nplus",       "borrow from nsdm");
    addComputedLayer(tech, PIMP,    KREG, "psd",       31, 20,  "Pplus",       "borrow from psdm");
    addComputedLayer(tech, NTAP,    KREG, "ntap_conn", 65, 144, "tap",        "Separate ntap, original tap is 65,44, we need seperate ntap/ptap");
    addComputedLayer(tech, PTAP,    KREG, "ptap_conn", 65, 244, "tap",        "Separate ptap, original tap is 65,44, we need seperate ntap/ptap");
    addComputedLayer(tech, METAL,   KREG, "poly_con",    30, 0,  "Poly2",       "Computed layer for poly");
    addComputedLayer(tech, METAL,   KREG, "metal1_con",  34, 0,  "Metal1",       "Computed layer for met1");
    addComputedLayer(tech, METAL,   KREG, "metal2_con",  36, 0,  "Metal2",       "Computed layer for met2");
    addComputedLayer(tech, METAL,   KREG, "metal3_con",  42, 0,  "Metal3",       "Computed layer for met3 (no cap)");
    addComputedLayer(tech, METAL,   KREG, "metal4_con",  46, 0,  "Metal4",       "Computed layer for met4 (no cap)");
    addComputedLayer(tech, METAL,   KREG, "metal5_con",  81, 0,  "MetalTop",       "Computed layer for met5");
    addComputedLayer(tech, CONT,    KREG, "m1_nsd_con",  66, 4401,  "Contact", "Computed layer for contact from nsdm to Metal1");
    addComputedLayer(tech, CONT,    KREG, "m1_psd_con",  66, 4402,  "Contact", "Computed layer for contact from psdm to Metal1");
    addComputedLayer(tech, CONT,    KREG, "m1_poly_con", 66, 4403,  "Contact", "Computed layer for contact from poly to Metal1");
    // addComputedLayer(tech, VIA,     KREG, "via1_con",  35, 44,  "Via1",       "Computed layer for contact between met1 and met2");
    // addComputedLayer(tech, VIA,     KREG, "via2_con",  38, 44,  "Via2",       "Computed layer for contact between met2 and met3");
    addComputedLayer(tech, VIA,     KREG, "via3_n_cap", 40, 144, "Via3",       "Computed layer for via3 (no MIM cap)");
    addComputedLayer(tech, VIA,     KREG, "via4_n_cap", 41, 144, "Via4",       "Computed layer for via4 (no MIM cap)");
    
    // NOTE: for CC whiteboxing to work,
    //       we must ensure all VPP/MIM metal layers map to the same GDS pair as the non-cap versions,
    //       to ensure they are be merged
    //
    //       for R mode, MIM cap vias should point to a different GDS number than the regular via
    //       as they have different resistances
//    addComputedLayer(tech, VIA,     KCAP, "via3_cap",  70, 244, "via3",       "Computed layer for via3 (with MIM cap)");
//    addComputedLayer(tech, VIA,     KCAP, "via4_cap",  71, 244, "via4",       "Computed layer for via4 (with MIM cap)");
//    addComputedLayer(tech, METAL,   KCAP, "met3_cap",  70, 20, "Metal4",       "metal3 part of MiM cap");
//    addComputedLayer(tech, METAL,   KCAP, "met4_cap",  71, 20, "Metal5",       "metal4 part of MiM cap");
//    addComputedLayer(tech, MIM,     KCAP, "capm",      89, 44,  "capm",       "MiM cap above metal3");
//    addComputedLayer(tech, MIM,     KCAP, "capm2",     97, 44,  "capm2",      "MiM cap above metal4");
//    addComputedLayer(tech, METAL,   KCAP, "poly_vpp",  66, 20,  "Poly2",       "Computed layer for poly (MOM cap)");
//    addComputedLayer(tech, METAL,   KCAP, "li_vpp",    67, 20,  "Metal1",        "Capacitor device metal (MOM cap)");
//    addComputedLayer(tech, METAL,   KCAP, "met1_vpp",  68, 20,  "Metal2",       "Capacitor device metal (MOM cap)");
//    addComputedLayer(tech, METAL,   KCAP, "met2_vpp",  69, 20,  "Metal3",       "Capacitor device metal (MOM cap)");
//    addComputedLayer(tech, METAL,   KCAP, "met3_vpp",  70, 20,  "Metal4",       "Capacitor device metal (MOM cap)");
//    addComputedLayer(tech, METAL,   KCAP, "met4_vpp",  71, 20,  "Metal5",       "Capacitor device metal (MOM cap)");
//    addComputedLayer(tech, METAL,   KCAP, "met5_vpp",  72, 20,  "MetalTop",       "Capacitor device metal (MOM cap)");
//    addComputedLayer(tech, CONT,    KCAP, "licon_vpp", 66, 44,  "licon1",     "Capacitor device contact (MOM cap)");
//    addComputedLayer(tech, VIA,     KCAP, "mcon_vpp",  67, 44,  "mcon",       "Capacitor device contact (MOM cap)");
//    addComputedLayer(tech, VIA,     KCAP, "via1_vpp",  68, 44,  "via",        "Capacitor device contact (MOM cap)");
//    addComputedLayer(tech, VIA,     KCAP, "via2_vpp",  69, 44,  "via2",       "Capacitor device contact (MOM cap)");
//    addComputedLayer(tech, VIA,     KCAP, "via3_vpp",  70, 44,  "via3",       "Capacitor device contact (MOM cap)");
//    addComputedLayer(tech, VIA,     KCAP, "via4_vpp",  71, 44,  "via4",       "Capacitor device contact (MOM cap)");
    
    addComputedLayer(tech, METAL,   KLBL, "comp_label",  30, 10,  "COMP_label",  "LABEL drawn at diffusion layer");
    addComputedLayer(tech, METAL,   KLBL, "Poly2_Label",  30, 10,  "Poly2_label",  "LABEL drawn at poly2 layer");
    addComputedLayer(tech, METAL,   KLBL, "metal1_Label", 34, 10,  "Metal1_label", "LABEL drawn at Metal1 layer");
    addComputedLayer(tech, METAL,   KLBL, "metal2_Label", 36, 10,  "Metal2_label", "LABEL drawn at Metal2 layer");
    addComputedLayer(tech, METAL,   KLBL, "metal3_Label", 42, 10,  "Metal3_label", "LABEL drawn at Metal3 layer");
    addComputedLayer(tech, METAL,   KLBL, "metal4_Label", 46, 10,  "Metal4_label", "LABEL drawn at Metal4 layer");
    addComputedLayer(tech, METAL,   KLBL, "metal5_Label", 81, 10,  "Metal5_label", "LABEL drawn at Metal5 layer");
}

void buildProcessStackInfo(kpex::tech::ProcessStackInfo *psi) {
    // https://gf180mcu-pdk.readthedocs.io/en/latest/_images/2_cross_section_43.png
    
    
    // SUBSTRATE:           name    height   thickness   reference
    //                              (TODO)   (TODO)
    //-----------------------------------------------------------------------------------------------
    addSubstrateLayer(psi, "subs",   0.0,     0.33,       "fox");

    // NWELL/DIFF:                     name     z        ref
    //                                          (TODO)
    //-----------------------------------------------------------------------------------------------
    auto nwell =    addNWellLayer(psi, "Nwell", 0.0,    "fox");
    
    auto ndiff = addDiffusionLayer(psi, "Nplus",  0.312,  "fox");
    auto pdiff = addDiffusionLayer(psi, "Pplus",  0.312,  "fox");

    // FOX:                 name     dielectric_k
    //-----------------------------------------------------------------------------------------------
    addFieldOxideLayer(psi, "fox",   4.0);

    // METAL:                      name,   z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto poly = addMetalLayer(psi, "Poly2", 0.32,  0.2);

    // DIELECTRIC (conformal)   name,   dielectric_k, thickness,   thickness,      thickness  ref
    //                                                over metal,  where no metal, sidewall
    //-----------------------------------------------------------------------------------------------
    addConformalDielectric(psi, "nit",  7.0,          0.05,        0.05,           0.05,     "Poly2");

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "ild",    4.0,         "nit");

    // METAL:                      name,    z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met1 = addMetalLayer(psi, "Metal1", 1.23,   0.55);

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "imd1",   4.0,         "ild");

    // METAL:                      name,     z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met2 = addMetalLayer(psi, "Metal2", 2.38,   0.55);

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "imd2",   4.0,         "imd1");

    // METAL:                      name,     z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met3 = addMetalLayer(psi, "Metal3", 3.53,   0.55);

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "imd3",   4.0,         "imd2");

    // METAL:                      name,      z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met4 = addMetalLayer(psi, "Metal4",  4.68,   0.55);

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "imd4",   4.0,         "imd3");

    // METAL:                      name,      z,      thickness
    //-----------------------------------------------------------------------------------------------
    auto met5 = addMetalLayer(psi, "Metal5",  6.13,   1.1925);

    // DIELECTRIC (simple)   name,     dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "pass",   4.0,         "imd4");
    
    // DIELECTRIC (simple)   name,   dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "sin",  8.5225,          "pass");

    // DIELECTRIC (simple)   name,   dielectric_k, ref
    //-----------------------------------------------------------------------------------------------
    addSimpleDielectric(psi, "air",  8.5225,          "sin");
    
    auto m1np = ndiff->mutable_contact_above();
    auto m1pp = pdiff->mutable_contact_above();
    auto m1po = poly->mutable_contact_above();
    auto via1 = met1->mutable_contact_above();
    auto via2 = met2->mutable_contact_above();
    auto via3 = met3->mutable_contact_above();
    auto via4 = met4->mutable_contact_above();
    
    
    // TODO! via sizes and thicknesses!!!
    
    // CONTACT:         contact,         layer_below, metal_above, thickness,              width, spacing,  border
    //                  (LVS)            (LVS)        (LVS)
    //-----------------------------------------------------------------------------------------------------------------
    setContact(m1np,    "M1-Nplus",      "Nplus",      "Metal1",     0.9361,                  0.22,    0.17,  0.0);
    setContact(m1pp,    "M1-Pplus",      "Pplus",      "Metal1",     0.9361,                  0.22,    0.17,  0.0);
    setContact(m1po,    "M1-Poly",       "Poly2",      "Metal1",     0.4299,                  0.22,    0.17,  0.0);
    setContact(via1,    "Via1_con",      "Metal1",     "Metal2",     1.3761 - (0.9361 + 0.1), 0.26,    0.19,  0.0);
    setContact(via2,    "Via2_con",      "Metal2",     "Metal3",     0.27,                    0.26,    0.17,  0.055);
    setContact(via3,    "Via3_con",      "Metal3",     "Metal4",     0.42,                    0.26,    0.20,  0.04);
    setContact(via4,    "Via4_ncap",     "Metal4",     "Metal5",     0.505,                   0.26,    0.80,  0.19);
}

void buildProcessParasiticsInfo(kpex::tech::ProcessParasiticsInfo *ex) {
    // See  https://gf180mcu-pdk.readthedocs.io/en/latest/analog/layout/inter_specs/inter_specs_2_1.html
    //      https://gf180mcu-pdk.readthedocs.io/en/latest/analog/spice/elec_specs/elec_specs_5_1.html
    
    ex->set_side_halo(8.0);
    
    kpex::tech::ResistanceInfo *ri = ex->mutable_resistance();

    // https://gf180mcu-pdk.readthedocs.io/en/latest/analog/spice/elec_specs/elec_specs_5_1.html
    // resistance values are in mΩ / square
    //                     layer, resistance, [corner_adjustment_fraction]
    addLayerResistance(ri, "Poly2",   7300);  // allpolynonres
    addLayerResistance(ri, "Metal1",   90);
    addLayerResistance(ri, "Metal2",   90);
    addLayerResistance(ri, "Metal3",   90);
    addLayerResistance(ri, "Metal4",   90);
    addLayerResistance(ri, "Metal5",   90);
    addLayerResistance(ri, "MetalTop", 40);  // TODO: there are options 9kA/6kA/11kA/30kA
    
    // https://gf180mcu-pdk.readthedocs.io/en/latest/analog/spice/elec_specs/elec_specs_5_2.html
    // resistance values are in mΩ / CNT
    //                       contact_layer,  layer_below,  layer_above, resistance
    addContactResistance(ri, "M1-Nplus",     "Nplus",      "Metal1",    6300);
    addContactResistance(ri, "M1-Pplus",     "Pplus",      "Metal1",    5200);
    addContactResistance(ri, "M1-Poly",      "Poly2",      "Metal1",    5900);

    // https://gf180mcu-pdk.readthedocs.io/en/latest/analog/spice/elec_specs/elec_specs_5_2.html
    // resistance values are in mΩ / CNT
    //                   via_layer,  resistance
    addViaResistance(ri, "M1-Poly",       5900);
    addViaResistance(ri, "Via1",          4500);
    addViaResistance(ri, "Via2",          4500);
    addViaResistance(ri, "Via3",          4500);
    addViaResistance(ri, "Via4",          4500);
    addViaResistance(ri, "Via5",          4500);
    
    kpex::tech::CapacitanceInfo *ci = ex->mutable_capacitance();
    
    //                  layer,    area_cap,  perimeter_cap
    // addSubstrateCap(ci, "dnwell", 120.0,   0.0); // TODO
    addSubstrateCap(ci, "Poly2",   110.67,    50.72);
    addSubstrateCap(ci, "Metal1",   29.304,   39.431);
    addSubstrateCap(ci, "Metal2",   15.016,   33.298);
    addSubstrateCap(ci, "Metal3",   10.094,   30.021);
    addSubstrateCap(ci, "Metal4",   7.602,    28.153);
    addSubstrateCap(ci, "Metal5",   5.798,    30.386);
    addSubstrateCap(ci, "MetalTop", 6.32,     38.85);
    
    const std::string diff_nonfet = "COMP"; // TODO: diff must be non-fet!
    const std::string poly_nonres = "Poly2"; // TODO: poly must be non-res!
    const std::string all_active = "COMP";   // TODO: must be allactive
    
    //                top_layer,  bottom_layer,  cap
    // addOverlapCap(ci, "LVPWELL", "dnwell",     120.0); // TODO
    addOverlapCap(ci, "Poly2",     "Nwell",        110.67);
    addOverlapCap(ci, "Poly2",     "LVPWELL",      110.67);
    addOverlapCap(ci, "Metal1",      "LVPWELL",    29.304);
    addOverlapCap(ci, "Metal1",      "Nwell",      29.304);
    addOverlapCap(ci, "Metal1",      diff_nonfet,  30.502);  // TODO: lv vs mv?
    addOverlapCap(ci, "Metal1",      "Poly2",      51.434);
    addOverlapCap(ci, "Metal2",     "LVPWELL",     15.016);
    addOverlapCap(ci, "Metal2",     "Nwell",       15.016);
    addOverlapCap(ci, "Metal2",     diff_nonfet,   17.305);  // TODO: lv vs mv?
    addOverlapCap(ci, "Metal2",     poly_nonres,   19.263);
    addOverlapCap(ci, "Metal2",     "Metal1",      59.027);
    addOverlapCap(ci, "Metal3",     "Nwell",       10.094);
    addOverlapCap(ci, "Metal3",     "LVPWELL",     10.094);
    addOverlapCap(ci, "Metal3",     diff_nonfet,   11.079);  // TODO: lv vs mv?
    addOverlapCap(ci, "Metal3",     poly_nonres,   11.85);
    addOverlapCap(ci, "Metal3",     "Metal1",      20.238);
    addOverlapCap(ci, "Metal3",     "Metal2",      59.027);
    addOverlapCap(ci, "Metal4",     "Nwell",       7.602);
    addOverlapCap(ci, "Metal4",     "LVPWELL",     7.602);
    addOverlapCap(ci, "Metal4",     all_active,    8.148);
    addOverlapCap(ci, "Metal4",     poly_nonres,   8.557);
    addOverlapCap(ci, "Metal4",     "Metal1",      12.212);
    addOverlapCap(ci, "Metal4",     "Metal2",      20.238);
    addOverlapCap(ci, "Metal4",     "Metal3",      59.027);
    addOverlapCap(ci, "Metal5",     "Nwell",       5.798);
    addOverlapCap(ci, "Metal5",     "LVPWELL",     5.798);
    addOverlapCap(ci, "Metal5",     all_active,    6.11);
    addOverlapCap(ci, "Metal5",     poly_nonres,   6.337);
    addOverlapCap(ci, "Metal5",     "Metal1",      8.142);
    addOverlapCap(ci, "Metal5",     "Metal2",      11.067);
    addOverlapCap(ci, "Metal5",     "Metal3",      17.276);
    addOverlapCap(ci, "Metal5",     "Metal4",      39.351);
    
    //                 layer_name, cap,  offset
    addSidewallCap(ci, "Poly2",     11.098, -0.082);
    addSidewallCap(ci, "Metal1",    40.512, -0.053);
    addSidewallCap(ci, "Metal2",    46.736,  0.289);
    addSidewallCap(ci, "Metal3",    70.675,  0.534);
    addSidewallCap(ci, "Metal4",    77.388,  0.611);
    addSidewallCap(ci, "Metal5",    114.86,  0.025);
    
    //                        in_layer,    out_layer,   cap
    addSidewallOverlapCap(ci, "Poly2",      "Nwell",     50.72);
    addSidewallOverlapCap(ci, "Poly2",      "LVPWELL",   50.72);
    addSidewallOverlapCap(ci, "Metal1",     "Nwell",     39.431);
    addSidewallOverlapCap(ci, "Metal1",     "LVPWELL",   39.431);
    addSidewallOverlapCap(ci, "Metal1",     diff_nonfet, 43.406);  // TODO: lv vs mv?
    addSidewallOverlapCap(ci, "Metal1",     poly_nonres, 46.700);
    addSidewallOverlapCap(ci, "Poly2",      "Metal1",    17.946);
    addSidewallOverlapCap(ci, "Metal2",     "Nwell",     33.298);
    addSidewallOverlapCap(ci, "Metal2",     "LVPWELL",   33.298);
    addSidewallOverlapCap(ci, "Metal2",     diff_nonfet, 35.189);  // TODO: lv vs mv?
    addSidewallOverlapCap(ci, "Metal2",     poly_nonres, 36.169);
    addSidewallOverlapCap(ci, "Poly2",      "Metal2",    8.706);
    addSidewallOverlapCap(ci, "Metal2",     "Metal1",    47.566);
    addSidewallOverlapCap(ci, "Metal1",     "Metal2",    32.048);
    addSidewallOverlapCap(ci, "Metal3",     "Nwell",     30.021);
    addSidewallOverlapCap(ci, "Metal3",     "LVPWELL",   30.021);
    addSidewallOverlapCap(ci, "Metal3",     diff_nonfet, 31.40);  // TODO: lv vs mv?
    addSidewallOverlapCap(ci, "Metal3",     poly_nonres, 31.927);
    addSidewallOverlapCap(ci, "Poly2",      "Metal3",    5.895);
    addSidewallOverlapCap(ci, "Metal3",     "Metal1",    36.609);
    addSidewallOverlapCap(ci, "Metal1",     "Metal3",    18.135);
    addSidewallOverlapCap(ci, "Metal3",     "Metal2",    49.011);
    addSidewallOverlapCap(ci, "Metal2",     "Metal3",    36.626);
    addSidewallOverlapCap(ci, "Metal4",     "Nwell",     28.153);
    addSidewallOverlapCap(ci, "Metal4",     "LVPWELL",   40.99);
    addSidewallOverlapCap(ci, "Metal4",     diff_nonfet, 29.065);
    addSidewallOverlapCap(ci, "Metal4",     poly_nonres, 29.407);
    addSidewallOverlapCap(ci, "Poly2",      "Metal4",     8.557);
    addSidewallOverlapCap(ci, "Metal4",     "Metal1",    32.104);
    addSidewallOverlapCap(ci, "Metal1",     "Metal4",    13.159);
    addSidewallOverlapCap(ci, "Metal4",     "Metal2",    36.563);
    addSidewallOverlapCap(ci, "Metal2",     "Metal4",    22.405);
    addSidewallOverlapCap(ci, "Metal4",     "Metal3",    47.871);
    addSidewallOverlapCap(ci, "Metal3",     "Metal4",    39.964);
    addSidewallOverlapCap(ci, "Metal5",     "Nwell",     30.386);
    addSidewallOverlapCap(ci, "Metal5",     "LVPWELL",   30.386);
    addSidewallOverlapCap(ci, "Metal5",     diff_nonfet, 31.165);
    addSidewallOverlapCap(ci, "Metal5",     poly_nonres, 31.458);
    addSidewallOverlapCap(ci, "Poly2",      "Metal5",     3.365);
    addSidewallOverlapCap(ci, "Metal5",     "Metal1",    33.316);
    addSidewallOverlapCap(ci, "Metal1",     "Metal5",     9.825);
    addSidewallOverlapCap(ci, "Metal5",     "Metal2",    36.591);
    addSidewallOverlapCap(ci, "Metal2",     "Metal5",    15.764);
    addSidewallOverlapCap(ci, "Metal5",     "Metal3",    41.466);
    addSidewallOverlapCap(ci, "Metal3",     "Metal5",    22.988);
    addSidewallOverlapCap(ci, "Metal5",     "Metal4",    52.692);
    addSidewallOverlapCap(ci, "Metal4",     "Metal5",    34.954);
}

void buildTech(kpex::tech::Technology &tech) {
    tech.set_name("gf180mcuD");

    buildLayers(&tech);
    
    buildLVSComputedLayers(&tech);

    kpex::tech::ProcessStackInfo *psi = tech.mutable_process_stack();
    buildProcessStackInfo(psi);

    kpex::tech::ProcessParasiticsInfo *ex = tech.mutable_process_parasitics();
    buildProcessParasiticsInfo(ex);
}

}
