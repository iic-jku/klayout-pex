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
This sample contains:

* `gcd.gds.gz` - a sample layout
* `gcd.lvsdb.gz` - a sample LVSDB database (derived using LVS from `Sky130A_el`, version 0.5)
  (NOTE: this LVS does not match, but this does not matter here)
* `gcd.spice` - the reference netlist

The LVSDB uses a layer-name enabled LVS version. The important 
layer names are: `poly_con`, `li_con`, `met1_con`, `met2_con`, `met3_ncap`, `met4_ncap`, `met5_con`.

