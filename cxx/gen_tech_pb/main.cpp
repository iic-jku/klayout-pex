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
#include "pdk/ihp_sg13g2.h"
#include "pdk/sky130A.h"

void writeTech(const std::string &tech_name,
               const kpex::tech::Technology &tech)
{
    const std::string stem = "build/" + tech_name + "_tech";
    write(tech, stem + ".pb.json", Format::JSON);
    
    //    write(tech, stem + ".binpb", Format::PROTOBUF_BINARY);
    //    write(tech, stem + ".txtpb", Format::PROTOBUF_TEXTUAL);
        
    //    std::cout << "--------------------------------------------" << std::endl;
    //    convert(stem + ".pb.json", Format::JSON,
    //            stem + "__from_json.txtpb", Format::PROTOBUF_TEXTUAL);
    //    std::cout << "--------------------------------------------" << std::endl;
    //    convert(stem + "_tech.pb.json", Format::JSON,
    //            stem + "_tech__from_json.binpb", Format::PROTOBUF_BINARY);
    //    std::cout << "--------------------------------------------" << std::endl;
    //    convert(stem + "_tech.pb.json", Format::JSON,
    //            stem + "_tech__from_json.json", Format::JSON);
}

int main(int argc, char **argv) {
    // Verify that the version of the library that we linked against is
    // compatible with the version of the headers we compiled against.
    GOOGLE_PROTOBUF_VERIFY_VERSION;
    
    {
        kpex::tech::Technology tech;
        sky130A::buildTech(tech);
        writeTech("sky130A", tech);
    }
    
    {
        kpex::tech::Technology tech;
        ihp_sg13g2::buildTech(tech);
        writeTech("ihp_sg13g2", tech);
    }

    // Optional:  Delete all global objects allocated by libprotobuf.
    google::protobuf::ShutdownProtobufLibrary();
}

