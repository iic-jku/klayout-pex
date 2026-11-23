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

"""Preservation and resistance of disjoint IHP bipolar emitter terminals."""

from __future__ import annotations

from pathlib import Path
from typing import *

import klayout.db as kdb
import numpy as np
import pytest

from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.klayout.shapes_pb2_converter import ShapesConverter
from klayout_pex.pdk_config import PDK
from klayout_pex.rcx25.extraction_results import DeviceTerminalKey
from klayout_pex.rcx25.pex_mode import PEXMode
from klayout_pex.tech_info import TechInfo
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.common.vacask import vacask_port_admittance, requires_vacask
from tests.common.xyce import xyce_port_admittance, requires_xyce
from tests.rcx25.rcx25_test_helpers import RCX25Extraction, effective_resistance


CELL = 'bjt_npn13g2_nx4_npn13g2l_npn13g2v_pnpmpa'
PDK_CONFIG = PDKTestConfig(PDKName.IHP_SG13G2)


@pytest.fixture(scope='module')
def database() -> kdb.LayoutVsSchematic:
    return RCX25Extraction(PDK_CONFIG, PEXMode.R, False).read_lvsdb('test_patterns', CELL + '.gds.gz')


@pytest.mark.parametrize('model, count', [('npn13G2', 4), ('npn13G2l', 1), ('npn13G2v', 1)])
@pytest.mark.parametrize('roundtrip', [False, True])
def test_bjt_emitter_footprints_survive_serialization(
        database: kdb.LayoutVsSchematic, tmp_path: Path, model: str, count: int, roundtrip: bool):
    # Single-emitter controls passed before #364. The Nx=4 device must retain
    # every disjoint footprint, including after another LVSDB write/read cycle.
    if roundtrip:
        path = tmp_path / 'roundtrip.lvsdb.gz'
        database.write(str(path))
        database = kdb.LayoutVsSchematic()
        database.read(str(path))
    device, = [d for d in database.netlist().top_circuit().each_device() if d.device_class().name == model]
    terminal_id = device.device_class().terminal_id('E')
    emitter_net = device.net_for_terminal(terminal_id)
    source = database.shapes_of_net(emitter_net, database.layer_by_name(model + '_e_pin'), True).merged()
    assert source.count() == count
    context = KLayoutExtractionContext.prepare_extraction(
        lvsdb=database, top_cell=CELL,
        tech=TechInfo.from_json(PDK.IHP_SG13G2.config.tech_pb_json_path, dielectric_filter=None),
        blackbox_devices=False)
    extracted, = [d for d in context.devices_by_name.values() if d.device_class_name == model]
    emitter, = [t for t in extracted.terminals if t.name == 'E']
    landing, = emitter.region_by_layer
    assert landing.layer.canonical_layer_name == 'Metal1'
    actual = ShapesConverter(context.dbu).klayout_region(landing.region).merged()
    assert actual.count() == count
    assert (source ^ actual).is_empty()


def emitter_network(mode: PEXMode) -> Tuple[Dict[FrozenSet[str], float], str, List[str]]:
    extraction = RCX25Extraction(PDK_CONFIG, mode, False)
    database = extraction.read_lvsdb('test_patterns', CELL + '.gds.gz')
    device, = [d for d in database.netlist().top_circuit().each_device() if d.device_class().name == 'npn13G2']
    emitter_id = device.device_class().terminal_id('E')
    net_name = device.net_for_terminal(emitter_id).expanded_name()
    results, _ = extraction.run_rcx25d_single_cell('test_patterns', CELL + '.gds.gz')
    summary = results.summarize()
    emitter = summary.device_terminal_nodes[DeviceTerminalKey(device.id(), emitter_id)]
    resistances = {frozenset((key.net1, key.net2)): value for key, value in summary.resistances.items()}
    network, = [n for n in results.r_extraction_result.networks if n.net_name == net_name]
    nodes = {node for pair in resistances for node in pair}
    bus = sorted({n.net_name for n in network.nodes if n.layer_name == 'Metal2'} & nodes)
    assert len(bus) >= 4
    return resistances, emitter, bus


def expected_emitter_resistance() -> float:
    # Equipotential Metal2 isolates the four identical Metal1/Via1 ladders.
    # Each finger has four landing positions, each with two 9-ohm vias.
    # At 0.11 ohm/square, 0.41-um centre spacing and 0.7-um wire width give
    # the inter-landing segments. The central terminal has 0.215/0.195-um
    # branches to the neighbouring landing centres. All dimensions are from
    # the committed layout; this circuit calculation is independent of PEX.
    landing = 9.0 / 2
    segment = 0.11 * 0.41 / 0.7
    half_ladder = 1 / (1 / landing + 1 / (landing + segment))
    left = half_ladder + 0.11 * 0.215 / 0.7
    right = half_ladder + 0.11 * 0.195 / 0.7
    return 1 / (1 / left + 1 / right) / 4


@pytest.mark.parametrize('mode', [PEXMode.R, PEXMode.RC])
def test_all_four_emitters_conduct_to_metal2_in_parallel(mode: PEXMode):
    resistances, emitter, bus = emitter_network(mode)
    # The old database produced about 1.149 ohm, one finger instead of four.
    # Tying the complete bus defines the reference; it does not bypass any
    # emitter Metal1 or Via1 branch in the extraction.
    resistance = effective_resistance(resistances, emitter, bus[0], joined=bus)
    assert resistance == pytest.approx(expected_emitter_resistance(), rel=1e-6)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', [pytest.param(ngspice_port_admittance, marks=requires_ngspice, id='ngspice'),
                                     pytest.param(xyce_port_admittance, marks=requires_xyce, id='Xyce'),
                                     pytest.param(vacask_port_admittance, marks=requires_vacask, id='VACASK')])
def test_emitter_network_carries_four_parallel_currents(tmp_path: Path, simulator: Callable):
    resistances, emitter, bus = emitter_network(PEXMode.R)
    # Export the extracted emitter resistor network, with the Metal2 bus at
    # the reference potential. BJT model parameters cannot mask a missing
    # interconnect path. Stable names also avoid SPICE-specific '$' escaping.
    selected = {pair: value for pair, value in resistances.items()
                if all(node == emitter or node.startswith(emitter + '.') for node in pair)}
    nodes = sorted({node for pair in selected for node in pair})
    names = {node: f'n{index}' for index, node in enumerate(nodes)}
    names.update({node: '0' for node in bus})
    names[emitter] = 'E'
    lines = ['.subckt emitter E']
    for index, (pair, resistance) in enumerate(selected.items()):
        a, b = sorted(pair)
        if names[a] != names[b]:
            lines.append(f'R{index} {names[a]} {names[b]} {resistance:.17g}')
    lines.append('.ends emitter')
    path = tmp_path / 'emitter.spice'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    _, admittance = simulator(str(path), 'emitter', ['E'], (0, 3), str(tmp_path))
    np.testing.assert_allclose(admittance, 1 / expected_emitter_resistance(), rtol=2e-6, atol=1e-12)
