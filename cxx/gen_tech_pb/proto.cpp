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
#include "proto.h"

#include <fstream>
#include <vector>

#include <capnp/message.h>
#include <capnp/serialize.h>
#include <capnp/serialize-text.h>
#include <capnp/compat/json.h>
#include <kj/io.h>
#include <kj/std/iostream.h> // Needed!

const char *describeFormat(Format format) {
    switch (format) {
        case Format::PROTO_TEXTUAL: return "Cap'n Proto Textual";
        case Format::PROTO_BINARY: return "Cap'n Proto Binary";
        case Format::JSON: return "JSON";
    }
}

void write(capnp::MessageBuilder &msg,
           kpex::tech::Technology::Builder &tech,
           const std::string &outputPath,
           Format format)
{
    std::cout << "Writing technology proto message to file '" << outputPath << "' "
              << "in " << describeFormat(format) << " format." << std::endl;
    
    std::ofstream output(outputPath, std::ios::out | std::ios::binary);

    switch (format) {
        case Format::PROTO_TEXTUAL: {
            output << "# proto-schema-file: tech.capnp" << std::endl
                   << "# proto-message: kpex.tech.Technology" << std::endl << std::endl;
            
            kj::std::StdOutputStream kjOut(output);
            capnp::TextCodec textCodec;
            textCodec.setPrettyPrint(true);
            kj::String protoTextString = textCodec.encode(tech);
            output << protoTextString.cStr();
            output.close();
            break;
        }

        case Format::PROTO_BINARY: {
            kj::std::StdOutputStream kjOut(output);
            capnp::writeMessage(kjOut, msg);
            break;
        }
            
        case Format::JSON: {
            capnp::JsonCodec jsonCodec;
            jsonCodec.setPrettyPrint(true);
            kj::String jsonString = jsonCodec.encode(tech);
            output << jsonString.cStr();
            output.close();
            break;
        }
    }
    
    output.close();
}


//-------------------------------------------------------------------------

void setSubstrateLayer(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                       const std::string &layer_name,
                       double height,
                       double thickness,
                       const std::string &reference)
{
    li.setName(layer_name);
    li.setLayerType(kpex::tech::ProcessStackInfo::LayerType::SUBSTRATE);
    auto sl = li.initSubstrateLayer();
    sl.setHeight(height);
    sl.setThickness(thickness);
    sl.setReference(reference);
}

void setNWellLayer(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                   const std::string &layer_name,
                   double z,
                   const std::string &reference)
{
    li.setName(layer_name);
    li.setLayerType(kpex::tech::ProcessStackInfo::LayerType::NWELL);
    auto wl = li.initNwellLayer();
    wl.setZ(z);
    wl.setReference(reference);
}

void setContact(kpex::tech::ProcessStackInfo::Contact::Builder *co,
                const std::string &name,
                const std::string &layer_below,
                const std::string &layer_above,
                double thickness,
                double width,
                double spacing,
                double border)
{
    co->setName(name);
    co->setLayerBelow(layer_below);
    co->setLayerAbove(layer_above);
    co->setThickness(thickness);
    co->setWidth(width);
    co->setSpacing(spacing);
    co->setBorder(border);
}

void setDiffusionLayer(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                       const std::string &layer_name,
                       double z,
                       const std::string &reference)
{
    li.setName(layer_name);
    li.setLayerType(kpex::tech::ProcessStackInfo::LayerType::DIFFUSION);
    auto dl = li.initDiffusionLayer();
    dl.setZ(z);
    dl.setReference(reference);
}

void setFieldOxideLayer(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                        const std::string &name,
                        double dielectric_k)
{
    li.setName(name);
    li.setLayerType(kpex::tech::ProcessStackInfo::LayerType::FIELD_OXIDE);
    auto fl = li.initFieldOxideLayer();
    fl.setDielectricK(dielectric_k);
}

void setMetalLayer(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                   const std::string &layer_name,
                   double z,
                   double thickness)
{
    li.setName(layer_name);
    li.setLayerType(kpex::tech::ProcessStackInfo::LayerType::METAL);
    auto ml = li.initMetalLayer();
    ml.setZ(z);
    ml.setThickness(thickness);
}

void setSidewallDielectric(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                           const std::string &name,
                           double dielectric_k,
                           double height_above_metal,
                           double width_outside_sidewall,
                           const std::string &reference)
{
    li.setName(name);
    li.setLayerType(kpex::tech::ProcessStackInfo::LayerType::SIDEWALL_DIELECTRIC);
    auto swl = li.initSidewallDielectricLayer();
    swl.setDielectricK(dielectric_k);
    swl.setHeightAboveMetal(height_above_metal);
    swl.setWidthOutsideSidewall(width_outside_sidewall);
    swl.setReference(reference);
}

void setSimpleDielectric(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                         const std::string &name,
                         double dielectric_k,
                         const std::string &reference)
{
    li.setName(name);
    li.setLayerType(kpex::tech::ProcessStackInfo::LayerType::SIMPLE_DIELECTRIC);
    auto sdl = li.initSimpleDielectricLayer();
    sdl.setDielectricK(dielectric_k);
    sdl.setReference(reference);
}

void setConformalDielectric(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                            const std::string &name,
                            double dielectric_k,
                            double thickness_over_metal,
                            double thickness_where_mo_metal,
                            double thickness_sidewall,
                            const std::string &reference)
{
    li.setName(name);
    li.setLayerType(kpex::tech::ProcessStackInfo::LayerType::CONFORMAL_DIELECTRIC);
    auto cl = li.initConformalDielectricLayer();
    cl.setDielectricK(dielectric_k);
    cl.setThicknessOverMetal(thickness_over_metal);
    cl.setThicknessWhereNoMetal(thickness_where_mo_metal);
    cl.setThicknessSidewall(thickness_sidewall);
    cl.setReference(reference);
}
