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
from unittest import mock

import allure
import klayout.db as kdb

from klayout_pex.klayout.pex25d_builder import PEX25DBuilder, BuilderOptions, BuildError
from klayout_pex.pdk_config import PDK
from klayout_pex.pex25d.diagnostics import DiagnosticsReport, Severity
from klayout_pex.pex25d.protobuf import pex25d_file_pb2, pex25d_terminal_pb2
from klayout_pex.pex25d.reader import read_pex25d_text
from klayout_pex.pex25d.resolver import resolve
from klayout_pex.pex25d.validator import validate
from klayout_pex.pex25d.writer import write_pex25d_text
from klayout_pex.tech_info import TechInfo
from klayout_pex.util.multiple_choice import MultipleChoicePattern
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2
import klayout_pex_protobuf.kpex.tech.process_stack_pb2 as stack_pb2


class TerminalFixture:
    def __init__(self, metal_names: Tuple[str, ...] = ('met1',), diffusion: bool = False, contact: bool = True):
        """
        :param metal_names: the metals of the stack on the drawn met1 (e.g. split by a MiM cap),
                            each of them with its LVS layer of the same name
        :param diffusion: also a diffusion of the stack (nsd, e.g. of a source/drain), with its LVS layer
        :param contact: whether the diffusion has a contact (cont_nsd, with its LVS layer) up to the first metal,
                        as a source/drain has, and a tap hasn't
        """
        self.metal_names = metal_names
        self.lvs_layer_names = list(metal_names)  # NOTE: by index, those of the markers
        self.netlist = kdb.Netlist()
        self.circuit = kdb.Circuit()
        self.circuit.name = 'test'
        self.netlist.add(self.circuit)
        self.net = self.circuit.create_net('N')
        self.device_class = kdb.DeviceClassMOS4Transistor()
        self.device_class.name = 'nfet'
        self.netlist.add(self.device_class)
        self.geometry = {metal_names[0]: kdb.Region(kdb.Box(0, 0, 100, 20))}  # by LVS layer
        self.geometry_by_other_net: Dict[str, Dict[str, kdb.Region]] = {}
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
        if diffusion:
            nsd = stack.layers.add(name='nsd', layer_type=stack_pb2.ProcessStackInfo.LAYER_TYPE_DIFFUSION)
            lvs_layers = [('nsd', 2)]
            if contact:
                nsd.diffusion_layer.contact_above.name = 'cont_nsd'
                nsd.diffusion_layer.contact_above.metal_above = metal_names[0]
                nsd.diffusion_layer.contact_above.thickness = 1.0  # NOTE: from z 0 to the metal
                lvs_layers.append(('cont_nsd', 3))
            for name, gds_layer in lvs_layers:
                tech.lvs_computed_layers.add(layer_info=tech_pb2.LayerInfo(name=name,
                                                                           drw_gds_pair=tech_pb2.GDSPair(layer=gds_layer)),
                                             process_layer_name=name)
        for name in metal_names:
            metal = stack.layers.add(name=name, layer_type=stack_pb2.ProcessStackInfo.LAYER_TYPE_METAL)
            metal.metal_layer.z = 1.0
            metal.metal_layer.thickness = 0.1
            tech.lvs_computed_layers.add(layer_info=tech_pb2.LayerInfo(name=name,
                                                                       drw_gds_pair=tech_pb2.GDSPair(layer=1)),
                                         original_layer_name='met1',
                                         process_layer_name=name)
        air = stack.layers.add(name='air', layer_type=stack_pb2.ProcessStackInfo.LAYER_TYPE_SIMPLE_DIELECTRIC)
        air.simple_dielectric_layer.dielectric_k = 1.0
        self.tech = TechInfo(tech, None)
        self.context = SimpleNamespace(
            port_label_keys=None,
            dbu=0.001, top_circuit=self.circuit,
            shapes_of_net=self.shapes_of_net,
            pins_of_layer=lambda pair: self.pins,
            labels_of_layer=lambda pair: self.labels,
            lvsdb=SimpleNamespace(
                layer_name=lambda index: self.lvs_layer_names[index],
                shapes_of_terminal=lambda ref: self.markers[ref.device().expanded_name()]))

    def shapes_of_net(self, gds_pair, net, lvs_layer_names=None):
        name = net.expanded_name()
        geometry = self.geometry if name == self.net.expanded_name() else self.geometry_by_other_net[name]
        shapes = kdb.Region()
        for lvs_layer_name, region in geometry.items():
            if lvs_layer_names is None or lvs_layer_name in lvs_layer_names:
                shapes += region
        return shapes

    def add_net(self, name: str, geometry: Dict[str, kdb.Region]):
        """
        :param geometry: the shapes of the net by LVS layer, as self.geometry those of N
        """
        self.circuit.create_net(name)
        self.geometry_by_other_net[name] = geometry

    def pin(self, label, x, y):
        self.labels.insert(kdb.Text(label, kdb.Trans(x, y)))

    def device(self, name, region, lvs_layer_name=None):
        """
        :param lvs_layer_name: the LVS layer of its marker, the first metal by default,
                               one of no metal is one the tech info has no layer for
        """
        device = self.circuit.create_device(self.device_class, name)
        device.connect_terminal('G', self.net)
        lvs_layer_name = lvs_layer_name or self.metal_names[0]
        if lvs_layer_name not in self.lvs_layer_names:
            self.lvs_layer_names.append(lvs_layer_name)
        self.markers[name] = {self.lvs_layer_names.index(lvs_layer_name): region}

    def build(self, options: Optional[BuilderOptions] = None):
        return PEX25DBuilder(self.context, self.tech, 'test', options).build()


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

    def test_one_label_twice_at_one_position_is_one_terminal(self):
        fixture = TerminalFixture()
        fixture.pin('A', 10, 10)
        fixture.pin('A', 10, 10)
        assert [t.name for t in fixture.build().terminals] == ['pin:A']

    def test_two_labels_at_one_position_are_two_terminals(self):
        fixture = TerminalFixture()
        fixture.pin('A', 10, 10)
        fixture.pin('B', 10, 10)
        file = fixture.build()
        assert [t.name for t in file.terminals] == ['pin:A', 'pin:B']
        assert file.terminals[0].region == file.terminals[1].region

    def test_a_pin_is_on_the_conductor_under_its_label(self):
        fixture = TerminalFixture()
        fixture.geometry['met1'] = kdb.Region(kdb.Box(0, 0, 40, 20))
        fixture.add_net('OTHER', {'met1': kdb.Region(kdb.Box(60, 0, 100, 20))})
        fixture.pin('A', 10, 10)
        fixture.pin('B', 90, 10)
        file = fixture.build()
        assert {t.name: t.conductor for t in file.terminals} == {'pin:A': 'N', 'pin:B': 'OTHER'}
        assert validate(file, strict=True).exit_code == 0

    def test_a_pin_over_two_conductors_reports_a_build_error(self):
        fixture = TerminalFixture()
        fixture.add_net('OTHER', {'met1': kdb.Region(kdb.Box(0, 0, 20, 20))})
        fixture.pin('A', 10, 10)
        with self.assertRaisesRegex(BuildError, "Pin 'A'.*must select one conductor.*found 2"):
            fixture.build()

    def test_a_pin_in_a_hole_of_a_conductor_reports_a_build_error(self):
        # NOTE: in the hole, though within the bounding box of the conductor
        fixture = TerminalFixture()
        fixture.geometry['met1'] -= kdb.Region(kdb.Box(40, 5, 60, 15))
        fixture.pin('A', 50, 10)
        with self.assertRaisesRegex(BuildError, 'must select one conductor.*found 0'):
            fixture.build()

    def test_terminal_names_escape_their_separators_and_round_trip(self):
        fixture = TerminalFixture()
        fixture.pin('block/A:B%[0]', 10, 10)
        fixture.pin('block%2FA:B%[0]', 90, 10)  # NOTE: the first with its / escaped, no collision
        fixture.device('block/M:1', kdb.Region(kdb.Box(50, 0, 60, 20)))
        file = fixture.build()
        expected = {'pin:block%2FA%3AB%25[0]', 'pin:block%252FA%3AB%25[0]', 'device:block%2FM%3A1:G'}
        assert {t.name for t in file.terminals} == expected
        round_tripped = read_pex25d_text(write_pex25d_text(file), '<generated>')
        assert {t.name for t in round_tripped.terminals} == expected
        assert validate(round_tripped, strict=True).exit_code == 0

    def test_a_pin_without_interconnect_reports_a_build_error(self):
        fixture = TerminalFixture()
        fixture.pin('A', 10, 10)
        fixture.geometry['met1'] = kdb.Region(kdb.Box(50, 0, 100, 20))
        with self.assertRaisesRegex(BuildError, 'must select one conductor'):
            fixture.build()

    def test_a_device_terminal_on_the_substrate_has_no_node_and_no_warning(self):
        # NOTE: the substrate is the ground plane, e.g. the terminal bn of the IHP rfcmim on rfmim_sub,
        #       an LVS layer the tech info has no layer for
        fixture = TerminalFixture()
        fixture.tech.tech.substrate.lvs_layer_names.append('sub_marker')
        fixture.device('C1', kdb.Region(kdb.Box(10, 0, 20, 20)), lvs_layer_name='sub_marker')
        with mock.patch('klayout_pex.tech_info.warning') as warning_mock:
            file = fixture.build()
        assert not file.terminals
        warning_mock.assert_not_called()

    def test_a_device_terminal_on_a_diffusion_is_on_the_whole_cuts_of_its_contacts(self):
        # NOTE: the diffusion is device geometry, an empty profile (an anchor) at the lower end of its contacts,
        #       so the terminal (e.g. of a source/drain) is a node at their lower face
        fixture = TerminalFixture(diffusion=True)
        fixture.geometry['cont_nsd'] = kdb.Region(kdb.Box(10, 5, 20, 15))
        fixture.geometry['cont_nsd'].insert(kdb.Box(30, 5, 40, 15))
        fixture.device('M1', kdb.Region(kdb.Box(15, 0, 50, 20)), lvs_layer_name='nsd')  # NOTE: half of a cut
        file = fixture.build()
        assert [(m.name, m.zlow, m.zhigh) for m in file.metals if m.name == 'nsd'] == [('nsd', -1, 0)]
        assert [(v.name, v.connects_below, v.connects_above) for v in file.vias] == [('cont_nsd', 'nsd', 'met1')]
        assert [(t.name, t.layer) for t in file.terminals] == [('device:M1:G', 'cont_nsd')]
        region = file.terminals[0].region
        assert (region.lower_left.x, region.lower_left.y, region.upper_right.x, region.upper_right.y) == \
               (100, 50, 400, 150)
        assert validate(file, strict=True).exit_code == 0

    def test_a_diffusion_without_contact_has_no_profile(self):
        # NOTE: e.g. a tap
        fixture = TerminalFixture(diffusion=True, contact=False)
        fixture.device('M1', kdb.Region(kdb.Box(10, 0, 20, 20)), lvs_layer_name='nsd')
        file = fixture.build()
        assert [m.name for m in file.metals] == ['met1']
        assert not file.vias and not file.terminals

    def test_a_device_terminal_on_an_unknown_layer_is_on_the_metal_it_overlaps_most(self):
        # NOTE: an LVS layer the tech info has no layer for (e.g. the ports of a MOM cap), as in the R extraction
        fixture = TerminalFixture(metal_names=('met1', 'met2'))
        fixture.geometry['met2'] = kdb.Region(kdb.Box(0, 0, 30, 20))
        fixture.device('C1', kdb.Region(kdb.Box(0, 0, 100, 20)), lvs_layer_name='ports')
        fixture.device('C2', kdb.Region(kdb.Box(0, 0, 30, 20)), lvs_layer_name='ports')
        with mock.patch('klayout_pex.tech_info.warning') as warning_mock:
            file = fixture.build()
        assert sorted((t.name, t.layer) for t in file.terminals) == \
               [('device:C1:G', 'met1'), ('device:C2:G', 'met1')]  # NOTE: C2 on the lowest of equals
        warning_mock.assert_not_called()

    def test_a_device_terminal_on_an_unknown_layer_is_on_the_cuts_of_device_contacts_first(self):
        fixture = TerminalFixture(diffusion=True)
        fixture.geometry['cont_nsd'] = kdb.Region(kdb.Box(10, 5, 20, 15))
        fixture.device('M1', kdb.Region(kdb.Box(0, 0, 100, 20)), lvs_layer_name='ports')
        assert [(t.name, t.layer) for t in fixture.build().terminals] == [('device:M1:G', 'cont_nsd')]

    def test_a_device_terminal_on_an_unknown_layer_off_the_interconnect_has_no_node(self):
        # NOTE: e.g. a terminal on a well, reported as in the R extraction
        fixture = TerminalFixture()
        fixture.device('C1', kdb.Region(kdb.Box(200, 0, 300, 20)), lvs_layer_name='well_marker')
        with mock.patch('klayout_pex.klayout.pex25d_builder.warning') as warning_mock:
            file = fixture.build()
        assert not file.terminals
        warning_mock.assert_called_once()
        assert 'nfet terminal G on LVS layer well_marker: C1' in warning_mock.call_args.args[0]

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

    def test_a_device_terminal_off_the_metal_of_its_net_has_no_node(self):
        for lvs_layer_name, marker in (('met2', kdb.Region(kdb.Box(10, 0, 20, 20))),  # NOTE: the net has no met2
                                       ('met1', kdb.Region(kdb.Box(200, 0, 220, 20))),
                                       ('met1', kdb.Region())):
            with self.subTest(lvs_layer_name=lvs_layer_name, marker=str(marker)):
                fixture = TerminalFixture()
                fixture.tech.tech.layers.add(name='met2').drw_gds_pair.layer = 2
                fixture.device('M1', marker, lvs_layer_name=lvs_layer_name)
                file = fixture.build()
                assert len(file.conductors) == 1
                assert not file.terminals

    def test_a_device_terminal_is_on_the_metal_of_its_own_net_only(self):
        fixture = TerminalFixture()
        fixture.add_net('OTHER', {'met1': kdb.Region(kdb.Box(200, 0, 220, 20))})
        fixture.device('M1', kdb.Region(kdb.Box(200, 0, 220, 20)))  # NOTE: on N, over the met1 of OTHER
        file = fixture.build()
        assert len(file.conductors) == 2
        assert not file.terminals

    def test_a_net_without_interconnect_has_no_conductor_and_no_terminal(self):
        fixture = TerminalFixture()
        fixture.geometry.clear()
        fixture.device('M1', kdb.Region(kdb.Box(10, 0, 20, 20)))
        file = fixture.build()
        assert not file.conductors
        assert not file.shapes
        assert not file.terminals

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

    def test_a_device_terminal_on_both_metals_reports_a_build_error(self):
        # NOTE: a node is on one layer
        fixture = self.fixture()
        fixture.device('C1', kdb.Region(kdb.Box(50, 0, 60, 20)), lvs_layer_name='met1_ncap')
        fixture.markers['C1'][fixture.lvs_layer_names.index('met1_cap')] = kdb.Region(kdb.Box(60, 0, 70, 20))
        with self.assertRaisesRegex(BuildError, r"device:C1:G.*spans multiple profiles \(met1_ncap, met1_cap\)"):
            fixture.build()


