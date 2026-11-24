#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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
from pathlib import Path
import tempfile
from typing import *
import unittest
from unittest import mock

import google.protobuf.json_format
import klayout.db as kdb
import pytest

from kpex.device_models import DeviceModelError, DeviceModels
from kpex.klayout.netlist_printer import NetlistHeader, NetlistPrinter, UnmappedDevicePolicy
from kpex.klayout.parasitic_device_classes import (
    PARASITIC_CAPACITOR_CLASS_NAME,
    PARASITIC_RESISTOR_CLASS_NAME,
)
from kpex.netlist.netlist_convert import convert_to_vacask
from tests.common.ngspice import ngspice_operating_point, requires_ngspice
from tests.common.vacask import read_ascii_raw, requires_vacask, run_vacask
from tests.common.xyce import read_prn, requires_xyce, run_xyce
import kpex_protobuf.kpex.tech.device_models_pb2 as device_models_pb2


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

# as the IHP antenna diode: a model of w and l, which LVS extracts by area and perimeter
DANTENNA = device_model_mapping(lvs_device_class_name='dantenna',
                                spice_prefix='X',
                                terminal_names=['A', 'C'],
                                parameters=[{'name': 'w', 'lvs_parameter_factor': 1e-6,
                                             'lvs_area_perimeter_side': {'area_parameter_name': 'A',
                                                                         'perimeter_parameter_name': 'P',
                                                                         'side': 'SIDE_LONG'}},
                                            {'name': 'l', 'lvs_parameter_factor': 1e-6,
                                             'lvs_area_perimeter_side': {'area_parameter_name': 'A',
                                                                         'perimeter_parameter_name': 'P',
                                                                         'side': 'SIDE_SHORT'}}])


def empty_netlist() -> kdb.Netlist:
    netlist = kdb.Netlist()
    circuit = kdb.Circuit()
    circuit.name = 'TOP'
    netlist.add(circuit)
    return netlist


