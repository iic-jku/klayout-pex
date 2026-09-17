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

from klayout_pex.log import debug
from klayout_pex.magic.magic_ext_file_parser import parse_magic_pex_run
from klayout_pex.magic.magic_ext_data_structures import MagicPEXRun, CellExtData

PROGRAM_NAME = "magic_log_analyzer"

# MAGIC has no position for the substrate node and writes its own infinity,
# (1 << 30) - 7, in place of one. Scaled to database units that is far outside
# the coordinate range of a kdb.Box.
MAGIC_INFINITY = (1 << 30) - 7


def is_magic_marker(*coordinates: float) -> bool:
    return any(abs(c) >= MAGIC_INFINITY for c in coordinates)


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

        def scaled(value: float) -> float:
            return value / dbu_to_um / self.dbu

        def box_for_point_dbu(x: float, y: float) -> kdb.Box:
            return kdb.Box(x, y, x + 20, y + 20)

        # Everything the cell does place, so that a marker position can be
        # reported clamped into it rather than dropped.
        cell_box = kdb.Box()
        for p in cell_data.ext_data.ports:
            if not is_magic_marker(p.x_bot, p.y_bot, p.x_top, p.y_top):
                cell_box += kdb.Box(scaled(p.x_bot), scaled(p.y_bot),
                                    scaled(p.x_top), scaled(p.y_top))
        for n in cell_data.ext_data.nodes:
            if not is_magic_marker(n.x_bot, n.y_bot):
                cell_box += box_for_point_dbu(scaled(n.x_bot), scaled(n.y_bot))
        for d in cell_data.ext_data.devices:
            if not is_magic_marker(d.x_bot, d.y_bot, d.x_top, d.y_top):
                cell_box += kdb.Box(scaled(d.x_bot), scaled(d.y_bot),
                                    scaled(d.x_top), scaled(d.y_top))

        def clamped(x: float, y: float) -> Optional[Tuple[float, float]]:
            """
            The point in database units, or the closest one inside the cell if
            MAGIC gave a marker instead of a position. None when there is
            nothing to clamp into, which is the only case worth dropping.
            """
            if not is_magic_marker(x, y):
                return scaled(x), scaled(y)
            if cell_box.empty():
                debug(f"Cell {cell}: node at MAGIC's marker position skipped, "
                      f"the cell places no other geometry to clamp it into")
                return None
            return (min(max(scaled(x), cell_box.left), cell_box.right),
                    min(max(scaled(y), cell_box.bottom), cell_box.top))

        for p in cell_data.ext_data.ports:
            port_cat = self.report.create_category(parent=ports_cat, name=f"{p.net} ({p.layer})")
            shapes = kdb.Shapes()
            shapes.insert(kdb.Box(scaled(p.x_bot), scaled(p.y_bot),
                                  scaled(p.x_top), scaled(p.y_top)))
            self.report.create_items(cell_id=rdb_cell.rdb_id(), category_id=port_cat.rdb_id(),
                                     trans=kdb.CplxTrans(mag=self.dbu), shapes=shapes)

        for n in cell_data.ext_data.nodes:
            point = clamped(n.x_bot, n.y_bot)
            if point is None:
                continue
            node_cat = self.report.create_category(parent=nodes_cat, name=f"{n.net} ({n.layer})")
            shapes = kdb.Shapes()
            shapes.insert(box_for_point_dbu(*point))
            self.report.create_items(cell_id=rdb_cell.rdb_id(), category_id=node_cat.rdb_id(),
                                     trans=kdb.CplxTrans(mag=self.dbu), shapes=shapes)

        for d in cell_data.ext_data.devices:
            device_cat = self.report.create_category(parent=devices_cat,
                                                     name=f"Type={d.device_type} Model={d.model}")
            shapes = kdb.Shapes()
            shapes.insert(kdb.Box(scaled(d.x_bot), scaled(d.y_bot),
                                  scaled(d.x_top), scaled(d.y_top)))
            self.report.create_items(cell_id=rdb_cell.rdb_id(), category_id=device_cat.rdb_id(),
                                     trans=kdb.CplxTrans(mag=self.dbu), shapes=shapes)

        if cell_data.res_ext_data is not None:
            for n in cell_data.res_ext_data.rnodes:
                point = clamped(n.x_bot, n.y_bot)
                if point is None:
                    continue
                rnode_cat = self.report.create_category(parent=rnodes_cat,
                                                        name=n.name)
                shapes = kdb.Shapes()
                shapes.insert(box_for_point_dbu(*point))
                self.report.create_items(cell_id=rdb_cell.rdb_id(), category_id=rnode_cat.rdb_id(),
                                         trans=kdb.CplxTrans(mag=self.dbu), shapes=shapes)

            for idx, r in enumerate(cell_data.res_ext_data.resistors):
                shapes = kdb.Shapes()
                for n in cell_data.res_ext_data.rnodes_by_name(r.node1) + \
                         cell_data.res_ext_data.rnodes_by_name(r.node2):
                    point = clamped(n.x_bot, n.y_bot)
                    if point is not None:
                        shapes.insert(box_for_point_dbu(*point))
                if shapes.is_empty():
                    continue
                res_cat = self.report.create_category(parent=resistors_cat,
                                                      name=f"#{idx} {r.node1}↔︎{r.node2} = {r.value_ohm} Ω")
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
