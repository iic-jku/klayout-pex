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

"""User circuit names containing varactor keywords remain circuits (#587)."""

from __future__ import annotations

from pathlib import Path
from typing import List

import klayout.db as kdb
import pytest

from kpex.kpex_cli import KpexCLI
from kpex.klayout.lvs_runner import LVSRunner
from kpex.pdk_config import PDK
from tests.common.cli_runner import run_cli
from tests.common.lvsdb_fixtures import klayout_exe_path, lvsdb_fixture_path
from tests.common.pdk_test_config import PDKName, PDKTestConfig


def varactor_layout_path(kind: str) -> str:
    return PDKTestConfig(PDKName.SKY130A).gds_path(
        'varactor_hierarchy', f'sky130_cap_var_{kind}.gds.gz')


@pytest.mark.parametrize('kind', ['hvt', 'lvt'])
@pytest.mark.parametrize('mode', ['C', 'CC', 'RC'])
def test_hierarchical_varactor_extraction_retains_root_ports_and_device(
        kind: str, mode: str, tmp_path: Path):
    # The empty dummy schematic must retain the user top, whose name used to
    # be mistaken for a varactor model. Every mode must keep its three terminals.
    cell_name = f'sky130_cap_var_{kind}'
    database_path = lvsdb_fixture_path('sky130A', varactor_layout_path(kind))
    database = kdb.LayoutVsSchematic()
    database.read(database_path)
    top = database.netlist().top_circuit()
    assert top.name == cell_name
    assert list(top.each_subcircuit()) == []
    assert len(list(top.each_device())) == 1

    code, output = run_cli(KpexCLI().main, [
        'kpex', 'extract', '--pdk', 'sky130A', '--2.5D', '--mode', mode,
        '--lvsdb', database_path, '--out-dir', str(tmp_path)])
    assert code == 0, output
    netlist_path = tmp_path / f'{cell_name}__{cell_name}' / f'{cell_name}_k25d_pex_netlist.spice'
    netlist = netlist_path.read_text(encoding='utf-8')
    assert f'.SUBCKT {cell_name} B C0 C1 sky130_gnd' in netlist
    devices = [line for line in netlist.splitlines() if line.startswith('X')]
    assert len(devices) == 1, netlist
    assert devices[0].split()[4:] == [f'sky130_fd_pr__cap_var_{kind}', 'w=1', 'l=0.18']
    if mode in ('C', 'CC'):
        assert devices[0].split()[1:4] == ['C0', 'C1', 'B']
    assert any(line.startswith('Cext_') for line in netlist.splitlines()), netlist


def write_varactor_layout(kind: str, placement: str, path: Path) -> List[str]:
    layout = kdb.Layout()
    layout.read(varactor_layout_path(kind))
    top = layout.top_cell()
    ports = ['B', 'C0', 'C1']
    if placement == 'flat':
        top.flatten(True)
    elif placement == 'two_children':
        # Copy the top-level well, bulk-contact routing and pin markers too,
        # not just the child device. Each instance has its own three ports.
        instance, = list(top.each_inst())
        transform = kdb.Trans(10000, 0)
        top.insert(kdb.CellInstArray(instance.cell_index, transform))
        for layer in layout.layer_indexes():
            for shape in list(top.shapes(layer).each()):
                copied = top.shapes(layer).insert(shape)
                copied.transform(transform)
                if copied.is_text():
                    text = copied.text
                    text.string += '_2'
                    copied.text = text
        ports += ['B_2', 'C0_2', 'C1_2']
    layout.write(str(path))
    return ports


@pytest.mark.slow
@pytest.mark.parametrize('kind', ['hvt', 'lvt'])
@pytest.mark.parametrize('placement,prefix', [('flat', 'C'), ('child', 'X'), ('two_children', 'X')])
def test_varactor_model_reader_preserves_similarly_named_user_circuits(
        kind: str, placement: str, prefix: str, tmp_path: Path):
    exe_path = klayout_exe_path()
    if exe_path is None:
        pytest.skip('needs the KLayout executable (KPEX_KLAYOUT_EXE)')
    gds_path = tmp_path / 'layout.gds'
    ports = write_varactor_layout(kind, placement, gds_path)
    cell_name = f'sky130_cap_var_{kind}'
    # A canonical model name plus a suffix is still a user circuit name.
    wrapper_name = f'sky130_fd_pr__cap_var_{kind}_wrapper'
    device_count = 2 if placement == 'two_children' else 1
    schematic = [f'.subckt {cell_name} {" ".join(ports)}']
    for index in range(device_count):
        suffix = '' if index == 0 else '_2'
        schematic.append(f'X{index + 1} C0{suffix} C1{suffix} B{suffix} {wrapper_name}')
    schematic += ['.ends', f'.subckt {wrapper_name} c0 c1 b',
                  f'{prefix}1 c0 c1 b sky130_fd_pr__cap_var_{kind} W=1 L=0.18', '.ends', '.end']
    schematic_path = tmp_path / 'schematic.spice'
    schematic_path.write_text('\n'.join(schematic) + '\n', encoding='utf-8')
    database_path = tmp_path / 'layout.lvsdb.gz'
    LVSRunner.run_klayout_lvs(
        exe_path=exe_path, lvs_script=PDK.SKY130A.config.pex_lvs_script_path,
        gds_path=str(gds_path), schematic_path=str(schematic_path),
        log_path=str(tmp_path / 'lvs.log'), lvsdb_path=str(database_path),
        netlist_path=str(tmp_path / 'layout.spice'), verbose=False)
    database = kdb.LayoutVsSchematic()
    database.read(str(database_path))
    for netlist in (database.netlist(), database.reference):
        top = netlist.top_circuit()
        assert top.name.upper() == cell_name.upper()
        assert list(top.each_subcircuit()) == []
        assert sorted(pin.name().upper() for pin in top.each_pin()) == sorted(ports)
        devices = list(top.each_device())
        assert len(devices) == device_count
        terminal_nets = sorted(tuple(device.net_for_terminal(terminal).expanded_name().upper()
                                     for terminal in ('A', 'B', 'W')) for device in devices)
        expected_nets = [('C0', 'C1', 'B')]
        if device_count == 2:
            expected_nets.append(('C0_2', 'C1_2', 'B_2'))
        assert terminal_nets == expected_nets
        for device in devices:
            assert device.device_class().name.upper() == f'SKY130_FD_PR__CAP_VAR_{kind.upper()}'
            assert device.parameter('W') == pytest.approx(1.0)
            assert device.parameter('L') == pytest.approx(0.18)
