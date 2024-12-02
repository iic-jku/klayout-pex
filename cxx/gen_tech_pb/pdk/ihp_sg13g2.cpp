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

void buildLayers(kpex::tech::Technology *tech) {
    addLayer(tech, "Activ", 1, 0, "Active (diffusion) area"); // ~ diff.drawing
//    addLayer(tech, "tap",  65, 44, "Active (diffusion) area (type equal to the well/substrate underneath) (i.e., N+ and P+)");
//    addLayer(tech, "diff", 65, 20, "Active (diffusion) area");
    
//    // map this to process stack nwell? (TODO: check this with Matthias)
//    addLayer(tech, "diff", 65, 144, "KLayout computed layer: ntap_conn");
//    
//    // map this to process stack subs? (TODO: check this with Matthias)
//    addLayer(tech, "diff", 65, 244, "KLayout computed layer: ptap_conn");
    
    addLayer(tech, "NWell",  31,  0, "N-well region");
    addLayer(tech, "PWell",  46,  0, "P-well region");
    addLayer(tech, "GatPoly", 5,  0, "Poly"); // ~ poly.drawing
    
    addLayer(tech, "Cont",    6,  0, "Defines 1-st metal contacts to Activ, GatPoly");
    addLayer(tech, "Metal1",  8,  0, "Defines 1-st metal interconnect");
    addLayer(tech, "Via1",   19,  0, "Defines 1-st metal to 2-nd metal contact");
    addLayer(tech, "Metal2", 10,  0, "Defines 2-nd metal interconnect");
    addLayer(tech, "Via2",   29,  0, "Defines 2-nd metal to 3-rd metal contact");
    addLayer(tech, "Metal3", 30,  0, "Defines 3-rd metal interconnect");
    addLayer(tech, "Via3",   49,  0, "Defines 3-rd metal to 4-th metal contact");
    addLayer(tech, "Metal4", 50,  0, "Defines 4-th metal interconnect");
//    addLayer(tech, "via3_ncap", 70, 144, "Contact from met3 to met4 (no MiM cap)");
//    addLayer(tech, "via3_cap",  70, 244, "Contact from cap above met3 to met4 (MiM cap)");
//    addLayer(tech, "capm",  89, 44,  "MiM capacitor plate over metal 3");
    addLayer(tech, "Via4",   66,  0, "Defines 4-th metal to 5-th metal contact");
    addLayer(tech, "Metal5", 67,  0, "Defines 5-th metal interconnect");
//    addLayer(tech, "via4_ncap", 71, 144, "Contact from met4 to met5 (no MiM cap)");
//    addLayer(tech, "via4_cap",  71, 244, "Contact from cap above met4 to met5 (MiM cap)");
    addLayer(tech, "TopVia1",   125,  0, "Defines 3-rd (or 5-th) metal to TopMetal1 contact");
    addLayer(tech, "TopMetal1", 126,  0, "Defines 1-st thick TopMetal layer");
    addLayer(tech, "TopVia2",   133,  0, "Defines via between TopMetal1 and TopMetal2");
    addLayer(tech, "TopMetal2", 134,  0, "Defines 2-nd thick TopMetal layer");
}

