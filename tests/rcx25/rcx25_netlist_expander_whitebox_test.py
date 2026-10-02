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

from klayout_pex.device_models import DeviceModels
from klayout_pex.rcx25.extraction_results import CellExtractionResults, ExtractionResults
from klayout_pex.rcx25.netlist_expander import RCX25NetlistExpander
import klayout_pex_protobuf.kpex.tech.device_models_pb2 as device_models_pb2


def device_models(*metal_capacitor_class_names: str) -> DeviceModels:
    info = device_models_pb2.DeviceModelsInfo()
    for name in metal_capacitor_class_names:
        info.device_model_mappings.add(lvs_device_class_name=name,
                                       kind=device_models_pb2.DeviceModelMapping.KIND_METAL_CAPACITOR)
    return DeviceModels(info)


def whiteboxed_device_names(netlist: kdb.Netlist, device_models: DeviceModels) -> list:
    expanded = RCX25NetlistExpander.expand(netlist, 'chip',
                                           ExtractionResults({'chip': CellExtractionResults(cell_name='chip')}),
                                           blackbox_devices=False,
                                           device_models=device_models)
    device_class_names = {dc.name for dc in netlist.each_device_class()}
    return [d.name for d in expanded.circuit_by_name('chip').each_device()
            if d.device_class().name in device_class_names]


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

        self.assertEqual(['M1'], whiteboxed_device_names(netlist, device_models('mim')))

    def test_whitebox_removes_the_metal_capacitors_whatever_their_device_class(self):
        # The devices were removed by their device class: sky130A reads VPP caps with 4 terminals as MOS4,
        # so they were kept, and counted twice (as device and as extracted geometry),
        # while the MOS capacitors are capacitor classes, so they were removed,
        # and their capacitance was lost, which the extraction doesn't have
        netlist = kdb.Netlist()
        circuit = kdb.Circuit()
        circuit.name = 'chip'
        netlist.add(circuit)
        vpp = kdb.DeviceClassMOS4Transistor()
        vpp.name = 'vpp'
        netlist.add(vpp)
        mos_cap = kdb.DeviceClassCapacitor()
        mos_cap.name = 'mos_cap'
        netlist.add(mos_cap)
        circuit.create_device(vpp, 'X1')
        circuit.create_device(mos_cap, 'C1')

        self.assertEqual(['C1'], whiteboxed_device_names(netlist, device_models('vpp')))
