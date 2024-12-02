//
//
//
// This creates a technology definition example for sky130A:
// https://skywater-pdk.readthedocs.io/en/main/_images/metal_stack.svg


#include "build/cxx/tech.pb.h"
#include <google/protobuf/io/zero_copy_stream.h>
#include <google/protobuf/io/printer.h>
#include <google/protobuf/text_format.h>
#include <google/protobuf/util/json_util.h>

#include <iostream>
#include <fstream>
#include <string>
#include <sstream>

enum Format {
    PROTOBUF_TEXTUAL,
    PROTOBUF_BINARY,
    JSON
};

const char *describeFormat(Format format) {
    switch (format) {
        case Format::PROTOBUF_TEXTUAL: return "Protobuf Textual";
        case Format::PROTOBUF_BINARY: return "Protobuf Binary";
        case Format::JSON: return "JSON";
    }
}

void write(const kpex::tech::Technology &tech,
           const std::string &outputPath,
           Format format)
{
    std::cout << "Writing technology protobuf message to file '" << outputPath << "' "
              << "in " << describeFormat(format) << " format." << std::endl;
    
    switch (format) {
        case Format::PROTOBUF_TEXTUAL: {
            std::ofstream output(outputPath, std::ios::out | std::ios::binary);
            google::protobuf::io::OstreamOutputStream zcos(&output);
            google::protobuf::TextFormat::Print(tech, &zcos);
            break;
        }
            
        case Format::PROTOBUF_BINARY: {
            std::ofstream output(outputPath, std::ios::out | std::ios::binary);
            tech.SerializeToOstream(&output);
            break;
        }
            
        case Format::JSON: {
            std::string jsonString;
            google::protobuf::util::JsonPrintOptions options;
            options.add_whitespace = true;
            options.preserve_proto_field_names = true;
            auto status =
                google::protobuf::util::MessageToJsonString(tech, &jsonString, options);
            std::ofstream output(outputPath, std::ios::out | std::ios::binary);
            output << jsonString;
            output.close();
            break;
        }
    }
}

void read(kpex::tech::Technology *tech,
          const std::string &inputPath,
          Format format)
{
    std::cout << "Reading technology protobuf message from file '" << inputPath << "' "
              << "in " << describeFormat(format) << " format." << std::endl;
    
    switch (format) {
        case Format::PROTOBUF_TEXTUAL: {
            std::fstream input(inputPath, std::ios::in);
            google::protobuf::io::IstreamInputStream fis(&input);
            google::protobuf::TextFormat::Parse(&fis, tech);
            break;
        }
            
        case Format::PROTOBUF_BINARY: {
            std::fstream input(inputPath, std::ios::in | std::ios::binary);
            tech->ParseFromIstream(&input);
            break;
        }
        
        case Format::JSON: {
            google::protobuf::util::JsonParseOptions options;

            std::fstream input(inputPath, std::ios::in);
            std::ostringstream buffer;
            buffer << input.rdbuf();
            auto status =
                google::protobuf::util::JsonStringToMessage(buffer.str(), tech, options);
            break;
        }
    }
}

void convert(const std::string &inputPath,
             Format inputFormat,
             const std::string &outputPath,
             Format outputFormat)
{
    std::cout << "Converting ..." << std::endl;
    
    kpex::tech::Technology tech;
    read(&tech, inputPath, inputFormat);
    write(tech, outputPath, outputFormat);
}

