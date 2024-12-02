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