void buildLVSComputedLayers(kpex::tech::Technology *tech) {
    kpex::tech::ComputedLayerInfo::Kind KREG = kpex::tech::ComputedLayerInfo_Kind_KIND_REGULAR;
    kpex::tech::ComputedLayerInfo::Kind KCAP = kpex::tech::ComputedLayerInfo_Kind_KIND_DEVICE_CAPACITOR;
    kpex::tech::ComputedLayerInfo::Kind KRES = kpex::tech::ComputedLayerInfo_Kind_KIND_DEVICE_RESISTOR;
    
//    addComputedLayer(tech, KREG, "dnwell",    64, 18,  "Deep NWell");

    addComputedLayer(tech, KREG, "cont_drw",     6, 0,  "Computed layer for contact to Metal1");
    addComputedLayer(tech, KREG, "metal1_con",  8,  0,  "Computed layer for Metal1");
    addComputedLayer(tech, KREG, "metal2_con",  10, 0,  "Computed layer for Metal2");
    addComputedLayer(tech, KREG, "metal3_con",  30, 0,  "Computed layer for Metal3");
    addComputedLayer(tech, KREG, "metal4_con",  50, 0,  "Computed layer for Metal4");
    addComputedLayer(tech, KREG, "metal5_n_cap",  67, 20,  "Computed layer for Metal5, case where no MiM cap");
    addComputedLayer(tech, KREG, "topmetal1_con", 126, 0,  "Computed layer for TopMetal1");
    addComputedLayer(tech, KREG, "topmetal2_con", 134, 0,  "Computed layer for TopMetal2");

    addComputedLayer(tech, KREG, "nsd_fet",     7, 0,   "Computed layer for nSD");
    addComputedLayer(tech, KREG, "psd_fet",     14, 0,   "Computed layer for pSD");

    addComputedLayer(tech, KREG, "ntap",        65, 144, "Computed layer for ntap");
    addComputedLayer(tech, KREG, "ptap",        65, 144, "Computed layer for ptap");

    addComputedLayer(tech, KREG, "pwell",       46, 0,   "Computed layer for PWell");
    addComputedLayer(tech, KREG, "pwell_sub",   46, 0,   "Computed layer for PWell");
    addComputedLayer(tech, KREG, "nwell_drw",   31, 0,   "Computed layer for NWell");
    
    addComputedLayer(tech, KREG, "poly_con",    5, 0,    "Computed layer for GatPoly");

    addComputedLayer(tech, KREG, "topvia1_n_cap", 125, 20, "Original TopVia1 is 125/0, case where no MiM cap");
    
    addComputedLayer(tech, KCAP, "mim_via",  125, 10, "Original TopVia1 is 125/0, case MiM cap");
    addComputedLayer(tech, KCAP, "metal5_cap",   67, 10,  "Computed layer for Metal5, case MiM cap");
    addComputedLayer(tech, KCAP, "cmim_dev",   36, 0,  "Computed layer for MiM cap above Metal5");

    
//    addComputedLayer(tech, KREG, "via1",      68, 44,  "");
//    addComputedLayer(tech, KREG, "via2",      69, 44,  "");
//    addComputedLayer(tech, KREG, "via3_ncap", 70, 144, "Original via3 is 70,44, case where no MiM cap");
//    addComputedLayer(tech, KREG, "via4_ncap", 71, 144, "Original via4 is 71,44, case where no MiM cap");
//    addComputedLayer(tech, KREG, "via3_cap",  70, 244,  "Original via3 is 70,44, via above metal 3 MIM cap");
//    addComputedLayer(tech, KREG, "via4_cap",  71, 244,  "Original via3 is 71,44, via above metal 4 MIM cap");
//    
//    addComputedLayer(tech, KCAP, "poly_vpp",  66, 20,  "Capacitor device metal");
//    addComputedLayer(tech, KCAP, "li_vpp",    67, 20,  "Capacitor device metal");
//    addComputedLayer(tech, KCAP, "met1_vpp",  68, 20,  "Capacitor device metal");
//    addComputedLayer(tech, KCAP, "met2_vpp",  69, 20,  "Capacitor device metal");
//    addComputedLayer(tech, KCAP, "met3_vpp",  70, 20,  "Capacitor device metal");
//    addComputedLayer(tech, KCAP, "met4_vpp",  71, 20,  "Capacitor device metal");
//    addComputedLayer(tech, KCAP, "met5_vpp",  72, 20,  "Capacitor device metal");
//    addComputedLayer(tech, KCAP, "licon_vpp", 66, 44,  "Capacitor device contact");
//    addComputedLayer(tech, KCAP, "mcon_vpp",  67, 44,  "Capacitor device contact");
//    addComputedLayer(tech, KCAP, "via1_vpp",  68, 44,  "Capacitor device contact");
//    addComputedLayer(tech, KCAP, "via2_vpp",  69, 44,  "Capacitor device contact");
//    addComputedLayer(tech, KCAP, "via3_vpp",  70, 44,  "Capacitor device contact");
//    addComputedLayer(tech, KCAP, "via4_vpp",  71, 44,  "Capacitor device contact");
//    addComputedLayer(tech, KCAP, "met3_cap",  70, 220, "metal3 part of MiM cap");
//    addComputedLayer(tech, KCAP, "met4_cap",  71, 220, "metal4 part of MiM cap");
//    addComputedLayer(tech, KCAP, "capm",      89, 44,  "MiM cap above metal3");
//    addComputedLayer(tech, KCAP, "capm2",     97, 44,  "MiM cap above metal4");
}

