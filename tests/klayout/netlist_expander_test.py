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

import allure
import os
import tempfile
import unittest

import klayout.db as kdb

from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.klayout.netlist_expander import NetlistExpander
from klayout_pex.log import (
    debug,
)
from klayout_pex.common.capacitance_matrix import CapacitanceMatrix
from klayout_pex.tech_info import TechInfo


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "Netlist Expansion")
class Test(unittest.TestCase):
    @property
    def klayout_testdata_dir(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'testdata', 'fastercap'))

    @property
    def tech_info_json_path(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'klayout_pex_protobuf', 'sky130A_tech.pb.json'))

    def test_netlist_expansion(self):
        exp = NetlistExpander()

        cell_name = 'nmos_diode2'

        lvsdb = kdb.LayoutVsSchematic()
        lvsdb_path = os.path.join(self.klayout_testdata_dir, f"{cell_name}.lvsdb.gz")
        lvsdb.read(lvsdb_path)

        csv_path = os.path.join(self.klayout_testdata_dir, f"{cell_name}_FasterCap_Result_Matrix.csv")

        cap_matrix = CapacitanceMatrix.parse_csv(csv_path, separator=';')

        tech = TechInfo.from_json(self.tech_info_json_path,
                                  dielectric_filter=None)

        pex_context = KLayoutExtractionContext.prepare_extraction(top_cell=cell_name,
                                                                  lvsdb=lvsdb,
                                                                  tech=tech,
                                                                  blackbox_devices=False)
        expanded_netlist = exp.expand(extracted_netlist=pex_context.lvsdb.netlist(),
                                      top_cell_name=pex_context.annotated_top_cell.name,
                                      cap_matrix=cap_matrix,
                                      blackbox_devices=False)
        out_path = tempfile.mktemp(prefix=f"{cell_name}_expanded_netlist_", suffix=".cir")
        spice_writer = kdb.NetlistSpiceWriter()
        expanded_netlist.write(out_path, spice_writer)
        debug(f"Wrote expanded netlist to: {out_path}")

        allure.attach.file(csv_path, attachment_type=allure.attachment_type.CSV)
        allure.attach.file(out_path, attachment_type=allure.attachment_type.TEXT)
