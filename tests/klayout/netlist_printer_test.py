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
import allure
from datetime import datetime
import os
import tempfile
import unittest

import klayout.db as kdb

from klayout_pex.klayout.netlist_printer import NetlistHeader, NetlistPrinter


HEADER = NetlistHeader(kpex_version='1.2.3',
                       extraction_engine='KPEX/2.5D',
                       tech='ihp_sg13g2',
                       date=datetime(2026, 9, 30, 18, 15, 1))


def empty_netlist() -> kdb.Netlist:
    netlist = kdb.Netlist()
    circuit = kdb.Circuit()
    circuit.name = 'TOP'
    netlist.add(circuit)
    return netlist


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "SPICE")
class Test(unittest.TestCase):
    @staticmethod
    def lines(printer: NetlistPrinter, netlist: kdb.Netlist) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, 'netlist.cir')
            printer.write(netlist, path)
            with open(path) as f:
                return [l.strip() for l in f if l.strip()]

    def test_header_is_written_as_comments(self):
        self.assertEqual([
            '*********************************************************',
            '*** NGSPICE file created by KLayout-PEX 1.2.3',
            '*** -----------------------------------------------------',
            '***     Extraction Engine: KPEX/2.5D',
            '***     Technology: ihp_sg13g2',
            '***     Date: 2026-09-30 18:15:01',
            '*********************************************************',
        ], self.lines(NetlistPrinter(header=HEADER), empty_netlist())[:7])
