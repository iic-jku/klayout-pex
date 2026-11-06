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

from pathlib import Path

import allure
import pytest

from klayout_pex.magic.magic_ext_data_structures import Device, DeviceType, Node, Port, ResNode, Resistor
from klayout_pex.magic.magic_ext_file_parser import (
    parse_magic_ext_file, parse_magic_pex_run, parse_magic_res_ext_file,
)


@allure.parent_suite('Unit Tests')
@allure.tag('MAGIC', 'Parser')
class TestMagicExtFileParser:
    def test_ports_nodes_and_substrate_preserve_names_and_signed_coordinates(self, tmp_path: Path):
        path = tmp_path / 'chip.ext'
        path.write_text(
            'timestamp 123456\n'
            'scale 1 1 1\n'
            '  port "VDD" 2 -600 800 500 1000 m1  \n'
            'port "VSS" 3 -600 -500 500 700 m2\n'
            'node "VDD" 12 34 -500 900 m1 0 0\n'
            'substrate "VSUBS" 0 56 -20 -30 pwell 0 0\n', encoding='utf-8')
        data = parse_magic_ext_file(path)
        assert data.path == path
        assert data.ports == [Port('VDD', -600, 800, 500, 1000, 'm1'),
                              Port('VSS', -600, -500, 500, 700, 'm2')]
        assert data.nodes == [Node('VDD', 12, 34, -500, 900, 'm1'),
                              Node('VSUBS', 0, 56, -20, -30, 'pwell')]
        assert data.devices == []

    @pytest.mark.parametrize('device_type', [DeviceType.MOSFET, DeviceType.BJT, DeviceType.DEVRES])
    def test_device_records_preserve_type_model_and_bounds(self, tmp_path: Path, device_type: DeviceType):
        path = tmp_path / 'device.ext'
        path.write_text(f'device {device_type.value} test_model -100 -200 300 400 0 0\n', encoding='utf-8')
        data = parse_magic_ext_file(path)
        assert data.devices == [Device(device_type, 'test_model', -100, -200, 300, 400)]
        assert data.ports == []
        assert data.nodes == []

    def test_unknown_device_types_are_rejected(self, tmp_path: Path):
        path = tmp_path / 'device.ext'
        path.write_text('device unsupported test_model 0 0 10 10 0 0\n', encoding='utf-8')
        with pytest.raises(ValueError, match='unsupported'):
            parse_magic_ext_file(path)

    def test_resistance_records_preserve_dotted_names_and_values(self, tmp_path: Path):
        path = tmp_path / 'chip.res.ext'
        path.write_text(
            'timestamp 123456\n'
            'rnode "wire.n1" 0 -12 -100 200 0\n'
            'rnode "wire.n1" 0 15 300 -400 0\n'
            'rnode "wire.n2" 0 0 500 600 0\n'
            'resist "wire.n1" "wire.n2" 12.75\n'
            'resist "wire.n2" "wire.n1" 0.125\n', encoding='utf-8')
        data = parse_magic_res_ext_file(path)
        assert data.path == path
        assert data.rnodes == [ResNode('wire.n1', 0, -12, -100, 200),
                               ResNode('wire.n1', 0, 15, 300, -400),
                               ResNode('wire.n2', 0, 0, 500, 600)]
        assert data.resistors == [Resistor('wire.n1', 'wire.n2', 12.75),
                                  Resistor('wire.n2', 'wire.n1', 0.125)]
        assert data.rnodes_by_name('wire.n1') == data.rnodes[:2]
        assert data.rnodes_by_name('missing') == []

    def test_run_pairs_main_and_resistance_files_by_cell_name(self, tmp_path: Path):
        (tmp_path / 'chip.v1.ext').write_text('port "A" 1 0 0 10 10 m1\n', encoding='utf-8')
        (tmp_path / 'chip.v1.res.ext').write_text('resist "A" "B" 2.5\n', encoding='utf-8')
        (tmp_path / 'other.ext').write_text('port "B" 1 20 20 30 30 m2\n', encoding='utf-8')
        (tmp_path / 'orphan.res.ext').write_text('resist "C" "D" 99.0\n', encoding='utf-8')
        (tmp_path / 'notes.txt').write_text('ignored', encoding='utf-8')
        run = parse_magic_pex_run(tmp_path)
        assert run.run_dir == tmp_path
        assert set(run.cells) == {'chip.v1', 'other'}
        assert run.cells['chip.v1'].ext_data.ports == [Port('A', 0, 0, 10, 10, 'm1')]
        assert run.cells['chip.v1'].res_ext_data.resistors == [Resistor('A', 'B', 2.5)]
        assert run.cells['other'].ext_data.ports == [Port('B', 20, 20, 30, 30, 'm2')]
        assert run.cells['other'].res_ext_data is None

    @pytest.mark.parametrize('resistance_only', [False, True])
    def test_run_without_main_extraction_files_is_rejected(self, tmp_path: Path, resistance_only: bool):
        if resistance_only:
            (tmp_path / 'chip.res.ext').write_text('resist "A" "B" 1.0\n', encoding='utf-8')
        with pytest.raises(Exception, match='Could not find any'):
            parse_magic_pex_run(tmp_path)

    def test_empty_files_produce_empty_collections(self, tmp_path: Path):
        path = tmp_path / 'empty.ext'
        path.touch()
        ext = parse_magic_ext_file(path)
        res_ext = parse_magic_res_ext_file(path)
        assert (ext.ports, ext.nodes, ext.devices) == ([], [], [])
        assert (res_ext.rnodes, res_ext.resistors) == ([], [])
