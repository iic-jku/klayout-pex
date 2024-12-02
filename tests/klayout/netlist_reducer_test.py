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
import os
import tempfile
import unittest

import klayout.db as kdb

from kpex.log import (
    LogLevel,
    set_log_level,
)
from kpex.klayout.netlist_reducer import NetlistReducer


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "Netlist Reduction")
class Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        set_log_level(LogLevel.DEBUG)

    @property
    def klayout_testdata_dir(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'testdata', 'klayout', 'netlists'))

    def _test_netlist_reduction(self, netlist_path: str, cell_name: str):
        netlist = kdb.Netlist()
        reader = kdb.NetlistSpiceReader()
        netlist.read(netlist_path, reader)

        reducer = NetlistReducer()
        reduced_netlist = reducer.reduce(netlist=netlist, top_cell_name=cell_name)

        out_path = tempfile.mktemp(prefix=f"{cell_name}_Reduced_Netlist_", suffix=".cir")
        spice_writer = kdb.NetlistSpiceWriter()
        reduced_netlist.write(out_path, spice_writer)
        print(f"Wrote reduced netlist to: {out_path}")
        allure.attach.file(out_path, attachment_type=allure.attachment_type.TEXT)

    def test_netlist_reduction_1(self):
        netlist_path = os.path.join(self.klayout_testdata_dir, 'nmos_diode2_Expanded_Netlist.cir')
        self._test_netlist_reduction(netlist_path=netlist_path, cell_name='nmos_diode2')

    def test_netlist_reduction_2(self):
        netlist_path = os.path.join(self.klayout_testdata_dir, 'cap_vpp_Expanded_Netlist.cir')
        self._test_netlist_reduction(netlist_path=netlist_path, cell_name='TOP')
