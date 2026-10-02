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
import unittest

import klayout.db as kdb

from klayout_pex.rcx25.extraction_results import CellExtractionResults, ExtractionResults
from klayout_pex.rcx25.netlist_expander import RCX25NetlistExpander


@allure.parent_suite("Unit Tests")
@allure.tag("RCX25", "Netlist Expansion")
class Test(unittest.TestCase):
    def test_whitebox_removes_all_capacitors(self):
        # Removing a device ended the iteration over the devices,
        # so only the first capacitor was removed, and the others were counted twice:
        # as device and as extracted geometry
        netlist = kdb.Netlist()
        circuit = kdb.Circuit()
        circuit.name = 'chip'
        netlist.add(circuit)
        mim = kdb.DeviceClassCapacitor()
        mim.name = 'mim'
        netlist.add(mim)
        nmos = kdb.DeviceClassMOS4Transistor()
        nmos.name = 'nmos'
        netlist.add(nmos)
        for name in ('C1', 'C2', 'C3'):
            circuit.create_device(mim, name)
        circuit.create_device(nmos, 'M1')

        expanded = RCX25NetlistExpander.expand(netlist, 'chip',
                                               ExtractionResults({'chip': CellExtractionResults(cell_name='chip')}),
                                               blackbox_devices=False)

        self.assertEqual(['M1'], [d.name for d in expanded.circuit_by_name('chip').each_device()
                                  if d.device_class().name in ('mim', 'nmos')])
