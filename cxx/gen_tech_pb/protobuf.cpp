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
#include "protobuf.h"

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
            output << "# proto-file: tech.proto" << std::endl
                   << "# proto-message: kpex.tech.Technology" << std::endl << std::endl;
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

void addLayer(kpex::tech::Technology *tech,
              const std::string &name,
              uint32_t gds_layer,
              uint32_t gds_datatype,
              const std::string &description)
{
    kpex::tech::LayerInfo *layer = tech->add_layers();
    layer->set_name(name);
    layer->set_description(description);
    layer->set_gds_layer(gds_layer);
    layer->set_gds_datatype(gds_datatype);
}

void addPinLayerMapping(kpex::tech::Technology *tech,
                        const std::string &description,
                        uint32_t pin_gds_layer,
                        uint32_t pin_gds_datatype,
                        uint32_t drw_gds_layer,
                        uint32_t drw_gds_datatype)
{
    kpex::tech::PinLayerMapping *m = tech->add_pin_layer_mappings();
    m->set_description(description);
    m->set_pin_gds_layer(pin_gds_layer);
    m->set_pin_gds_datatype(pin_gds_datatype);
    m->set_drw_gds_layer(drw_gds_layer);
    m->set_drw_gds_datatype(drw_gds_datatype);
}

void addComputedLayer(kpex::tech::Technology *tech,
                      kpex::tech::ComputedLayerInfo_Kind kind,
                      const std::string &name,
                      uint32_t gds_layer,
                      uint32_t gds_datatype,
                      const std::string &original_layer_name,
                      const std::string &description)
{
    kpex::tech::ComputedLayerInfo *cl = tech->add_lvs_computed_layers();
    cl->set_kind(kind);
    cl->set_original_layer_name(original_layer_name);
    kpex::tech::LayerInfo *layer = cl->mutable_layer_info();
    layer->set_name(name);
    layer->set_description(description);
    layer->set_gds_layer(gds_layer);
    layer->set_gds_datatype(gds_datatype);
}

//-------------------------------------------------------------------------

void addSubstrateLayer(kpex::tech::ProcessStackInfo *psi,
                       const std::string &layer_name,
                       double height,
                       double thickness,
                       const std::string &reference)
{
    kpex::tech::ProcessStackInfo::LayerInfo *li = psi->add_layers();
    li->set_name(layer_name);
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SUBSTRATE);
    kpex::tech::ProcessStackInfo::SubstrateLayer *sl = li->mutable_substrate_layer();
    sl->set_height(height);
    sl->set_thickness(thickness);
    sl->set_reference(reference);
}

kpex::tech::ProcessStackInfo::NWellLayer *
addNWellLayer(kpex::tech::ProcessStackInfo *psi,
                   const std::string &layer_name,
                   double height,
                   const std::string &reference)
{
    kpex::tech::ProcessStackInfo::LayerInfo *li = psi->add_layers();
    li->set_name(layer_name);
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_NWELL);
    kpex::tech::ProcessStackInfo::NWellLayer *wl = li->mutable_nwell_layer();
    wl->set_height(height);
    wl->set_reference(reference);
    return wl;
}

void setContact(kpex::tech::ProcessStackInfo::Contact *co,
                const std::string &name,
                const std::string &layer_above,
                double thickness,
                double width,
                double spacing,
                double border)
{
    co->set_name(name);
    co->set_metal_above(layer_above);
    co->set_thickness(thickness);
    co->set_width(width);
    co->set_spacing(spacing);
    co->set_border(border);
}

kpex::tech::ProcessStackInfo::DiffusionLayer *
addDiffusionLayer(kpex::tech::ProcessStackInfo *psi,
                  const std::string &name,
                  double height,
                  const std::string &reference)
{
    kpex::tech::ProcessStackInfo::LayerInfo *li = psi->add_layers();
    li->set_name(name);
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_DIFFUSION);
    kpex::tech::ProcessStackInfo::DiffusionLayer *dl = li->mutable_diffusion_layer();
    dl->set_height(height);
    dl->set_reference(reference);
    return dl;
}

void addFieldOxideLayer(kpex::tech::ProcessStackInfo *psi,
                        const std::string &name,
                        double dielectric_k)
{
    kpex::tech::ProcessStackInfo::LayerInfo *li = psi->add_layers();
    li->set_name(name);
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_FIELD_OXIDE);
    kpex::tech::ProcessStackInfo::FieldOxideLayer *fl = li->mutable_field_oxide_layer();
    fl->set_dielectric_k(dielectric_k);
}

kpex::tech::ProcessStackInfo::MetalLayer *
addMetalLayer(kpex::tech::ProcessStackInfo *psi,
              const std::string &layer_name,
              double height,
              double thickness,
              const std::string &reference_below,
              const std::string &reference_above)
{
    kpex::tech::ProcessStackInfo::LayerInfo *li = psi->add_layers();
    li->set_name(layer_name);
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_METAL);
    kpex::tech::ProcessStackInfo::MetalLayer *ml = li->mutable_metal_layer();
    ml->set_height(height);
    ml->set_thickness(thickness);
    ml->set_reference_below(reference_below);
    ml->set_reference_above(reference_above);
    return ml;
}

