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
#ifndef __PROTO_H__
#define __PROTO_H__

#include <iostream>
#include <fstream>
#include <string>
#include <sstream>

#include "tech.capnp.h"

enum Format {
    PROTO_TEXTUAL,
    PROTO_BINARY,
    JSON
};

const char *describeFormat(Format format);

void write(capnp::MessageBuilder &msg,
           kpex::tech::Technology::Builder &tech,
           const std::string &outputPath,
           Format format);

//-------------------------------------------------------------------------

struct LayerInfoEntry {
    std::string name;
    uint32_t drwGDSLayer;
    uint32_t drwGDSDataType;
    int64_t pinGDSLayer;       // -1 if not available
    int64_t pinGDSDataType;    // -1 if not available
    int64_t labelGDSLayer;     // -1 if not available
    int64_t labelGDSDataType;  // -1 if not available
    std::string description;
};

struct ComputedLayerInfoEntry {
    kpex::tech::ComputedLayerInfo::Kind kind;
    std::string name;
    uint32_t gdsLayer;
    uint32_t gdsDataType;
    std::string originalLayerName;
    std::string description;
};

template<std::size_t N>
void setLayerInfos(kpex::tech::Technology::Builder *tech,
                   const LayerInfoEntry (&entries)[N])
{
    auto layers = tech->initLayers(N);
    
    for (uint i=0; i < N; ++i) {
        auto ei = entries[i];

        auto li = layers[i];
        li.setName(ei.name);
        li.setDescription(ei.description);
        
        {
            auto gdsPair = li.initDrwGDSPair();
            gdsPair.setLayer(ei.drwGDSLayer);
            gdsPair.setDatatype(ei.drwGDSDataType);
        }
        
        if (ei.pinGDSLayer >= 0 && ei.pinGDSDataType >= 0) {
            auto gdsPair = li.initPinGDSPair();
            gdsPair.setLayer((uint32_t)ei.pinGDSLayer);
            gdsPair.setDatatype((uint32_t)ei.pinGDSDataType);
        }
        
        if (ei.labelGDSLayer >= 0 && ei.labelGDSDataType >= 0) {
            auto gdsPair = li.initLabelGDSPair();
            gdsPair.setLayer((uint32_t)ei.labelGDSLayer);
            gdsPair.setDatatype((uint32_t)ei.labelGDSDataType);
        }
    }
}

template<std::size_t N>
void setLvsComputedLayerInfos(kpex::tech::Technology::Builder *tech,
                              const ComputedLayerInfoEntry (&entries)[N])

{
    auto cl = tech->initLvsComputedLayers(N);
    
    for (uint i=0; i < N; ++i) {
        auto ei = entries[i];
        
        auto cli = cl[i];
        cli.setKind(ei.kind);
        cli.setOriginalLayerName(ei.originalLayerName);
        auto li = cli.initLayerInfo();
        li.setName(ei.name);
        li.setDescription(ei.description);
        auto gdsPair = li.initDrwGDSPair();
        gdsPair.setLayer(ei.gdsLayer);
        gdsPair.setDatatype(ei.gdsDataType);
    }
}


//-------------------------------------------------------------------------

void setSubstrateLayer(::kpex::tech::ProcessStackInfo::LayerInfo::Builder layer,
                       const std::string &layer_name,
                       double height,
                       double thickness,
                       const std::string &reference);

void setNWellLayer(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                   const std::string &layer_name,
                   double z,
                   const std::string &reference);

void setContact(kpex::tech::ProcessStackInfo::Contact::Builder *co,
                const std::string &name,
                const std::string &layer_below,
                const std::string &layer_above,
                double thickness,
                double width,
                double spacing,
                double border);

void setDiffusionLayer(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                       const std::string &layer_name,
                       double z,
                       const std::string &reference);

void setFieldOxideLayer(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                        const std::string &name,
                        double dielectric_k);

void setMetalLayer(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
              const std::string &layer_name,
              double z,
              double thickness);

void setSidewallDielectric(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                           const std::string &name,
                           double dielectric_k,
                           double height_above_metal,
                           double width_outside_sidewall,
                           const std::string &reference);

void setSimpleDielectric(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                         const std::string &name,
                         double dielectric_k,
                         const std::string &reference);

