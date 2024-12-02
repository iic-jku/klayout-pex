## KPEX Extractor

### Prerequisites

- cmake
- protobuf
- python3 with pip packages:
   - protobuf
   - mypy-protobuf
   - rich

#### Ubuntu / Debian installation

Install Python3.12 + VENV
```bash
sudo apt install python3.12-venv
python3 -m venv ~/myvenv
# also add to .bashrc / .zprofile:
source ~/myvenv/bin/activate
```

```bash
sudo apt install cmake libprotobuf-dev protobuf-compiler 
sudo apt install libcurl4-openssl-dev   # required for klayout pip module
pip3 install protobuf mypy-protobuf rich klayout
```

### Building

Calling `./build.sh release` will: 
- create Python and C++ Protobuffer APIs for the given schema (present in `protos`)
- compile `tech_tool.cpp` C++ example showing how to read/write/convert different representations

### Generating KPEX Tech Info JSON files

Calling `./gen_tech_pb` will create the JSON tech info files: 
   - `build/sky130A_tech.pb.json`
   - `build/ihp_sg13g2_tech.pb.json`

### Running KPEX

To quickly run a PEX example with KPEX/2.5D and KPEX/FasterCap engines:
```bash
./kpex.sh --tech build/sky130A_tech.pb.json \
  --out_dir output_sky130A \
  --2.5D yes \
  --fastercap yes \
  --gds ../designs/sky130A/test_patterns/sideoverlap_complex_li1_m1.gds.gz
```

## Debugging Hints for PyCharm

### Enable `rich` logging

In your debugging configuration, set:
- `Modify Options` > `Emulate terminal in output console`
- Add environmental variable `COLUMNS=120`