void addSidewallDielectric(kpex::tech::ProcessStackInfo *psi,
                           const std::string &name,
                           double dielectric_k,
                           double height_above_metal,
                           double width_outside_sidewall,
                           const std::string &reference)
{
    kpex::tech::ProcessStackInfo::LayerInfo *li = psi->add_layers();
    li->set_name(name);
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIDEWALL_DIELECTRIC);
    kpex::tech::ProcessStackInfo::SidewallDielectricLayer *swl = li->mutable_sidewall_dielectric_layer();
    swl->set_dielectric_k(dielectric_k);
    swl->set_height_above_metal(height_above_metal);
    swl->set_width_outside_sidewall(width_outside_sidewall);
    swl->set_reference(reference);
}

void addSimpleDielectric(kpex::tech::ProcessStackInfo *psi,
                         const std::string &name,
                         double dielectric_k,
                         const std::string &reference)
{
    kpex::tech::ProcessStackInfo::LayerInfo *li = psi->add_layers();
    li->set_name(name);
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_SIMPLE_DIELECTRIC);
    kpex::tech::ProcessStackInfo::SimpleDielectricLayer *sdl = li->mutable_simple_dielectric_layer();
    sdl->set_dielectric_k(dielectric_k);
    sdl->set_reference(reference);
}

void addConformalDielectric(kpex::tech::ProcessStackInfo *psi,
                            const std::string &name,
                            double dielectric_k,
                            double thickness_over_metal,
                            double thickness_where_mo_metal,
                            double thickness_sidewall,
                            const std::string &reference)
{
    kpex::tech::ProcessStackInfo::LayerInfo *li = psi->add_layers();
    li->set_name(name);
    li->set_layer_type(kpex::tech::ProcessStackInfo::LAYER_TYPE_CONFORMAL_DIELECTRIC);
    kpex::tech::ProcessStackInfo::ConformalDielectricLayer *cl = li->mutable_conformal_dielectric_layer();
    cl->set_dielectric_k(dielectric_k);
    cl->set_thickness_over_metal(thickness_over_metal);
    cl->set_thickness_where_no_metal(thickness_where_mo_metal);
    cl->set_thickness_sidewall(thickness_sidewall);
    cl->set_reference(reference);
}


//-------------------------------------------------------------------------

void addLayerResistance(kpex::tech::ResistanceInfo *ri,
                        const std::string &layer_name,
                        double resistance)
{
    kpex::tech::ResistanceInfo::LayerResistance *lr = ri->add_layers();
    lr->set_layer_name(layer_name);
    lr->set_resistance(resistance);
}

void addLayerResistance(kpex::tech::ResistanceInfo *ri,
                        const std::string &layer_name,
                        double resistance,
                        double corner_adjustment_fraction)
{
    kpex::tech::ResistanceInfo::LayerResistance *lr = ri->add_layers();
    lr->set_layer_name(layer_name);
    lr->set_resistance(resistance);
    if (corner_adjustment_fraction != 0.0) {
        lr->set_corner_adjustment_fraction(corner_adjustment_fraction);
    }
}

void addViaResistance(kpex::tech::ResistanceInfo *ri,
                      const std::string &via_name,
                      double resistance)
{
    kpex::tech::ResistanceInfo::ViaResistance *vr = ri->add_vias();
    vr->set_via_name(via_name);
    vr->set_resistance(resistance);
}

void addSubstrateCap(kpex::tech::CapacitanceInfo *ci,
                     const std::string &layer_name,
                     float area_cap,
                     float perimeter_cap)
{
    kpex::tech::CapacitanceInfo::SubstrateCapacitance *sc = ci->add_substrates();
    sc->set_layer_name(layer_name);
    sc->set_area_capacitance(area_cap);
    sc->set_perimeter_capacitance(perimeter_cap);
}

void addOverlapCap(kpex::tech::CapacitanceInfo *ci,
                   const std::string &top_layer,
                   const std::string &bottom_layer,
                   float cap)
{
    kpex::tech::CapacitanceInfo::OverlapCapacitance *oc = ci->add_overlaps();
    oc->set_top_layer_name(top_layer);
    oc->set_bottom_layer_name(bottom_layer);
    oc->set_capacitance(cap);
}

void addSidewallCap(kpex::tech::CapacitanceInfo *ci,
                    const std::string &layer_name,
                    float cap,
                    float offset)
{
    kpex::tech::CapacitanceInfo::SidewallCapacitance *swc = ci->add_sidewalls();
    swc->set_layer_name(layer_name);
    swc->set_capacitance(cap);
    swc->set_offset(offset);
}

void addSidewallOverlapCap(kpex::tech::CapacitanceInfo *ci,
                           const std::string &in_layer,
                           const std::string &out_layer,
                           float cap)
{
    kpex::tech::CapacitanceInfo::SideOverlapCapacitance *soc = ci->add_sideoverlaps();
    soc->set_in_layer_name(in_layer);
    soc->set_out_layer_name(out_layer);
    soc->set_capacitance(cap);
}