void buildProcessStackInfo(kpex::tech::ProcessStackInfo *psi) {
    kpex::tech::ProcessStackInfo::LayerInfo *li = psi->add_layers();
    li->set_name("subs");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SUBSTRATE);
    kpex::tech::ProcessStackInfo::SubstrateLayer *subs = li->mutable_substrate_layer();
    subs->set_height(0.1); // TODO
    subs->set_thickness(0.28); // TODO
    subs->set_reference("fox");
    
    li = psi->add_layers();
    li->set_name("NWell");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_NWELL);
    kpex::tech::ProcessStackInfo::NWellLayer *nwell = li->mutable_nwell_layer();
    nwell->set_height(0.0);
    nwell->set_reference("fox");
    kpex::tech::ProcessStackInfo::Contact *nwell_cont = nwell->mutable_contact_above();
    nwell_cont->set_name("Cont");
    nwell_cont->set_metal_above("Metal1");
    nwell_cont->set_thickness(0.64);
    
    li = psi->add_layers();
    li->set_name("Activ");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_DIFFUSION);
    kpex::tech::ProcessStackInfo::DiffusionLayer *diff = li->mutable_diffusion_layer();
    diff->set_height(0.323); // TODO
    diff->set_reference("fox");
    kpex::tech::ProcessStackInfo::Contact *diff_cont = diff->mutable_contact_above();
    diff_cont->set_name("Cont");
    diff_cont->set_metal_above("Metal1");
    diff_cont->set_thickness(0.64);
    
    li = psi->add_layers();
    li->set_name("fox");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_FIELD_OXIDE);
    kpex::tech::ProcessStackInfo::FieldOxideLayer *fl = li->mutable_field_oxide_layer();
    fl->set_dielectric_k(0.4); // from SG13G2_os_process_spec.pdf p6
    
    li = psi->add_layers();
    li->set_name("GatPoly");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    kpex::tech::ProcessStackInfo::MetalLayer *poly = li->mutable_metal_layer();
    poly->set_height(0.3262); // TODO
    poly->set_thickness(0.16);  // from SG13G2_os_process_spec.pdf p17
    poly->set_reference_below("fox");
    poly->set_reference_above("psg");
    
    li = psi->add_layers();
    li->set_name("nitride"); // TODO
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_CONFORMAL_DIELECTRIC);
    kpex::tech::ProcessStackInfo::ConformalDielectricLayer *cl = li->mutable_conformal_dielectric_layer();
    cl->set_dielectric_k(6.5);
    cl->set_thickness_over_metal(0.05);
    cl->set_thickness_where_no_metal(0.05);
    cl->set_thickness_sidewall(0.05);
    cl->set_reference("GatPoly");
    
    kpex::tech::ProcessStackInfo::Contact *poly_cont = poly->mutable_contact_above();
    poly_cont->set_name("Cont");
    poly_cont->set_metal_above("Metal1");
    poly_cont->set_thickness(0.4299);  // TODO!
    
    li = psi->add_layers();
    li->set_name("psg");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    kpex::tech::ProcessStackInfo::SimpleDielectricLayer *sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(4.1);
    sdl->set_reference("fox");
    
    li = psi->add_layers();
    li->set_name("Metal1");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    kpex::tech::ProcessStackInfo::MetalLayer *metal1 = li->mutable_metal_layer();
    metal1->set_height(poly->height() + poly->thickness() + poly_cont->thickness());
    metal1->set_thickness(0.42);
    metal1->set_reference_below("psg");
    metal1->set_reference_above("lint");
    
    kpex::tech::ProcessStackInfo::Contact *via1 = metal1->mutable_contact_above();
    via1->set_name("Via1");
    via1->set_metal_above("Metal2");
    via1->set_thickness(0.54);
    
    li = psi->add_layers();
    li->set_name("nild2");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(4.1);
    sdl->set_reference("lint");
    
    li = psi->add_layers();
    li->set_name("Metal2");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    kpex::tech::ProcessStackInfo::MetalLayer *metal2 = li->mutable_metal_layer();
    metal2->set_height(metal1->height() + metal1->thickness() + via1->thickness());
    metal2->set_thickness(0.36);
    metal2->set_reference_below("nild2");
    metal2->set_reference_above("nild3");
    
    kpex::tech::ProcessStackInfo::Contact *via2 = metal2->mutable_contact_above();
    via2->set_name("Via2");
    via2->set_metal_above("Metal3");
    via2->set_thickness(0.54);
    
    li = psi->add_layers();
    li->set_name("nild3");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(4.1);
    sdl->set_reference("nild2");
    
    li = psi->add_layers();
    li->set_name("Metal3");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    kpex::tech::ProcessStackInfo::MetalLayer *metal3 = li->mutable_metal_layer();
    metal3->set_height(metal2->height() + metal2->thickness() + via2->thickness());
    metal3->set_thickness(0.49);
    metal3->set_reference_below("nild3");
    metal3->set_reference_above("nild4");
    
    kpex::tech::ProcessStackInfo::Contact *via3 = metal3->mutable_contact_above();
    via3->set_name("Via3");
    via3->set_metal_above("Metal4");
    via3->set_thickness(0.54);
        
    li = psi->add_layers();
    li->set_name("nild4");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(4.1);
    sdl->set_reference("nild3");
    
    li = psi->add_layers();
    li->set_name("Metal4");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    kpex::tech::ProcessStackInfo::MetalLayer *metal4 = li->mutable_metal_layer();
    metal4->set_height(metal3->height() + metal3->thickness() + via3->thickness());
    metal4->set_thickness(0.49);
    metal4->set_reference_below("nild4");
    metal4->set_reference_above("nild5");
    
    kpex::tech::ProcessStackInfo::Contact *via4 = metal4->mutable_contact_above();
    via4->set_name("Via4");
    via4->set_metal_above("Metal5");
    via4->set_thickness(0.54);
    
    li = psi->add_layers();
    li->set_name("nild5");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(4.1);
    sdl->set_reference("nild4");
    
    li = psi->add_layers();
    li->set_name("metal5_n_cap");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    kpex::tech::ProcessStackInfo::MetalLayer *metal5_ncap = li->mutable_metal_layer();
    metal5_ncap->set_height(metal4->height() + metal4->thickness() + via4->thickness());
    metal5_ncap->set_thickness(0.49);
    metal5_ncap->set_reference_below("nild6");
    metal5_ncap->set_reference_above("topox");
    
    kpex::tech::ProcessStackInfo::Contact *topVia1_ncap = metal5_ncap->mutable_contact_above();
    topVia1_ncap->set_name("topvia1_n_cap");
    topVia1_ncap->set_metal_above("TopMetal1");
    topVia1_ncap->set_thickness(0.85);

    li = psi->add_layers();
    li->set_name("nild5");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(4.1);
    sdl->set_reference("nild4");

    li = psi->add_layers();
    li->set_name("metal5_cap");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    kpex::tech::ProcessStackInfo::MetalLayer *metal5_cap = li->mutable_metal_layer();
    metal5_cap->set_height(metal5_ncap->height());
    metal5_cap->set_thickness(metal5_ncap->thickness());
    metal5_cap->set_reference_below("nild6");
    metal5_cap->set_reference_above("topox");

    li = psi->add_layers();
    li->set_name("nild5");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(4.1);
    sdl->set_reference("nild4");

    double capild_k = 4.52;  // to match design cap_mim_m3_w18p9_l5p1_no_interconnect to 200fF
    double capild_thickness = 0.04;

    li = psi->add_layers();
    li->set_name("tismim");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_CONFORMAL_DIELECTRIC);
    cl = li->mutable_conformal_dielectric_layer();
    cl->set_dielectric_k(capild_k);
    cl->set_thickness_over_metal(capild_thickness);
    cl->set_thickness_where_no_metal(0.0);
    cl->set_thickness_sidewall(0.0);
    cl->set_reference("metal5_cap");

    li = psi->add_layers();
    li->set_name("cmim_dev");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    kpex::tech::ProcessStackInfo::MetalLayer *cmim = li->mutable_metal_layer();
    cmim->set_height(metal5_cap->height() + metal5_cap->thickness() + capild_thickness);
    cmim->set_thickness(0.15);
    cmim->set_reference_below("nild6");
    cmim->set_reference_above("topox");
    
    kpex::tech::ProcessStackInfo::Contact *topVia1_cap = metal5_cap->mutable_contact_above();
    topVia1_cap->set_name("mim_via");
    topVia1_cap->set_metal_above("TopMetal1");
    topVia1_cap->set_thickness(topVia1_ncap->thickness() - capild_thickness - cmim->thickness());

    li = psi->add_layers();
    li->set_name("nild5");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(4.1);
    sdl->set_reference("nild4");

    li = psi->add_layers();
    li->set_name("TopMetal1");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    kpex::tech::ProcessStackInfo::MetalLayer *topMetal1 = li->mutable_metal_layer();
    topMetal1->set_height(metal5_ncap->height() + metal5_ncap->thickness() + topVia1_ncap->thickness());
    topMetal1->set_thickness(2.0);
    topMetal1->set_reference_below("nild6");
    topMetal1->set_reference_above("topox");
    
    kpex::tech::ProcessStackInfo::Contact *topVia2 = topMetal1->mutable_contact_above();
    topVia2->set_name("TopVia2");
    topVia2->set_metal_above("TopMetal2");
    topVia2->set_thickness(2.8);

    li = psi->add_layers();
    li->set_name("TopMetal2");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    kpex::tech::ProcessStackInfo::MetalLayer *topMetal2 = li->mutable_metal_layer();
    topMetal2->set_height(topMetal1->height() + topMetal1->thickness() + topVia2->thickness());
    topMetal2->set_thickness(3.0);
    topMetal2->set_reference_below("nild6");
    topMetal2->set_reference_above("topox");

    // TODO: add conformal k=6.6 height 0.4µm, sidewall 0.6µm
    
    li = psi->add_layers();
    li->set_name("air");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(3.0);
    sdl->set_reference("topnit");
}

