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

from typing import *
import unittest

import allure
import klayout.rdb as rdb

from klayout_pex.rcx25.extraction_reporter import ExtractionReporter
import klayout_pex_protobuf.kpex.klayout.r_extractor_tech_pb2 as r_extractor_tech_pb2


def category_names(categories: Iterable[rdb.RdbCategory]) -> List[str]:
    """
    :return: the names of the categories and of their subcategories, at all depths
    """
    return [name for c in categories for name in [c.name(), *category_names(c.each_sub_category())]]


@allure.parent_suite("Unit Tests")
@allure.tag("PEX", "2.5D", "Report")
class Test(unittest.TestCase):
    def test_r_extractor_tech_names_the_units_of_its_resistances(self):
        # NOTE: the sheet resistance of a conductor, the area resistance of a via (resistance of a cut times its area)
        tech = r_extractor_tech_pb2.RExtractorTech()
        conductor = tech.conductors.add(resistance=0.125)
        conductor.layer.id = 1
        conductor.layer.canonical_layer_name = 'met1'
        conductor.layer.lvs_layer_name = 'met1_con'
        via = tech.vias.add(resistance=0.18)
        via.layer.id = 2
        via.layer.canonical_layer_name = 'via'
        via.layer.lvs_layer_name = 'via_con'
        via.bottom_conductor.id = 1
        via.top_conductor.id = 1
        reporter = ExtractionReporter(cell_name='test', dbu=0.001, report_caps=False)
        reporter.output_rex_tech(tech)
        names = category_names(reporter.report.each_category())
        self.assertIn('1: met1 (LVS met1_con), 0.125 Ω/□', names)
        self.assertIn('2: via (LVS via_con, met1↔︎met1), 0.18 Ω·µm²', names)
