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

import google.protobuf.json_format
import klayout.db as kdb

from klayout_pex.device_models import DeviceModelError, DeviceModels
import klayout_pex_protobuf.kpex.tech.device_models_pb2 as device_models_pb2


def device_models(*mappings: dict) -> DeviceModels:
    return DeviceModels(google.protobuf.json_format.ParseDict({'device_model_mappings': list(mappings)},
                                                              device_models_pb2.DeviceModelsInfo()))


def netlist() -> kdb.Netlist:
    """
    A netlist with an nmos and a resistor, and a capacitor device class without devices
    """
    netlist = kdb.Netlist()
    circuit = kdb.Circuit()
    circuit.name = 'TOP'
    netlist.add(circuit)

    mos = kdb.DeviceClassMOS4Transistor()
    mos.name = 'nmos'
    netlist.add(mos)
    circuit.create_device(mos, 'M1')

    res = kdb.DeviceClassResistor()
    res.name = 'rppd'
    netlist.add(res)
    circuit.create_device(res, 'R1')
    circuit.create_device(res, 'R2')

    cap = kdb.DeviceClassCapacitor()
    cap.name = 'cap_cmim'
    netlist.add(cap)

    return netlist


NMOS = {'lvs_device_class_name': 'nmos', 'spice_prefix': 'X', 'terminal_names': ['D', 'G', 'S', 'B']}
RPPD = {'lvs_device_class_name': 'rppd', 'spice_prefix': 'X', 'terminal_names': ['A', 'B']}


@allure.parent_suite('Unit Tests')
@allure.tag('TechInfo', 'Device Models')
class Test(unittest.TestCase):
    def test_mapping_by_lvs_device_class_name(self):
        self.assertEqual(['nmos', 'rppd'], sorted(device_models(NMOS, RPPD).mapping_by_lvs_device_class_name))

    def test_device_classes_with_mappings_pass(self):
        # NOTE: cap_cmim has no mapping, but no devices either
        device_models(NMOS, RPPD).check_mappings(netlist())

    def test_missing_mappings_are_reported(self):
        with self.assertRaises(DeviceModelError) as ctx:
            device_models(NMOS).check_mappings(netlist())
        self.assertEqual("The device model mappings of the tech info are missing or invalid "
                         "for these LVS device classes:\n"
                         "  - rppd (2 devices): no mapping",
                         str(ctx.exception))

    def test_ignored_device_classes_need_no_mapping(self):
        device_models(NMOS).check_mappings(netlist(), ignored_device_class_names={'rppd'})

    def test_invalid_mappings_are_reported(self):
        invalid_nmos = {'lvs_device_class_name': 'nmos',
                        'terminal_names': ['D', 'G', 'S', 'X'],
                        'parameters': [{'name': 'w', 'lvs_parameter_name': 'w'},
                                       {'name': 'rfmode'}]}
        with self.assertRaises(DeviceModelError) as ctx:
            device_models(invalid_nmos, RPPD).check_mappings(netlist())
        self.assertEqual("The device model mappings of the tech info are missing or invalid "
                         "for these LVS device classes:\n"
                         "  - nmos: no SPICE prefix\n"
                         "  - nmos: no LVS terminal 'X' (terminals are S, G, D, B)\n"
                         "  - nmos: LVS terminal 'B' is missing in the terminal names\n"
                         "  - nmos: parameter 'w': no LVS parameter 'w' (parameters are L, W, AS, AD, PS, PD)\n"
                         "  - nmos: parameter 'rfmode': no value",
                         str(ctx.exception))