void buildExtractionInfo(kpex::tech::ExtractionInfo *ex) {
//    ex->set_side_halo(8);
//    ex->set_fringe_shield_halo(8);
//    
//    kpex::tech::ResistanceInfo *ri = ex->mutable_resistance();
//    kpex::tech::ResistanceInfo::LayerResistance *lr = ri->add_layers();
//    lr->set_layer_name("ndiffres");
//    lr->set_resistance(120000);
//    lr->set_corner_adjustment_fraction(0.5);
//    //...
//    lr = ri->add_layers();
//    lr->set_layer_name("poly");
//    lr->set_resistance(48200);
//    //...
//    
//    kpex::tech::ResistanceInfo::ViaResistance *vr = ri->add_vias();
//    vr->set_via_name("mcon");
//    vr->set_resistance(9300);
//    //...
//    
//    kpex::tech::CapacitanceInfo *ci = ex->mutable_capacitance();
//    kpex::tech::CapacitanceInfo::SubstrateCapacitance *sc = ci->add_substrates();
//    sc->set_layer_name("poly");
//    sc->set_area_capacitance(106.13);
//    sc->set_perimeter_capacitance(55.27);
//    
//    kpex::tech::CapacitanceInfo::OverlapCapacitance *oc = ci->add_overlaps();
//    oc->set_top_layer_name("poly");
//    oc->set_bottom_layer_name("active");
//    oc->set_capacitance(106.13);
//    // ...
//    oc = ci->add_overlaps();
//    oc->set_top_layer_name("met1");
//    oc->set_bottom_layer_name("poly");
//    oc->set_capacitance(44.81);
//    
//    kpex::tech::CapacitanceInfo::SidewallCapacitance *swc = ci->add_sidewalls();
//    swc->set_layer_name("met1");
//    swc->set_capacitance(44);
//    swc->set_offset(0.25);
//    // ...
//    
//    kpex::tech::CapacitanceInfo::SideOverlapCapacitance *soc = ci->add_sideoverlaps();
//    soc->set_in_layer_name("met1");
//    soc->set_out_layer_name("poly");
//    soc->set_capacitance(46.72);
//    // ...
}

void buildTech(kpex::tech::Technology &tech) {
    tech.set_name("ihp_sg13g2");
    
    buildLayers(&tech);
    
    buildLVSComputedLayers(&tech);
    
    kpex::tech::ProcessStackInfo *psi = tech.mutable_process_stack();
    buildProcessStackInfo(psi);
    
    kpex::tech::ExtractionInfo *ex = tech.mutable_extraction();
    buildExtractionInfo(ex);
}

}
