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
Writes a SPICE netlist (see spice_netlist.py) as a netlist of the VACASK simulator
(https://codeberg.org/arpadbuermen/VACASK), to be included by a VACASK testbench.

What differs from SPICE:
    - names: an identifier is [A-Za-z_$][A-Za-z0-9_$]*, other names are quoted ('A,B', 'sub!'),
      which VACASK takes with any character but whitespace (written as \\xHH, as KLayout does).
      Two names that would get the same VACASK name (e.g. 'a b' and 'a\\x20b') are an error,
      as VACASK would short their nets.
    - case: VACASK is case-sensitive, the names are written as they are, the parameter names in lowercase
      (VACASK lowercases the parameters of its devices, and so does its ng2vc, which converts PDK models)
    - numbers: plain floats (VACASK reads the SI prefix M as mega, SPICE as milli)
    - R, C, L: VACASK's own resistor, capacitor and inductor devices, and its builtin sources
    - m: the $mfactor of a device, but a VACASK subcircuit takes m only if it declares it,
      a call with m = N of another subcircuit is written as N calls;
      an element whose model is a subcircuit that declares m (e.g. an M line of a PDK MOS) takes m too,
      and m = 1 of another element with a model is left out (its model may be a subcircuit)

NOTE: imports neither KLayout nor generated protobuf code, so that format-only paths can use it
"""

from __future__ import annotations
from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import *

from .spice_netlist import SpiceElement, SpiceNetlist, SpiceSource, SpiceSubcircuit


class VacaskWriterError(Exception):
    """
    The netlist has no VACASK equivalent, e.g. two of its nets would get the same VACASK name
    """
    pass


ParameterValue = Union[float, str, List[float]]


# NOTE: VACASK reads these as keywords at the start of a line (e.g. an instance named model),
#       so they are quoted wherever they are names
RESERVED_WORDS = frozenset({
    'include', 'section', 'endsection', 'load', 'model', 'global', 'ground', 'subckt', 'ends',
    'parameters', 'control', 'endc', 'analysis', 'sweep', 'embed', 'save',
})

_IDENTIFIER = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')
_NODE_NUMBER = re.compile(r'0|[1-9][0-9]*')  # NOTE: not 007, VACASK might read it as 7


def vacask_identifier_value(name: str) -> str:
    """
    The name with each character VACASK names can't have (whitespace, unprintable) as \\xHH (of its UTF-8 bytes)
    """
    return ''.join(c if c.isprintable() and not c.isspace()
                   else ''.join(f"\\x{b:02x}" for b in c.encode('utf-8'))
                   for c in name)


def vacask_identifier(name: str, is_node: bool = False) -> str:
    """
    The name as VACASK identifier: itself, if it is a plain identifier (or a node number),
    else quoted (a quote doubled)
    """
    value = vacask_identifier_value(name)
    if _IDENTIFIER.fullmatch(value) and value not in RESERVED_WORDS:
        return value
    if is_node and _NODE_NUMBER.fullmatch(value):
        return value
    return "'" + value.replace("'", "''") + "'"


def vacask_number(value: float) -> str:
    """
    The number with 12 significant digits (as the SPICE netlist printer writes them), without SI prefix
    """
    return f"{value:.12g}".replace('e+', 'e')


def vacask_value(value: ParameterValue) -> str:
    if isinstance(value, str):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    if isinstance(value, (list, tuple)):
        return '[' + ', '.join(vacask_number(v) for v in value) + ']'
    return vacask_number(value)


@dataclass(frozen=True, order=True)
class VacaskDevice:
    """
    A device of VACASK, under the model name the netlist gives it
    """
    model_name: str
    device_name: str
    osdi_file: Optional[str] = None  # None for a builtin device


RESISTOR = VacaskDevice('resistor', 'resistor', 'resistor.osdi')
CAPACITOR = VacaskDevice('capacitor', 'capacitor', 'capacitor.osdi')
INDUCTOR = VacaskDevice('inductor', 'inductor', 'inductor.osdi')
VSOURCE = VacaskDevice('vsource', 'vsource')
ISOURCE = VacaskDevice('isource', 'isource')
VCVS = VacaskDevice('vcvs', 'vcvs')
VCCS = VacaskDevice('vccs', 'vccs')
CCVS = VacaskDevice('ccvs', 'ccvs')
CCCS = VacaskDevice('cccs', 'cccs')
MUTUAL = VacaskDevice('mutual', 'mutual')

ALL_DEVICES = (RESISTOR, CAPACITOR, INDUCTOR, VSOURCE, ISOURCE, VCVS, VCCS, CCVS, CCCS, MUTUAL)

# the device and its value parameter of an element without model
_PASSIVE_DEVICES: Dict[str, Tuple[VacaskDevice, str]] = {
    'R': (RESISTOR, 'r'),
    'C': (CAPACITOR, 'c'),
    'L': (INDUCTOR, 'l'),
}

# the parameters (besides m) the devices of an element without model take, as they are named in SPICE
_PASSIVE_PARAMETERS: Dict[str, Set[str]] = {
    'R': {'noisy'},
    'C': set(),
    'L': set(),
}

_CONTROLLED_SOURCES: Dict[str, VacaskDevice] = {
    'E': VCVS,
    'G': VCCS,
    'H': CCVS,
    'F': CCCS,
}


class _NodeNames:
    """
    The VACASK names of the nodes of a subcircuit (or of the top level), which differ for different nodes
    """

    def __init__(self, scope: str):
        self.scope = scope
        self.identifier_by_name: Dict[str, str] = {}
        self.name_by_identifier: Dict[str, str] = {}

    def __call__(self, name: str) -> str:
        identifier = self.identifier_by_name.get(name)
        if identifier is None:
            identifier = vacask_identifier(name, is_node=True)
            other = self.name_by_identifier.setdefault(identifier, name)
            if other != name:
                raise VacaskWriterError(f"The nets {other!r} and {name!r} of {self.scope} "
                                        f"would both be the net {identifier} in VACASK, which shorts them")
            self.identifier_by_name[name] = identifier
        return identifier


class _InstanceNames:
    """
    The VACASK names of the instances of a subcircuit (or of the top level), which must differ
    """

    def __init__(self, scope: str):
        self.scope = scope
        self.description_by_identifier: Dict[str, str] = {}

    def declare(self, name: str, origin: Optional[str] = None) -> str:
        identifier = vacask_identifier(name)
        description = repr(name) + (f" ({origin})" if origin else '')
        other = self.description_by_identifier.get(identifier)
        if other is not None:
            raise VacaskWriterError(f"The instances {other} and {description} of {self.scope} "
                                    f"would both be the instance {identifier} in VACASK")
        self.description_by_identifier[identifier] = description
        return identifier


class VacaskWriter:
    def __init__(self,
                 subcircuits_with_m: Collection[str] = frozenset(),
                 header: Sequence[str] = ()):
        """
        :param subcircuits_with_m: the subcircuits whose VACASK definition declares the multiplier m
                                   (e.g. the MOS of a PDK), which a call with m = N gets as it is.
                                   A call with m = N of another subcircuit is written as N calls,
                                   the meaning of m in SPICE (VACASK rejects parameters a subcircuit doesn't declare).
        :param header: the lines of the comment at the top of the netlist
        """
        self.subcircuits_with_m = frozenset(subcircuits_with_m)
        self.header = list(header)

    def write(self,
              netlist: SpiceNetlist,
              output_path: str | Path):
        """
        :raises VacaskWriterError: if the netlist has no VACASK equivalent
        """
        text = self.text(netlist)  # NOTE: before opening the file, so that an error writes none
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(text)

    def text(self, netlist: SpiceNetlist) -> str:
        """
        :raises VacaskWriterError: if the netlist has no VACASK equivalent
        """
        self._check_subcircuit_names(netlist)

        body: List[str] = []
        used_devices: Set[VacaskDevice] = set()

        if netlist.global_nodes:
            body.append('global ' + ' '.join(vacask_identifier(n, is_node=True) for n in netlist.global_nodes))
            body.append('')

        for subcircuit in netlist.subcircuits:
            body += self._subcircuit_lines(subcircuit, used_devices)
            body.append('')

        if netlist.elements:
            scope = 'the top level'
            instance_lines, devices = self._instance_lines(netlist.elements, scope, _NodeNames(scope))
            used_devices |= devices
            body += [f"model {d.model_name} {d.device_name}" for d in sorted(devices)]
            body += instance_lines
            body.append('')

        lines = [f"// {line}".rstrip() for line in self.header]
        if lines:
            lines.append('')
        osdi_files = sorted({d.osdi_file for d in used_devices if d.osdi_file})
        if osdi_files:
            lines += [f'load "{f}"' for f in osdi_files]
            lines.append('')
        lines += body
        return '\n'.join(lines).rstrip('\n') + '\n'

    # --------------------------------------------------------------------------------

    @staticmethod
    def _check_subcircuit_names(netlist: SpiceNetlist):
        # NOTE: the models of the VACASK devices are defined in each subcircuit that uses them,
        #       where they would hide a subcircuit of the same name
        model_names = sorted(d.model_name for d in ALL_DEVICES)
        names: Dict[str, str] = {}
        for subcircuit in netlist.subcircuits:
            identifier = vacask_identifier(subcircuit.name)
            if identifier in names:
                raise VacaskWriterError(f"The subcircuits {names[identifier]!r} and {subcircuit.name!r} "
                                        f"would both be the subcircuit {identifier} in VACASK")
            names[identifier] = subcircuit.name
            if subcircuit.name in model_names:
                raise VacaskWriterError(f"The subcircuit {subcircuit.name!r} has the name of a model "
                                        f"the VACASK netlist defines ({', '.join(model_names)})")

    def _subcircuit_lines(self,
                          subcircuit: SpiceSubcircuit,
                          used_devices: Set[VacaskDevice]) -> List[str]:
        scope = f"subcircuit {subcircuit.name!r}"
        nodes = _NodeNames(scope)
        ports: List[str] = []
        for port in subcircuit.ports:
            identifier = nodes(port)
            if identifier in ports:
                raise VacaskWriterError(f"The port {port!r} of {scope} is there twice")
            ports.append(identifier)

        lines = [f"subckt {vacask_identifier(subcircuit.name)} ({' '.join(ports)})"]
        if subcircuit.parameters:
            lines.append('  parameters ' + self._parameters_text(list(subcircuit.parameters.items()), scope))

        instance_lines, devices = self._instance_lines(subcircuit.elements, scope, nodes)
        used_devices |= devices
        lines += [f"  model {d.model_name} {d.device_name}" for d in sorted(devices)]
        lines += [f"  {line}" for line in instance_lines]
        lines.append('ends')
        return lines

    def _instance_lines(self,
                        elements: List[SpiceElement],
                        scope: str,
                        nodes: _NodeNames) -> Tuple[List[str], Set[VacaskDevice]]:
        instances = _InstanceNames(scope)
        element_kinds = {e.name: e.kind for e in elements}
        lines: List[str] = []
        devices: Set[VacaskDevice] = set()

        def referenced_instance(element: SpiceElement, name: str, kind: str) -> str:
            if element_kinds.get(name) != kind:
                raise VacaskWriterError(f"The element {element.name!r} of {scope} refers to {name!r}, "
                                        f"which is no element {kind} there")
            return vacask_identifier_value(name)

        for element in elements:
            kind = element.kind
            master: str
            prefix: List[Tuple[str, ParameterValue]] = []  # e.g. the value, before the element's parameters
            parameters: List[Tuple[str, ParameterValue]] = []
            m: Optional[float] = None
            m_name = '$mfactor'
            m_index = 0  # NOTE: m stays where it is among the parameters
            copies = 1
            element_nodes = element.nodes

            for name, value in element.parameters.items():
                if name.lower() == 'm':
                    m, m_index = value, len(parameters)
                else:
                    parameters.append((name, value))

            if kind in _PASSIVE_DEVICES and element.model is None:
                device, value_name = _PASSIVE_DEVICES[kind]
                devices.add(device)
                master = device.model_name
                if element.value is None:
                    raise VacaskWriterError(f"The element {element.name!r} of {scope} has no value")
                unknown = [n for n, _ in parameters if n.lower() not in _PASSIVE_PARAMETERS[kind]]
                if unknown:
                    raise VacaskWriterError(f"The element {element.name!r} of {scope} has parameters "
                                            f"VACASK's {device.device_name} doesn't take: {', '.join(unknown)}")
                prefix = [(value_name, element.value)]
            elif kind == 'X':
                if element.model is None:
                    raise VacaskWriterError(f"The subcircuit call {element.name!r} of {scope} has no subcircuit")
                master = vacask_identifier(element.model)
                if element.model in self.subcircuits_with_m:
                    m_name = 'm'
                elif m is not None:
                    if m == 1:
                        m = None
                    elif float(m).is_integer() and m > 1:
                        copies = int(m)
                        m = None
                    else:
                        raise VacaskWriterError(
                            f"The subcircuit call {element.name!r} of {scope} has m={m:g}, "
                            f"which VACASK's {element.model} doesn't declare and which is no number of copies"
                        )
            elif kind == 'K':
                devices.add(MUTUAL)
                master = MUTUAL.model_name
                element_nodes = []
                if len(element.references) != 2 or element.value is None:
                    raise VacaskWriterError(f"The coupling {element.name!r} of {scope} needs two inductors "
                                            f"and a coupling factor")
                prefix = [('k', element.value),
                          ('ind1', referenced_instance(element, element.references[0], 'L')),
                          ('ind2', referenced_instance(element, element.references[1], 'L'))]
            elif kind in ('V', 'I'):
                device = VSOURCE if kind == 'V' else ISOURCE
                devices.add(device)
                master = device.model_name
                prefix = self._source_parameters(element, scope)
            elif kind in _CONTROLLED_SOURCES:
                device = _CONTROLLED_SOURCES[kind]
                devices.add(device)
                master = device.model_name
                if element.value is None:
                    raise VacaskWriterError(f"The element {element.name!r} of {scope} has no gain")
                prefix = [('gain', element.value)]
                if kind in ('F', 'H'):
                    if len(element.references) != 1:
                        raise VacaskWriterError(f"The element {element.name!r} of {scope} needs "
                                                f"the voltage source of its controlling current")
                    prefix.append(('ctlinst', referenced_instance(element, element.references[0], 'V')))
            elif element.model is not None:  # e.g. a diode, a MOS, a resistor of a model
                master = vacask_identifier(element.model)
                if kind in _PASSIVE_DEVICES and element.value is not None:
                    prefix = [(_PASSIVE_DEVICES[kind][1], element.value)]
                if element.model in self.subcircuits_with_m:
                    m_name = 'm'  # NOTE: e.g. an M line of a PDK MOS, whose VACASK model is a subcircuit
                elif m == 1:
                    m = None  # NOTE: the model may be a subcircuit, on which VACASK rejects $mfactor
            else:
                raise VacaskWriterError(f"The element {element.name!r} of {scope} has no model")

            if m is not None:
                parameters.insert(m_index, (m_name, m))
            parameters = prefix + parameters

            node_text = ' '.join(nodes(n) for n in element_nodes)
            parameter_text = self._parameters_text(parameters, f"the element {element.name!r} of {scope}")
            for copy in range(1, copies + 1):
                if copies == 1:
                    name = instances.declare(element.name)
                else:
                    name = instances.declare(f"{element.name}_{copy}",
                                             origin=f"copy {copy} of {element.name}, m={copies}")
                line = f"{name} ({node_text}) {master}"
                if parameter_text:
                    line += ' ' + parameter_text
                lines.append(line)

        return lines, devices

    @staticmethod
    def _parameters_text(parameters: List[Tuple[str, ParameterValue]],
                         owner: str) -> str:
        names: Set[str] = set()
        items: List[str] = []
        for name, value in parameters:
            name = name.lower()
            if name in names:
                raise VacaskWriterError(f"The parameter {name} of {owner} is there twice")
            names.add(name)
            items.append(f"{vacask_identifier(name)}={vacask_value(value)}")
        return ' '.join(items)

    @staticmethod
    def _source_parameters(element: SpiceElement,
                           scope: str) -> List[Tuple[str, ParameterValue]]:
        """
        The parameters of VACASK's vsource or isource for the value of a SPICE source.

        The waveform parameters SPICE defaults to the time step or stop time of the transient analysis
        must be given, as are those whose default differs (e.g. a pulse without fall time doesn't fall in VACASK).
        """
        source = element.source or SpiceSource()
        owner = f"the source {element.name!r} of {scope}"

        def error(problem: str) -> VacaskWriterError:
            return VacaskWriterError(f"{owner[0].upper()}{owner[1:]}: {problem}")

        parameters: List[Tuple[str, ParameterValue]] = []
        function = source.function
        if function is None:
            parameters.append(('dc', source.dc if source.dc is not None else 0.0))
        else:
            a = function.arguments
            match function.name:
                case 'pulse':
                    if len(a) not in (6, 7):
                        raise error("PULSE needs V1 V2 TD TR TF PW and optionally PER "
                                    "(SPICE defaults TR, TF, PW to the time step or stop time)")
                    if a[3] <= 0 or a[4] <= 0:
                        raise error("PULSE needs TR > 0 and TF > 0 (SPICE takes the time step for 0, "
                                    "VACASK doesn't fall for TF = 0)")
                    parameters += [('type', 'pulse'), ('val0', a[0]), ('val1', a[1]), ('delay', a[2]),
                                   ('rise', a[3]), ('fall', a[4]), ('width', a[5])]
                    if len(a) == 7:
                        parameters.append(('period', a[6]))
                    initial_value = a[0]
                case 'sin':
                    if not 3 <= len(a) <= 6:
                        raise error("SIN needs VO VA FREQ and optionally TD THETA PHASE "
                                    "(SPICE defaults FREQ to the stop time)")
                    vo, va, freq = a[0], a[1], a[2]
                    td, theta, phase = (a[3:] + [0.0, 0.0, 0.0])[:3]
                    if td > 0 and phase != 0:
                        raise error("SIN with TD > 0 and PHASE != 0 holds VO until TD in SPICE, "
                                    "but VO + VA·sin(PHASE) in VACASK")
                    parameters += [('type', 'sine'), ('sinedc', vo), ('ampl', va), ('freq', freq)]
                    if td:
                        parameters.append(('delay', td))
                    if theta:
                        parameters.append(('theta', theta))
                    if phase:
                        parameters.append(('tdphase', phase))
                    initial_value = vo + va * math.sin(math.radians(phase))
                case 'exp':
                    if len(a) != 6:
                        raise error("EXP needs V1 V2 TD1 TAU1 TD2 TAU2 "
                                    "(SPICE defaults them to the time step)")
                    if a[4] <= a[2]:
                        raise error("EXP needs TD2 > TD1")
                    parameters += [('type', 'exp'), ('val0', a[0]), ('val1', a[1]), ('delay', a[2]),
                                   ('tau1', a[3]), ('td2', a[4] - a[2]), ('tau2', a[5])]
                    initial_value = a[0]
                case 'pwl':
                    if len(a) < 4 or len(a) % 2:
                        raise error("PWL needs two or more pairs of time and value")
                    parameters += [('type', 'pwl'), ('wave', list(a))]
                    initial_value = a[1]
                case _:
                    raise error(f"VACASK has no source function {function.name.upper()}")
            # NOTE: SPICE takes the DC value for the operating point, VACASK the value at time 0
            if source.dc is not None and source.dc != initial_value:
                raise error(f"its DC value {source.dc:g} differs from its value {initial_value:g} at time 0, "
                            f"which VACASK takes for the operating point")
        if source.ac_magnitude is not None:
            parameters.append(('mag', source.ac_magnitude))
        if source.ac_phase is not None:
            parameters.append(('phase', source.ac_phase))
        return parameters
