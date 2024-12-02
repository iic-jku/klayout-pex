all: python_api cxx_api tech_tool dump_example

UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
	PB_PREFIX = /opt/homebrew
else
	PB_PREFIX = /usr
endif

PROTOBUF_SOURCES = \
	protos/tech.proto \
	protos/extract.proto \
	protos/units.proto \
	protos/process_stack.proto \
        protos/fastercap_file_format.proto

python_api: $(PROTOBUF_SOURCES)
	@echo "---------------------------------------------------------"
	@echo "Creating Python Protobuf API"
	protoc -I=protos --python_out=build/python --mypy_out=build/python $(PROTOBUF_SOURCES)

cxx_api: $(PROTOBUF_SOURCES)
	@echo "---------------------------------------------------------"
	@echo "Creating C++ Protobuf API"
	protoc -I=protos --cpp_out=build/cxx $(PROTOBUF_SOURCES)

tech_tool: tech_tool.cpp build/cxx/*.cc
	@echo "---------------------------------------------------------"
	$(CXX) \
		-std=c++17 \
		-I$(PB_PREFIX)/include \
		-L$(PB_PREFIX)/lib \
		-lprotobuf \
		-labsl_cord -labsl_log_internal_proto -labsl_log_internal_check_op -labsl_log_internal_message -labsl_status \
		build/cxx/*.cc \
		tech_tool.cpp \
		-o build/tech_tool

dump_example: build/tech_tool
	@echo "---------------------------------------------------------"
	build/tech_tool