void buildLayers(kpex::tech::Technology *tech) {
    kpex::tech::LayerInfo *layer;
    layer = tech->add_layers();
    layer->set_name("diff");
    layer->set_description("Active (diffusion) area");
    layer->set_gds_layer(65);
    layer->set_gds_datatype(20);
    
    layer = tech->add_layers();
    layer->set_name("tap");
    layer->set_description("Active (diffusion) area (type equal to the well/substrate underneath) (i.e., N+ and P+)");
    layer->set_gds_layer(65);
    layer->set_gds_datatype(44);

    layer = tech->add_layers();
    layer->set_name("diff"); // map this to process stack nwell? (TODO: check this with Matthias)
    layer->set_description("KLayout computed layer: ntap_conn");
    layer->set_gds_layer(65);
    layer->set_gds_datatype(144);

    layer = tech->add_layers();
    layer->set_name("diff"); // map this to process stack subs? (TODO: check this with Matthias)
    layer->set_description("KLayout computed layer: ptap_conn");
    layer->set_gds_layer(65);
    layer->set_gds_datatype(244);

    layer = tech->add_layers();
    layer->set_name("nwell");
    layer->set_description("N-well region");
    layer->set_gds_layer(64);
    layer->set_gds_datatype(20);
    
    layer = tech->add_layers();
    layer->set_name("poly");
    layer->set_description("Poly");
    layer->set_gds_layer(66);
    layer->set_gds_datatype(20);
    
    layer = tech->add_layers();
    layer->set_name("licon1");
    layer->set_description("Contact to local interconnect");
    layer->set_gds_layer(66);
    layer->set_gds_datatype(44);
    
    layer = tech->add_layers();
    layer->set_name("li1");
    layer->set_description("Local interconnect");
    layer->set_gds_layer(67);
    layer->set_gds_datatype(20);
    
    layer = tech->add_layers();
    layer->set_name("mcon");
    layer->set_description("Contact from local interconnect to met1");
    layer->set_gds_layer(67);
    layer->set_gds_datatype(44);
    
    layer = tech->add_layers();
    layer->set_name("met1");
    layer->set_description("Metal 1");
    layer->set_gds_layer(68);
    layer->set_gds_datatype(20);
    
    layer = tech->add_layers();
    layer->set_name("via");
    layer->set_description("Contact from met1 to met2");
    layer->set_gds_layer(68);
    layer->set_gds_datatype(44);
    
    layer = tech->add_layers();
    layer->set_name("met2");
    layer->set_description("Metal 2");
    layer->set_gds_layer(69);
    layer->set_gds_datatype(20);
    
    layer = tech->add_layers();
    layer->set_name("via2");
    layer->set_description("Contact from met2 to met3");
    layer->set_gds_layer(69);
    layer->set_gds_datatype(44);
    
    layer = tech->add_layers();
    layer->set_name("met3");
    layer->set_description("Metal 3");
    layer->set_gds_layer(70);
    layer->set_gds_datatype(20);
    
    layer = tech->add_layers();
    layer->set_name("via3");
    layer->set_description("Contact from met3 to met4");
    layer->set_gds_layer(70);
    layer->set_gds_datatype(44);
    
    layer = tech->add_layers();
    layer->set_name("met4");
    layer->set_description("Metal 4");
    layer->set_gds_layer(71);
    layer->set_gds_datatype(20);

    layer = tech->add_layers();
    layer->set_name("via4");
    layer->set_description("Contact from met4 to met5");
    layer->set_gds_layer(71);
    layer->set_gds_datatype(44);

    layer = tech->add_layers();
    layer->set_name("met5");
    layer->set_description("Metal 5");
    layer->set_gds_layer(72);
    layer->set_gds_datatype(20);
}

void buildProcessStackInfo(kpex::tech::ProcessStackInfo *psi) {
    kpex::tech::ProcessStackInfo::LayerInfo *li = psi->add_layers();
    li->set_name("subs");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SUBSTRATE);
    kpex::tech::ProcessStackInfo::SubstrateLayer *sl = li->mutable_substrate_layer();
    sl->set_height(0.1); // TODO
    sl->set_thickness(0.33); // TODO
    sl->set_reference("fox");

    li = psi->add_layers();
    li->set_name("nwell");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_NWELL);
    kpex::tech::ProcessStackInfo::NWellLayer *wl = li->mutable_nwell_layer();
    wl->set_height(0.0);
    wl->set_reference("fox");
    kpex::tech::ProcessStackInfo::Contact *co = wl->mutable_contact_above();
    co->set_name("licon1");
    co->set_metal_above("li1");
    co->set_thickness(0.9361);

    li = psi->add_layers();
    li->set_name("diff");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_DIFFUSION);
    kpex::tech::ProcessStackInfo::DiffusionLayer *dl = li->mutable_diffusion_layer();
    dl->set_height(0.323);
    dl->set_reference("fox");
    co = dl->mutable_contact_above();
    co->set_name("licon1");
    co->set_metal_above("li1");
    co->set_thickness(0.9361);

