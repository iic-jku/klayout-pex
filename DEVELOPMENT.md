<!--
--------------------------------------------------------------------------------
SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
Johannes Kepler University, Institute for Integrated Circuits.

This file is part of KPEX 
(see https://github.com/iic-jku/klayout-pex).

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
-->
## KPEX Extractor

### Prerequisites

- cmake
   - NOTE: `cmake/CPM.cmake` will handle C++ dependencies
- protobuf
- python3 with pip packages:
   - poetry (will manage additional dependencies)

### Optional prerequisites

- allure (only needed for test reports)

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
pip3 install poetry
poetry update
```

### Building

Calling `./build.sh release` will: 
- create Python and C++ Protobuffer APIs for the given schema (present in `protos`)
- compile the `gen_tech_pb` C++ tool

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
  --gds testdata/sky130A/test_patterns/sideoverlap_complex_li1_m1.gds.gz
```

## Debugging Hints for PyCharm

### Enable `rich` logging

In your debugging configuration, set:
- `Modify Options` > `Emulate terminal in output console`
- Add environmental variable `COLUMNS=120`

## Credits

**Thanks to**

- [Protocol Buffers](https://github.com/protocolbuffers/protobuf) for (de)serialization of data and shared data
  structures
- [CMake](https://cmake.org/), for building on multiple platforms
- [CPM.cmake](https://github.com/cpm-cmake/CPM.cmake) for making CMake dependency management easier