void setConformalDielectric(::kpex::tech::ProcessStackInfo::LayerInfo::Builder li,
                            const std::string &name,
                            double dielectric_k,
                            double thickness_over_metal,
                            double thickness_where_mo_metal,
                            double thickness_sidewall,
                            const std::string &reference);

//-------------------------------------------------------------------------

struct LayerResistanceEntry {
    std::string layerName;
    double resistance;
};

struct ContactResistanceEntry {
    std::string contactName;
    std::string deviceLayerName;
    double resistance;
};

struct ViaResistanceEntry {
    std::string viaName;
    double resistance;
};


template<std::size_t N>
void setLayerResistances(kpex::tech::ResistanceInfo::Builder *ri,
                         const LayerResistanceEntry (&entries)[N])
{
    auto lr = ri->initLayers(N);
    for (uint i=0; i < N; ++i) {
        auto lri = lr[i];
        auto ei = entries[i];
        lri.setLayerName(ei.layerName);
        lri.setResistance(ei.resistance);
    }
}

template<std::size_t N>
void setContactResistance(kpex::tech::ResistanceInfo::Builder *ri,
                          const ContactResistanceEntry (&entries)[N])
{
    auto cl = ri->initContacts(N);
    for (uint i=0; i < N; ++i) {
        auto cli = cl[i];
        auto ei = entries[i];
        cli.setContactName(ei.contactName);
        cli.setDeviceLayerName(ei.deviceLayerName);
        cli.setResistance(ei.resistance);
    }
}

template<std::size_t N>
void setViaResistance(kpex::tech::ResistanceInfo::Builder *ri,
                      const ViaResistanceEntry (&entries)[N])
{
    auto vl = ri->initVias(N);
    for (uint i=0; i < N; ++i) {
        auto vli = vl[i];
        auto ei = entries[i];
        vli.setViaName(ei.viaName);
        vli.setResistance(ei.resistance);
    }
}

struct SubstrateCapEntry {
    std::string layerName;
    float areaCapacitance;
    float perimeterCapacitance;
};

struct OverlapCapEntry {
    std::string topLayerName;
    std::string bottomLayerName;
    float capacitance;
};

struct SidewallCapEntry {
    std::string layerName;
    float capacitance;
    float offset;
};

struct FringeCapEntry {
    std::string inLayerName;
    std::string outLayerName;
    float capacitance;
};


template<std::size_t N>
void setSubstrateCaps(kpex::tech::CapacitanceInfo::Builder *ci,
                      const SubstrateCapEntry (&entries)[N])
{
   auto sl = ci->initSubstrates(N);
   for (uint i=0; i < N; ++i) {
       auto sli = sl[i];
       auto ei = entries[i];
       sli.setLayerName(ei.layerName);
       sli.setAreaCapacitance(ei.areaCapacitance);
       sli.setPerimeterCapacitance(ei.perimeterCapacitance);
   }
}

template<std::size_t N>
void setOverlapCaps(kpex::tech::CapacitanceInfo::Builder *ci,
                    const OverlapCapEntry (&entries)[N])
{
   auto ol = ci->initOverlaps(N);
   for (uint i=0; i < N; ++i) {
       auto oli = ol[i];
       auto ei = entries[i];
       oli.setTopLayerName(ei.topLayerName);
       oli.setBottomLayerName(ei.bottomLayerName);
       oli.setCapacitance(ei.capacitance);
   }
}

template<std::size_t N>
void setSidewallCaps(kpex::tech::CapacitanceInfo::Builder *ci,
                    const SidewallCapEntry (&entries)[N])
{
   auto sl = ci->initSidewalls(N);
   for (uint i=0; i < N; ++i) {
       auto sli = sl[i];
       auto ei = entries[i];
       sli.setLayerName(ei.layerName);
       sli.setCapacitance(ei.capacitance);
       sli.setOffset(ei.offset);
   }
}

template<std::size_t N>
void setFringeCaps(kpex::tech::CapacitanceInfo::Builder *ci,
                   const FringeCapEntry (&entries)[N])
{
   auto ol = ci->initFringes(N);
   for (uint i=0; i < N; ++i) {
       auto oli = ol[i];
       auto ei = entries[i];
       oli.setInLayerName(ei.inLayerName);
       oli.setOutLayerName(ei.outLayerName);
       oli.setCapacitance(ei.capacitance);
   }
}

#endif
