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

from types import SimpleNamespace
from typing import *
import unittest

import allure
import klayout.db as kdb

from klayout_pex.klayout.pex25d_builder import PEX25DBuilder, BuildError
from klayout_pex.pex25d.protobuf import pex25d_terminal_pb2
from klayout_pex.pex25d.reader import read_pex25d_text
from klayout_pex.pex25d.resolver import resolve
from klayout_pex.pex25d.validator import validate
from klayout_pex.pex25d.writer import write_pex25d_text
from klayout_pex.tech_info import TechInfo
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2
import klayout_pex_protobuf.kpex.tech.process_stack_pb2 as stack_pb2


class TerminalFixture:
    def __init__(self, metal_names: Tuple[str, ...] = ('met1',)):
        """
        :param metal_names: the metals of the stack on the drawn met1 (e.g. split by a MiM cap),
                            each of them with its LVS layer of the same name
        """
        self.metal_names = metal_names
        self.netlist = kdb.Netlist()
        self.circuit = kdb.Circuit()
        self.circuit.name = 'test'
        self.netlist.add(self.circuit)
        self.net = self.circuit.create_net('N')
        self.device_class = kdb.DeviceClassMOS4Transistor()
        self.device_class.name = 'nfet'
        self.netlist.add(self.device_class)
        self.geometry = {metal_names[0]: kdb.Region(kdb.Box(0, 0, 100, 20))}  # by LVS layer
        self.markers = {}
        self.labels = kdb.Texts()
        self.pins = kdb.Region(kdb.Box(0, 0, 100, 20))
        tech = tech_pb2.Technology(name='test')
        metal = tech.layers.add(name='met1')
        metal.drw_gds_pair.layer = 1
        metal.pin_gds_pair.layer = 1
        metal.pin_gds_pair.datatype = 16
        metal.label_gds_pair.layer = 1
        metal.label_gds_pair.datatype = 5
        stack = tech.process_stack
        substrate = stack.layers.add(name='subs', layer_type=stack_pb2.ProcessStackInfo.LAYER_TYPE_SUBSTRATE)
        substrate.substrate_layer.height = 0.1
        substrate.substrate_layer.thickness = 0.2
        for name in metal_names:
            metal = stack.layers.add(name=name, layer_type=stack_pb2.ProcessStackInfo.LAYER_TYPE_METAL)
            metal.metal_layer.z = 1.0
            metal.metal_layer.thickness = 0.1
            tech.lvs_computed_layers.add(layer_info=tech_pb2.LayerInfo(name=name,
                                                                       drw_gds_pair=tech_pb2.GDSPair(layer=1)),
                                         original_layer_name='met1')
        air = stack.layers.add(name='air', layer_type=stack_pb2.ProcessStackInfo.LAYER_TYPE_SIMPLE_DIELECTRIC)
        air.simple_dielectric_layer.dielectric_k = 1.0
        self.tech = TechInfo(tech, None)
        self.context = SimpleNamespace(
            dbu=0.001, top_circuit=self.circuit,
            shapes_of_net=self.shapes_of_net,
            pins_of_layer=lambda pair: self.pins,
            labels_of_layer=lambda pair: self.labels,
            lvsdb=SimpleNamespace(
                layer_name=lambda index: self.metal_names[index],
                shapes_of_terminal=lambda ref: self.markers[ref.device().expanded_name()]))

    def shapes_of_net(self, gds_pair, net, lvs_layer_names=None):
        shapes = kdb.Region()
        for lvs_layer_name, region in self.geometry.items():
            if lvs_layer_names is None or lvs_layer_name in lvs_layer_names:
                shapes += region
        return shapes

    def pin(self, label, x, y):
        self.labels.insert(kdb.Text(label, kdb.Trans(x, y)))

    def device(self, name, region, lvs_layer_name=None):
        device = self.circuit.create_device(self.device_class, name)
        device.connect_terminal('G', self.net)
        self.markers[name] = {self.metal_names.index(lvs_layer_name or self.metal_names[0]): region}

    def build(self):
        return PEX25DBuilder(self.context, self.tech, 'test').build()


