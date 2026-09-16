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

import os
from pathlib import Path
import tempfile
from typing import *
import unittest

import allure
import klayout.db as kdb
import klayout.rdb as rdb

from klayout_pex.magic.magic_ext_file_parser import parse_magic_pex_run
from klayout_pex.magic.magic_log_analyzer import MagicLogAnalyzer

CELL = 'r_wire_voltage_divider_li1'

HEADER = """timestamp 0
version 8.3
tech sky130A
style ngspice()
scale 1000 1 500000
port "B" 1 1970 -15 2000 15 li
port "A" 2 0 -15 30 15 li
port "C" 3 985 185 1015 215 li
"""

# MAGIC writes the node's resistance and capacitance before its position, and
# the capacitance is not an integer.
NODE = 'node "B" 939 968.643 1970 -15 li 0 0 0 0\n'

# MAGIC places the substrate node at its own infinity marker, 2^30 - 7. Scaled
# to DBU that is far outside the 32 bit range of a kdb.Box coordinate.
SUBSTRATE = 'substrate "VSUBS" 0 0 -1073741817 -1073741817 space 0 0 0 0\n'


@allure.parent_suite('Unit Tests')
@allure.tag('MAGIC', 'Log Analyzer')
class Test(unittest.TestCase):
    @staticmethod
    def analyze(ext_file_content: str) -> rdb.ReportDatabase:
        with tempfile.TemporaryDirectory() as run_dir:
            with open(os.path.join(run_dir, f"{CELL}.ext"), 'w') as f:
                f.write(ext_file_content)
            report = rdb.ReportDatabase('')
            MagicLogAnalyzer(magic_pex_run=parse_magic_pex_run(Path(run_dir)),
                             report=report,
                             dbu=0.001).analyze()
            return report

    @staticmethod
    def items_by_category_path(report: rdb.ReportDatabase) -> List[Tuple[str, Any]]:
        """Every reported item, paired with the path of its category."""
        path_by_id: Dict[int, str] = {}

        def collect(categories: Any, prefix: str):
            for category in categories:
                path = f"{prefix}/{category.name()}"
                path_by_id[category.rdb_id()] = path
                collect(category.each_sub_category(), path)

        collect(report.each_category(), '')
        return [(path_by_id[item.category_id()], item) for item in report.each_item()]

    @staticmethod
    def categories_with_items(report: rdb.ReportDatabase) -> Dict[str, int]:
        """The item count per category, keyed on the category's path."""
        counts: Dict[str, int] = {}
        for path, _ in Test.items_by_category_path(report):
            counts[path] = counts.get(path, 0) + 1
        return counts

    @staticmethod
    def item_boxes(report: rdb.ReportDatabase) -> Dict[str, List[kdb.DBox]]:
        """The bounding box of every reported shape, keyed on its category."""
        boxes: Dict[str, List[kdb.DBox]] = {}
        for path, item in Test.items_by_category_path(report):
            for value in item.each_value():
                boxes.setdefault(path, []).append(value.polygon().bbox())
        return boxes

    def test_ports_are_reported(self):
        report = self.analyze(HEADER)
        assert self.categories_with_items(report) == {
            '/MAGIC Extraction/Ports/A (li)': 1,
            '/MAGIC Extraction/Ports/B (li)': 1,
            '/MAGIC Extraction/Ports/C (li)': 1,
        }

    def test_node_capacitance_may_be_fractional(self):
        report = self.analyze(HEADER + NODE)
        assert self.categories_with_items(report).get('/MAGIC Extraction/Nodes/B (li)') == 1

    def test_substrate_node_at_magic_infinity_is_clamped_into_the_cell(self):
        # The marker position describes no geometry and cannot become a box of
        # its own, but the node is still worth reporting — at the closest point
        # of what the cell does place.
        report = self.analyze(HEADER + NODE + SUBSTRATE)
        assert self.categories_with_items(report) == {
            '/MAGIC Extraction/Ports/A (li)': 1,
            '/MAGIC Extraction/Ports/B (li)': 1,
            '/MAGIC Extraction/Ports/C (li)': 1,
            '/MAGIC Extraction/Nodes/B (li)': 1,
            '/MAGIC Extraction/Nodes/VSUBS (space)': 1,
        }

        boxes = self.item_boxes(report)
        substrate = boxes.pop('/MAGIC Extraction/Nodes/VSUBS (space)')
        cell_box = kdb.DBox()
        for placed in boxes.values():
            for box in placed:
                cell_box += box
        assert cell_box.contains(substrate[0].p1)