//    li = psi->add_layers();
//    li->set_name("mvdiff");
//    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_DIFFUSION);
//    dl = li->mutable_diffusion_layer();
//    dl->set_height(0.3152);
//    dl->set_reference("fox");
//
    li = psi->add_layers();
    li->set_name("fox");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_FIELD_OXIDE);
    kpex::tech::ProcessStackInfo::FieldOxideLayer *fl = li->mutable_field_oxide_layer();
    fl->set_dielectric_k(0.39);
    
    li = psi->add_layers();
    li->set_name("poly");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    kpex::tech::ProcessStackInfo::MetalLayer *ml = li->mutable_metal_layer();
    ml->set_height(0.3262);
    ml->set_thickness(0.18);
    ml->set_reference_below("fox");
    ml->set_reference_above("psg");

    co = ml->mutable_contact_above();
    co->set_name("licon1");
    co->set_metal_above("li1");
    co->set_thickness(0.4299);

    li = psi->add_layers();
    li->set_name("iox");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIDEWALL_DIELECTRIC);
    kpex::tech::ProcessStackInfo::SidewallDielectricLayer *swl = li->mutable_sidewall_dielectric_layer();
    swl->set_dielectric_k(0.39);
    swl->set_height_above_metal(0.18);
    swl->set_width_outside_sidewall(0.006);
    swl->set_reference("poly");
    
    li = psi->add_layers();
    li->set_name("spnit");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIDEWALL_DIELECTRIC);
    swl = li->mutable_sidewall_dielectric_layer();
    swl->set_dielectric_k(7.5);
    swl->set_height_above_metal(0.121);
    swl->set_width_outside_sidewall(0.0431);
    swl->set_reference("iox");
    
    li = psi->add_layers();
    li->set_name("psg");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    kpex::tech::ProcessStackInfo::SimpleDielectricLayer *sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(3.9);
    sdl->set_reference("fox");
    
    li = psi->add_layers();
    li->set_name("li1");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    ml = li->mutable_metal_layer();
    ml->set_height(0.9361);
    ml->set_thickness(0.1);
    ml->set_reference_below("psg");
    ml->set_reference_above("lint");

    co = ml->mutable_contact_above();
    co->set_name("mcon");
    co->set_metal_above("met1");
    co->set_thickness(1.3761 - (0.9361 + 0.1));

    li = psi->add_layers();
    li->set_name("lint");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_CONFORMAL_DIELECTRIC);
    kpex::tech::ProcessStackInfo::ConformalDielectricLayer *cl = li->mutable_conformal_dielectric_layer();
    cl->set_dielectric_k(7.3);
    cl->set_thickness_over_metal(0.075);
    cl->set_thickness_where_no_metal(0.075);
    cl->set_thickness_sidewall(0.075);
    cl->set_reference("li1");

    li = psi->add_layers();
    li->set_name("nild2");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(4.05);
    sdl->set_reference("lint");
    
    li = psi->add_layers();
    li->set_name("met1");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    ml = li->mutable_metal_layer();
    ml->set_height(1.3761);
    ml->set_thickness(0.36);
    ml->set_reference_below("nild2");
    ml->set_reference_above("nild3");

    co = ml->mutable_contact_above();
    co->set_name("via");
    co->set_metal_above("met2");
    co->set_thickness(0.27);

    li = psi->add_layers();
    li->set_name("nild3c");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIDEWALL_DIELECTRIC);
    swl = li->mutable_sidewall_dielectric_layer();
    swl->set_dielectric_k(3.5);
    swl->set_height_above_metal(0.0);
    swl->set_width_outside_sidewall(0.03);
    swl->set_reference("met1");
    
    li = psi->add_layers();
    li->set_name("nild3");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(4.5);
    sdl->set_reference("nild2");

    li = psi->add_layers();
    li->set_name("met2");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    ml = li->mutable_metal_layer();
    ml->set_height(2.0061);
    ml->set_thickness(0.36);
    ml->set_reference_below("nild3");
    ml->set_reference_above("nild4");

    co = ml->mutable_contact_above();
    co->set_name("via2");
    co->set_metal_above("met3");
    co->set_thickness(0.42);

    li = psi->add_layers();
    li->set_name("nild4c");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIDEWALL_DIELECTRIC);
    swl = li->mutable_sidewall_dielectric_layer();
    swl->set_dielectric_k(3.5);
    swl->set_height_above_metal(0.0);
    swl->set_width_outside_sidewall(0.03);
    swl->set_reference("met2");
    
    li = psi->add_layers();
    li->set_name("nild4");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(4.2);
    sdl->set_reference("nild3");

    li = psi->add_layers();
    li->set_name("met3");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    ml = li->mutable_metal_layer();
    ml->set_height(2.7861);
    ml->set_thickness(0.845);
    ml->set_reference_below("nild4");
    ml->set_reference_above("nild5");

    co = ml->mutable_contact_above();
    co->set_name("via3");
    co->set_metal_above("met4");
    co->set_thickness(0.39);

    li = psi->add_layers();
    li->set_name("nild5");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(4.1);
    sdl->set_reference("nild4");
    
    li = psi->add_layers();
    li->set_name("met4");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    ml = li->mutable_metal_layer();
    ml->set_height(4.0211);
    ml->set_thickness(0.845);
    ml->set_reference_below("nild5");
    ml->set_reference_above("nild6");

    co = ml->mutable_contact_above();
    co->set_name("via4");
    co->set_metal_above("met5");
    co->set_thickness(0.505);

    li = psi->add_layers();
    li->set_name("nild6");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(4.0);
    sdl->set_reference("nild5");
    
    li = psi->add_layers();
    li->set_name("met5");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    ml = li->mutable_metal_layer();
    ml->set_height(5.3711);
    ml->set_thickness(1.26);
    ml->set_reference_below("nild6");
    ml->set_reference_above("topox");

    li = psi->add_layers();
    li->set_name("topox");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIDEWALL_DIELECTRIC);
    swl = li->mutable_sidewall_dielectric_layer();
    swl->set_dielectric_k(3.9);
    swl->set_height_above_metal(0.09);
    swl->set_width_outside_sidewall(0.07);
    swl->set_reference("met5");
    
    li = psi->add_layers();
    li->set_name("topnit");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_CONFORMAL_DIELECTRIC);
    cl = li->mutable_conformal_dielectric_layer();
    cl->set_dielectric_k(7.5);
    cl->set_thickness_over_metal(0.54);
    cl->set_thickness_where_no_metal(0.4223);
    cl->set_thickness_sidewall(0.3777);
    cl->set_reference("topox");

    li = psi->add_layers();
    li->set_name("air");
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(3.0);
    sdl->set_reference("topnit");
}