@allure.parent_suite('Unit Tests')
@allure.tag('PEX25D', 'Builder')
class Pex25DBuilderTerminalTest(unittest.TestCase):
    def test_pin_uses_its_label_not_the_whole_pin_polygon(self):
        fixture = TerminalFixture()
        fixture.pin('A', 10, 10)
        fixture.pin('B', 90, 10)
        file = fixture.build()
        assert [t.name for t in file.terminals] == ['pin:A', 'pin:B']
        assert all(t.kind == pex25d_terminal_pb2().TERMINAL_KIND_PIN for t in file.terminals)
        terminal = file.terminals[0]
        assert terminal.conductor == 'N'
        assert (terminal.region.lower_left.x, terminal.region.upper_right.x) == (90, 110)
        assert file.shapes[0].box.upper_right.x == 1000
        assert validate(file, strict=True).exit_code == 0

    def test_pin_on_a_bent_wire_resolves(self):
        fixture = TerminalFixture()
        fixture.geometry['met1'] = kdb.Region(kdb.Polygon([
            kdb.Point(0, 0), kdb.Point(100, 0), kdb.Point(100, 20),
            kdb.Point(20, 20), kdb.Point(20, 100), kdb.Point(0, 100)]))
        fixture.pin('A', 10, 10)
        file = fixture.build()
        scene = resolve(read_pex25d_text(write_pex25d_text(file), '<generated>'))
        terminal = scene.conductors[0].terminals[0]
        assert len(terminal.boxes) == 1
        assert terminal.boxes[0].upper_right.x - terminal.boxes[0].lower_left.x == 20

    def test_repeated_labels_produce_unique_stable_names(self):
        fixture = TerminalFixture()
        fixture.pin('A', 10, 10)
        fixture.pin('A', 90, 10)
        names = [t.name for t in fixture.build().terminals]
        assert names == [t.name for t in fixture.build().terminals]
        assert len(names) == len(set(names)) == 2

    def test_a_label_outside_the_pin_marker_is_ignored(self):
        fixture = TerminalFixture()
        fixture.pin('A', 200, 10)
        assert not fixture.build().terminals

    def test_a_pin_without_interconnect_reports_a_build_error(self):
        fixture = TerminalFixture()
        fixture.pin('A', 10, 10)
        fixture.geometry['met1'] = kdb.Region(kdb.Box(50, 0, 100, 20))
        with self.assertRaisesRegex(BuildError, 'must select one conductor'):
            fixture.build()

    def test_a_device_terminal_keeps_all_its_disjoint_shapes_in_one_node(self):
        fixture = TerminalFixture()
        fixture.geometry['met1'] = kdb.Region(kdb.Box(10, 0, 20, 100))
        fixture.geometry['met1'].insert(kdb.Box(40, 0, 50, 100))
        marker = kdb.Region(kdb.Box(10, 40, 20, 50))
        marker.insert(kdb.Box(40, 40, 50, 50))
        fixture.device('M1', marker)
        file = fixture.build()
        assert len(file.terminals) == 1
        terminal = file.terminals[0]
        assert terminal.name == 'device:M1:G'
        assert terminal.kind == pex25d_terminal_pb2().TERMINAL_KIND_DEVICE_TERMINAL
        scene = resolve(file)
        assert len(scene.conductors[0].terminals) == 1
        assert len(scene.conductors[0].terminals[0].boxes) == 2

    def test_an_abutting_device_gets_only_a_boundary_strip(self):
        fixture = TerminalFixture()
        fixture.device('M1', kdb.Region(kdb.Box(-20, 0, 0, 20)))
        file = fixture.build()
        terminal = resolve(file).conductors[0].terminals[0]
        assert (terminal.boxes[0].lower_left.x, terminal.boxes[0].upper_right.x) == (0, 10)

    def test_a_box_cannot_silently_short_interconnect_between_device_shapes(self):
        fixture = TerminalFixture()
        marker = kdb.Region(kdb.Box(10, 0, 20, 20))
        marker.insert(kdb.Box(40, 0, 50, 20))
        fixture.device('M1', marker)
        with self.assertRaisesRegex(BuildError, 'shorting additional interconnect'):
            fixture.build()

    def test_device_terminal_names_cannot_collide_with_pin_names(self):
        fixture = TerminalFixture()
        fixture.pin('M1:G', 10, 10)
        fixture.device('M1', kdb.Region(kdb.Box(50, 0, 60, 20)))
        file = fixture.build()
        assert len({t.name for t in file.terminals}) == 2
        assert len(read_pex25d_text(write_pex25d_text(file), '<generated>').terminals) == 2


@allure.parent_suite('Unit Tests')
@allure.tag('PEX25D', 'Builder')
class Pex25DBuilderMetalsSharingGDSPairTest(unittest.TestCase):
    # NOTE: e.g. sky130A met3, split into the bottom plates of the MiM caps (met3_cap) and the rest (met3_ncap)
    @staticmethod
    def fixture() -> TerminalFixture:
        fixture = TerminalFixture(metal_names=('met1_ncap', 'met1_cap'))
        fixture.geometry = {'met1_ncap': kdb.Region(kdb.Box(0, 0, 60, 20)),
                            'met1_cap': kdb.Region(kdb.Box(60, 0, 100, 20))}
        return fixture

    def test_each_metal_has_the_shapes_of_its_own_lvs_layer(self):
        file = self.fixture().build()
        assert [(s.layer, s.box.lower_left.x, s.box.upper_right.x) for s in file.shapes] == \
               [('met1_ncap', 0, 600), ('met1_cap', 600, 1000)]
        assert validate(file, strict=True).exit_code == 0

    def test_a_pin_is_on_the_metal_under_its_label(self):
        fixture = self.fixture()
        fixture.pin('A', 10, 10)
        fixture.pin('B', 90, 10)
        assert [(t.name, t.layer) for t in fixture.build().terminals] == \
               [('pin:A', 'met1_ncap'), ('pin:B', 'met1_cap')]

    def test_a_device_terminal_is_on_the_metal_of_its_lvs_layer(self):
        # NOTE: the bottom plate of a MiM cap abuts the rest of its metal
        fixture = self.fixture()
        fixture.device('C1', kdb.Region(kdb.Box(60, 0, 100, 20)), lvs_layer_name='met1_cap')
        assert [(t.name, t.layer) for t in fixture.build().terminals] == [('device:C1:G', 'met1_cap')]
