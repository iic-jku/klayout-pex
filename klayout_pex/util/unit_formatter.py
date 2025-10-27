#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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

from typing import Optional


# NGSPICE manual, Table 2.1 "Ngspice scale factors"
prefix_scales = [
    ('T', 1e12),
    ('G', 1e9),
    ('Meg', 1e6),
    ('K', 1e3),
    ('', 1.0),
    ('mil', 25.4e-6),
    ('m', 1e-3),
    ('u', 1e-6),
    ('n', 1e-9),
    ('p', 1e-12),
    ('f', 1e-15),
    ('a', 1e-18),
]


valid_prefixes = {p for p, _ in prefix_scales}


def format_spice_number(value: float, force_prefix: Optional[str] = None) -> str:
    """
    Format a spice number into NGSPICE-compatible string.

    Args:
        value: capacitance in farads (can be negative or zero).
        force_prefix: optional forced prefix (must match NGSPICE case, e.g., 'a','f','p','n','u','m','K','Meg','G','T').

    Returns:
        NGSPICE-compatible string like '4.7n', '1p', '2.2u', '-33f', or '0'.
    """
    if value == 0:
        return "0"

    if force_prefix is not None:
        if force_prefix not in valid_prefixes:
            raise ValueError(f"Invalid prefix '{force_prefix}'. Must be one of {sorted(valid_prefixes)}")
        scale = dict(prefix_scales)[force_prefix]
        scaled = value / scale
        # Force decimal notation for NGSPICE (no scientific notation)
        if scaled.is_integer():
            return f"{int(scaled)}{force_prefix}"
        else:
            return f"{scaled:.6g}{force_prefix}"

    chosen_prefix = ''
    chosen_scaled = value

    for i, (prefix, scale) in enumerate(prefix_scales):
        scaled = value / scale
        if 1 <= abs(scaled) < 1000:
            chosen_prefix = prefix
            chosen_scaled = scaled
            break
        elif abs(scaled) >= 1000:
            # bump up to next larger prefix if possible
            if i == 0:
                chosen_prefix = prefix
                chosen_scaled = scaled
            else:
                next_prefix, next_scale = prefix_scales[i - 1]
                chosen_prefix = next_prefix
                chosen_scaled = value / next_scale
            break
    else:
        # too small, pick smallest prefix
        chosen_prefix, chosen_scaled = prefix_scales[-1][0], value / prefix_scales[-1][1]

    # Avoid scientific notation for NGSPICE
    if chosen_scaled.is_integer():
        return f"{int(chosen_scaled)}{chosen_prefix}"
    else:
        return f"{chosen_scaled:.6g}{chosen_prefix}"
