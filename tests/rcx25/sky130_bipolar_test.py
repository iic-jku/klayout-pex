#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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

"""BJT terminal ownership and connectivity, including the poly-gated 11 V NPN.

Regenerate the transformed layout variants and their LVS fixtures:
    poetry run python -m tests.rcx25.sky130_bipolar_test
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import *
from unittest import mock

import klayout.db as kdb
import pytest

from kpex.klayout.lvsdb_extractor import KLayoutExtractionContext
from kpex.klayout.shapes_pb2_converter import ShapesConverter
from kpex.netlist.spice_reader import SpiceReader
from kpex.netlist.spice_netlist import SpiceSubcircuit
from kpex.rcx25.pex_mode import PEXMode
from kpex.tech_info import TechInfo
from kpex.pdk_config import PDK
from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.ngspice import ngspice_operating_point, requires_ngspice
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction, effective_resistance, netlist_path_of

PDK_CONFIG = PDKTestConfig(PDKName.SKY130A)
MODELS = ('npn_05v5_W1p00L1p00', 'npn_05v5_W1p00L2p00', 'npn_11v0_W1p00L1p00',
          'pnp_05v5_W0p68L0p68', 'pnp_05v5_W3p40L3p40')
VARIANTS = ('sky130_npn_11v0_rotated', 'sky130_npn_11v0_mirrored_with_poly_contact')
CELLS = tuple('sky130_' + model for model in MODELS) + VARIANTS
TERMINAL_LAYERS = dict(zip(MODELS, ('npn_5v0_1x1', 'npn_5v0_1x2', 'npn_11v0_1x1',
                                   'pnp_5v0_0p68x0p68', 'pnp_5v0_3p4x3p4')))


def read_database(cell_name: str) -> kdb.LayoutVsSchematic:
    path = PDK_CONFIG.gds_path('bipolar_transistors', cell_name + '.gds.gz')
    database = kdb.LayoutVsSchematic()
    database.read(lvsdb_fixture_path('sky130A', path))
    return database


def extraction_context(database: kdb.LayoutVsSchematic) -> KLayoutExtractionContext:
    return KLayoutExtractionContext.prepare_extraction(
        lvsdb=database, top_cell=database.netlist().top_circuit().name,
        tech=TechInfo.from_json(PDK.SKY130A.config.tech_pb_json_path, dielectric_filter=None),
        blackbox_devices=False)


@pytest.mark.parametrize('cell_name', CELLS)
def test_bjt_lvs_preserves_model_and_all_terminal_nets(cell_name: str):
    # The custom 11 V extractor used to fail before producing any device. Rotation
    # and reflection must neither duplicate the device nor interchange B/C/E.
    database = read_database(cell_name)
    device, = database.netlist().top_circuit().each_device()
    model = 'npn_11v0_W1p00L1p00' if cell_name in VARIANTS else cell_name.removeprefix('sky130_')
    assert device.device_class().name == 'sky130_fd_pr__' + model
    expected = {'C': 'C', 'B': 'B', 'E': 'E'}
    if model.startswith('npn'):
        expected['S'] = 'sky130_gnd'
    assert {terminal.name: device.net_for_terminal(terminal.id()).expanded_name()
            for terminal in device.device_class().terminal_definitions()} == expected

    context = extraction_context(database)
    extracted, = context.devices_by_name.values()
    assert {terminal.name: [r.layer.canonical_layer_name for r in terminal.region_by_layer]
            for terminal in extracted.terminals if terminal.name in ('C', 'B', 'E')} == {
                'C': ['li1'], 'B': ['li1'], 'E': ['li1']}
    # Model-owned contacts are absent from the R/C layers, but known to the tech.
    assert 'licon_bjt_con' not in {
        layer.lvs_layer_name for merged in context.extracted_layers.values() for layer in merged.source_layers}
    assert not context.unmodeled_layers


@pytest.mark.parametrize('cell_name', CELLS)
def test_bjt_terminal_landings_preserve_every_contact_and_ring_hole(cell_name: str):
    database = read_database(cell_name)
    context = extraction_context(database)
    device, = database.netlist().top_circuit().each_device()
    extracted, = context.devices_by_name.values()
    converter = ShapesConverter(context.dbu)
    for terminal in extracted.terminals:
        if terminal.name not in ('C', 'B', 'E'):
            continue
        net = device.net_for_terminal(terminal.terminal_id)
        model = device.device_class().name.removeprefix('sky130_fd_pr__')
        source_layer = TERMINAL_LAYERS[model] + '_' + terminal.name.lower()
        source = database.shapes_of_net(net, database.layer_by_name(source_layer), True)
        metal = database.shapes_of_net(net, database.layer_by_name('li_con'), True)
        expected = source & metal
        landing, = terminal.region_by_layer
        actual = converter.klayout_region(landing.region)
        assert not expected.is_empty()
        # Several contact cuts share one continuous device terminal. Preserve all
        # its landing geometry, including the holes in collector/base rings, so
        # unrelated same-net routing inside a ring is not shorted to the terminal.
        assert (expected ^ actual).is_empty(), terminal.name


@pytest.mark.parametrize('cell_name', CELLS)
def test_bjt_contacts_are_complete_and_disjoint_from_external_contacts(cell_name: str):
    database = read_database(cell_name)
    internal = database.layer_by_name('licon_bjt_con').dup().flatten()
    external = kdb.Region()
    for name in ('licon_nsd_con', 'licon_psd_con', 'licon_poly_con', 'licon_ntap_con', 'licon_ptap_con'):
        external += database.layer_by_name(name).dup().flatten()
    original = database.layer_by_name('licon').dup().flatten()
    assert not internal.is_empty()
    assert (internal & external).is_empty()
    assert (original ^ (internal | external)).is_empty()
    # Marker boundaries can cross a cut. Never turn that cut into two resistors,
    # or discard the portion outside the marker.
    for contact in original.each_merged():
        part = kdb.Region(contact) & internal
        assert part.is_empty() or part.area() == contact.area()


def extract_netlist(cell_name: str, mode: PEXMode) -> Tuple[Path, SpiceSubcircuit]:
    extraction = RCX25Extraction(PDK_CONFIG, mode, False)
    with mock.patch('kpex.klayout.lvsdb_extractor.warning') as warnings, \
            mock.patch('kpex.kpex_cli.warning') as cli_warnings:
        cli = extraction.run_kpex('bipolar_transistors', cell_name + '.gds.gz')
    assert not [call.args[0] for call in warnings.call_args_list
                if 'leaves out these LVS layers' in call.args[0] or 'has no nodes' in call.args[0]]
    assert not [call.args[0] for call in cli_warnings.call_args_list if 'Nothing drives' in call.args[0]]
    path = Path(netlist_path_of(cli))
    circuit, = SpiceReader().read(path).subcircuits
    return path, circuit


def resistances_of(circuit: SpiceSubcircuit) -> Dict[FrozenSet[str], float]:
    conductances: Dict[FrozenSet[str], float] = {}
    for element in circuit.elements:
        if element.kind == 'R':
            assert isinstance(element.value, float)
            nodes = frozenset(element.nodes)
            conductances[nodes] = conductances.get(nodes, 0.0) + 1.0 / element.value
    return {nodes: 1.0 / value for nodes, value in conductances.items()}


@pytest.mark.parametrize('cell_name', CELLS)
@pytest.mark.parametrize('mode', [PEXMode.C, PEXMode.CC, PEXMode.R, PEXMode.RC])
def test_bjt_extraction_retains_terminal_paths_in_every_mode(cell_name: str, mode: PEXMode):
    _, circuit = extract_netlist(cell_name, mode)
    device, = [element for element in circuit.elements if element.kind == 'X']
    assert len(set(device.nodes[:3])) == 3
    if mode.need_resistance():
        resistances = resistances_of(circuit)
        assert resistances
        for port, node in zip(('C', 'B', 'E'), device.nodes):
            resistance = effective_resistance(resistances, port, node)
            assert math.isfinite(resistance) and 0 <= resistance < 100, (port, node, resistance)
            # The smallest PNP labels its emitter directly on the terminal.
            # Every other path includes external li1/met1 wiring and/or mcon.
            if not (cell_name == 'sky130_pnp_05v5_W0p68L0p68' and port == 'E'):
                assert resistance > 0, (port, node, resistance)
            for other in {'C', 'B', 'E'} - {port}:
                assert math.isinf(effective_resistance(resistances, other, node))
        if cell_name.endswith('with_poly_contact'):
            assert effective_resistance(resistances, 'P', 'L') == pytest.approx(152.0)
    else:
        assert device.nodes[:3] == ['C', 'B', 'E']


@pytest.mark.slow
@requires_ngspice
@pytest.mark.parametrize('cell_name', tuple('sky130_' + model for model in MODELS))
def test_bjt_rc_network_delivers_current_to_each_terminal(cell_name: str, tmp_path: Path):
    path, circuit = extract_netlist(cell_name, PEXMode.RC)
    device, = [element for element in circuit.elements if element.kind == 'X']
    resistances = resistances_of(circuit)
    # A separate 1 kohm load at each compact-model terminal probes the extracted
    # interconnect without relying on fitted BJT model parameters. Capacitors are
    # open at DC. The independent nodal solution predicts every source current.
    ports = 'c b e s' if len(device.nodes) == 4 else 'c b e'
    loads = (f'.subckt {device.model} {ports} params: m=1 mult=1\n'
             'Rc c 0 1000\nRb b 0 1000\nRe e 0 1000\n.ends\n')
    uut_nodes = ' '.join(port.lower() if port in ('B', 'C', 'E') else '0' for port in circuit.ports)
    values = ngspice_operating_point(
        loads + f'.include "{path}"\nXuut {uut_nodes} {circuit.name}\n'
        'Vc c 0 1\nVb b 0 1\nVe e 0 1\n', ['i(vc)', 'i(vb)', 'i(ve)'], str(tmp_path))
    for port, node in zip(('C', 'B', 'E'), device.nodes):
        expected = -1.0 / (1000.0 + effective_resistance(resistances, port, node))
        assert values[f'i(v{port.lower()})'] == pytest.approx(expected, rel=2e-6)


def generate_variants():
    for name, transform in zip(VARIANTS, (kdb.Trans.R90, kdb.Trans.M0)):
        layout = kdb.Layout()
        layout.read(PDK_CONFIG.gds_path('bipolar_transistors', 'sky130_npn_11v0_W1p00L1p00.gds.gz'))
        top = layout.top_cell()
        top.transform(kdb.Trans(transform))
        top.name = name
        if name.endswith('with_poly_contact'):
            # An unrelated real poly contact must still produce its 152 ohm cut.
            x = top.bbox().right + 1000
            contact = kdb.Box(x, 0, x + 170, 170)
            for pair in ((66, 20), (67, 20)):
                top.shapes(layout.layer(*pair)).insert(contact.enlarged(80))
            top.shapes(layout.layer(66, 44)).insert(contact)
            top.shapes(layout.layer(95, 20)).insert(contact.enlarged(100))  # npc
            for layer, label in ((66, 'P'), (67, 'L')):
                top.shapes(layout.layer(layer, 16)).insert(contact.enlarged(80))
                top.shapes(layout.layer(layer, 5)).insert(kdb.Text(label, x + 85, 85))
        path = PDK_CONFIG.gds_path('bipolar_transistors', name + '.gds.gz')
        layout.write(path)
        lvsdb_fixture_path('sky130A', path)


if __name__ == '__main__':
    generate_variants()
