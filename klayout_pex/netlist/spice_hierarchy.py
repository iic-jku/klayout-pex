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
The elements of a SPICE netlist in the hierarchy of its subcircuit calls, with their values evaluated
in the scopes of parameters as ngspice has them (as of ngspice-46):
    - a subcircuit call: its parameters, else the defaults of its subcircuit, and the .param lines
      of its subcircuit; the parameters of the call refer to this scope (e.g. ad='w*0.29' w=1u),
      but to the caller's parameter of their own name (e.g. w='w*2')
    - then the scope of its caller, e.g. of the call of the calling subcircuit, up to the .param lines
      of the top level
    - the values of another element refer to the scope of its subcircuit call

NOTE: imports neither KLayout nor generated protobuf code, so that format-only paths can use it
"""

from __future__ import annotations
from dataclasses import dataclass, replace
from functools import partial
from itertools import chain
from typing import *

from .expression.nodes import ExpressionError, NumberOrExpression
from .expression.scope import ParameterScope
from .spice_netlist import SpiceElement, SpiceNetlist, SpiceSubcircuit


class SpiceEvaluationError(Exception):
    """
    A value of the netlist without number, e.g. an expression of a parameter that is not defined
    """
    pass


@dataclass(frozen=True)
class HierarchyElement:
    path: str  # the names of the subcircuit calls and of the element, e.g. X1.XM2
    element: SpiceElement  # with its value and parameters as numbers


class SpiceHierarchy:
    def __init__(self, netlist: SpiceNetlist):
        self.netlist = netlist
        self._subcircuit_by_key = {s.name.casefold(): s for s in netlist.subcircuits}
        self._top_scope = ParameterScope(netlist.parameters)

    def subcircuit(self, name: str) -> Optional[SpiceSubcircuit]:
        """
        The subcircuit of that name, in any case
        """
        return self._subcircuit_by_key.get(name.casefold())

    def uncalled_subcircuits(self) -> List[SpiceSubcircuit]:
        """
        The subcircuits no element calls, e.g. the cells of a schematic
        """
        elements = chain(self.netlist.elements, *(s.elements for s in self.netlist.subcircuits))
        called = {e.model.casefold() for e in elements if e.kind == 'X' and e.model is not None}
        return [s for s in self.netlist.subcircuits if s.name.casefold() not in called]

    def flat_elements(self, subcircuit: Optional[SpiceSubcircuit] = None) -> Iterator[HierarchyElement]:
        """
        The elements of the subcircuit (with the defaults of its parameters), or else of the top level,
        with the calls of the subcircuits of the netlist as their elements, recursively

        :raises SpiceEvaluationError: if a value has no number (e.g. of a parameter that is not defined),
                                      or a subcircuit calls itself
        """
        if subcircuit is None:
            return self._flat_elements(self.netlist.elements, self._top_scope, '', ())
        return self._flat_elements(subcircuit.elements, self._call_scope(None, subcircuit, self._top_scope),
                                   '', (subcircuit.name.casefold(),))

    # --------------------------------------------------------------------------------

    @staticmethod
    def _call_scope(call: Optional[SpiceElement],
                    subcircuit: Optional[SpiceSubcircuit],
                    caller_scope: ParameterScope) -> ParameterScope:
        """
        :param call: None for the subcircuit of the top cell
        :param subcircuit: None for a call of a subcircuit the netlist doesn't define (e.g. a device of a PDK)
        """
        definitions: Dict[str, NumberOrExpression] = {}
        if subcircuit is not None:
            definitions.update(subcircuit.parameters)
        if call is not None:
            definitions.update(call.parameters)
        if subcircuit is not None:
            definitions.update(subcircuit.local_parameters)
        return ParameterScope(definitions, parent=caller_scope)

    def _flat_elements(self,
                       elements: List[SpiceElement],
                       scope: ParameterScope,
                       path: str,
                       calls: Tuple[str, ...]) -> Iterator[HierarchyElement]:
        for element in elements:
            name = f"{path}{element.name}"
            if element.kind != 'X':
                yield HierarchyElement(path=name, element=self._evaluated(element, scope, name))
                continue
            subcircuit = self.subcircuit(element.model) if element.model is not None else None
            call_scope = self._call_scope(element, subcircuit, scope)
            evaluated = self._evaluated(element, call_scope, name)
            if subcircuit is None:
                yield HierarchyElement(path=name, element=evaluated)
                continue
            key = subcircuit.name.casefold()
            if key in calls:
                raise SpiceEvaluationError(f"{name} calls the subcircuit {subcircuit.name} within itself")
            yield from self._flat_elements(subcircuit.elements, call_scope, f"{name}.", calls + (key,))

    @staticmethod
    def _evaluated(element: SpiceElement, scope: ParameterScope, path: str) -> SpiceElement:
        """
        :param scope: of the element, or of the call for a subcircuit call (which has its parameters)
        """
        def evaluate(what: str, value: NumberOrExpression, evaluation: Callable[[], float]) -> float:
            try:
                return evaluation()
            except ExpressionError as e:
                raise SpiceEvaluationError(f"the {what} {value} of {path}: {e}") from None

        if element.kind == 'X':
            parameters = {n: evaluate(f"parameter {n} =", v, partial(scope.value, n))
                          for n, v in element.parameters.items()}
        else:
            parameters = {n: evaluate(f"parameter {n} =", v, partial(scope.evaluate, v))
                          for n, v in element.parameters.items()}
        value = None
        if element.value is not None:
            value = evaluate('value', element.value, partial(scope.evaluate, element.value))
        return replace(element, value=value, parameters=parameters)
