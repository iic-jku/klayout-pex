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

"""Check the terminal response of the written RC network after reduction (#215)."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .rc_network import RCNetwork
from .spice_rc_netlist import SpiceRCNetlist
from ..util.unit_formatter import format_spice_number


TerminalAdmittance = Dict[Tuple[str, str], complex]

# Exact elimination can fill a sparse network. A requested check that reaches
# either bound fails explicitly rather than silently passing an unchecked result.
_MAX_ENTRIES = 100_000
_MAX_UPDATES = 1_000_000


def _validate_frequency(frequency: float):
    if isinstance(frequency, bool) or not isinstance(frequency, (int, float)) or \
            not math.isfinite(frequency) or frequency < 0:
        raise ValueError(f"check frequency must be a finite number of Hz ≥ 0, got {frequency!r}")


@dataclass(frozen=True)
class AdmittanceCheckOptions:
    frequency: float
    """Frequency [Hz], including zero for DC."""
    max_relative_error: float = 0.01
    """Maximum ‖Y_reduced − Y_original‖_F / ‖Y_original‖_F, inclusive."""

    def __post_init__(self):
        _validate_frequency(self.frequency)
        value = self.max_relative_error
        if isinstance(value, bool) or not isinstance(value, (int, float)) or \
                not math.isfinite(value) or not 0 < value < 1:
            raise ValueError(f"check relative error must be a finite number > 0 and < 1, got {value!r}")


@dataclass(frozen=True)
class AdmittanceCheck:
    scope: str
    options: AdmittanceCheckOptions
    relative_error: Optional[float] = None
    error: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.error is None and self.relative_error is not None and \
            self.relative_error <= self.options.max_relative_error

    def describe(self) -> str:
        context = f"{self.scope}: admittance at {format_spice_number(self.options.frequency)} Hz"
        if self.error is not None:
            return f"{context} could not be checked: {self.error}"
        return (f"{context}: relative Frobenius error {self.relative_error:.6g}, "
                f"limit {self.options.max_relative_error:g}")


class AdmittanceCheckError(Exception):
    """An exact admittance could not be computed within the numerical/resource limits."""


def _finite(value: complex) -> complex:
    if not math.isfinite(value.real) or not math.isfinite(value.imag):
        raise AdmittanceCheckError("non-finite nodal admittance")
    return value


def _sum(values: Sequence[complex]) -> complex:
    try:
        return _finite(complex(math.fsum(value.real for value in values),
                               math.fsum(value.imag for value in values)))
    except OverflowError as exc:
        raise AdmittanceCheckError("nodal admittance overflow") from exc


def terminal_admittance(network: RCNetwork, terminals: Sequence[str], frequency: float) -> TerminalAdmittance:
    """
    Exact ``G + 2πjf C`` at the terminals, by sparse complex Schur elimination.

    Keys are case-insensitive terminal-name pairs. Missing entries are zero.
    Components without a path to a terminal at this frequency contribute nothing,
    including capacitor-only islands at DC. No ground shunts are added.
    """
    _validate_frequency(frequency)
    boundary = {RCNetwork.name_key(name) for name in terminals}
    nodes = network.nodes()
    if len(nodes) > _MAX_ENTRIES:
        raise AdmittanceCheckError(f"network exceeds the check limit of {_MAX_ENTRIES} nodes and coupling entries")
    graph: Dict[str, Dict[str, complex]] = {
        RCNetwork.name_key(network.name(node)): {} for node in nodes}
    graph.update((name, {}) for name in boundary - graph.keys())
    entries = len(graph)
    if entries > _MAX_ENTRIES:
        raise AdmittanceCheckError(f"network exceeds the check limit of {_MAX_ENTRIES} nodes and coupling entries")

    def add(left: str, right: str, value: complex):
        nonlocal entries
        if value == 0:
            return
        old = graph[left].get(right, 0j)
        updated = _finite(old + value)
        if updated == 0:
            del graph[left][right]
            del graph[right][left]
            entries -= 2
        else:
            if old == 0:
                if entries + 2 > _MAX_ENTRIES:
                    raise AdmittanceCheckError(
                        f"network exceeds the check limit of {_MAX_ENTRIES} nodes and coupling entries")
                entries += 2
            graph[left][right] = graph[right][left] = updated

    # Avoid constructing a second list of all edges before the size check can stop us.
    for left in nodes:
        for right, branch in network.branches(left).items():
            if left >= right:
                continue
            if any(not math.isfinite(value) or value < 0 for value in (branch.conductance, branch.capacitance)):
                raise AdmittanceCheckError("RC values must be finite and non-negative")
            # Multiplying the smaller factor by 2*pi first avoids intermediate
            # overflow and preserves representable subnormal admittances.
            capacitive_y = (min(frequency, branch.capacitance) * math.tau) * max(frequency, branch.capacitance)
            if capacitive_y == 0 and frequency != 0 and branch.capacitance != 0:
                raise AdmittanceCheckError("capacitive admittance underflow")
            value = _finite(complex(branch.conductance, capacitive_y))
            add(RCNetwork.name_key(network.name(left)), RCNetwork.name_key(network.name(right)), value)

    reachable = set(boundary)
    todo = list(boundary)
    while todo:
        for neighbour in graph[todo.pop()]:
            if neighbour not in reachable:
                reachable.add(neighbour)
                todo.append(neighbour)
    graph = {name: neighbours for name, neighbours in graph.items() if name in reachable}
    entries = len(graph) + sum(len(neighbours) for neighbours in graph.values())
    internal = set(graph) - boundary
    heap: List[Tuple[int, str]] = []
    queued: Dict[str, int] = {}

    def queue(name: str):
        if name in internal:
            degree = len(graph[name])
            if queued.get(name) != degree:
                queued[name] = degree
                heapq.heappush(heap, (degree, name))
                if len(heap) > _MAX_ENTRIES:
                    raise AdmittanceCheckError(f"elimination exceeds the check limit of {_MAX_ENTRIES} queued nodes")

    for name in sorted(internal):
        queue(name)
    updates = 0
    while heap:
        degree, name = heapq.heappop(heap)
        if name not in internal or queued.get(name) != degree:
            continue
        del queued[name]
        internal.remove(name)
        neighbours = sorted(graph[name].items())
        updates += degree * (degree - 1) // 2
        if updates > _MAX_UPDATES:
            raise AdmittanceCheckError(f"elimination exceeds the check limit of {_MAX_UPDATES} coupling updates")
        diagonal = _sum([value for _, value in neighbours])
        if neighbours and diagonal == 0:
            raise AdmittanceCheckError(f"zero nodal admittance at internal node '{name}'")
        del graph[name]
        for neighbour, _ in neighbours:
            del graph[neighbour][name]
        entries -= 1 + 2 * degree
        for index, (left, value_left) in enumerate(neighbours):
            for right, value_right in neighbours[index + 1:]:
                # Divide the larger factor first so a very unequal series pair
                # keeps its smaller, but representable, terminal admittance.
                larger, smaller = value_left, value_right
                if max(abs(larger.real), abs(larger.imag)) < max(abs(smaller.real), abs(smaller.imag)):
                    larger, smaller = smaller, larger
                value = _finite((larger / diagonal) * smaller)
                if value == 0:
                    raise AdmittanceCheckError("nodal admittance underflow")
                add(left, right, value)
        for neighbour, _ in neighbours:
            queue(neighbour)

    result: TerminalAdmittance = {}
    for name in sorted(boundary):
        diagonal = _sum(list(graph[name].values()))
        if diagonal != 0:
            result[name, name] = diagonal
        result.update(((name, neighbour), -value) for neighbour, value in graph[name].items())
    return result


def _relative_error(original: Mapping[Tuple[str, str], complex],
                    reduced: Mapping[Tuple[str, str], complex]) -> float:
    # Scale before subtraction/norms, so tiny capacitances do not underflow and
    # large conductances do not overflow. There is no absolute-error floor.
    scale = max((abs(part) for matrix in (original, reduced) for value in matrix.values()
                 for part in (value.real, value.imag)), default=0.0)
    if scale == 0:
        return 0.0
    original_norm = math.hypot(*(part / scale for value in original.values()
                                 for part in (value.real, value.imag)))
    difference = []
    for key in original.keys() | reduced.keys():
        before, after = original.get(key, 0j), reduced.get(key, 0j)
        difference.extend((after.real / scale - before.real / scale,
                           after.imag / scale - before.imag / scale))
    difference_norm = math.hypot(*difference)
    if original_norm == 0:
        return 0.0 if difference_norm == 0 else math.inf
    return difference_norm / original_norm


def check_reduction_admittance(original_path: str, reduced_path: str,
                               options: AdmittanceCheckOptions,
                               keep: Sequence[str] = ()) -> List[AdmittanceCheck]:
    """
    Compare the written plain R/C elements in each scope at every protected terminal.
    Real tie resistors and writer rounding are included. Non-RC devices remain boundary conditions.
    """
    original = SpiceRCNetlist.read(original_path, recognize_ties=False)
    reduced = SpiceRCNetlist.read(reduced_path, recognize_ties=False)
    if [scope.name for scope in original.scopes] != [scope.name for scope in reduced.scopes]:
        return [AdmittanceCheck('netlist', options, error='reduction changed the subcircuit definitions')]
    checks = []
    for before, after in zip(original.scopes, reduced.scopes):
        if not (before.resistors_read or before.capacitors_read or after.resistors_read or after.capacitors_read):
            continue
        terminals = {before.network.name(node) for node in before.network.nodes()
                     if before.network.is_protected(node)}
        terminals.update(name for name in keep if before.network.find_node(name) is not None)
        terminals.add('0')  # A newly written tie may add the global reference.
        try:
            original_y = terminal_admittance(before.network, list(terminals), options.frequency)
            reduced_y = terminal_admittance(after.network, list(terminals), options.frequency)
            checks.append(AdmittanceCheck(before.title, options, _relative_error(original_y, reduced_y)))
        except AdmittanceCheckError as exc:
            checks.append(AdmittanceCheck(before.title, options, error=str(exc)))
    return checks
