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

"""Schottky electrode ownership and external interconnect resistance."""

from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
from typing import *

import klayout.db as kdb
import numpy as np
import pytest

from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.klayout.shapes_pb2_converter import ShapesConverter
from klayout_pex.netlist.spice_reader import SpiceReader
from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist
from klayout_pex.pdk_config import PDK
from klayout_pex.rcx25.extraction_results import DeviceTerminalKey
from klayout_pex.rcx25.pex_mode import PEXMode
from klayout_pex.tech_info import TechInfo
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.common.rc_networks import port_admittance, scope_named
from tests.common.vacask import vacask_port_admittance, requires_vacask
from tests.common.xyce import xyce_port_admittance, requires_xyce
from tests.rcx25.rcx25_test_helpers import RCX25Extraction, effective_resistance, netlist_path_of


PDK_CONFIG = PDKTestConfig(PDKName.GF180MCUD)
CELLS = ('r_schottky_diode_contact', 'r_schottky_diode_routed',
         'r_schottky_diode_long', 'r_schottky_diode_pair')


def read_database(cell_name: str) -> kdb.LayoutVsSchematic:
    return RCX25Extraction(PDK_CONFIG, PEXMode.R, False).read_lvsdb('test_patterns', cell_name + '.gds.gz')


@pytest.mark.parametrize('cell_name', CELLS)
def test_schottky_preserves_every_contact_terminal(cell_name: str):
    # One cut can conceal terminal polygon loss. Two separated cuts must both
    # survive, without a bounding-box bridge across the opposite electrode.
    # A second, transformed marker must not donate contacts to its neighbour.
    database = read_database(cell_name)
    context = KLayoutExtractionContext.prepare_extraction(
        lvsdb=database, top_cell=cell_name,
        tech=TechInfo.from_json(PDK.GF180MCUD.config.tech_pb_json_path, dielectric_filter=None),
        blackbox_devices=False)
    assert not context.unmodeled_layers
    cuts = 1 if cell_name.endswith('_contact') else 2
    count = 4 if cell_name.endswith('_pair') else 2
    assert len(context.devices_by_name) == count
    observed = Counter()
    converter = ShapesConverter(context.dbu)
    source_contacts = database.layer_by_name('contact_sc_diode_con').dup().flatten()
    all_terminals = kdb.Region()
    for device in context.devices_by_name.values():
        assert device.device_class_name == 'sc_diode'
        assert {p.name: p.value for p in device.parameters} == pytest.approx({'A': 0.36, 'P': 2.72})
        ports = {t.name: t.net_name for t in device.terminals}
        assert ports in ({'A': 'A', 'C': 'C'}, {'A': 'A2', 'C': 'C2'})
        observed[ports['A']] += 1
        regions = {}
        for terminal in device.terminals:
            landing, = terminal.region_by_layer
            assert landing.layer.canonical_layer_name == 'Metal1'
            region = converter.klayout_region(landing.region).merged()
            assert region.count() == cuts
            assert (region - source_contacts).is_empty()
            regions[terminal.name] = region
            all_terminals += region
        assert (regions['A'] & regions['C']).is_empty()
    assert observed == ({'A': 2, 'A2': 2} if count == 4 else {'A': 2})
    assert (source_contacts ^ all_terminals.merged()).is_empty()
    # The compact model owns these contacts; external well/tap contacts must
    # neither duplicate them nor lose any of the remaining contact geometry.
    external = kdb.Region()
    for name in ('contact_nsd_con', 'contact_psd_con', 'contact_poly_con',
                 'contact_ntap_con', 'contact_ptap_con', 'contact_ntap_dw_con',
                 'contact_ptap_dw_con', 'contact_res_con'):
        external += database.layer_by_name(name).dup().flatten()
    original = database.layer_by_name('contact').dup().flatten()
    assert (source_contacts & external).is_empty()
    assert (original ^ (source_contacts | external)).is_empty()


