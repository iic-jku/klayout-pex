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

from datetime import datetime
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple
import unittest

import allure
import klayout.db as kdb

from klayout_pex.klayout.netlist_printer import NetlistHeader, NetlistPrinter
from klayout_pex.klayout.parasitic_device_classes import PARASITIC_CAPACITOR_CLASS_NAME
from klayout_pex.netlist.spice_reader import SpiceReader
from klayout_pex.rcx25.schematic_device_names import use_schematic_device_names
from tests.common.device_model_mappings import NMOS, RPPD, device_models


MODELS = device_models(NMOS, RPPD)


def layout(devices: List[Tuple[str, str, List[str], float, float]],
           ports: Dict[str, str]) -> kdb.Netlist:
    netlist = kdb.Netlist()
    for device_class, name in ((kdb.DeviceClassMOS4Transistor(), 'nmos'),
                               (kdb.DeviceClassResistor(), 'rppd')):
        device_class.name = name
        netlist.add(device_class)
    circuit = kdb.Circuit()
    circuit.name = 'TOP'
    netlist.add(circuit)
    nets: Dict[str, kdb.Net] = {}

    def net(name: str) -> kdb.Net:
        if name not in nets:
            nets[name] = circuit.create_net(name)
            nets[name].cluster_id = len(nets)
        return nets[name]

    for name, class_name, nodes, width, length in devices:
        device = circuit.create_device(netlist.device_class_by_name(class_name), name)
        device.set_parameter('W', width)
        device.set_parameter('L', length)
        for terminal, node in zip(MODELS.mapping_by_lvs_device_class_name[class_name].terminal_names, nodes):
            device.connect_terminal(terminal, net(node))
    for name, node in ports.items():
        circuit.connect_pin(circuit.create_pin(name).id(), net(node))
    return netlist


def names(netlist: kdb.Netlist) -> List[str]:
    return [device.expanded_name() for device in netlist.circuit_by_name('TOP').each_device()]


def rename(netlist: kdb.Netlist, schematic: str) -> Tuple[kdb.Netlist, List[str]]:
    exported = netlist.dup()
    messages = use_schematic_device_names(netlist, exported, SpiceReader().parse(schematic), MODELS, 'TOP')
    return exported, messages


def device_lines(netlist: kdb.Netlist) -> List[str]:
    printer = NetlistPrinter(NetlistHeader('test', 'KPEX/2.5D', 'test', datetime(2026, 1, 1)), MODELS)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'extracted.cir'
        printer.write(netlist, path)
        return [line for line in path.read_text(encoding='utf-8').splitlines() if line and line[0] not in '*.']


