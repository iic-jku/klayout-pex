#! /usr/bin/env python3
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

import argparse
import os
from pathlib import Path
import re
import sys
from typing import *

from rich_argparse import RichHelpFormatter

import klayout.db as kdb
import klayout.rdb as rdb

from klayout_pex.magic.magic_ext_file_parser import parse_magic_pex_run
from klayout_pex.magic.magic_ext_data_structures import MagicPEXRun, CellExtData

PROGRAM_NAME = "magic_log_analyzer"


class MagicLogAnalyzer:
    def __init__(self,
                 magic_pex_run: MagicPEXRun,
                 report: rdb.ReportDatabase,
                 dbu: float):
        self.magic_pex_run = magic_pex_run
        self.report = report
        self.magic_category = self.report.create_category('MAGIC Extraction')
        self.dbu = dbu

    def analyze(self):
        for cell, cell_data in self.magic_pex_run.cells.items():
            self.analyze_cell(cell=cell, cell_data=cell_data)

    def analyze_cell(self,
                     cell: str,
                     cell_data: CellExtData):
        rdb_cell = self.report.create_cell(name=cell)
        ports_cat = self.report.create_category(parent=self.magic_category, name='Ports')
        nodes_cat = self.report.create_category(parent=self.magic_category, name='Nodes')
        devices_cat = self.report.create_category(parent=self.magic_category, name='Devices')
        rnodes_cat = self.report.create_category(parent=self.magic_category, name='Resistor Nodes')
        resistors_cat = self.report.create_category(parent=self.magic_category, name='Resistors')

        dbu_to_um = 200.0

        def box_for_point_dbu(x: float, y: float) -> kdb.Box:
            return kdb.Box(x, y, x + 20, y + 20)

        for p in cell_data.ext_data.ports:
            port_cat = self.report.create_category(parent=ports_cat, name=f"{p.net} ({p.layer})")
            shapes = kdb.Shapes()
            shapes.insert(kdb.Box(p.x_bot / dbu_to_um / self.dbu,
                                  p.y_bot / dbu_to_um / self.dbu,
                                  p.x_top / dbu_to_um / self.dbu,
                                  p.y_top / dbu_to_um / self.dbu))
            self.report.create_items(cell_id=rdb_cell.rdb_id(), category_id=port_cat.rdb_id(),
                                     trans=kdb.CplxTrans(mag=self.dbu), shapes=shapes)

        for n in cell_data.ext_data.nodes:
            node_cat = self.report.create_category(parent=nodes_cat, name=f"{n.net} ({n.layer})")
            shapes = kdb.Shapes()
            shapes.insert(box_for_point_dbu(n.x_bot / dbu_to_um / self.dbu,
                                            n.y_bot / dbu_to_um / self.dbu))
            self.report.create_items(cell_id=rdb_cell.rdb_id(), category_id=node_cat.rdb_id(),
                                     trans=kdb.CplxTrans(mag=self.dbu), shapes=shapes)

        for d in cell_data.ext_data.devices:
            device_cat = self.report.create_category(parent=devices_cat,
                                                     name=f"Type={d.device_type} Model={d.model}")
            shapes = kdb.Shapes()
            shapes.insert(kdb.Box(d.x_bot / dbu_to_um / self.dbu,
                                  d.y_bot / dbu_to_um / self.dbu,
                                  d.x_top / dbu_to_um / self.dbu,
                                  d.y_top / dbu_to_um / self.dbu))
            self.report.create_items(cell_id=rdb_cell.rdb_id(), category_id=device_cat.rdb_id(),
                                     trans=kdb.CplxTrans(mag=self.dbu), shapes=shapes)

        if cell_data.res_ext_data is not None:
            for n in cell_data.res_ext_data.rnodes:
                rnode_cat = self.report.create_category(parent=rnodes_cat,
                                                        name=n.name)
                shapes = kdb.Shapes()
                shapes.insert(box_for_point_dbu(n.x_bot / dbu_to_um / self.dbu,
                                                n.y_bot / dbu_to_um / self.dbu))
                self.report.create_items(cell_id=rdb_cell.rdb_id(), category_id=rnode_cat.rdb_id(),
                                         trans=kdb.CplxTrans(mag=self.dbu), shapes=shapes)

            for idx, r in enumerate(cell_data.res_ext_data.resistors):
                res_cat = self.report.create_category(parent=resistors_cat,
                                                      name=f"#{idx} {r.node1}↔︎{r.node2} = {r.value_ohm} Ω")
                shapes = kdb.Shapes()
                for n in cell_data.res_ext_data.rnodes_by_name(r.node1) + \
                         cell_data.res_ext_data.rnodes_by_name(r.node2):
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

    magic_pex_run = parse_magic_pex_run(Path(args.magic_log_dir_path))

    c = MagicLogAnalyzer(magic_pex_run=magic_pex_run,
                         report=report,
                         dbu=1e-3)
    c.analyze()
    report.save(args.output_rdb_path)


if __name__ == "__main__":
    main()