@allure.parent_suite('Unit Tests')
@allure.tag('PEX25D', 'Builder')
class Pex25DBuilderGridTest(unittest.TestCase):
    def test_a_grid_the_layout_dbu_is_no_multiple_of_reports_a_build_error(self):
        with self.assertRaisesRegex(BuildError, r'layout DBU \(0\.001\) is not an integer multiple'):
            TerminalFixture().build(BuilderOptions(grid_um='0.0003'))

    def test_a_height_of_the_stack_off_the_grid_reports_a_build_error(self):
        fixture = TerminalFixture()
        fixture.tech.process_stack_layer_by_name['met1'].metal_layer.z = 1.00005
        with self.assertRaisesRegex(BuildError, 'met1 bottom: 1.00005 µm is not an integer multiple of the grid'):
            fixture.build()

    def test_decimal_heights_of_the_stack_and_negative_coordinates_are_on_the_grid(self):
        # NOTE: in binary floating point, 0.3262 % 0.0001 is 9.9999999999e-05
        fixture = TerminalFixture()
        fixture.tech.process_stack_layer_by_name['met1'].metal_layer.z = 0.3262
        fixture.geometry['met1'] = kdb.Region(kdb.Box(-100, -20, 0, 0))
        file = fixture.build()
        assert (file.metals[0].zlow, file.metals[0].zhigh) == (3262, 4262)
        assert (file.ground_plane.zlow, file.ground_plane.zhigh) == (-3000, -1000)
        assert (file.shapes[0].box.lower_left.x, file.shapes[0].box.lower_left.y) == (-1000, -200)
        assert validate(file, strict=True).exit_code == 0


