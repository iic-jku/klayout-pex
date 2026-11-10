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

from __future__ import annotations

from datetime import datetime
from itertools import permutations
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple
from unittest import mock

import klayout.db as kdb
import pytest

from klayout_pex.device_models import DeviceModels
from klayout_pex.klayout.netlist_printer import NetlistHeader, NetlistPrinter
from klayout_pex.netlist.netlist_reduction import reduce_spice_netlist
from klayout_pex.netlist.rc_reduction import ReductionOptions
from klayout_pex.netlist.spice_netlist import SpiceNetlist
from klayout_pex.netlist.spice_reader import SpiceReader
from klayout_pex.rcx25.extraction_results import ExtractionResults, ExtractionSummary, NetCoupleKey
from klayout_pex.rcx25.netlist_checks import check_schematic_pins
from klayout_pex.rcx25.netlist_expander import RCX25NetlistExpander
from tests.common.ngspice import ngspice_operating_point, requires_ngspice
import klayout_pex_protobuf.kpex.tech.device_models_pb2 as device_models_pb2


MODELS = DeviceModels(device_models_pb2.DeviceModelsInfo())
REPORTED_PORTS = ('vref', 'vss', 'vcopy', 'sky130_gnd')


def expand_ports(order: Sequence[str], schematic: Optional[SpiceNetlist] = None,
                 connections: Optional[Mapping[str, Optional[str]]] = None,
                 summary: Optional[ExtractionSummary] = None) -> Tuple[kdb.Netlist, kdb.Netlist]:
    source = kdb.Netlist()
    circuit = kdb.Circuit()
    circuit.name = 'chip'
    source.add(circuit)
    connections = connections if connections is not None else {name: name for name in order}
    nets = {name: circuit.create_net(name) for name in sorted({n for n in connections.values() if n is not None})}
    for name in order:
        pin = circuit.create_pin(name)
        if connections[name] is not None:
            circuit.connect_pin(pin, nets[connections[name]])
    expanded = RCX25NetlistExpander.expand(
        source, 'chip', ExtractionResults({}), blackbox_devices=True, device_models=MODELS,
        substrate_net_name='bulk', summary=summary, schematic=schematic)
    return source, expanded


def pin_connections(netlist: kdb.Netlist) -> Dict[str, Optional[str]]:
    circuit = netlist.circuit_by_name('chip')
    return {pin.name(): net.expanded_name() if (net := circuit.net_for_pin(pin.id())) is not None else None
            for pin in circuit.each_pin()}


def write_netlist(netlist: kdb.Netlist, path: Path) -> SpiceNetlist:
    NetlistPrinter(NetlistHeader('test', 'KPEX/2.5D', 'test', datetime(2000, 1, 1)), MODELS).write(netlist, path)
    return SpiceReader().read(path)


@pytest.mark.parametrize('order', list(permutations(REPORTED_PORTS)))
@pytest.mark.parametrize('preferred', [None, 'vcopy vss vref'])
def test_reported_interface_is_independent_of_pin_creation_order(
        order: Tuple[str, ...], preferred: Optional[str], tmp_path: Path):
    # Every permutation must bind the same positional call to the same nets.
    # The substrate is unmatched by the schematic and follows its named ports.
    schematic = SpiceReader().parse(f'.subckt CHIP {preferred}\n.ends\n') if preferred else None
    summary = ExtractionSummary({}, {NetCoupleKey(name, '0'): (index + 1) * 1000.0
                                     for index, name in enumerate(REPORTED_PORTS)})
    source, expanded = expand_ports(order, schematic, summary=summary)
    written = write_netlist(expanded, tmp_path / 'extracted.cir').subcircuits[0]
    expected = ['vcopy', 'vss', 'vref', 'sky130_gnd'] if preferred else ['sky130_gnd', 'vcopy', 'vref', 'vss']
    assert written.ports == expected
    assert pin_connections(expanded) == pin_connections(source)
    assert [pin.name() for pin in source.circuit_by_name('chip').each_pin()] == list(order)
    # Independent name-to-value evidence catches reconnection mistakes during reordering.
    assert {tuple(element.nodes): element.value for element in written.elements} == {
        (name, '0'): (index + 1) * 1000.0 for index, name in enumerate(REPORTED_PORTS)}


@pytest.mark.parametrize('order,expected', [
    ((), []),
    (('only',), ['only']),
    (('x2', 'x10', 'B', 'a'), ['a', 'B', 'x10', 'x2']),
])
def test_empty_single_and_lexically_sorted_interfaces(order: Tuple[str, ...], expected: Sequence[str], tmp_path: Path):
    _, expanded = expand_ports(order)
    assert write_netlist(expanded, tmp_path / 'sorted.cir').subcircuits[0].ports == list(expected)


