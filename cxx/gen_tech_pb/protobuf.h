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
#ifndef __PROTOBUF_H__
#define __PROTOBUF_H__

#include <google/protobuf/io/zero_copy_stream.h>
#include <google/protobuf/io/zero_copy_stream_impl.h>
#include <google/protobuf/io/printer.h>
#include <google/protobuf/text_format.h>
#include <google/protobuf/util/json_util.h>

#include <iostream>
#include <fstream>
#include <string>
#include <sstream>

#include "tech.pb.h"

enum Format {
    PROTOBUF_TEXTUAL,
    PROTOBUF_BINARY,
    JSON
};

const char *describeFormat(Format format);

void write(const kpex::tech::Technology &tech,
           const std::string &outputPath,
           Format format);

void read(kpex::tech::Technology *tech,
          const std::string &inputPath,
          Format format);

void convert(const std::string &inputPath,
             Format inputFormat,
             const std::string &outputPath,
             Format outputFormat);

void addLayer(kpex::tech::Technology *tech,
              const std::string &name,
              uint32_t gds_layer,
              uint32_t gds_datatype,
              const std::string &description);

void addComputedLayer(kpex::tech::Technology *tech,
                      kpex::tech::ComputedLayerInfo_Kind kind,
                      const std::string &name,
                      uint32_t gds_layer,
                      uint32_t gds_datatype,
                      const std::string &original_layer_name,
                      const std::string &description);

void addLayerResistance(kpex::tech::ResistanceInfo *ri,
                        const std::string &layer_name,
                        double resistance);

void addLayerResistance(kpex::tech::ResistanceInfo *ri,
                        const std::string &layer_name,
                        double resistance,
                        double corner_adjustment_fraction);

void addViaResistance(kpex::tech::ResistanceInfo *ri,
                      const std::string &via_name,
                      double resistance);

void addSubstrateCap(kpex::tech::CapacitanceInfo *ci,
                     const std::string &layer_name,
                     float area_cap,
                     float perimeter_cap);

void addOverlapCap(kpex::tech::CapacitanceInfo *ci,
                   const std::string &top_layer,
                   const std::string &bottom_layer,
                   float cap);

void addSidewallCap(kpex::tech::CapacitanceInfo *ci,
                    const std::string &layer_name,
                    float cap,
                    float offset);

void addSidewallOverlapCap(kpex::tech::CapacitanceInfo *ci,
                           const std::string &in_layer,
                           const std::string &out_layer,
                           float cap);

#endif

