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

from __future__ import annotations

import os
import unittest
from unittest import mock

import allure
import klayout.db as kdb

from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext, LVSDBError
from klayout_pex.tech_info import TechInfo


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "LVSDB")
class Test(unittest.TestCase):
    # NOTE: the IHP LVS script replaced the extracted rfnmos by a newly created
    #       sg13_lv_nmos (RF MOS model mapping), which has no device abstract,
    #       and left the abstract of the extracted one as a second top cell
    cell_name = 'rfnmos_w1u_l0u72'

    @property
    def lvsdb_path(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'testdata', 'klayout', 'lvs',
                                             f"{self.cell_name}_broken_rfmos_model_mapping.lvsdb.gz"))

    @property
    def tech_info_json_path(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'klayout_pex_protobuf', 'ihp-sg13g2_tech.pb.json'))

    def prepare_extraction(self) -> KLayoutExtractionContext:
        lvsdb = kdb.LayoutVsSchematic()
        lvsdb.read(self.lvsdb_path)
        tech = TechInfo.from_json(self.tech_info_json_path, dielectric_filter=None)
        return KLayoutExtractionContext.prepare_extraction(top_cell=self.cell_name,
                                                           lvsdb=lvsdb,
                                                           tech=tech,
                                                           blackbox_devices=False)

    def test_leftover_top_cells_are_ignored_with_a_warning(self):
        with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning') as warning:
            pex_context = self.prepare_extraction()
        messages = [call.args[0] for call in warning.call_args_list]
        self.assertTrue(any('D$rfnmos' in m for m in messages), messages)
        self.assertFalse(pex_context.top_cell_bbox().empty())

    def test_a_device_without_layout_geometry_is_an_error(self):
        pex_context = self.prepare_extraction()
        with self.assertRaises(LVSDBError) as cm:
            pex_context.devices_by_name
        self.assertIn('$1 (sg13_lv_nmos)', str(cm.exception))
