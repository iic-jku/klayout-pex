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

#include <iostream>
#include <filesystem>

#include "proto.h"
#include "pdk/ihp_sg13g2.h"
#include "pdk/sky130A.h"

#include <capnp/message.h>

void writeTech(const std::filesystem::path &output_directory,
               const std::string &tech_name,
               capnp::MessageBuilder &msg,
               kpex::tech::Technology::Builder &tech)
{
    const std::filesystem::path json_pb_path = output_directory / (tech_name + "_tech" + ".pb.json");
    write(msg, tech, json_pb_path.string(), Format::JSON);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <output-directory>" << std::endl;
        return 1;
    }
    
    std::filesystem::path output_directory(argv[1]);
    if (std::filesystem::exists(output_directory) && !std::filesystem::is_directory(output_directory)) {
        std::cerr << "ERROR: Output directory path already exists, but is not a directory" << std::endl;
        return 2;
    }
    std::filesystem::create_directories(output_directory);

    {
        ::capnp::MallocMessageBuilder msg;
        kpex::tech::Technology::Builder tech = msg.initRoot<kpex::tech::Technology>();
        sky130A::buildTech(tech);
        writeTech(output_directory, "sky130A", msg, tech);
    }
    
    {
        ::capnp::MallocMessageBuilder msg;
        kpex::tech::Technology::Builder tech = msg.initRoot<kpex::tech::Technology>();
        ihp_sg13g2::buildTech(tech);
        writeTech(output_directory, "ihp_sg13g2", msg, tech);
    }

    return 0;
}

