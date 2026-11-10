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
  - the workers write their extraction outputs to `output_<pdk>_worker<N>`
  - more workers gain little: the longest test takes 20 s, and a gf180mcuD LVS needs up to 1.7 GB
  - coverage needs pytest-cov's `--cov` with workers, `coverage run` only sees the main process

### Running KPEX

`kpex` is organized into subcommands. `kpex extract` runs the extraction engines;
`kpex pex25d` stops before them and writes the scene out as PEX25D.

To quickly run a PEX example with the KPEX/2.5D and KPEX/FasterCap engines:
```bash
./kpex.sh extract \
  --pdk sky130A \
  --out-dir output_sky130A \
  --2.5D \
  --fastercap \
  --gds testdata/sky130A/test_patterns/sideoverlap_complex_li1_m1.gds.gz
```

> The older flat form without a subcommand (`./kpex.sh --pdk sky130A --gds …`) still
> works and is treated as `kpex extract …`, but it warns and will be removed.

### Result file

Each run of `kpex extract` and `kpex pex25d` writes `kpex_result.json` into its run directory,
and with `--out-result PATH` also to that path, so that scripts need neither the naming of the
run directory nor the log. JSON in UTF-8, with absolute paths.

It is written:
- to `--out-result` once the command line is parsed (a path that can't be written fails the run
  with exit code 2), into the run directory once the arguments are checked
- at the start of each stage, so that a run killed by the OS (e.g. for its memory) leaves the
  stage it was in, with `exit_code` `null`
- when the run ends, also if it fails
- not for `--help`, nor for a command line with an unknown option or an invalid value (exit code 2)

Keys (`format_version` 1, which goes up when a key is removed or changes its meaning, not for new keys):
- `format_version`, `kpex_version`
- `command`: `extract` or `pex25d`, `arguments`: the command line after `kpex`
- `pdk`, `cell`, `run_dir`: `null` until known
- `engines`: e.g. `["KPEX/2.5D"]`, as the netlists name them, `mode`: the `--mode` of the 2.5D engine
- `inputs`: `gds`, `lvsdb` and `schematic`, each a path or `null`, and
  `device_capacitance_references` when `--check-device-caps` is requested
- `stage`: the stage the run was in when it ended or was killed: `arguments`, `magic`, `lvs`,
  `fastercap`, `fastcap2`, `2.5d` or `pex25d`, and `done` after exit code 0
- `exit_code`: `null` until the run ends, so also of a run that is killed or interrupted
- `halo_um`: the sidewall halo of the 2.5D engine (`--halo` or the tech info), `null` without capacitances
- `devices`: the numbers of the devices of the cell that the netlists leave to their models,
  `black_boxed` (with `--blackbox y`, e.g. MIM and MOM caps) and `excluded` (of `--cut`),
  or remove, `white_boxed` (with `--blackbox n`, their capacitances extracted)
- `check_problems`: what `--check` finds in the netlist of the 2.5D engine, also where it only warns,
  plus failed or unevaluable comparisons requested with `--check-device-caps`
- `device_capacitance_checks`: the requested device/terminal-pair comparisons, or `null` without
  `--check-device-caps`, as described below
- `peak_memory`: `process_bytes` and `largest_subprocess_bytes` (`null` on Windows), as logged
- `files`: the outputs, in the order written, each with `kind`, `path` and `engine` (`null` for those
  of the run, e.g. its log), the netlists also with `format` (`spice` or `vacask`), `reduced` and
  `ports`, as the `.SUBCKT` line of the cell has them (`null` for VACASK, which names them differently)
  - kinds: `netlist`, `out_netlist` (`--out-netlist`), `netlist_csv`, `capacitance_matrix`, `report`,
    `lvsdb`, `log`, `pex25d_file` and `pex25d_scene`
  - not the intermediate files, e.g. the layout dumps and the solver input
- `warnings`, `errors`: as logged (`--log-level error` leaves out the warnings)
- the keys of what a run didn't get to, e.g. `devices` before LVS, or `halo_um` of MAGIC, are `null`

### Device capacitance comparisons

`kpex extract --check-device-caps` compares the coupling within metal capacitor recognition
markers against nominal model values from the tech info's device mappings. Devices without a
reference are named in warnings. A layout without any supported device is an error.
`--check-device-caps references.json` instead selects only the file's device/terminal pairs,
overriding the automatic selection with explicit references and optional ratio bounds. It needs `--2.5D`, `--blackbox y`,
`--mode CC` or `--mode RC`, and the original `--gds`. Adding `--gds` to `--lvsdb` supplies the
recognition markers without rerunning LVS. Device abstracts in an LVS database can contain only
terminal pins, so their bounding boxes do not define the recognition markers.

A tech-info `DeviceCapacitanceModel` names two LVS terminals and evaluates a capacitance in
farads using the existing mapping's exported model parameters. Its `capacitance`, local
`parameters` and optional `valid_when` predicate use ngspice expression syntax, including
SPICE suffixes. Local names cannot shadow model parameters. The formula must include the
instance multiplier exactly once. `source` and `description` record the model provenance
and nominal assumptions. Invalid expressions, unsupported parameter values and nonpositive
or nonfinite results fail before extraction. This needs no installed simulator or model library.

Bundled references cover `cap_cmomf` and `cap_cmomi` in `ihp-sg13g2` and `ihp-sg13cmos5l`.
They reproduce the nominal low-frequency mutual model capacitance, including finger-grid
rounding, feed style and instance multiplier. Substrate shunts and series resistance/inductance
are excluded. These engineering models do not characterize corner or mismatch variation.