@allure.parent_suite('Unit Tests')
@allure.tag('Netlist', 'Schematic')
class SchematicDeviceNamesTest(unittest.TestCase):
    def test_native_devices_and_wrappers_keep_stems_and_required_output_prefix(self):
        netlist = layout([('old', 'nmos', ['drain', 'gate', 'vss', 'vss'], 2.0, 1.0)],
                         {'G': 'gate', 'S': 'vss', 'D': 'drain'})
        original = netlist.to_s()
        for designator in ('X', 'M'):
            with self.subTest(designator=designator):
                exported, messages = rename(netlist, f'.subckt TOP D G S\n{designator}tail D G S S nmos w=2u l=1u\n.ends\n')
                self.assertEqual([], messages)
                self.assertEqual(['tail'], names(exported))
                self.assertTrue(device_lines(exported)[0].startswith('Xtail '))
                self.assertEqual(['G', 'S', 'D'], [pin.name() for pin in exported.circuit_by_name('TOP').each_pin()])
                self.assertEqual(original, netlist.to_s())

    def test_native_scale_and_external_wrapper_units_match_the_same_geometry(self):
        netlist = layout([('old', 'nmos', ['d', 'g', 's', 's'], 2.0, 1.0)],
                         {'d': 'd', 'g': 'g', 's': 's'})
        for device in ('Mtail d g s s nmos w=2 l=1', 'Xtail d g s s nmos w=2u l=1u'):
            with self.subTest(device=device):
                exported, messages = rename(netlist, f'.option scale=1u\n.subckt TOP d g s\n{device}\n.ends\n')
                self.assertEqual([], messages)
                self.assertEqual(['tail'], names(exported))

    def test_geometry_rounding_uses_the_existing_relative_tolerance(self):
        netlist = layout([('old', 'nmos', ['d', 'g', 's', 's'], 1.0, 0.5)],
                         {'d': 'd', 'g': 'g', 's': 's'})
        # Below, at and above the shared 1 ppm unit-conversion tolerance. This
        # must not turn a physically different device into a naming match.
        for width, matches in ((1.0000005, True), (1.000001, True), (1.000002, False)):
            with self.subTest(width=width):
                source = f'.subckt TOP d g s\nXtail d g s s nmos w={width}u l=0.5u\n.ends\n'
                exported, messages = rename(netlist, source)
                self.assertEqual(['tail'] if matches else ['old'], names(exported))
                self.assertEqual(not matches, bool(messages))

    def test_parallel_width_overflow_keeps_layout_names(self):
        netlist = layout([('old1', 'nmos', ['d', 'g', 's', 's'], 1e308, 0.5),
                          ('old2', 'nmos', ['d', 'g', 's', 's'], 1e308, 0.5)],
                         {'d': 'd', 'g': 'g', 's': 's'})
        exported, messages = rename(netlist, '.subckt TOP d g s\nXtail d g s s nmos w=1e302 l=0.5u\n.ends\n')
        self.assertEqual(names(netlist), names(exported))
        self.assertIn('not finite', messages[0])

    def test_fingers_and_multiplier_use_repeatable_zero_based_suffixes(self):
        # One, two and three fingers cover the no-suffix boundary and both sides.
        for count in (1, 2, 3):
            with self.subTest(count=count):
                netlist = layout([(f'old{i}', 'nmos', ['d', 'g', 's', 's'], 1.0, 0.5)
                                  for i in range(count)], {'d': 'd', 'g': 'g', 's': 's'})
                for geometry in (f'w={count}u l=0.5u', f'w=1u l=0.5u m={count}'):
                    source = f'.subckt TOP d g s\nXtail d g s s nmos {geometry}\n.ends\n'
                    expected = ['tail'] if count == 1 else [f'tail_{i}' for i in range(count)]
                    for _ in range(2):
                        exported, messages = rename(netlist, source)
                        self.assertEqual([], messages)
                        self.assertEqual(expected, names(exported))

    def test_hierarchical_instances_follow_connected_ports(self):
        netlist = layout([('old1', 'nmos', ['q1', 'g', 's', 's'], 1.0, 0.5),
                          ('old2', 'nmos', ['q2', 'g', 's', 's'], 1.0, 0.5)],
                         {'q1': 'q1', 'q2': 'q2', 'g': 'g', 's': 's'})
        exported, messages = rename(netlist, '''\
.subckt cell D G S
Mcore D G S S nmos w=1u l=0.5u
.ends
.subckt TOP q1 q2 g s
Xleft q1 g s cell
Xright q2 g s cell
.ends
''')
        self.assertEqual([], messages)
        self.assertEqual(['left.Mcore', 'right.Mcore'], names(exported))

    def test_resistor_name_is_matched_by_connections_and_geometry(self):
        netlist = layout([('old1', 'rppd', ['a', 'b'], 1.0, 2.0),
                          ('old2', 'rppd', ['a', 'b'], 2.0, 2.0)], {'a': 'a', 'b': 'b'})
        exported, messages = rename(netlist, '''\
.subckt TOP a b
Xwide b a rppd w=2u l=2u
Xbias a b rppd w=1u l=2u
.ends
''')
        self.assertEqual([], messages)
        self.assertEqual(['bias', 'wide'], names(exported))

    def test_removed_finger_keeps_remaining_suffix_and_does_not_rename_a_parasitic(self):
        netlist = layout([('old1', 'nmos', ['d', 'g', 's', 's'], 1.0, 0.5),
                          ('old2', 'nmos', ['d', 'g', 's', 's'], 1.0, 0.5)],
                         {'d': 'd', 'g': 'g', 's': 's'})
        source = SpiceReader().parse('.subckt TOP d g s\nXtail d g s s nmos w=2u l=0.5u\n.ends\n')
        exported = netlist.dup()
        circuit = exported.circuit_by_name('TOP')
        circuit.remove_device(list(circuit.each_device())[0])
        self.assertEqual([], use_schematic_device_names(netlist, exported, source, MODELS, 'TOP'))
        self.assertEqual(['tail_1'], names(exported))

        # A white-boxed device can disappear before parasitic creation. IDs alone
        # cannot identify a modeled device in a separately constructed output.
        exported = layout([], {})
        parasitic_class = kdb.DeviceClassCapacitor()
        parasitic_class.name = PARASITIC_CAPACITOR_CLASS_NAME
        exported.add(parasitic_class)
        capacitor = exported.circuit_by_name('TOP').create_device(parasitic_class, 'ext_1')
        self.assertEqual(list(netlist.circuit_by_name('TOP').each_device())[0].id(), capacitor.id())
        self.assertEqual([], use_schematic_device_names(netlist, exported, source, MODELS, 'TOP'))
        self.assertEqual(['ext_1'], names(exported))

    def test_indistinguishable_parallel_instances_retain_layout_names(self):
        netlist = layout([('old1', 'nmos', ['d', 'g', 's', 's'], 1.0, 0.5),
                          ('old2', 'nmos', ['d', 'g', 's', 's'], 1.0, 0.5)],
                         {'d': 'd', 'g': 'g', 's': 's'})
        exported, messages = rename(netlist, '''\
.subckt TOP d g s
Xleft d g s s nmos w=1u l=0.5u
Xright d g s s nmos w=1u l=0.5u
.ends
''')
        self.assertEqual(names(netlist), names(exported))
        self.assertIn('indistinguishable', messages[0])

    def test_parallel_devices_within_parameter_tolerance_remain_ambiguous(self):
        # Net correspondence alone cannot identify parallel devices. Values
        # accepted as equal by the comparer must not choose an arbitrary name.
        netlist = layout([('old1', 'rppd', ['a', 'b'], 1.0, 2.0),
                          ('old2', 'rppd', ['a', 'b'], 1.0000005, 2.0)], {'a': 'a', 'b': 'b'})
        exported, messages = rename(netlist, '''\
.subckt TOP a b
Xfirst a b rppd w=1u l=2u
Xsecond a b rppd w=1.0000005u l=2u
.ends
''')
        self.assertEqual(names(netlist), names(exported))
        self.assertTrue(all('indistinguishable' in message for message in messages))

    def test_symmetric_internal_nets_do_not_get_arbitrary_device_names(self):
        netlist = layout([('old1', 'nmos', ['internal1', 'g', 's', 's'], 1.0, 0.5),
                          ('old2', 'nmos', ['internal2', 'g', 's', 's'], 1.0, 0.5)],
                         {'g': 'g', 's': 's'})
        exported, messages = rename(netlist, '''\
.subckt TOP g s
Xleft a g s s nmos w=1u l=0.5u
Xright b g s s nmos w=1u l=0.5u
.ends
''')
        self.assertEqual(names(netlist), names(exported))
        self.assertIn('ambiguous', messages[0])

    def test_unmapped_native_component_does_not_disappear_from_the_topology(self):
        netlist = layout([('old', 'nmos', ['d', 'g', 's', 's'], 1.0, 0.5)],
                         {'d': 'd', 'g': 'g', 's': 's'})
        # Ignoring the ideal series resistor would incorrectly equate the gate
        # with its external port and give the unmatched transistor a source name.
        exported, messages = rename(netlist, '''\
.subckt TOP d g s
Xtail d internal s s nmos w=1u l=0.5u
Rseries g internal 1k
.ends
''')
        self.assertEqual(['old'], names(exported))
        self.assertIn('without a model mapping: Rseries', messages[0])

    def test_finger_suffix_collision_rejects_the_assignment_case_insensitively(self):
        netlist = layout([('old1', 'nmos', ['d', 'g', 's', 's'], 1.0, 0.5),
                          ('old2', 'nmos', ['d', 'g', 's', 's'], 1.0, 0.5),
                          ('old3', 'nmos', ['q', 'g', 's', 's'], 1.0, 0.5)],
                         {'d': 'd', 'q': 'q', 'g': 'g', 's': 's'})
        exported, messages = rename(netlist, '''\
.subckt TOP d q g s
Xtail d g s s nmos w=2u l=0.5u
XTAIL_0 q g s s nmos w=1u l=0.5u
.ends
''')
        self.assertEqual(names(netlist), names(exported))
        self.assertIn('collide', messages[0])

    def test_incomplete_or_mismatching_schematic_keeps_extraction_usable(self):
        netlist = layout([('old', 'nmos', ['d', 'g', 's', 's'], 1.0, 0.5)],
                         {'d': 'd', 'g': 'g', 's': 's'})
        for body in ('Xtail d g s s nmos w=2u l=0.5u',
                     'Xtail d g s s nmos w=1u l=0.5u m=0',
                     'Xtail d g s s nmos w=1u l=0.5u m=-1',
                     'Xtail d g s s nmos w=0 l=0.5u',
                     'Xtail d g s s nmos w=1u l=-0.5u',
                     'Xtail d g s s nmos w=1u', 'Xcell d g s unknown'):
            with self.subTest(body=body):
                exported, messages = rename(netlist, f'.subckt TOP d g s\n{body}\n.ends\n')
                self.assertEqual(names(netlist), names(exported))
                self.assertTrue(messages)
                self.assertTrue(device_lines(exported)[0].startswith('Xold '))