@allure.parent_suite('Unit Tests')
@allure.tag('PEX25D', 'Builder')
class Pex25DBuilderShippedStacksTest(unittest.TestCase):
    @staticmethod
    def stack(pdk: PDK, dielectric_filter: Optional[MultipleChoicePattern] = None) -> Any:
        """
        :return: the PEX25D file of the process stack of the PDK, without layout
        """
        tech_info = TechInfo.from_json(pdk.config.tech_pb_json_path, dielectric_filter=dielectric_filter)
        builder = PEX25DBuilder(SimpleNamespace(dbu=0.001), tech_info, 'stack')
        pex25d_file = pex25d_file_pb2().PEX25DFile()
        for build_part in (builder.build_units, builder.build_ground_plane,
                           builder.build_layers, builder.build_dielectrics):
            build_part(pex25d_file)
        return pex25d_file

    def test_no_simple_dielectric_band_is_empty(self):
        # NOTE: the FasterCap export skips an empty band with a warning, e.g. one between two metals at the same z
        #       (sg13g2's ildtm1, between the Metal5 without and with MIM cap)
        for pdk in PDK:
            with self.subTest(pdk=pdk.value):
                scene = resolve(self.stack(pdk))
                assert [d.name for d in scene.dielectrics if d.zhigh <= d.zlow] == []

    def test_dielectric_filter_keeps_the_background(self):
        # NOTE: PEX25D requires one, which fills whatever nothing else claims, --diel none left it out (#450)
        for pdk in PDK:
            background = self.stack(pdk).background
            for pattern in ('none', f'all,-{background.name}'):
                with self.subTest(pdk=pdk.value, pattern=pattern):
                    pex25d_file = self.stack(pdk, MultipleChoicePattern(pattern))
                    assert pex25d_file.background == background
                    report = DiagnosticsReport()
                    resolve(pex25d_file, report=report)
                    assert [d.code for d in report.diagnostics if d.severity == Severity.ERROR] == []

    def test_simple_dielectrics_between_the_top_metal_and_the_background_are_reported(self):
        # NOTE: no metal above bounds them, so they have no extent; gf180mcuD's pass and sin became the background
        #       in turn, silently, until air replaced them (#470)
        with mock.patch('klayout_pex.klayout.pex25d_builder.warning') as warning_mock:
            pex25d_file = self.stack(PDK.GF180MCUD)
        assert pex25d_file.background.name == 'air'
        assert [c.args[0] for c in warning_mock.call_args_list] == [
            f"Simple dielectric '{name}' has no metal above it in the process stack to bound it; skipping"
            for name in ('pass', 'sin')]