Tech references have no default acceptance bounds: the comparison is informational.
They must come from the device model, independently of the extraction coefficients.
Add a model-admittance regression test when adding a formula or changing its source model.

The optional reference file is UTF-8 JSON:

```json
{
  "format_version": 1,
  "references": [
    {
      "device": "$1",
      "device_class": "cap_cmomf",
      "terminals": ["mim_top", "mim_btm"],
      "capacitance": "228.75f",
      "min_ratio": 0.7,
      "max_ratio": 1.0
    }
  ]
}
```

Reference semantics:

- `device` is the exact expanded LVS device name, before any output renaming
- `device_class` guards against selecting a device of another class
- `terminals` names an unordered pair of distinct, connected terminals on different nets
- `capacitance` is the positive nominal low-frequency mutual model capacitance for that instance,
  including its multiplier, in farads as a number or with SPICE suffixes as a string
- The reference must use the intended model corner, temperature and bias, with other terminals
  held at their reference potentials when obtaining mutual capacitance from an admittance matrix
- `min_ratio` and `max_ratio` are optional inclusive bounds on extracted/reference capacitance
- Without either bound, the comparison is informational, not a passed check
- The example bounds are chosen for this example, not a universal acceptance range
- Unlisted devices and terminal pairs are unchecked

The measurement observes overlap, sidewall and fringe contributions suppressed by blackboxing
between the selected terminal nets' capacitor plates inside one recognition marker. Surrounding
conductors still shield them. Coupling to routing outside that marker, unrelated nets and other
devices is not included. The extraction's coefficients, halo, normalization and fringe cutoff
remain in effect. Enabling the comparison does not add the measured coupling to the netlist.
The measurement precedes exclusion filtering: `--exclude-net`, `--cut` and exclusion markers
affect the exported netlist, not the selected device's full marker-internal comparison.

Both terminals need capacitor-plate geometry wholly within a unique marker. Missing markers,
markers shared by devices, combined devices spanning markers, partial plate geometry and missing
plate geometry for either terminal cannot be evaluated. In particular, a substrate terminal whose geometry
extends beyond the marker is not silently treated as a local plate. LVS parameters named `C`
are not used as model references, because some decks store placeholders there.

Each `device_capacitance_checks` entry contains the device, class, terminals, nets, reference and
extracted capacitance in farads, their ratio, optional bounds, and `status`. Status is
`informational`, `passed`, `failed` or `unevaluable`. The `contributions` object separates
`overlap_f`, `sidewall_f` and `fringe_f`. Unevaluable measurements have an `error` and `null`
measurement values.

Automatic comparison records also include `reference_source` and `reference_description`.
These fields are null for an explicit reference file, whose path is in `inputs`.

Failure behavior:

- Invalid reference files or incompatible options return exit code `2` before loading the layout
- Invalid device or marker selections return exit code `1` before extraction
- Failed bounds or unevaluable measurements return exit code `1` after writing the netlist,
  including with `--check n`

### Tool version checks

The Python package dependency remains `klayout>=0.30.12`. KLayout `0.30.13` or later
is recommended for terminal-lookup performance, neighborhood-visitor memory leaks
and resistance-extraction crash fixes. Older supported versions emit a warning
and extraction continues.

Extraction commands check the loaded `klayout` Python module separately from the
KLayout executable used for LVS. With `--lvsdb`, the executable is not needed or
checked. The report distinguishes required versions from recommendations.
Format-only netlist commands do not load KLayout for these checks.

`--tool-version-checks on` retains each constraint's severity, `warn` downgrades
errors to warnings, and `off` disables detection and reporting. An unknown version
is reported as unchecked and does not block the run.

The `0.30.13` recommendation does not resolve #364: retaining all polygons of a
device terminal is still tracked in [KLayout #2541](https://github.com/KLayout/klayout/issues/2541).

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
pex25d export cell.pex25d --to example --out-dir solver-input
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
- The export flags `--field-margin`, `--delaunay-amax`, `--delaunay-b`, `--stl` and
  `--geo-check` are shorthands for their options; each option may be given only once.

For batches, reuse `registry = pex25d.exporter_registry()` and pass `registry=registry`
to each call; create another registry to refresh installed metadata.

`pex25d.export_with_backend(exporter, scene, target, …)` runs an already loaded
exporter. Unexpected exceptions raise `ExporterExecutionError` (CLI exit 4,
traceback with `--log-level debug`); `ExportError` and `OSError` exit 2.

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

The built-in `openrcx-uf` imports OpenRCX Universal Pattern Format (UF) 3D patterns:
- rectangular wires with `LENGTH` and exactly one `GROUND_PLANE`
- other input raises `ImporterError`
- one `METAL` per wire-name prefix (`M1_w2` → `M1`), one conductor and box per wire
- the domain is `WINDOW_BBOX` extended by `SIM_WIN_EXT`, starting at the top of the
  ground plane
- dielectrics and the window below the top of the ground plane are cut off there, so
  heights from the substrate (`gen_solver_patterns -version 1`, the default) and heights
  from the top of the plane (`-version 2`) import alike
- each UF dielectric except the topmost becomes a `DIELECTRIC_SIMPLE` between anchor
  profiles at its bottom and top: an existing ground plane or metal bottom face where
  one lies at that height, otherwise a shape-less 1-grid-unit `METAL` `uf_anchor_<i>`,
  listed in `META uf_anchors`
- the topmost UF dielectric becomes the background
- `OpenRCXUFImporter.placeholder_file()` is a template for new importers: it fills
  every part of a `PEX25DFile` with placeholders

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
