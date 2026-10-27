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
A SPICE netlist as its elements and subcircuits, with the values as numbers or expressions
(of parameters, see spice_hierarchy.py for their values in the subcircuit calls).

It is what the writers of other netlist formats take (e.g. the VACASK writer),
from a SPICE file (the SPICE reader) or from a KLayout netlist (the netlist printers).

NOTE: imports neither KLayout nor generated protobuf code, so that format-only paths can use it
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import *

from .expression.nodes import NumberOrExpression


@dataclass
class SpiceSourceFunction:
    """
    The transient function of an independent source, e.g. PULSE(0 1 0 1n 1n 5n 10n)
    """
    name: str  # lowercase, e.g. 'pulse', 'sin', 'exp', 'pwl'
    arguments: List[float]


@dataclass
class SpiceSource:
    """
    The value of an independent source (V or I)
    """
    dc: Optional[float] = None
    ac_magnitude: Optional[float] = None
    ac_phase: Optional[float] = None  # in degrees
    function: Optional[SpiceSourceFunction] = None


@dataclass
class SpiceElement:
    """
    An element of a SPICE netlist, e.g. R1 a b 1k, or a subcircuit call, e.g. X1 a b inv.

    The names are the ones of the netlist: nodes with the same name are one node
    (a reader resolves SPICE's case insensitivity), the parameter names are lowercase.
    """
    name: str  # the first letter is the kind of the element, e.g. 'R1', 'Xinv'
    nodes: List[str] = field(default_factory=list)

    # the model or subcircuit, e.g. of a diode or a subcircuit call
    model: Optional[str] = None

    # the value of R, C, L (resistance, capacitance, inductance), the coupling of K,
    # the gain of E, F, G, H
    value: Optional[NumberOrExpression] = None

    parameters: Dict[str, NumberOrExpression] = field(default_factory=dict)

    # K: the coupled inductors, F and H: the voltage source of the controlling current
    references: List[str] = field(default_factory=list)

    # V and I
    source: Optional[SpiceSource] = None

    @property
    def kind(self) -> str:
        """
        The element letter in uppercase, e.g. 'R' or 'X'
        """
        return self.name[0].upper()


@dataclass
class SpiceSubcircuit:
    name: str
    ports: List[str]
    parameters: Dict[str, NumberOrExpression] = field(default_factory=dict)  # the defaults
    elements: List[SpiceElement] = field(default_factory=list)

    # of its .param lines, which its calls don't set
    local_parameters: Dict[str, NumberOrExpression] = field(default_factory=dict)


@dataclass
class SpiceNetlist:
    subcircuits: List[SpiceSubcircuit] = field(default_factory=list)

    # the elements outside of subcircuits (e.g. of a testbench)
    elements: List[SpiceElement] = field(default_factory=list)

    # nodes that are the same in all subcircuits (.global), besides ground
    global_nodes: List[str] = field(default_factory=list)

    # of the .param lines outside of subcircuits
    parameters: Dict[str, NumberOrExpression] = field(default_factory=dict)
