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

- python3 with pip packages:
   - poetry (will manage additional dependencies,
     including `grpcio-tools`, which bundles the protobuf compiler `protoc`)

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
sudo apt install libcurl4-openssl-dev   # required for klayout pip module
pip3 install poetry
poetry update
```

#### Windows: symlinks in the checkout

Some PDK files are symlinks, e.g. most rule decks of `pdk/ihp-sg13cmos5l` link to `pdk/ihp-sg13g2`.
By default, git on Windows checks out a symlink as a plain text file, containing only the link target path.
As `poetry install` runs KPEX directly from your checkout (editable install),
KLayout would then fail to include those rule decks.

NOTE: Released wheels are not affected, the build backend `scripts/build/kpex_build_backend.py`
packages symlinks as regular files.

**Recommended:** use real symlinks, this requires Windows *Developer Mode* (or an administrator shell).

For a new clone:
```bash
git clone -c core.symlinks=true https://github.com/iic-jku/klayout-pex.git
```

For an existing clone (NOTE: discards uncommitted changes in `pdk/`):
```bash
git config core.symlinks true
git checkout -- pdk
```

**Fallback** (no symlinks possible): install a non-editable copy of KPEX into the poetry venv,
built by the build backend (which resolves the symlinks):
```bash
poetry install --no-root
poetry run pip install --no-deps .
```
- run KPEX with `poetry run kpex …` (`kpex.sh` would use the checkout)
- after code changes, reinstall with `poetry run pip install --no-deps --force-reinstall .`

### Building

Calling `./gen_tech_pb.sh` will:
- create the Python Protobuffer APIs for the given schema (present in `protos`),
  i.e. `klayout_pex_protobuf/**/*_pb2.py`, using the `protoc` bundled with `grpcio-tools`
- generate the KPEX tech info JSON files (see below)

### Generating KPEX Tech Info JSON files

The tech info of each bundled PDK (layers, process stack, parasitics) is defined in `scripts/gen_tech_pb`.
Calling `poetry run python scripts/gen_tech_pb klayout_pex_protobuf` (the last step of `./gen_tech_pb.sh`)
will create the JSON tech info files:
   - `klayout_pex_protobuf/gf180mcuD_tech.pb.json`
   - `klayout_pex_protobuf/ihp-sg13cmos5l_tech.pb.json`
   - `klayout_pex_protobuf/ihp-sg13g2_tech.pb.json`
   - `klayout_pex_protobuf/sky130A_tech.pb.json`

### Running KPEX

`kpex` is organized into subcommands. `kpex extract` runs the extraction engines;
`kpex pex25d` stops before them and writes the scene out as PEX25D.

To quickly run a PEX example with the KPEX/2.5D and KPEX/FasterCap engines:
```bash
./kpex.sh extract \
  --pdk sky130A \
  --out_dir output_sky130A \
  --2.5D \
  --fastercap \
  --gds testdata/sky130A/test_patterns/sideoverlap_complex_li1_m1.gds.gz
```

> The older flat form without a subcommand (`./kpex.sh --pdk sky130A --gds …`) still
> works and is treated as `kpex extract …`, but it warns and will be removed.

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
