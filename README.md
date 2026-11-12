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
[![PyPi](https://img.shields.io/pypi/v/klayout-pex)](https://pypi.org/project/klayout-pex/)
[![CI](https://github.com/iic-jku/klayout-pex/actions/workflows/ci-cd.yml/badge.svg?branch=main&event=push)](https://github.com/iic-jku/klayout-pex/actions/workflows/ci-cd.yml?query=branch%3Amain)
[![Coverage](https://img.shields.io/badge/coverage-report-blue.svg)](https://iic-jku.github.io/klayout-pex/pycov/)
[![GitHub issues](https://img.shields.io/badge/issue_tracking-github-blue.svg)](https://github.com/iic-jku/klayout-pex/issues)
[![DOI](https://zenodo.org/badge/897408519.svg)](https://doi.org/10.5281/zenodo.17822625)

# KLayout-PEX

KLayout-PEX is a parasitic extraction tool for [KLayout](https://klayout.org).
There a multiple engines supported:
  - FasterCap (requires [FasterCap](https://github.com/iic-jku/FasterCap) installation)
  - MAGIC wrapper (requires [MAGIC](https://github.com/RTimothyEdwards/magic) installation)
  - 2.5D engine (**under development**)

Check out the [documentation website](https://iic-jku.github.io/klayout-pex-website) for more information.

## Install

`pip install klayout-pex`

After that, you should be able to run `kpex --help`.

## Port labels

`kpex extract --port-labels auto` uses top-level labels for ports when the top cell has a label on a pin shape.
Otherwise, it retains ports from labels in child cells. `--port-labels top` always uses top-level labels.
Both preserve existing ports named by top-level text labels without pin shapes, and the substrate port.
Labels in child cells still name internal nets and ports of excluded device models.

The default is `auto`. Supply `--gds` alongside `--lvsdb` to identify top-level labels: the LVS database has
flattened them. With `--lvsdb` alone, `auto` retains hierarchical labels, and `top` reports an error.

## Capacitance output modes

The analytical engine keeps coupled capacitance by default. Select the approximation explicitly:

| Command options | Capacitance written to the netlist |
| :--- | :--- |
| `--2.5D --mode CC` | Coupled capacitance, one node per net |
| `--2.5D --mode C` | Floating capacitance eliminated exactly, then inter-net coupling grounded |
| `--2.5D --mode CC --coupling grounded` | Same capacitance policy as `C` |
| `--2.5D --mode RC` | Coupled capacitance distributed onto the resistance networks |
| `--2.5D --mode RC --coupling grounded` | Floating capacitance eliminated exactly, then inter-net coupling grounded at distributed nodes |
| `--2.5D --mode R` | Resistance without extracted capacitance |

`--coupling coupled` explicitly selects the existing `CC` or `RC` behavior. `--mode C` requires
`grounded` if `--coupling` is also specified. No coupling threshold or switching multiplier is applied.

### Floating conductors

Conductors without a port or retained device terminal are electrically floating. For `C`, their
capacitance is eliminated by an exact capacitive star-mesh reduction before any coupling is grounded.
For example, `A` ↔ `F` = `2 fF` and `F` ↔ reference = `2 fF`, with floating `F`, produce a `1 fF`
load from `A` to reference. `F` is removed, rather than held at reference. A floating component
connected to only one retained node contributes no load there.

The log lists eliminated floating nets so an unintended disconnected rail remains visible. Ports
created by labels and exclusion blocks remain observable. Explicit exclusion-marker settings retain
their existing contract, including the treatment of floating metal inside a marker.

For `RC`, capacitor-only floating conductors are also eliminated exactly. A floating island with
extracted resistance is rejected: its frequency-dependent behavior cannot generally be represented
by a single capacitance. Use `--coupling coupled` to retain its dynamics, or `--mode C` to use the
ideal-conductor capacitance model. All retained resistors keep their values and node connections.

Exact elimination uses the shared reduction limit of 64 neighbors per eliminated node to bound
fill-in. A node still above that limit after other floating nodes are removed produces a diagnostic
that recommends coupled output. The grounded modes never replace a remaining floating conductor
with a ground tie.

### Grounded inter-net coupling

After floating-node elimination, each inter-net pair is replaced by its full capacitance to the
reference at each endpoint. For example, `A` ↔ `B` = `2 fF`, `A` ↔ reference = `1 fF` and
`B` ↔ reference = `3 fF` become `3 fF` from `A` to reference and `5 fF` from `B` to reference.

This preserves the reduced capacitance matrix's diagonal at each retained node with the other
nodes clamped to reference. It removes inter-net transfer admittance and does not represent
switching-dependent Miller effects or preserve arbitrary distributed-RC terminal impedance.
Capacitance between distributed nodes of the same net stays between those nodes, including
capacitance created by eliminating a floating conductor, so the internal RC dynamics are retained.

The reference is the layout's substrate net, including its distributed nodes, or `VSUBS` when no
substrate net is available. It is not implicitly SPICE node `0`. Existing capacitance to reference
nodes stays on those nodes. New grounded loads use the substrate's ideal net.

The policy changes CSV, SPICE and VACASK netlists after spatial distribution and before reduction.
Reduction checks compare the approximated network with its reduced version. Geometry reports and
`--check-device-caps` continue to describe the coupled extraction.

Intentional capacitor models remain unchanged with `--blackbox y`. The default remains `--blackbox n`:
if the layout contains metal capacitors whose models would be removed, grounded output reports an
error before capacitance extraction and asks for `--blackbox y`. Bare interconnect layouts work with
either setting. This prevents grounding the intended terminal coupling of a white-boxed capacitor.

These policies apply to `--2.5D`. They do not change `MAGIC`, FasterCap or FastCap2 output.
Existing `CC`, `RC` and `R` defaults are unchanged.

### Grounding an existing SPICE netlist

`netlist ground` applies the same floating elimination and grounding policy without a layout or PDK:

```sh
netlist ground coupled.spice --reference sub! --out-netlist grounded.spice
```

The reference is required. It must be a node, port or global in the selected scope, or `0`/`gnd`.
SPICE ground aliases `0` and `gnd` identify the same conductor, including distributed reference nodes.
By default, the command selects `Cext_*` and `Cgrnd_*` capacitors and uses `Rext_*` resistors to
identify distributed conductors. Resistor lines stay unchanged. Intentional devices, unselected
elements, directives and other subcircuits remain in the output.

For another extractor's naming scheme, supply explicit name patterns. Each option may be repeated
and replaces its respective defaults. Quote patterns to prevent shell expansion:

```sh
netlist ground extracted.spice --cell amplifier --reference VSS \
  --capacitor 'Cpar_*' --resistor 'Rwire_*' --keep bias_internal
```

Ports, global nodes, terminals named by retained devices or sources, and `--keep` nodes retain
their entire conductors. Other conductors are floating. Selected resistors define connectivity
within each conductor. If disconnected pieces belong to the same conductor, provide a flat JSON
node map, for example `{"OUT.1": "OUT", "OUT.2": "OUT"}`, using `--net-map nodes.json`.
The map supplies conductor identity without shorting or renaming nodes. It cannot assign different
conductors to nodes connected by selected resistors. SPICE names and patterns are case-insensitive.

Use `--cell NAME` when several subcircuits contain selected capacitors, or `--top-level` to select
elements outside subcircuits. Selected elements must be numeric two-node primitives. Symbolic
values, floating resistor islands and excessive floating elimination fail before writing output.
The default output name is `extracted_grounded.spice`; the input cannot be overwritten.

Use coupled input with intentional capacitance represented by retained devices. After white-box
extraction has mixed device capacitance with parasitics, postprocessing cannot distinguish them.
The transformation intentionally removes inter-net transfer, so an equivalence check against the
coupled input is not expected to pass. A subsequent `netlist reduce` check should use the grounded
netlist as its reference.

## VACASK conversion

`netlist convert --to vacask circuit.spice` writes two files:

- `circuit.inc` contains the circuit, with instance parameters unchanged
- `circuit.options.inc` sets the global geometry scale from `.option` or `.options scale`

Include the circuit at the top level and its options inside the testbench's existing `control` block:

```text
include "circuit.inc"

control
  include "circuit.options.inc"
  analysis op1 op
endc
```

The scale applies to the entire simulation through compatible models, including those inside external
`X` wrappers. A later `options scale` command overrides it. Do not combine fragments requiring different
scales without first normalizing their model interfaces. The companion is rewritten even at the default
`scale=1`, so reconversion cannot leave an earlier scale active.

`--out-netlist` derives the companion name from the chosen output path. `kpex --netlist-format vacask`
also writes and reports both files. Numeric SPICE suffixes are converted to plain numbers because the
simulators interpret some suffixes differently. Parameter expressions and model libraries remain outside
the converter's supported input.

## Acknowledgements

This project is funded by the JKU/SAL [IWS Lab](https://research.jku.at/de/projects/jku-lit-sal-intelligent-wireless-systems-lab-iws-lab/), a collaboration of [Johannes Kepler University](https://jku.at) and [Silicon Austria Labs](https://silicon-austria-labs.com).

This project had been further funded by the German project [FMD-QNC (16ME0831)](https://www.elektronikforschung.de/projekte/fmd-qnc).

This project is further funded by the European project [ODE4EC-AMS](https://ode4ec.eu/projects/ams/), which has received funding from the Chips Joint Undertaking (Chips JU) under Grant Agreement No 101252962.
Funded by the European Union. Views and opinions expressed are however those of the author(s) only and do not necessarily reflect those of the European Union or the Chips Joint Undertaking. Neither the European Union nor the granting authority can be held responsible for them.

<p align="center">
  <a href="https://iic.jku.at" target="_blank">
    <img src="https://github.com/iic-jku/klayout-pex-website/raw/main/figures/funding/iic-jku.svg" alt="Johannes Kepler University: Institute for Integrated Circuits and Quantum Computing" width="300"/>
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://silicon-austria-labs.com" target="_blank">
    <img src="https://github.com/iic-jku/klayout-pex-website/raw/main/figures/funding/silicon-austria-labs-logo.svg" alt="Silicon Austria Labs" width="300"/>
  </a>
</p>

<p align="center">
  <a href="https://www.elektronikforschung.de/projekte/fmd-qnc" target="_blank">
    <img src="https://github.com/iic-jku/klayout-pex-website/raw/main/figures/funding/bfmtr-bund-de-logo.svg" alt="Bundesministerium für Forschung, Technologie und Raumfahrt" width="300">
  </a>
</p>

<p align="center">
  <a href="https://ode4ec.eu/projects/ams/" target="_blank">
    <img src="https://github.com/iic-jku/klayout-pex-website/raw/main/figures/funding/eu-cofunded.svg" alt="Co-funded by the European Union" width="300"/>
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://www.chips-ju.europa.eu" target="_blank">
    <img src="https://github.com/iic-jku/klayout-pex-website/raw/main/figures/funding/chips-ju.png" alt="Chips Joint Undertaking" width="300"/>
  </a>
</p>
