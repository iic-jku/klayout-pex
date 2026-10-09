#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/klayout-pex).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
# --------------------------------------------------------------------------------
#

"""
The names KPEX works with, as type aliases, so that signatures say which name is meant

NOTE: imports neither KLayout nor generated protobuf code, so that format-only paths can use them
"""

from typing import Tuple


# ------------------------------- Layers and GDS -------------------------------

LayerName = str              # a layer of the process stack, as the extraction engines name it (e.g. met1, met3_cap)
CanonicalLayerName = str     # a drawn layer of the tech info (e.g. met1, on GDS 68/20)
LVSLayerName = str           # a layer of the LVS deck (e.g. met1_con, met3_ncap)
GDSPair = Tuple[int, int]    # a GDS layer and datatype (e.g. (68, 20))


# -------------------------- Connectivity and Netlist --------------------------

CellName = str
NetName = str                # a net of the LVS netlist (e.g. VDD, or $3 without a label)
