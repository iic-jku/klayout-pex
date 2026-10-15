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

import math
import re
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

# NOTE: the prefixes format_spice_number chooses: not mil (no SI prefix, 3e-3 would be 118.11mil),
#       and not a, which Xyce reads as a unit (Xyce 7.10 reads 2a as 2, but 0.002f as 2e-18)
_CHOSEN_PREFIX_SCALES = [(p, s) for p, s in prefix_scales if p not in ('mil', 'a')]


def format_spice_number(value: float, force_prefix: Optional[str] = None) -> str:
    """
    Format a spice number into NGSPICE-compatible string (and Xyce-compatible, unless forced to 'a'):
    with the largest SI prefix that gives a value ≥ 1, but no smaller one than 'f' (e.g. '0.223458f').

    Args:
        value: capacitance in farads (can be negative or zero).
        force_prefix: optional forced prefix (must match NGSPICE case, e.g., 'a','f','p','n','u','m','K','Meg','G','T').

    Returns:
        NGSPICE-compatible string like '4.7n', '1p', '2.2u', '-33f', '0.5f', or '0'.
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

    for i, (prefix, scale) in enumerate(_CHOSEN_PREFIX_SCALES):
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
                next_prefix, next_scale = _CHOSEN_PREFIX_SCALES[i - 1]
                chosen_prefix = next_prefix
                chosen_scaled = value / next_scale
            break
    else:
        # too small, pick smallest prefix
        chosen_prefix, chosen_scaled = _CHOSEN_PREFIX_SCALES[-1][0], value / _CHOSEN_PREFIX_SCALES[-1][1]

    # Avoid scientific notation for NGSPICE
    if chosen_scaled.is_integer():
        return f"{int(chosen_scaled)}{chosen_prefix}"
    else:
        return f"{chosen_scaled:.6g}{chosen_prefix}"


def format_spice_resistance(value: float) -> str:
    """
    Format a resistance in Ω the way KPEX writes it into SPICE netlists:
    12 significant digits, without scale factor (e.g. '426.666666667', '0.001')
    """
    return f"{value:.12g}"


_SPICE_NUMBER = re.compile(r'([+-]?(?:\d+\.?\d*|\.\d+))(?:[eE]([+-]?\d+))?([a-zA-Z]*)')

# scale factor (lower case) → power of ten
_SCALE_EXPONENTS = {prefix.lower(): round(math.log10(scale))
                    for prefix, scale in prefix_scales
                    if prefix not in ('', 'mil')}


def parse_spice_number(text: str) -> float:
    """
    Parse a SPICE number, e.g. '1.5', '2e-15', '223.458a', '0.1p', '10k', '1Meg', '1pF'.

    The scale factor is case-insensitive (NGSPICE manual, Table 2.1 "Ngspice scale factors"),
    'meg' and 'mil' are matched before 'm'. As in NGSPICE, letters after the scale factor are ignored,
    so are letters that are no scale factor (e.g. the unit in '10V').
    The result is the double nearest to the decimal value ('0.1p' is the same as 1e-13).

    :raises ValueError: if the text is no SPICE number (e.g. an expression like '{2*c0}')
    """
    match = _SPICE_NUMBER.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"Not a SPICE number: '{text}' (examples of valid numbers: "
                         f"'1.5', '2e-15', '0.1p', '10k', '1Meg')")
    significand, exponent, letters = match.groups()
    exponent = int(exponent or 0)
    letters = letters.lower()
    if letters.startswith('mil'):
        return float(f"{significand}e{exponent}") * 25.4e-6
    if letters.startswith('meg'):
        exponent += 6
    elif letters[:1] in _SCALE_EXPONENTS:
        exponent += _SCALE_EXPONENTS[letters[:1]]
    return float(f"{significand}e{exponent}")
