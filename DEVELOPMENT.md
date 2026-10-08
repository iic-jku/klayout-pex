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

### Running tests

- `./run_unit_tests.sh`, `./run_integration_tests.sh`: with coverage and an allure report in `build/`
- Quick runs in the poetry venv, e.g. `poetry run pytest tests/rcx25 -n 3` (pytest-xdist):
  - the workers write their extraction outputs to `output_<pdk>_worker<N>` and share the LVS cache
    in `output_<pdk>/.kpex_cache`
  - more workers gain little: the longest test takes 20 s, and a gf180mcuD LVS needs up to 1.7 GB
  - coverage needs pytest-cov's `--cov` with workers, `coverage run` only sees the main process

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

## Exporter plugins

Install plugins into the Python environment running KPEX. Register a zero-argument
factory returning a `PEX25DSceneExporter` from `klayout_pex.plugin_api.v1`:

```toml
[project.entry-points."klayout_pex.exporters.v1"]
example = "my_exporter.plugin:create_exporter"
```

The exporter implements:

```python
from __future__ import annotations
from typing import TYPE_CHECKING, Any, List, Mapping, Optional

if TYPE_CHECKING:
    from klayout_pex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene

def export(self, scene: PEX25DScene, *, output_dir_path: str,
           prefix: str = '', options: Optional[Mapping[str, Any]] = None) -> List[str]:
    ...
```

Write solver inputs from the resolved scene and return only paths written by this
call, primary input first. Do not run the solver or mutate the scene or options.
Validate option names and values; raise `ExportError` for invalid or unsupported
input and `ExporterUnavailable` for missing dependencies. Both errors come from
`klayout_pex.plugin_api.v1`. Import optional dependencies only when needed.
The entry-point group versions the Python contract independently of the PEX25D format.
`v1` is provisional: it may still change until it is declared stable.

Use a bare entry-point name or `distribution:name`. Built-ins (`fastercap`,
`fastcap2`, `stl`) take priority for bare names; colliding plugins remain available by
qualified name. Other collisions require a qualified name. Distribution names
follow Python package normalization; exporter names are case-sensitive.
Discovery reads metadata without importing plugins. Loading creates a fresh
instance; one plugin's load failure does not prevent loading another.

```bash
pex25d plugins
pex25d exporters
pex25d export cell.pex25d --to example --out_dir solver-input
```

`pex25d plugins` shows all importers and exporters, built-ins included, with:
- the selector to pass to `--from` / `--to`
- package and version
- package summary (for a built-in, the first line of its factory's docstring)
- entry point

Plugin-specific options:
- Python: `pex25d.export(..., options={...})`
- CLI: `--option NAME=VALUE`, repeatable, for `pex25d export` and `pex25d import`.
  VALUE is read as JSON where it parses (`10`, `1e-9`, `true`, `"10"`), otherwise as text.
- The export flags `--field_margin`, `--delaunay_amax`, `--delaunay_b`, `--stl` and
  `--geo_check` are shorthands for their options; each option may be given only once.

For batches, reuse `registry = pex25d.exporter_registry()` and pass `registry=registry`
to each call; create another registry to refresh installed metadata.

`pex25d.export_with_backend(exporter, scene, target, …)` runs an already loaded
exporter. Unexpected exceptions raise `ExporterExecutionError` (CLI exit 4,
traceback with `--log_level debug`); `ExportError` and `OSError` exit 2.

## Importer plugins

Importers translate another tool's scene description into one unresolved `PEX25DFile`.
Register a zero-argument factory returning a `PEX25DImporter` from
`klayout_pex.plugin_api.v1` in the `klayout_pex.importers.v1` group.

`import_file(input_file_path, *, supporting_files, options, report)`:
- reads the primary input and the named supporting files the importer defines
  (e.g. `process_stack`)
- appends diagnostics to `report` and returns the file
- leaves resolution and validation to the caller
- raises `ImporterError` for invalid or unsupported input, `ImporterUnavailable` for
  missing dependencies, and `NotImplementedError` for what it does not implement yet

Selectors, collisions and discovery work as for exporters.

The built-in `openrcx-uf` is a stub for OpenRCX Universal Pattern Format (UF) input:
- `pex25d import --from openrcx-uf` exits 3 (not implemented yet)
- `OpenRCXUFImporter.placeholder_file()` in `klayout_pex/openrcx/pex25d_importer.py`
  is the template:
  it fills every part of a `PEX25DFile` with placeholders, each `TODO(UF)` names what
  the Universal Pattern Format input has to provide

```bash
pex25d importers
pex25d import design.xyz --from example --supporting process_stack=stack.xyz -o cell.pex25d
```

`pex25d import` validates the result and writes it even if it is invalid (exit 1).
From Python, call `pex25d.import_file(path, 'example', supporting_files=...)`.
Unexpected importer exceptions, or a result that is not a `PEX25DFile`, raise
`pex25d.ImporterExecutionError`; the CLI exits 4 for them. `NotImplementedError` exits 3.

## Debugging Hints for PyCharm

### Enable `rich` logging

In your debugging configuration, set:
- `Modify Options` > `Emulate terminal in output console`
- Add environmental variable `COLUMNS=120`

## Credits

**Thanks to**

- [Protocol Buffers](https://github.com/protocolbuffers/protobuf) for (de)serialization of data and shared data
  structures
- [grpcio-tools](https://pypi.org/project/grpcio-tools/), for bundling the protobuf compiler `protoc`