@pytest.mark.parametrize('text,expected,ambiguous', [
    ('.subckt CHIP C a B\n.ends\n.subckt other z\n.ends\n', ['C', 'A', 'B'], False),
    ('.subckt schematic C a B\nX1 C a child\n.ends\n.subckt child z y\n.ends\n', ['C', 'A', 'B'], False),
    ('.subckt left C A B\n.ends\n.subckt right B C A\n.ends\n', ['A', 'B', 'C'], True),
    ('R1 a b 1k\n', ['A', 'B', 'C'], True),
    ('.subckt chip\n.ends\n', ['A', 'B', 'C'], False),
    ('.subckt chip C C a\n.ends\n', ['C', 'A', 'B'], False),
])
def test_schematic_top_selection_and_case_matching(
        text: str, expected: Sequence[str], ambiguous: bool, tmp_path: Path):
    with mock.patch('klayout_pex.rcx25.netlist_expander.warning') as warn:
        _, expanded = expand_ports(('B', 'A', 'C'), SpiceReader().parse(text))
    assert write_netlist(expanded, tmp_path / 'selected.cir').subcircuits[0].ports == list(expected)
    assert bool(warn.call_count) == ambiguous
    if ambiguous:
        assert 'Sorting extracted ports by name' in warn.call_args.args[0]


def test_reordering_uses_emitted_net_names_and_preserves_aliases_and_disconnected_pins():
    # KLayout pin names can differ from the net names emitted by the SPICE writer.
    connections = {'pZ': 'Z', 'pA': 'a', 'aliasA': 'a', 'unused': None}
    source, expanded = expand_ports(('pZ', 'unused', 'pA', 'aliasA'), connections=connections)
    assert pin_connections(expanded) == pin_connections(source) == connections
    assert list(pin_connections(expanded)) == ['aliasA', 'pA', 'unused', 'pZ']
    circuit = expanded.circuit_by_name('chip')
    assert circuit.net_for_pin(circuit.pin_by_name('pA').id()).pin_count() == 2
    assert circuit.net_for_pin(circuit.pin_by_name('aliasA').id()).pin_count() == 2


def test_all_added_ports_are_ordered_after_label_expansion(tmp_path: Path):
    # Exclusion ports and the new substrate must not retain the order in which
    # extraction discovered them. Split labels still reach their own RC nodes.
    summary = ExtractionSummary(
        {NetCoupleKey('D', 'VSUBS'): 1.0},
        {NetCoupleKey('D', 'X'): 10.0, NetCoupleKey('G', 'cut.z'): 20.0, NetCoupleKey('G', 'cut.a'): 30.0},
        label_ports={'D,X': ['X', 'D'], 'G': ['G', 'cut.z', 'cut.a']},
        exclusion_ports={'G': ['cut.z', 'cut.a']})
    _, expanded = expand_ports(('D,X', 'G', 'S'), SpiceReader().parse('.subckt chip X S G\n.ends\n'), summary=summary)
    written = write_netlist(expanded, tmp_path / 'expanded.cir').subcircuits[0]
    assert written.ports == ['X', 'S', 'G', 'bulk', 'cut.a', 'cut.z', 'D']
    assert pin_connections(expanded) == {name: name for name in written.ports}
    assert {tuple(element.nodes): element.value for element in written.elements if element.kind == 'R'} == {
        ('D', 'X'): 10.0, ('G', 'cut.z'): 20.0, ('G', 'cut.a'): 30.0}


def test_coalesced_cc_labels_use_the_first_matching_schematic_position(tmp_path: Path):
    _, expanded = expand_ports(('C', 'A,B'), SpiceReader().parse('.subckt chip B C A\n.ends\n'))
    assert write_netlist(expanded, tmp_path / 'coalesced.cir').subcircuits[0].ports == ['A|B', 'C']


def test_reordering_neither_invents_missing_ports_nor_hides_membership_problems(tmp_path: Path):
    schematic = SpiceReader().parse('.subckt chip C B\n.ends\n')
    source, expanded = expand_ports(('A', 'C'), schematic)
    ports = write_netlist(expanded, tmp_path / 'missing.cir').subcircuits[0].ports
    assert ports == ['C', 'A']
    assert check_schematic_pins(schematic, 'chip', ports, MODELS, source) == [
        'the schematic has pins without port in the netlist: B',
        'the netlist has ports without pin in the schematic: A']


@pytest.mark.slow
@requires_ngspice
@pytest.mark.parametrize('with_schematic', [False, True])
@pytest.mark.parametrize('reduced', [False, True])
def test_positional_consumer_drives_the_intended_resistor_divider(
        with_schematic: bool, reduced: bool, tmp_path: Path):
    schematic = SpiceReader().parse('.subckt chip drive sense ref\n.ends\n') if with_schematic else None
    summary = ExtractionSummary({}, {NetCoupleKey('drive', 'sense'): 1000.0, NetCoupleKey('sense', 'ref'): 3000.0})
    _, expanded = expand_ports(('ref', 'drive', 'sense'), schematic, summary=summary)
    path = tmp_path / 'divider.cir'
    write_netlist(expanded, path)
    if reduced:
        destination = tmp_path / 'reduced.cir'
        reduce_spice_netlist(str(path), str(destination), reduction_options=ReductionOptions())
        path = destination
    positional_nodes = 'stimulus output 0' if with_schematic else 'stimulus 0 output'
    values = ngspice_operating_point(
        f'.include "{path}"\nXuut {positional_nodes} chip\nVstimulus stimulus 0 1\n',
        ['v(output)'], str(tmp_path))
    assert values['v(output)'] == pytest.approx(0.75, abs=1e-8)
