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
import math
import unittest

import klayout.db as kdb

from klayout_pex.device_models import DeviceModelError, DeviceModels, rectangle_sides
from klayout_pex.netlist.spice_netlist import SpiceElement
from tests.common.device_model_mappings import MIM, NMOS, NPN, RPPD, device_models


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


@allure.parent_suite('Unit Tests')
@allure.tag('TechInfo', 'Device Models')
class Test(unittest.TestCase):
    def test_mapping_by_lvs_device_class_name(self):
        self.assertEqual(['nmos', 'rppd'], sorted(device_models(NMOS, RPPD).mapping_by_lvs_device_class_name))

    def test_vacask_subcircuits_with_m_are_the_models_of_the_mappings_that_declare_m(self):
        rfnmos = {**NMOS, 'lvs_device_class_name': 'rfnmos', 'model_name': 'sg13_lv_nmos', 'vacask_declares_m': True}
        rppd = {**RPPD, 'vacask_declares_m': True}
        self.assertEqual({'sg13_lv_nmos', 'rppd'}, device_models(NMOS, rfnmos, rppd).vacask_subcircuits_with_m)

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

    def test_invalid_rectangle_sides_are_reported(self):
        rppd = {'lvs_device_class_name': 'rppd', 'spice_prefix': 'X', 'terminal_names': ['A', 'B'],
                'parameters': [{'name': 'w', 'lvs_area_perimeter_side': {'area_parameter_name': 'A',
                                                                         'perimeter_parameter_name': 'X',
                                                                         'side': 'SIDE_LONG'}},
                               {'name': 'l', 'lvs_area_perimeter_side': {'area_parameter_name': 'A',
                                                                         'perimeter_parameter_name': 'P'}}]}
        with self.assertRaises(DeviceModelError) as ctx:
            device_models(NMOS, rppd).check_mappings(netlist())
        self.assertEqual("The device model mappings of the tech info are missing or invalid "
                         "for these LVS device classes:\n"
                         "  - rppd: parameter 'w': no LVS parameter 'X' (parameters are R, L, W, A, P)\n"
                         "  - rppd: parameter 'l': no side of the rectangle",
                         str(ctx.exception))

    def test_rectangle_sides(self):
        self.assertEqual((2.0, 1.0), rectangle_sides(area=2.0, perimeter=6.0))
        self.assertEqual((3.0, 3.0), rectangle_sides(area=9.0, perimeter=12.0))
        self.assertEqual((5.0, 0.0), rectangle_sides(area=0.0, perimeter=10.0))

    def test_rectangle_sides_of_a_long_narrow_rectangle_are_exact(self):
        long_side, short_side = rectangle_sides(area=1e4 * 1e-4, perimeter=2 * (1e4 + 1e-4))
        self.assertAlmostEqual(1e4, long_side, delta=1e-12 * 1e4)
        self.assertAlmostEqual(1e-4, short_side, delta=1e-12 * 1e-4)

    def test_shape_without_rectangle_is_the_square_of_its_area(self):
        # NOTE: a regular octagon of side 1 has a perimeter of 8, less than 4·√area
        area = 2 * (1 + math.sqrt(2))
        self.assertEqual((math.sqrt(area), math.sqrt(area)), rectangle_sides(area=area, perimeter=8.0))

    def test_lvs_device_class_of_a_schematic_device(self):
        rfnmos = {**NMOS, 'lvs_device_class_name': 'rfnmos', 'model_name': 'sg13_lv_nmos',
                  'parameters': [{'name': 'rfmode', 'constant': 1}]}
        nmos = {**NMOS, 'model_name': 'sg13_lv_nmos'}
        models = device_models(nmos, rfnmos, RPPD)
        self.assertEqual('nmos', models.lvs_device_class_name(
            SpiceElement(name='XM1', model='SG13_LV_NMOS', parameters={'w': 1e-6})))
        # NOTE: rfnmos writes the model of nmos with rfmode=1
        self.assertEqual('rfnmos', models.lvs_device_class_name(
            SpiceElement(name='XM2', model='sg13_lv_nmos', parameters={'w': 1e-6, 'rfmode': 1})))

    def test_lvs_device_class_of_a_schematic_device_named_as_its_class(self):
        # NOTE: e.g. M1 d g s b nmos, as LVS reads it, though the mapping writes X1 d g s b sg13_lv_nmos
        models = device_models({**NMOS, 'model_name': 'sg13_lv_nmos'})
        self.assertEqual('nmos', models.lvs_device_class_name(SpiceElement(name='M1', model='NMOS')))

    def test_no_lvs_device_class_of_an_unknown_model(self):
        models = device_models(NMOS)
        self.assertIsNone(models.lvs_device_class_name(SpiceElement(name='XM1', model='pmos')))
        self.assertIsNone(models.lvs_device_class_name(SpiceElement(name='R1', value=1e3)))

    def test_lvs_parameters_of_a_schematic_device(self):
        values = DeviceModels.lvs_parameter_values(
            device_models(NMOS).mapping_by_lvs_device_class_name['nmos'],
            SpiceElement(name='XM1', model='nmos', parameters={'w': 2e-6, 'l': 0.13e-6, 'ng': 2}))
        self.assertEqual(['L', 'W'], sorted(values))
        self.assertAlmostEqual(2.0, values['W'], places=12)
        self.assertAlmostEqual(0.13, values['L'], places=12)

    def test_lvs_parameters_the_schematic_device_doesnt_give_are_missing(self):
        # NOTE: e.g. left to the model's default
        values = DeviceModels.lvs_parameter_values(device_models(NMOS).mapping_by_lvs_device_class_name['nmos'],
                                                   SpiceElement(name='XM1', model='nmos', parameters={'w': 2e-6}))
        self.assertEqual(['W'], sorted(values))

    def test_lvs_area_and_perimeter_of_the_sides_of_a_schematic_device(self):
        values = DeviceModels.lvs_parameter_values(device_models(MIM).mapping_by_lvs_device_class_name['mim'],
                                                   SpiceElement(name='XC1', model='mim',
                                                                parameters={'w': 4e-6, 'l': 2e-6}))
        self.assertAlmostEqual(8.0, values['A'], places=12)
        self.assertAlmostEqual(12.0, values['P'], places=12)

    def test_multiplier_lvs_parameter_name(self):
        mappings = device_models(NMOS, NPN).mapping_by_lvs_device_class_name
        self.assertEqual('NE', DeviceModels.multiplier_lvs_parameter_name(mappings['npn']))
        self.assertIsNone(DeviceModels.multiplier_lvs_parameter_name(mappings['nmos']))
