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
    NAME capnproto
    GIT_TAG v2   #v1.2.0
    GITHUB_REPOSITORY capnproto/capnproto
    OPTIONS
        "WITH_OPENSSL OFF"
        "BUILD_TESTING OFF"
)

add_definitions(${CAPNP_DEFINITIONS})

#_____________________________________________________________________________________________

set(CPNPROTO_OUT_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${CPNPROTO_OUT_DIR}")

set(PROTO_DIR ${CMAKE_CURRENT_LIST_DIR}/schemas)
set(PROTO_SCHEMA_SOURCES
    ${PROTO_DIR}/kpex.capnp
    ${PROTO_DIR}/tech.capnp
    ${PROTO_DIR}/process_stack.capnp
    ${PROTO_DIR}/process_parasitics.capnp
)

set(GENERATED_CAPNP_SOURCES
  "${CPNPROTO_OUT_DIR}/kpex.capnp.c++"
  "${CPNPROTO_OUT_DIR}/tech.capnp.c++"
  "${CPNPROTO_OUT_DIR}/process_stack.capnp.c++"
  "${CPNPROTO_OUT_DIR}/process_parasitics.capnp.c++"
)

add_custom_target(generate_capnproto_cpp_files
    COMMAND $<TARGET_FILE:capnp_tool> compile
             -o$<TARGET_FILE:capnpc_cpp>:"${CPNPROTO_OUT_DIR}"
             --src-prefix="${PROTO_DIR}"
             --import-path="${capnproto_SOURCE_DIR}/c++/src"
             ${PROTO_SCHEMA_SOURCES}
    DEPENDS ${PROTO_SCHEMA_SOURCES}
    COMMENT "Generating Cap'n Proto C++ bindings"
)

add_library(kpex-protos ${GENERATED_CAPNP_SOURCES})
target_link_libraries(kpex-protos PRIVATE CapnProto::capnp CapnProto::capnp-json  ${capnproto_BINARY_DIR}/c++/src/capnp/libcapnpc.a)
add_dependencies(kpex-protos generate_capnproto_cpp_files)

#_____________________________________________________________________________________________

# NOTE: Python bindings are not compiled via C++ / CMake,
#       instead install using: pip install pycapnp

#_____________________________________________________________________________________________

include_directories(${PROJECT_SOURCE_DIR}/cxx/gen_tech_pb)
set(GEN_TECH_PB_SOURCES
    ${CMAKE_CURRENT_LIST_DIR}/cxx/gen_tech_pb/pdk/sky130A.cpp
    ${CMAKE_CURRENT_LIST_DIR}/cxx/gen_tech_pb/pdk/ihp_sg13g2.cpp
    ${CMAKE_CURRENT_LIST_DIR}/cxx/gen_tech_pb/proto.cpp
    ${CMAKE_CURRENT_LIST_DIR}/cxx/gen_tech_pb/main.cpp
)
add_executable(gen_tech_pb ${GEN_TECH_PB_SOURCES})
target_include_directories(gen_tech_pb PUBLIC ${CPNPROTO_OUT_DIR})

get_target_property(CAPNP_INCLUDE_DIR capnp INTERFACE_INCLUDE_DIRECTORIES)
message(STATUS "Cap’n Proto include dir: ${CAPNP_INCLUDE_DIR}")

target_include_directories(gen_tech_pb PRIVATE ${CAPNP_INCLUDE_DIR})
target_link_libraries(gen_tech_pb kpex-protos)

#_____________________________________________________________________________________________
