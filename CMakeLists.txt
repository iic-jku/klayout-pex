# minimum version is 3.0 to be able to handle Eigen library
cmake_minimum_required (VERSION 3.12)
project (kpex)

#_____________________________________________________________________________________________

# see https://github.com/protocolbuffers/protobuf/blob/main/docs/cmake_protobuf_generate.md

find_package(protobuf CONFIG REQUIRED)

set(PROTOBUF_SOURCES 
	${CMAKE_CURRENT_LIST_DIR}/protos/tech.proto
	${CMAKE_CURRENT_LIST_DIR}/protos/extract.proto
	${CMAKE_CURRENT_LIST_DIR}/protos/process_stack.proto
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

set(PROTOBUF_PYTHON_GENERATED "${CMAKE_CURRENT_LIST_DIR}/build/python")
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
target_link_libraries(gen_tech_pb kpex-protobuf)

#_____________________________________________________________________________________________
