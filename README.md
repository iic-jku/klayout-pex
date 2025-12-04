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

## Acknowledgements

This project is funded by the JKU/SAL [IWS Lab](https://research.jku.at/de/projects/jku-lit-sal-intelligent-wireless-systems-lab-iws-lab/), a collaboration of [Johannes Kepler University](https://jku.at) and [Silicon Austria Labs](https://silicon-austria-labs.com).

This project is further funded by the German project [FMD-QNC (16ME0831)](https://www.elektronikforschung.de/projekte/fmd-qnc).

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
