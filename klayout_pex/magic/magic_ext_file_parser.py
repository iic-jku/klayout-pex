#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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

from typing import *
from pathlib import Path
import re

from .magic_ext_data_structures import (
    MagicPEXRun,
    CellName,
    CellExtData,
    ExtData,
    ResExtData,
    Port,
    Device,
    DeviceType,
    Node,
    ResNode,
    Resistor
)


def parse_magic_pex_run(run_dir: Path) -> MagicPEXRun:
    # search for <cell>.ext files (C related)
    # search for <cell>.res.ext files (R related)
    # ext_files = [f.resolve() for f in self.magic_log_dir_path.glob('*.ext')]
    ext_files = run_dir.glob('*.ext')

    main_paths_by_cell_name: Dict[CellName, Path] = dict()
    res_paths_by_cell_name: Dict[CellName, Path] = dict()

    regex = r'(?P<cell>.*?)(?P<res>\.res)?\.ext'
    for ef in ext_files:
        m = re.match(regex, ef.name)
        if not m:
            continue

        cell = m.group('cell')
        res = m.group('res')

        if res:
            res_paths_by_cell_name[cell] = ef
        else:
            main_paths_by_cell_name[cell] = ef

    if not main_paths_by_cell_name:
        raise Exception(f"Could not find any *.ext files to analyze in {run_dir}")

    cells: Dict[CellName, CellExtData] = {}
    for cell, ext_path in main_paths_by_cell_name.items():
        ext_data = parse_magic_ext_file(ext_path)
        res_ext_path = res_paths_by_cell_name.get(cell, None)
        res_ext_data = None if res_ext_path is None else parse_magic_res_ext_file(res_ext_path)
        cells[cell] = CellExtData(ext_data=ext_data, res_ext_data=res_ext_data)

    return MagicPEXRun(
        run_dir=run_dir,
        cells=cells
    )


def parse_magic_ext_file(path: Path) -> ExtData:
    ports: List[Port] = []
    nodes: List[Node] = []
    devices: List[Device] = []

    with open(path, 'r') as f:
        for line in f.readlines():
            # port "VDD" 2 -600 800 500 1000 m1
            # port "VSS" 3 -600 500 500 700 m1
            m = re.match(
                r'^port "(?P<net>\w+)" (?P<nr>\d+) (?P<x_bot>-?\d+) (?P<y_bot>-?\d+) (?P<x_top>-?\d+) (?P<y_top>-?\d+) (?P<layer>\w+)$',
                line.strip())
            if m:
                ports.append(Port(net=m.group('net'),
                                  x_bot=int(m.group('x_bot')),
                                  y_bot=int(m.group('y_bot')),
                                  x_top=int(m.group('x_top')),
                                  y_top=int(m.group('y_top')),
                                  layer=m.group('layer')))

            m = re.match(
                r'^(node|substrate) "(?P<net>\w+)" (?P<int_r>\d+) (?P<fin_c>\d+) (?P<x_bot>-?\d+) (?P<y_bot>-?\d+) (?P<layer>\w+) .*$',
                line.strip())
            if m:
                nodes.append(Node(net=m.group('net'),
                                  int_r=int(m.group('int_r')),
                                  fin_c=int(m.group('fin_c')),
                                  x_bot=int(m.group('x_bot')),
                                  y_bot=int(m.group('y_bot')),
                                  layer=m.group('layer')))

            m = re.match(
                r'^device (?P<type>\w+) (?P<model>\w+) (?P<x_bot>-?\d+) (?P<y_bot>-?\d+) (?P<x_top>-?\d+) (?P<y_top>-?\d+) .*$',
                line.strip())
            if m:
                t = m.group('type')
                device_type = DeviceType(t)
                devices.append(Device(device_type=device_type,
                                      model=m.group('model'),
                                      x_bot=int(m.group('x_bot')),
                                      y_bot=int(m.group('y_bot')),
                                      x_top=int(m.group('x_top')),
                                      y_top=int(m.group('y_top'))))
    return ExtData(path=path, ports=ports, nodes=nodes, devices=devices)


def parse_magic_res_ext_file(path: Path) -> ResExtData:
    rnodes = []
    resistors = []

    with open(path, 'r') as f:
        for line in f.readlines():
            m = re.match(
                r'^rnode "(?P<name>[\w\\.]+)" (?P<int_r>-?\d+) (?P<fin_c>-?\d+) (?P<x_bot>-?\d+) (?P<y_bot>-?\d+) 0$',
                line.strip())
            if m:
                rnodes.append(ResNode(name=m.group('name'),
                                      int_r=int(m.group('int_r')),  # NOTE: R is always 0!
                                      fin_c=int(m.group('fin_c')),
                                      x_bot=int(m.group('x_bot')),
                                      y_bot=int(m.group('y_bot'))))

            m = re.match(
                r'^resist "(?P<node1>[\w\\.]+)" "(?P<node2>[\w\\.]+)" (?P<value>-?[\d\\.]+)$',
                line.strip())
            if m:
                resistors.append(Resistor(node1=m.group('node1'),
                                          node2=m.group('node2'),
                                          value_ohm=float(m.group('value'))))

    return ResExtData(path=path, rnodes=rnodes, resistors=resistors)
