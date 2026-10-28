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
VACASK netlists (https://codeberg.org/arpadbuermen/VACASK) in tests:
what the VACASK writer wrote, compared with a SPICE netlist, and simulations,
which are skipped where VACASK isn't installed (vacask on PATH)
"""

from __future__ import annotations
from dataclasses import dataclass, field
import math
import os
import re
import shutil
import subprocess
from typing import *

import pytest

from klayout_pex.netlist.spice_netlist import SpiceNetlist


VACASK_EXE = shutil.which('vacask')

requires_vacask = pytest.mark.skipif(VACASK_EXE is None, reason='vacask is not on PATH')


def write_vacaskrc(run_dir: str, models_dir: str):
    """
    Writes the .vacaskrc.toml into the run directory, by which VACASK finds the devices (OSDI)
    that the VACASK models of a PDK load by name

    :param models_dir: e.g. the one of PDKTestConfig.simulator_models_dir('vacask')
    """
    with open(os.path.join(run_dir, '.vacaskrc.toml'), 'w', encoding='utf-8') as f:
        f.write(f'[Paths]\nmodule_path_prefix = [ "{models_dir}/osdi" ]\n')


def run_vacask(deck_path: str):
    """
    Runs the deck in its directory, where the analyses write their results (e.g. op1.raw)
    """
    result = subprocess.run([VACASK_EXE, os.path.basename(deck_path)], cwd=os.path.dirname(deck_path),
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
    assert result.returncode == 0, f"vacask failed on {deck_path}:\n{result.stdout}\n{result.stderr}"


def read_ascii_raw(path: str) -> Dict[str, List[complex]]:
    """
    The vectors of a raw file of VACASK (options rawfile="ascii"), by name (e.g. x1:out)
    """
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    names: List[str] = []
    values: List[complex] = []
    section = None
    for line in lines:
        if line.startswith('Variables:'):
            section = 'variables'
        elif line.startswith('Values:'):
            section = 'values'
        elif section == 'variables':
            names.append(line.split('\t')[2])
        elif section == 'values' and line.strip():
            text = line.split('\t')[-1]
            real, _, imag = text.partition(',')
            values.append(complex(float(real), float(imag or 0.0)))
    point_count = len(values) // len(names)
    return {name: [values[point * len(names) + i] for point in range(point_count)]
            for i, name in enumerate(names)}


@dataclass
class VacaskInstance:
    name: str
    nodes: List[str]
    master: str
    parameters: Dict[str, str]


@dataclass
class VacaskSubcircuit:
    name: str
    ports: List[str]
    instances: Dict[str, VacaskInstance] = field(default_factory=dict)


_TOKEN = re.compile(r"'(?:[^']|'')*'|\(|\)|[^\s()]+")


def _unquote(token: str) -> str:
    if token.startswith("'"):
        return token[1:-1].replace("''", "'")
    return token


def read_vacask_subcircuits(text: str) -> Dict[str, VacaskSubcircuit]:
    """
    The subcircuits of a VACASK netlist, as the VACASK writer writes them (a statement per line)
    """
    subcircuits: Dict[str, VacaskSubcircuit] = {}
    current: Optional[VacaskSubcircuit] = None
    for line in text.splitlines():
        if line.startswith('//'):
            continue
        tokens = _TOKEN.findall(line)
        if not tokens or tokens[0] in ('load', 'model', 'parameters', 'global'):
            continue
        if tokens[0] == 'subckt':
            current = VacaskSubcircuit(name=_unquote(tokens[1]), ports=[_unquote(t) for t in tokens[3:-1]])
            subcircuits[current.name] = current
        elif tokens[0] == 'ends':
            current = None
        elif current is not None:
            close = tokens.index(')')
            instance = VacaskInstance(name=_unquote(tokens[0]),
                                      nodes=[_unquote(t) for t in tokens[2:close]],
                                      master=_unquote(tokens[close + 1]),
                                      parameters=dict(t.split('=', 1) for t in tokens[close + 2:]))
            current.instances[instance.name] = instance
    return subcircuits


def assert_same_nets_and_values(spice: SpiceNetlist,
                                vacask_text: str,
                                rel_tol: float):
    """
    Asserts that the VACASK netlist has the subcircuits, nets and elements of the SPICE netlist,
    with the same values (within rel_tol).

    The nets may be named differently (e.g. KLayout's SPICE writer writes the net A,B as A|B),
    but each net of one netlist is one net of the other.
    (The netlists have no subcircuit calls with m > 1, which VACASK may have as copies.)
    """
    vacask = read_vacask_subcircuits(vacask_text)
    assert sorted(s.name for s in spice.subcircuits) == sorted(vacask)
    for subcircuit in spice.subcircuits:
        vacask_subcircuit = vacask[subcircuit.name]
        vacask_net_by_spice_net: Dict[str, str] = {}
        spice_net_by_vacask_net: Dict[str, str] = {}

        def assert_same_net(spice_net: str, vacask_net: str, where: str):
            other_vacask_net = vacask_net_by_spice_net.setdefault(spice_net, vacask_net)
            assert other_vacask_net == vacask_net, \
                f"{where}: the SPICE net {spice_net} is the VACASK nets {other_vacask_net} and {vacask_net}"
            other_spice_net = spice_net_by_vacask_net.setdefault(vacask_net, spice_net)
            assert other_spice_net == spice_net, \
                f"{where}: the VACASK net {vacask_net} is the SPICE nets {other_spice_net} and {spice_net}"

        assert len(subcircuit.ports) == len(vacask_subcircuit.ports), subcircuit.name
        for spice_port, vacask_port in zip(subcircuit.ports, vacask_subcircuit.ports):
            assert_same_net(spice_port, vacask_port, f"port of {subcircuit.name}")

        assert sorted(e.name for e in subcircuit.elements) == sorted(vacask_subcircuit.instances)
        for element in subcircuit.elements:
            instance = vacask_subcircuit.instances[element.name]
            assert len(element.nodes) == len(instance.nodes), element.name
            for spice_net, vacask_net in zip(element.nodes, instance.nodes):
                assert_same_net(spice_net, vacask_net, element.name)
            parameters = dict(element.parameters)
            if element.value is not None:
                parameters[element.kind.lower()] = element.value
            if element.model is not None:
                assert element.model == instance.master, element.name
            for name, value in parameters.items():
                if name.lower() == 'm' and value == 1 and 'm' not in instance.parameters:
                    continue  # NOTE: not written to a subcircuit that doesn't declare m
                obtained = float(instance.parameters[name.lower()])
                assert math.isclose(value, obtained, rel_tol=rel_tol), \
                    f"{element.name}: {name}={value} in SPICE, {obtained} in VACASK"