void buildExtractionInfo(kpex::tech::ExtractionInfo *ex) {
    ex->set_side_halo(8);
    ex->set_fringe_shield_halo(8);

    kpex::tech::ResistanceInfo *ri = ex->mutable_resistance();
    kpex::tech::ResistanceInfo::LayerResistance *lr = ri->add_layers();
    lr->set_layer_name("ndiffres");
    lr->set_resistance(120000);
    lr->set_corner_adjustment_fraction(0.5);
    //...
    lr = ri->add_layers();
    lr->set_layer_name("poly");
    lr->set_resistance(48200);
    //...

    kpex::tech::ResistanceInfo::ViaResistance *vr = ri->add_vias();
    vr->set_via_name("mcon");
    vr->set_resistance(9300);
    //...

    kpex::tech::CapacitanceInfo *ci = ex->mutable_capacitance();
    kpex::tech::CapacitanceInfo::SubstrateCapacitance *sc = ci->add_substrates();
    sc->set_layer_name("poly");
    sc->set_area_capacitance(106.13);
    sc->set_perimeter_capacitance(55.27);

    kpex::tech::CapacitanceInfo::OverlapCapacitance *oc = ci->add_overlaps();
    oc->set_top_layer_name("poly");
    oc->set_bottom_layer_name("active");
    oc->set_capacitance(106.13);
    // ...
    oc = ci->add_overlaps();
    oc->set_top_layer_name("met1");
    oc->set_bottom_layer_name("poly");
    oc->set_capacitance(44.81);

    kpex::tech::CapacitanceInfo::SidewallCapacitance *swc = ci->add_sidewalls();
    swc->set_layer_name("met1");
    swc->set_capacitance(44);
    swc->set_offset(0.25);
    // ...

    kpex::tech::CapacitanceInfo::SideOverlapCapacitance *soc = ci->add_sideoverlaps();
    soc->set_in_layer_name("met1");
    soc->set_out_layer_name("poly");
    soc->set_capacitance(46.72);
    // ...
}

void buildDemoTech(kpex::tech::Technology &tech) {
    tech.set_name("sky130A");

    buildLayers(&tech);

    kpex::tech::ProcessStackInfo *psi = tech.mutable_process_stack();
    buildProcessStackInfo(psi);

    kpex::tech::ExtractionInfo *ex = tech.mutable_extraction();
    buildExtractionInfo(ex);
}

int main(int argc, char **argv) {
    // Verify that the version of the library that we linked against is
    // compatible with the version of the headers we compiled against.
    GOOGLE_PROTOBUF_VERIFY_VERSION;
    
    kpex::tech::Technology tech;
    buildDemoTech(tech);
    
    write(tech, "build/sky130A_tech.pb.json", Format::JSON);
    write(tech, "build/sky130A_tech.binpb", Format::PROTOBUF_BINARY);
    write(tech, "build/sky130A_tech.txtpb", Format::PROTOBUF_TEXTUAL);
    
    std::cout << "--------------------------------------------" << std::endl;
    convert("build/sky130A_tech.pb.json", Format::JSON,
            "build/sky130A_tech__from_json.txtpb", Format::PROTOBUF_TEXTUAL);
    std::cout << "--------------------------------------------" << std::endl;
    convert("build/sky130A_tech.pb.json", Format::JSON,
            "build/sky130A_tech__from_json.binpb", Format::PROTOBUF_BINARY);
    std::cout << "--------------------------------------------" << std::endl;
    convert("build/sky130A_tech.pb.json", Format::JSON,
            "build/sky130A_tech__from_json.json", Format::JSON);

    // Optional:  Delete all global objects allocated by libprotobuf.
    google::protobuf::ShutdownProtobufLibrary();
}

