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
A small but complete PEX25D file, and the helpers the tests read it with.

The fixture is deliberately hand-written rather than generated from a PDK: it
has to stay readable, and a test that fails should point at a record somebody
can see, not at the output of the builder it is meant to be independent of.
"""

from __future__ import annotations

from typing import *

from klayout_pex.pex25d.diagnostics import DiagnosticsReport
from klayout_pex.pex25d.reader import ReadError, read_pex25d_text

HEADER = """\
PEX25D 1.0-rc1
UNITS LENGTH um GRID 0.0001
META technology testpdk
META source_cell tiny
"""

STACK = """\
GROUND_PLANE subs Z_OFFSETS -0.4 -0.1

METAL met1 Z_OFFSETS 1.0 1.4
METAL met2 Z_OFFSETS 2.0 2.4
VIA via1 CONNECTS met1 met2

DIELECTRIC_BACKGROUND air PERMITTIVITY 1.0
DIELECTRIC_SIMPLE fox WRAPS subs PERMITTIVITY 3.9 BETWEEN subs met1
DIELECTRIC_CONFORMAL lint WRAPS met1 PERMITTIVITY 7.3 THICKNESS_OVER_WRAPPED 0.1 \\
    THICKNESS_BESIDE_WRAPPED 0.08 THICKNESS_ON_FIELD 0.0
DIELECTRIC_SIMPLE ild WRAPS lint PERMITTIVITY 4.1 BETWEEN met1 met2
"""

RESISTANCE = """\
RESISTANCE TEMPERATURE 25.0
RESISTANCE METAL met1 SHEET 0.125
RESISTANCE METAL met2 SHEET 0.125
RESISTANCE VIA via1 PER_CUT 4.5
"""

SHAPES = """\
CONDUCTOR A neta
CONDUCTOR B netb
BOX CONDUCTOR A LAYER met1 LL 0.0 0.0 UR 1.0 0.5
BOX CONDUCTOR A LAYER via1 LL 0.2 0.1 UR 0.4 0.3
BOX CONDUCTOR A LAYER met2 LL 0.0 0.0 UR 1.0 0.5
POLYGON CONDUCTOR B LAYER met1 OUTER 2.0 0.0 3.0 0.0 3.0 1.0 2.0 1.0
TERMINAL t1 CONDUCTOR A LAYER met1 KIND PIN LL 0.0 0.0 UR 0.2 0.5
DOMAIN_MARGIN X 4.0 Y 4.0 Z 2.0
"""

MINIMAL = f"{HEADER}\n{STACK}\n{RESISTANCE}\n{SHAPES}"

# Everything except the conductors, for tests that supply their own geometry.
STACK_ONLY = f"{HEADER}\n{STACK}\n"


def read(text: str,
         report: Optional[DiagnosticsReport] = None,
         **kwargs: Any) -> Any:
    """Read PEX25D text, raising ``ReadError`` on a syntax error as usual."""
    return read_pex25d_text(text.encode(), '<fixture>', report=report, **kwargs)


def read_codes(text: str) -> List[str]:
    """The diagnostic codes reading ``text`` produces, error or not."""
    report = DiagnosticsReport()
    try:
        read(text, report=report)
    except ReadError:
        pass
    return codes(report)


def codes(report: DiagnosticsReport) -> List[str]:
    return [d.code for d in report.diagnostics]


def replacing(old: str, new: str, text: str = MINIMAL) -> str:
    """The fixture with one line or clause substituted. Fails loudly on a typo."""
    assert text.count(old) == 1, f"{old!r} appears {text.count(old)} times"
    return text.replace(old, new)


def without(line: str, text: str = MINIMAL) -> str:
    return replacing(f"{line}\n", '', text)
