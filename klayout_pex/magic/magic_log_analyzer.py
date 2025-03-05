#! /usr/bin/env python3
#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/martinjankoehler/klayout-pex).
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

import argparse
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import re
import sys
from typing import *

import rich
from rich_argparse import RichHelpFormatter

import klayout.db as kdb
import klayout.rdb as rdb

from klayout_pex.log import (
    LogLevel,
    set_log_level,
    register_additional_handler,
    deregister_additional_handler,
    # console,
    # debug,
    info,
    warning,
    subproc,
    error,
    rule
)

from klayout_pex.magic.magic_ext_file_parser import (
    parse_magic_ext_file,
    parse_magic_res_ext_file
)


PROGRAM_NAME = "magic_log_analyzer"


class MagicLogAnalyzer:
    def __init__(self,
                 magic_log_dir_path: str,
                 report: rdb.ReportDatabase,
                 dbu: float):
        self.magic_log_dir_path = Path(magic_log_dir_path)
        self.report = report
        self.magic_category = self.report.create_category('MAGIC Extraction')
        self.dbu = dbu

    def analyze(self):
        # search for <cell>.ext files (C related)
        # search for <cell>.res.ext files (R related)
        # ext_files = [f.resolve() for f in self.magic_log_dir_path.glob('*.ext')]
        ext_files = self.magic_log_dir_path.glob('*.ext')

        CellName = str
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
            raise Exception(f"Could not find any *.ext files to analyze in {self.magic_log_dir_path}")

        for cell, ext_path in main_paths_by_cell_name.items():
            self.analyze_cell(cell=cell,
                              main_ext_path=ext_path,
                              res_ext_path=res_paths_by_cell_name.get(cell, None))

    def analyze_cell(self,
                     cell: str,
                     main_ext_path: Path,
                     res_ext_path: Optional[Path]):
        rdb_cell = self.report.create_cell(name=cell)
        ports_cat = self.report.create_category(parent=self.magic_category, name='Ports')
        nodes_cat = self.report.create_category(parent=self.magic_category, name='Nodes')
        devices_cat = self.report.create_category(parent=self.magic_category, name='Devices')
        rnodes_cat = self.report.create_category(parent=self.magic_category, name='Resistor Nodes')
        resistors_cat = self.report.create_category(parent=self.magic_category, name='Resistors')

        ext_data = parse_magic_ext_file(main_ext_path)
        res_ext_data = None if res_ext_path is None else parse_magic_res_ext_file(res_ext_path)

        dbu_to_um = 200.0

        def box_for_point_dbu(x: float, y: float) -> kdb.Box:
            return kdb.Box(x, y, x + 20, y + 20)

        for p in ext_data.ports:
            port_cat = self.report.create_category(parent=ports_cat, name=f"{p.net} ({p.layer})")
            shapes = kdb.Shapes()
            shapes.insert(kdb.Box(p.x_bot / dbu_to_um / self.dbu,
                                  p.y_bot / dbu_to_um / self.dbu,
                                  p.x_top / dbu_to_um / self.dbu,
                                  p.y_top / dbu_to_um / self.dbu))
            self.report.create_items(cell_id=rdb_cell.rdb_id(), category_id=port_cat.rdb_id(),
                                     trans=kdb.CplxTrans(mag=self.dbu), shapes=shapes)

        for n in ext_data.nodes:
            node_cat = self.report.create_category(parent=nodes_cat, name=f"{n.net} ({n.layer})")
            shapes = kdb.Shapes()
            shapes.insert(box_for_point_dbu(n.x_bot / dbu_to_um / self.dbu,
                                            n.y_bot / dbu_to_um / self.dbu))
            self.report.create_items(cell_id=rdb_cell.rdb_id(), category_id=node_cat.rdb_id(),
                                     trans=kdb.CplxTrans(mag=self.dbu), shapes=shapes)

        for d in ext_data.devices:
            device_cat = self.report.create_category(parent=devices_cat,
                                                     name=f"Type={d.device_type} Model={d.model}")
            shapes = kdb.Shapes()
            shapes.insert(kdb.Box(d.x_bot / dbu_to_um / self.dbu,
                                  d.y_bot / dbu_to_um / self.dbu,
                                  d.x_top / dbu_to_um / self.dbu,
                                  d.y_top / dbu_to_um / self.dbu))
            self.report.create_items(cell_id=rdb_cell.rdb_id(), category_id=device_cat.rdb_id(),
                                     trans=kdb.CplxTrans(mag=self.dbu), shapes=shapes)

        if res_ext_data is not None:
            for n in res_ext_data.rnodes:
                rnode_cat = self.report.create_category(parent=rnodes_cat,
                                                        name=n.name)
                shapes = kdb.Shapes()
                shapes.insert(box_for_point_dbu(n.x_bot / dbu_to_um / self.dbu,
                                                n.y_bot / dbu_to_um / self.dbu))
                self.report.create_items(cell_id=rdb_cell.rdb_id(), category_id=rnode_cat.rdb_id(),
                                         trans=kdb.CplxTrans(mag=self.dbu), shapes=shapes)

            for idx, r in enumerate(res_ext_data.resistors):
                res_cat = self.report.create_category(parent=resistors_cat,
                                                      name=f"#{idx} {r.node1}↔︎{r.node2} = {r.value_ohm} Ω")
                shapes = kdb.Shapes()
                for n in res_ext_data.rnodes_by_name(r.node1) + \
                         res_ext_data.rnodes_by_name(r.node2):
                    box = box_for_point_dbu(n.x_bot / dbu_to_um / self.dbu,
                                            n.y_bot / dbu_to_um / self.dbu)
                    shapes.insert(box)
                self.report.create_items(cell_id=rdb_cell.rdb_id(), category_id=res_cat.rdb_id(),
                                         trans=kdb.CplxTrans(mag=self.dbu), shapes=shapes)


class ArgumentValidationError(Exception):
    pass


def _parse_args(arg_list: List[str] = None) -> argparse.Namespace:
    main_parser = argparse.ArgumentParser(description=f"{PROGRAM_NAME}: "
                                                      f"Tool to create KLayout RDB for magic runs",
                                          add_help=False,
                                          formatter_class=RichHelpFormatter)

    main_parser.add_argument("--magic_log_dir", "-m",
                             dest="magic_log_dir_path", required=True,
                             help="Input magic log directory path")

    main_parser.add_argument("--out", "-o",
                             dest="output_rdb_path", default=None,
                             help="Magic log directory path (default is input directory / 'report.rdb.gz')")

    if arg_list is None:
        arg_list = sys.argv[1:]
    args = main_parser.parse_args(arg_list)

    if not os.path.isdir(args.magic_log_dir_path):
        raise ArgumentValidationError(f"Intput magic log directory does not exist at '{args.magic_log_dir_path}'")

    if args.output_rdb_path is None:
        os.path.join(args.magic_log_dir_path, 'report.rdb.gz')

    return args


def main():
    args = _parse_args()
    report = rdb.ReportDatabase('')
    c = MagicLogAnalyzer(magic_log_dir_path=args.magic_log_dir_path,
                         report=report,
                         dbu=1e-3)
    c.analyze()
    report.save(args.output_rdb_path)


if __name__ == "__main__":
    main()
