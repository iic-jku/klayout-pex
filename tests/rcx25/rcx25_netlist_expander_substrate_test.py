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
from klayout_pex.rcx25.extraction_results import ExtractionSummary, NetCoupleKey
from klayout_pex.rcx25.netlist_expander import RCX25NetlistExpander
import klayout_pex_protobuf.kpex.tech.device_models_pb2 as device_models_pb2


class Results:
    """
    Extraction results of a given summary
    """
    def __init__(self, summary: ExtractionSummary):
        self.summary = summary

    def summarize(self) -> ExtractionSummary:
        return self.summary


def netlist() -> kdb.Netlist:
    """
    The nets D and B, with a pin each
    """
    netlist = kdb.Netlist()
    circuit = kdb.Circuit()
    circuit.name = 'chip'
    netlist.add(circuit)
    for name in ('D', 'B'):
        circuit.connect_pin(circuit.create_pin(name), circuit.create_net(name))
    return netlist


def capacitances(expanded: kdb.Netlist) -> dict:
    circuit = expanded.circuit_by_name('chip')
    return {frozenset((d.net_for_terminal('A').name, d.net_for_terminal('B').name)): d.parameter('C') * 1e15
            for d in circuit.each_device() if d.device_class().name == 'PEX_CAP'}


@allure.parent_suite("Unit Tests")
@allure.tag("RCX25", "Netlist Expansion")
class Test(unittest.TestCase):
    # the capacitances to the substrate are on VSUBS in the summary
    SUMMARY = ExtractionSummary(capacitances={NetCoupleKey('D', 'VSUBS'): 1.0, NetCoupleKey('B', 'VSUBS'): 2.0},
                                resistances={})

    def test_capacitances_to_the_substrate_are_on_its_net(self):
        expanded = RCX25NetlistExpander.expand(netlist(), 'chip', Results(self.SUMMARY), blackbox_devices=True,
                                               device_models=DeviceModels(device_models_pb2.DeviceModelsInfo()),
                                               substrate_net_name='B')
        circuit = expanded.circuit_by_name('chip')
        # NOTE: the capacitance of B to the substrate is shorted, as B is the substrate net
        self.assertEqual({frozenset(('D', 'B')): 1.0}, capacitances(expanded))
        self.assertIsNone(circuit.net_by_name('VSUBS'))
        self.assertEqual(['D', 'B'], [p.name() for p in circuit.each_pin()])

    def test_substrate_without_net_is_a_port(self):
        # e.g. a metal test pattern, without taps or transistors
        expanded = RCX25NetlistExpander.expand(netlist(), 'chip', Results(self.SUMMARY), blackbox_devices=True,
                                               device_models=DeviceModels(device_models_pb2.DeviceModelsInfo()),
                                               substrate_net_name='sky130_gnd')
        circuit = expanded.circuit_by_name('chip')
        self.assertEqual({frozenset(('D', 'sky130_gnd')): 1.0, frozenset(('B', 'sky130_gnd')): 2.0},
                         capacitances(expanded))
        self.assertEqual(['D', 'B', 'sky130_gnd'], [p.name() for p in circuit.each_pin()])
        self.assertEqual('sky130_gnd', circuit.net_for_pin(circuit.pin_by_name('sky130_gnd').id()).name)

    def test_substrate_net_without_pin_is_a_port(self):
        # e.g. IHP's global net sub!, which the LVS creates without shapes in a metal test pattern
        lvs_netlist = netlist()
        lvs_netlist.circuit_by_name('chip').create_net('sub!')
        expanded = RCX25NetlistExpander.expand(lvs_netlist, 'chip', Results(self.SUMMARY), blackbox_devices=True,
                                               device_models=DeviceModels(device_models_pb2.DeviceModelsInfo()),
                                               substrate_net_name='sub!')
        circuit = expanded.circuit_by_name('chip')
        self.assertEqual({frozenset(('D', 'sub!')): 1.0, frozenset(('B', 'sub!')): 2.0},
                         capacitances(expanded))
        self.assertEqual(['D', 'B', 'sub!'], [p.name() for p in circuit.each_pin()])
        self.assertEqual('sub!', circuit.net_for_pin(circuit.pin_by_name('sub!').id()).name)
        self.assertEqual(1, len([n for n in circuit.each_net() if n.name == 'sub!']))
