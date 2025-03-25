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
import allure
import json
import os
import tempfile
from typing import *
import unittest

import klayout.db as kdb

from klayout_pex.log import (
    LogLevel,
    set_log_level,
)
from klayout_pex.netlistsvg.netlist_json import NetlistJSONWriter


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "Netlist SVG Diagram")
class Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        set_log_level(LogLevel.DEBUG)

    @property
    def netlistsvg_testdata_dir(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'testdata', 'netlistsvg', 'netlists'))

    def _test_netlistsvg(self, netlist_path: str, cell_name: str) -> Dict[str, Any]:
        netlist = kdb.Netlist()
        reader = kdb.NetlistSpiceReader()
        netlist.read(netlist_path, reader)

        writer = NetlistJSONWriter()

        circuit = netlist.circuit_by_name(cell_name)
        dict = writer.netlist_json_dict(netlist=netlist, top_circuit=circuit)

        out_path = tempfile.mktemp(prefix=f"{cell_name}_netlistsvg_input_file", suffix=".json")
        writer.write_json(netlist=netlist, top_circuit=circuit, output_path=out_path)

        print(f"Wrote reduced netlist to: {out_path}")
        allure.attach.file(out_path, attachment_type=allure.attachment_type.TEXT)
        return dict

    def test_netlist_reduction_1(self):
        netlist_path = os.path.join(self.netlistsvg_testdata_dir, 'r_wire_voltage_divider_li1.pex.spice')
        d = self._test_netlistsvg(netlist_path=netlist_path, cell_name='r_wire_voltage_divider_li1')
        print(json.dumps(d, indent=4))

    def test_netlist_reduction_2(self):
        netlist_path = os.path.join(self.netlistsvg_testdata_dir, 'sky130_fd_sc_hd__inv_1.pex.spice')
        d = self._test_netlistsvg(netlist_path=netlist_path, cell_name='sky130_fd_sc_hd__inv_1')
        print(json.dumps(d, indent=4))
