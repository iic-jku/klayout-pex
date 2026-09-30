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

import google.protobuf.json_format
import klayout.db as kdb

from klayout_pex.device_models import DeviceModelError, DeviceModels
from klayout_pex.klayout.netlist_printer import NetlistHeader, NetlistPrinter
from klayout_pex.klayout.parasitic_device_classes import (
    PARASITIC_CAPACITOR_CLASS_NAME,
    PARASITIC_RESISTOR_CLASS_NAME,
)
import klayout_pex_protobuf.kpex.tech.device_models_pb2 as device_models_pb2


HEADER = NetlistHeader(kpex_version='1.2.3',
                       extraction_engine='KPEX/2.5D',
                       tech='ihp_sg13g2',
                       date=datetime(2026, 9, 30, 18, 15, 1))


def device_model_mapping(**kwargs) -> device_models_pb2.DeviceModelMapping:
    return google.protobuf.json_format.ParseDict(kwargs, device_models_pb2.DeviceModelMapping())


# as the IHP RF MOS: a device class only LVS knows, written as the base MOS subcircuit
RFNMOS = device_model_mapping(lvs_device_class_name='rfnmos',
                              spice_prefix='X',
                              model_name='sg13_lv_nmos',
                              terminal_names=['D', 'G', 'S', 'B'],
                              parameters=[{'name': 'w', 'lvs_parameter_name': 'W', 'lvs_parameter_factor': 1e-6},
                                          {'name': 'l', 'lvs_parameter_name': 'L', 'lvs_parameter_factor': 1e-6},
                                          {'name': 'rfmode', 'constant': 1}])


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


def lvs_netlist() -> kdb.Netlist:
    """
    An LVS netlist with a single rfnmos, expanded by parasitics, as KPEX does
    """
    netlist = netlist_with_parasitics()
    circuit = netlist.circuit_by_name('TOP')

    mos = kdb.DeviceClassMOS4Transistor()
    mos.name = 'rfnmos'
    netlist.add(mos)

    # NOTE: a device class without devices
    unused = kdb.DeviceClassResistor()
    unused.name = 'rppd'
    netlist.add(unused)

    d = circuit.create_device(mos, 'M1')
    for t, net_name in (('S', 'source'), ('G', 'gate'), ('D', 'drain'), ('B', 'bulk')):
        d.connect_terminal(t, circuit.create_net(net_name))
    d.set_parameter('W', 1.0)
    d.set_parameter('L', 0.72)

    return netlist


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "SPICE")
class Test(unittest.TestCase):
    @staticmethod
    def printer(*device_model_mappings: device_models_pb2.DeviceModelMapping) -> NetlistPrinter:
        device_models = device_models_pb2.DeviceModelsInfo(device_model_mappings=device_model_mappings)
        return NetlistPrinter(header=HEADER,
                              device_models=DeviceModels(device_models))

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

    def test_lvs_device_is_written_with_its_device_model_mapping(self):
        self.assertEqual([
            'Cext_1 a b 1f',
            'Rext_1 a b 12.5',
            'XM1 drain gate source bulk sg13_lv_nmos w=1e-06 l=7.2e-07 rfmode=1',
        ], self.device_lines(self.printer(RFNMOS), lvs_netlist()))

    def test_lvs_device_without_device_model_mapping_is_an_error(self):
        # NOTE: the parasitics KPEX added need no device model mapping
        with self.assertRaises(DeviceModelError) as ctx:
            self.device_lines(self.printer(), lvs_netlist())
        self.assertEqual("The device model mappings of the tech info are missing or invalid "
                         "for these LVS device classes:\n"
                         "  - rfnmos (1 devices): no mapping",
                         str(ctx.exception))
