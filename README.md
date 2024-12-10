<!--
--------------------------------------------------------------------------------
SPDX-FileCopyrightText: 2024 Martin Jan Köhler and Harald Pretl
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
-->
[![PyPi](https://img.shields.io/pypi/v/klayout-pex)](https://pypi.org/project/klayout-pex/)
[![GitHub issues](https://img.shields.io/badge/issue_tracking-github-blue.svg)](https://github.com/martinjankoehler/klayout-pex/issues)

# KLayout-PEX

KLayout-PEX is a parasitic extraction tool for [KLayout](https://klayout.org).
There a multiple engines supported:
  - FasterCap (requires [FasterCap](https://github.com/martinjankoehler/FasterCap) installation)
  - MAGIC wrapper (requires [MAGIC](https://github.com/RTimothyEdwards/magic) installation)
  - 2.5D engine (**under development**)

Check out the [documentation website](https://martinjankoehler.github.io/klayout-pex-website) for more information.

## Install

`pip install klayout-pex`

After that, you should be able to run `kpex --help`.
