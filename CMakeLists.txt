#[[
--------------------------------------------------------------------------------
SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
Johannes Kepler University, Institute for Integrated Circuits.

This file is part of KPEX 
(see https://github.com/martinjankoehler/klayout-pex).

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
SPDX-License-Identifier: GPL-3.0-or-later
--------------------------------------------------------------------------------
]]

# minimum version is 3.0 to be able to handle Eigen library
cmake_minimum_required (VERSION 3.12)
project (kpex)

set(CMAKE_CXX_STANDARD 23)
if(MSVC)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /std:c++latest")
endif(MSVC)

#_____________________________________________________________________________________________

# add dependencies
include(cmake/CPM.cmake)
CPMAddPackage(
    NAME protobuf
    GIT_TAG v31.0
    GIT_REPOSITORY "https://github.com/protocolbuffers/protobuf.git"
    OPTIONS
        "protobuf_INSTALL OFF"
        "protobuf_BUILD_TESTS OFF"
        "protobuf_BUILD_SHARED_LIBS OFF"
        "protobuf_BUILD_EXAMPLES OFF"
        "ABSL_PROPAGATE_CXX_STD ON"
)

#_____________________________________________________________________________________________

# see https://github.com/protocolbuffers/protobuf/blob/main/docs/cmake_protobuf_generate.md
include(${protobuf_SOURCE_DIR}/cmake/protobuf-generate.cmake)
set(Protobuf_INCLUDE_DIRS ${protobuf_SOURCE_DIR}/src)

set(PROTOBUF_SOURCES
    ${CMAKE_CURRENT_LIST_DIR}/protos/kpex/geometry/shapes.proto
    ${CMAKE_CURRENT_LIST_DIR}/protos/kpex/result/pex_result.proto
    ${CMAKE_CURRENT_LIST_DIR}/protos/kpex/tech/tech.proto
    ${CMAKE_CURRENT_LIST_DIR}/protos/kpex/tech/process_stack.proto
    ${CMAKE_CURRENT_LIST_DIR}/protos/kpex/tech/process_parasitics.proto
)

add_library(kpex-protobuf OBJECT ${PROTOBUF_SOURCES})

target_link_libraries(kpex-protobuf PUBLIC protobuf::libprotobuf)

file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/generated")
set(PROTOBUF_BINARY_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated")

target_include_directories(kpex-protobuf PUBLIC "$<BUILD_INTERFACE:${PROTOBUF_BINARY_DIR}>")

protobuf_generate(
	TARGET kpex-protobuf 
	IMPORT_DIRS "${CMAKE_CURRENT_LIST_DIR}/protos"
	PROTOC_OUT_DIR "${PROTOBUF_BINARY_DIR}"
)

#_____________________________________________________________________________________________

set(PROTOBUF_PYTHON_GENERATED "${CMAKE_CURRENT_LIST_DIR}/klayout_pex_protobuf")
file(MAKE_DIRECTORY "${PROTOBUF_PYTHON_GENERATED}")

protobuf_generate(
	TARGET kpex-protobuf
	LANGUAGE python
	IMPORT_DIRS "${CMAKE_CURRENT_LIST_DIR}/protos"
	PROTOC_OUT_DIR "${PROTOBUF_PYTHON_GENERATED}"
)

#_____________________________________________________________________________________________

include_directories(${PROJECT_SOURCE_DIR}/cxx/gen_tech_pb)
set(GEN_TECH_PB_SOURCES
    ${CMAKE_CURRENT_LIST_DIR}/cxx/gen_tech_pb/pdk/sky130A.cpp
    ${CMAKE_CURRENT_LIST_DIR}/cxx/gen_tech_pb/pdk/ihp_sg13g2.cpp
    ${CMAKE_CURRENT_LIST_DIR}/cxx/gen_tech_pb/protobuf.cpp
    ${CMAKE_CURRENT_LIST_DIR}/cxx/gen_tech_pb/main.cpp
)
add_executable(gen_tech_pb ${GEN_TECH_PB_SOURCES})
target_include_directories(gen_tech_pb PUBLIC ${Protobuf_INCLUDE_DIRS})
target_link_libraries(gen_tech_pb kpex-protobuf)

#_____________________________________________________________________________________________
