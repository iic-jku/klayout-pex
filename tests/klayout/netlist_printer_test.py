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
from klayout_pex.klayout.parasitic_device_classes import (
    PARASITIC_CAPACITOR_CLASS_NAME,
    PARASITIC_RESISTOR_CLASS_NAME,
)


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


def netlist_with_parasitics() -> kdb.Netlist:
    """
    A netlist with the parasitics KPEX adds
    """
    netlist = empty_netlist()
    circuit = netlist.circuit_by_name('TOP')
    a = circuit.create_net('a')
    b = circuit.create_net('b')

    cap = kdb.DeviceClassCapacitor()
    cap.name = PARASITIC_CAPACITOR_CLASS_NAME
    netlist.add(cap)
    c = circuit.create_device(cap, 'ext_1')
    c.connect_terminal('A', a)
    c.connect_terminal('B', b)
    c.set_parameter('C', 1e-15)

    res = kdb.DeviceClassResistor()
    res.name = PARASITIC_RESISTOR_CLASS_NAME
    netlist.add(res)
    r = circuit.create_device(res, 'ext_1')
    r.connect_terminal('A', a)
    r.connect_terminal('B', b)
    r.set_parameter('R', 12.5)

    return netlist


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "SPICE")
class Test(unittest.TestCase):
    @staticmethod
    def printer() -> NetlistPrinter:
        return NetlistPrinter(header=HEADER)

    @staticmethod
    def lines(printer: NetlistPrinter, netlist: kdb.Netlist) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, 'netlist.cir')
            printer.write(netlist, path)
            with open(path) as f:
                return [l.strip() for l in f if l.strip()]

    @classmethod
    def device_lines(cls, printer: NetlistPrinter, netlist: kdb.Netlist) -> list[str]:
        return [l for l in cls.lines(printer, netlist) if l[0] not in '*.']

    def test_header_is_written_as_comments(self):
        self.assertEqual([
            '*********************************************************',
            '*** NGSPICE file created by KLayout-PEX 1.2.3',
            '*** -----------------------------------------------------',
            '***     Extraction Engine: KPEX/2.5D',
            '***     Technology: ihp_sg13g2',
            '***     Date: 2026-09-30 18:15:01',
            '*********************************************************',
        ], self.lines(self.printer(), empty_netlist())[:7])

    def test_parasitics_are_written_without_a_model(self):
        self.assertEqual([
            'Cext_1 a b 1f',
            'Rext_1 a b 12.5',
        ], self.device_lines(self.printer(), netlist_with_parasitics()))
