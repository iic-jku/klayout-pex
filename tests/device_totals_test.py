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

from __future__ import annotations

import unittest

import allure
import klayout.db as kdb

from klayout_pex.device_totals import DeviceTotalParameters
from tests.common.device_model_mappings import MIM, NMOS, NPN, device_models


def total_parameters(mapping: dict, device_class: kdb.DeviceClass) -> DeviceTotalParameters:
    mappings = device_models(mapping).mapping_by_lvs_device_class_name
    return DeviceTotalParameters.of(device_class, mappings[mapping['lvs_device_class_name']])


@allure.parent_suite("Unit Tests")
@allure.tag('TechInfo', 'Device Models')
class DeviceTotalParametersTest(unittest.TestCase):
    def test_area_and_width_of_a_mos(self):
        parameters = total_parameters(NMOS, kdb.DeviceClassMOS4Transistor())
        self.assertEqual(DeviceTotalParameters(width='W', length='L', mos=True), parameters)
        self.assertEqual(['W·L', 'W'], parameters.quantity_names)
        self.assertEqual({'W·L': 3.0, 'W': 6.0}, parameters.quantities({'W': 2.0, 'L': 0.5}, m=3))

    def test_area_of_another_device(self):
        # NOTE: e.g. of a resistor, whose width alone depends on how it is split into series segments
        parameters = total_parameters({**NMOS, 'lvs_device_class_name': 'rppd'}, kdb.DeviceClassResistor())
        self.assertEqual({'W·L': 1.0}, parameters.quantities({'W': 2.0, 'L': 0.5, 'R': 7.0}))

    def test_area_of_the_rectangle_of_an_area_and_perimeter(self):
        parameters = total_parameters(MIM, kdb.DeviceClassCapacitor())
        self.assertEqual({'A': 16.0}, parameters.quantities({'A': 8.0, 'P': 12.0}, m=2))

    def test_multiplier_of_an_lvs_parameter(self):
        # NOTE: of the LVS parameter, the device of the schematic gives m, if it doesn't give that
        parameters = total_parameters(NPN, kdb.DeviceClassBJT3Transistor())
        self.assertEqual({'NE': 2.0}, parameters.quantities({'NE': 2.0}, m=5))
        self.assertEqual({'NE': 5.0}, parameters.quantities({}, m=5))

    def test_names_of_the_lvs_parameters_in_any_case(self):
        # NOTE: e.g. the IHP resistors, whose models take w, l and m of the LVS parameters w, l and m
        mapping = {**NMOS, 'lvs_device_class_name': 'rsil',
                   'parameters': [{'name': 'w', 'lvs_parameter_name': 'w'}, {'name': 'l', 'lvs_parameter_name': 'l'},
                                  {'name': 'm', 'lvs_parameter_name': 'm'}]}
        parameters = total_parameters(mapping, kdb.DeviceClassResistor())
        self.assertEqual({'w·l': 2.0, 'm': 2.0}, parameters.quantities({'w': 1.0, 'l': 1.0, 'm': 2.0}))

    def test_quantities_without_value(self):
        parameters = total_parameters(NMOS, kdb.DeviceClassMOS4Transistor())
        self.assertEqual({'W·L': None, 'W': 2.0}, parameters.quantities({'W': 2.0}))

    def test_class_without_totals(self):
        # NOTE: e.g. a tap, or a cap of a fixed size
        parameters = total_parameters({**NMOS, 'parameters': []}, kdb.DeviceClassMOS4Transistor())
        self.assertEqual({}, parameters.quantities({'W': 2.0, 'L': 0.5}))