def netlist_with_parasitics(capacitance: float = 1e-15) -> kdb.Netlist:
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
    c.set_parameter('C', capacitance)

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
    def printer(*device_model_mappings: device_models_pb2.DeviceModelMapping,
                policy: UnmappedDevicePolicy = UnmappedDevicePolicy.ERROR) -> NetlistPrinter:
        device_models = device_models_pb2.DeviceModelsInfo(device_model_mappings=device_model_mappings)
        return NetlistPrinter(header=HEADER,
                              device_models=DeviceModels(device_models), unmapped_devices=policy)

    @staticmethod
    def lines(printer: NetlistPrinter, netlist: kdb.Netlist) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, 'netlist.cir')
            printer.write(netlist, path)
            with open(path, encoding='utf-8') as f:
                return [l.strip() for l in f if l.strip()]

    @classmethod
    def device_lines(cls, printer: NetlistPrinter, netlist: kdb.Netlist) -> list[str]:
        return [l for l in cls.lines(printer, netlist) if l[0] not in '*.']

    def test_header_is_written_as_comments(self):
        self.assertEqual([
            '*********************************************************',
            '*** NGSPICE file created by KPEX 1.2.3',
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

    def test_capacitance_below_1f_is_written_in_f(self):
        # NOTE: not in a (atto), which Xyce reads as a unit
        self.assertEqual([
            'Cext_1 a b 0.223458f',
            'Rext_1 a b 12.5',
        ], self.device_lines(self.printer(), netlist_with_parasitics(capacitance=223.458e-18)))

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

    def test_rectangle_sides_are_written_for_area_and_perimeter(self):
        netlist = empty_netlist()
        circuit = netlist.circuit_by_name('TOP')
        diode = kdb.DeviceClassDiode()
        diode.name = 'dantenna'
        netlist.add(diode)
        d = circuit.create_device(diode, 'D1')
        d.connect_terminal('A', circuit.create_net('sub'))
        d.connect_terminal('C', circuit.create_net('pin'))
        d.set_parameter('A', 0.48 * 0.78)  # µm²
        d.set_parameter('P', 2 * (0.48 + 0.78))  # µm
        self.assertEqual([
            'XD1 sub pin dantenna w=7.8e-07 l=4.8e-07',
        ], self.device_lines(self.printer(DANTENNA), netlist))

    def test_keep_preserves_native_mos_terminals_geometry_and_parasitics(self):
        # W/L alone could hide a unit error: also assert the absolute SI geometry.
        printer = self.printer(policy=UnmappedDevicePolicy.KEEP)
        with mock.patch('kpex.klayout.netlist_printer.warning') as warn:
            lines = self.lines(printer, lvs_netlist())
        self.assertIn('MM1 drain gate source bulk rfnmos L=0.72U W=1U AS=0P AD=0P PS=0U PD=0U', lines)
        self.assertIn('Cext_1 a b 1f', lines)
        self.assertIn('Rext_1 a b 12.5', lines)
        self.assertIn('* Unmapped LVS device: rfnmos', lines)
        warn.assert_called_once()
        self.assertIn('No simulation models are supplied', warn.call_args.args[0])
        self.assertNotIn('rppd', warn.call_args.args[0])  # Unused classes need no models.

    def test_keep_does_not_override_valid_mapping_or_warn_for_known_devices(self):
        with mock.patch('kpex.klayout.netlist_printer.warning') as warn:
            self.assertEqual(self.device_lines(self.printer(RFNMOS), lvs_netlist()),
                             self.device_lines(self.printer(RFNMOS, policy=UnmappedDevicePolicy.KEEP), lvs_netlist()))
        warn.assert_not_called()

    def test_reused_printer_does_not_report_previously_unmapped_devices(self):
        printer = self.printer(policy=UnmappedDevicePolicy.KEEP)
        self.lines(printer, lvs_netlist())
        with mock.patch('kpex.klayout.netlist_printer.warning') as warn:
            lines = self.lines(printer, netlist_with_parasitics())
        warn.assert_not_called()
        self.assertFalse(any('Unmapped LVS device' in line for line in lines))


@allure.parent_suite('Unit Tests')
@pytest.mark.parametrize('policy', list(UnmappedDevicePolicy))
def test_invalid_existing_mapping_never_falls_back_or_truncates_output(policy: UnmappedDevicePolicy, tmp_path: Path):
    # An invalid mapping differs from an absent one, even under the keep policy.
    invalid = device_models_pb2.DeviceModelMapping()
    invalid.CopyFrom(RFNMOS)
    invalid.terminal_names.pop()
    printer = Test.printer(invalid, policy=policy)
    path = tmp_path / 'retained.spice'
    path.write_text('previous output', encoding='utf-8')
    with pytest.raises(DeviceModelError, match="LVS terminal 'B' is missing"):
        printer.write(lvs_netlist(), path)
    assert path.read_text(encoding='utf-8') == 'previous output'


@allure.parent_suite('Unit Tests')
@pytest.mark.parametrize('device_class, parameters, expected', [
    (kdb.DeviceClassDiode, {'A': 2, 'P': 6}, 'D1 A C unknown A=2P P=6U'),
    (kdb.DeviceClassBJT4Transistor, {'NE': 2}, 'Q1 C B E S unknown AE=0P PE=0U AB=0P PB=0U AC=0P PC=0U NE=2'),
    # Native C/R output intentionally includes only primary parameters. Nonzero
    # secondary geometry documents that contract, rather than promising an adapter.
    (kdb.DeviceClassCapacitorWithBulk, {'C': 2e-12, 'A': 3, 'P': 8}, 'C1 A B W 2e-12 unknown'),
    (kdb.DeviceClassResistorWithBulk, {'R': 42, 'L': 3, 'W': 2}, 'R1 A B W 42 unknown'),
])
def test_keep_preserves_native_device_representation(device_class: Type[kdb.DeviceClass],
                                                      parameters: Dict[str, float], expected: str):
    # Photodiodes and VPP capacitors need terminal and geometry preservation even
    # when their native LVS representation needs a user-provided simulation adapter.
    netlist = empty_netlist()
    circuit = netlist.circuit_by_name('TOP')
    dc = device_class()
    dc.name = 'unknown'
    netlist.add(dc)
    device = circuit.create_device(dc, '1')
    for terminal in dc.terminal_definitions():
        device.connect_terminal(terminal.id(), circuit.create_net(terminal.name))
    for name, value in parameters.items():
        device.set_parameter(name, value)
    assert Test.device_lines(Test.printer(policy=UnmappedDevicePolicy.KEEP), netlist) == [expected]


@allure.parent_suite('Unit Tests')
def test_keep_preserves_custom_devices_as_subcircuit_calls():
    # A nonstandard device must not vanish just because it has no native SPICE type.
    # A mixed netlist must still apply mappings to the other devices.
    netlist = lvs_netlist()
    circuit = netlist.circuit_by_name('TOP')
    dc = kdb.DeviceClass()
    dc.name = 'custom'
    for name in ('PLUS', 'MINUS', 'SHIELD'):
        dc.add_terminal(kdb.DeviceTerminalDefinition(name, name))
    dc.add_parameter(kdb.DeviceParameterDefinition('GAIN', 'gain', 1))
    netlist.add(dc)
    device = circuit.create_device(dc, 'custom1')
    for terminal in dc.terminal_definitions():
        device.connect_terminal(terminal.id(), circuit.create_net(terminal.name))
    device.set_parameter('GAIN', 2.5)
    assert Test.device_lines(Test.printer(RFNMOS, policy=UnmappedDevicePolicy.KEEP), netlist) == [
        'Cext_1 a b 1f',
        'Rext_1 a b 12.5',
        'XM1 drain gate source bulk sg13_lv_nmos w=1e-06 l=7.2e-07 rfmode=1',
        'XD_custom1 PLUS MINUS SHIELD custom PARAMS: GAIN=2.5']


@pytest.fixture
def unmapped_mos_circuit(tmp_path: Path) -> Path:
    netlist = lvs_netlist()
    circuit = netlist.circuit_by_name('TOP')
    for name in ('a', 'b', 'source', 'gate', 'drain', 'bulk'):
        pin = circuit.create_pin(name)
        circuit.connect_pin(pin.id(), circuit.net_by_name(name))
    path = tmp_path / 'unmapped.spice'
    Test.printer(policy=UnmappedDevicePolicy.KEEP).write(netlist, path)
    return path


def expected_mos_current(gate_voltage: float) -> float:
    # Independent level-1 saturation law, with lateral diffusion so an incorrect
    # absolute length cannot hide behind an unchanged W/L ratio. Exercise cutoff,
    # threshold and conduction. The allowed absolute error covers simulator gmin.
    return 0.5 * 50e-6 * (1e-6 / (0.72e-6 - 2 * 0.1e-6)) * max(gate_voltage - 0.3, 0) ** 2


@allure.parent_suite('Simulation Tests')
@pytest.mark.slow
@requires_ngspice
@pytest.mark.parametrize('gate_voltage', [0.2, 0.3, 1.0])
def test_kept_mos_simulates_with_user_model_ngspice(unmapped_mos_circuit: Path,
                                                    gate_voltage: float, tmp_path: Path):
    deck = (f'.include "{unmapped_mos_circuit}"\n'
            '.model rfnmos nmos level=1 vto=0.3 kp=50u ld=0.1u\n'
            'X1 load 0 0 gate drain 0 TOP\nVload load 0 1\nVd drain 0 1\n'
            f'Vg gate 0 {gate_voltage}\n')
    result = ngspice_operating_point(deck, ['i(vd)', 'i(vload)'], str(tmp_path))
    assert -result['i(vd)'] == pytest.approx(expected_mos_current(gate_voltage), rel=1e-6, abs=3e-12)
    assert -result['i(vload)'] == pytest.approx(1 / 12.5, rel=1e-6)


@allure.parent_suite('Simulation Tests')
@pytest.mark.slow
@requires_xyce
def test_kept_mos_simulates_with_user_model_xyce(unmapped_mos_circuit: Path, tmp_path: Path):
    deck = tmp_path / 'tb.cir'
    deck.write_text('* retained LVS MOS with user model\n'
                    f'.include "{unmapped_mos_circuit}"\n'
                    '.model rfnmos nmos level=1 vto=0.3 kp=50u ld=0.1u\n'
                    'X1 load 0 0 gate drain 0 TOP\nVload load 0 1\nVd drain 0 1\nVg gate 0 1\n'
                    '.dc Vg 0.2 1.0 0.1\n.print dc V(gate) I(Vd) I(Vload)\n.end\n', encoding='utf-8')
    run_xyce(str(deck))
    result = read_prn(str(deck) + '.prn')
    for voltage, drain, load in zip(result['V(GATE)'], result['I(VD)'], result['I(VLOAD)']):
        assert -drain == pytest.approx(expected_mos_current(voltage), rel=1e-6, abs=3e-12)
        assert -load == pytest.approx(1 / 12.5, rel=1e-6)


@allure.parent_suite('Simulation Tests')
@pytest.mark.slow
@requires_vacask
@pytest.mark.parametrize('gate_voltage', [0.2, 0.3, 1.0])
def test_kept_mos_simulates_with_user_model_vacask(unmapped_mos_circuit: Path,
                                                   gate_voltage: float, tmp_path: Path):
    circuit, options = convert_to_vacask(str(unmapped_mos_circuit), str(tmp_path / 'unmapped.inc'), ())
    deck = tmp_path / 'tb.sim'
    deck.write_text('Retained LVS MOS with user model\n'
                    'load "spice/mos1.osdi"\nmodel rfnmos sp_mos1 type=1 vto=0.3 kp=50e-6 ld=0.1e-6\n'
                    f'include "{circuit}"\n'
                    'x1 (load 0 0 gate drain 0) TOP\nmodel supply vsource\n'
                    'vload (load 0) supply dc=1\nvd (drain 0) supply dc=1\n'
                    f'vg (gate 0) supply dc={gate_voltage}\n'
                    f'control\ninclude "{options}"\noptions rawfile="ascii"\n'
                    'save default\nanalysis op1 op\nendc\n', encoding='utf-8')
    run_vacask(str(deck))
    result = read_ascii_raw(str(tmp_path / 'op1.raw'))
    assert -result['vd:flow(br)'][0].real == pytest.approx(expected_mos_current(gate_voltage), rel=1e-6, abs=3e-12)
    assert -result['vload:flow(br)'][0].real == pytest.approx(1 / 12.5, rel=1e-6)