@pytest.mark.parametrize('cell_name', CELLS)
@pytest.mark.parametrize('mode', [PEXMode.C, PEXMode.CC, PEXMode.R, PEXMode.RC])
def test_schottky_extracts_in_every_mode(cell_name: str, mode: PEXMode):
    extraction = RCX25Extraction(PDK_CONFIG, mode, False)
    assert extraction.device_layer_warnings('test_patterns', cell_name + '.gds.gz') == []
    rows = extraction.written_device_lines('test_patterns', cell_name + '.gds.gz')
    assert len(rows) == (4 if cell_name.endswith('_pair') else 2)
    assert all(row.startswith('D') and 'sc_diode' in row for row in rows)


def lead_resistances(cell_name: str) -> Dict[Tuple[int, str], float]:
    extraction = RCX25Extraction(PDK_CONFIG, PEXMode.R, False)
    database = read_database(cell_name)
    results, _ = extraction.run_rcx25d_single_cell('test_patterns', cell_name + '.gds.gz')
    summary = results.summarize()
    resistances = {frozenset((k.net1, k.net2)): v for k, v in summary.resistances.items()}
    leads = {}
    for device in database.netlist().top_circuit().each_device():
        for terminal in device.device_class().terminal_definitions():
            port = device.net_for_terminal(terminal.id()).expanded_name()
            node = summary.device_terminal_nodes[DeviceTerminalKey(device.id(), terminal.id())]
            resistance = effective_resistance(resistances, port, node)
            assert math.isfinite(resistance) and resistance > 0
            leads[device.id(), terminal.name] = resistance
            for other in {'A', 'C'} - {port}:
                assert math.isinf(effective_resistance(resistances, other, node))
    return leads


def test_added_lead_length_has_sheet_resistance():
    short = lead_resistances('r_schottky_diode_routed')
    long = lead_resistances('r_schottky_diode_long')
    assert short.keys() == long.keys()
    # Add exactly 10 um of uniform Metal1 to each external lead, leaving the
    # diode/contact geometry unchanged: delta R = R_sheet * delta L / width.
    # This rejects ignored/shorted routing independently of device-model Rs.
    widths = {'A': 0.62, 'C': 0.36}
    for key, value in short.items():
        assert long[key] - value == pytest.approx(0.09 * 10 / widths[key[1]], rel=1e-6)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', [pytest.param(ngspice_port_admittance, marks=requires_ngspice, id='ngspice'),
                                     pytest.param(xyce_port_admittance, marks=requires_xyce, id='Xyce'),
                                     pytest.param(vacask_port_admittance, marks=requires_vacask, id='VACASK')])
def test_schottky_rc_interconnect_preserves_loaded_terminal_response(tmp_path: Path, simulator: Callable):
    cli = RCX25Extraction(PDK_CONFIG, PEXMode.RC, False).run_kpex(
        'test_patterns', 'r_schottky_diode_routed.gds.gz')
    path = Path(netlist_path_of(cli))
    circuit, = SpiceReader().read(path).subcircuits
    diodes = {e.name: e for e in circuit.elements if e.kind == 'D'}
    assert len(diodes) == 2
    # Replace each nonlinear diode with a known 1 kohm load at exactly its
    # exported A/C nodes. This tests interconnect in all simulators without
    # attributing model-specific device physics to the resistance extractor.
    lines = []
    for line in path.read_text(encoding='utf-8').replace('\n+', ' ').splitlines():
        fields = line.split()
        if fields and fields[0] in diodes:
            device = diodes[fields[0]]
            line = f'Rload_{device.name} {device.nodes[0]} {device.nodes[1]} 1000'
        lines.append(line)
    loaded = tmp_path / 'loaded.spice'
    loaded.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    network = scope_named(SpiceRCNetlist.read(str(loaded)), circuit.name).network
    frequencies, actual = simulator(str(loaded), circuit.name, circuit.ports, (0, 6), str(tmp_path))
    expected = np.asarray([port_admittance(network, circuit.ports, f) for f in frequencies])
    np.testing.assert_allclose(actual, expected, rtol=2e-6, atol=1e-12)
