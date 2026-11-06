#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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

import os
import tempfile
from typing import *
import unittest
from unittest import mock

import allure
import klayout.db as kdb

from klayout_pex.klayout.lvsdb_extractor import (
    KLayoutExtractedLayerInfo,
    KLayoutExtractionContext,
    KLayoutMergedExtractedLayerInfo,
    LVSDBError,
    subcell_label_name
)
from klayout_pex.pdk_config import PDK
from klayout_pex.types import LVSLayerName, NetName
from klayout_pex.tech_info import TechInfo
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2
from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.pdk_test_config import PDKName, PDKTestConfig


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "LVSDB")
class Test(unittest.TestCase):
    # NOTE: the IHP LVS script replaced the extracted rfnmos by a newly created
    #       sg13_lv_nmos (RF MOS model mapping), which has no device abstract,
    #       and left the abstract of the extracted one as a second top cell
    cell_name = 'rfnmos_w1u_l0u72'

    @property
    def lvsdb_path(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'testdata', 'klayout', 'lvs',
                                             f"{self.cell_name}_broken_rfmos_model_mapping.lvsdb.gz"))

    @property
    def tech_info_json_path(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'klayout_pex_protobuf', 'ihp-sg13g2_tech.pb.json'))

    def tech_info(self,
                  renamed_layers_derived_from: Optional[str] = None,
                  device_internal_layers: Collection[LVSLayerName] = ()) -> TechInfo:
        tech = TechInfo.parse_tech_def(jsonpb_path=self.tech_info_json_path)
        for layer in tech.lvs_computed_layers:
            # NOTE: e.g. like gf180mcuD, whose tech info names the contacts differently than its LVS deck
            if layer.original_layer_name == renamed_layers_derived_from:
                layer.layer_info.name += '_renamed'
            if layer.layer_info.name in device_internal_layers:
                layer.kind = tech_pb2.ComputedLayerInfo.Kind.KIND_DEVICE_INTERNAL
        return TechInfo(tech=tech, dielectric_filter=None)

    def prepare_extraction(self, tech: Optional[TechInfo] = None) -> KLayoutExtractionContext:
        lvsdb = kdb.LayoutVsSchematic()
        lvsdb.read(self.lvsdb_path)
        return KLayoutExtractionContext.prepare_extraction(top_cell=self.cell_name,
                                                           lvsdb=lvsdb,
                                                           tech=tech or self.tech_info(),
                                                           blackbox_devices=False)

    def test_unnamed_layer_partly_covered_by_derived_layers_is_a_warning(self):
        # the contacts to the taps (e.g. the guard ring) have no layer in the tech info
        with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning') as warning:
            pex_context = self.prepare_extraction()
        self.assertIn("The extraction leaves out these LVS layers, as the tech info doesn't know them:\n"
                      "  - cont_drw (Cont): 36 of 46 shapes are not within cont_nsd_con, cont_psd_con, cont_poly_con, "
                      "schottcky_p, schottcky_n_con, diodevdd_4kv_te, diodevss_4kv_te",
                      [call.args[0] for call in warning.call_args_list])
        self.assertEqual([], pex_context.unmodeled_layers)

    def test_unnamed_layer_without_derived_layers_is_unmodeled(self):
        pex_context = self.prepare_extraction(tech=self.tech_info(renamed_layers_derived_from='Cont'))
        self.assertEqual(['cont_drw (Cont): the tech info has no layer derived from it'],
                         pex_context.unmodeled_layers)

    def test_layers_within_devices_are_known_but_not_extracted(self):
        # e.g. the contacts and the emitter windows of bipolar transistors, whose models have their resistances
        with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning') as warning:
            pex_context = self.prepare_extraction(tech=self.tech_info(device_internal_layers=['cont_nsd_con']))
        lvs_layer_names = {sl.lvs_layer_name for layer in pex_context.extracted_layers.values()
                           for sl in layer.source_layers}
        self.assertNotIn('cont_nsd_con', lvs_layer_names)
        self.assertIn('cont_poly_con', lvs_layer_names)
        self.assertEqual([], pex_context.unmodeled_layers)
        # NOTE: they still cover the shapes of the layer they are derived from
        self.assertIn("The extraction leaves out these LVS layers, as the tech info doesn't know them:\n"
                      "  - cont_drw (Cont): 36 of 46 shapes are not within cont_nsd_con, cont_psd_con, cont_poly_con, "
                      "schottcky_p, schottcky_n_con, diodevdd_4kv_te, diodevss_4kv_te",
                      [call.args[0] for call in warning.call_args_list])

    def test_leftover_top_cells_are_ignored_with_a_warning(self):
        with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning') as warning:
            pex_context = self.prepare_extraction()
        messages = [call.args[0] for call in warning.call_args_list]
        self.assertTrue(any('D$rfnmos' in m for m in messages), messages)
        self.assertFalse(pex_context.top_cell_bbox().empty())

    def test_a_device_without_layout_geometry_is_an_error(self):
        pex_context = self.prepare_extraction()
        with self.assertRaises(LVSDBError) as cm:
            pex_context.devices_by_name
        self.assertIn('$1 (sg13_lv_nmos)', str(cm.exception))


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "LVSDB", "Net Names")
class NetNameTest(unittest.TestCase):
    def test_nets_get_the_unique_names_of_the_spice_writer(self):
        # NOTE: nets can share a name, e.g. the metal islands of a supply, joined only in the parent (#211 §10)
        netlist = kdb.Netlist()
        circuit = kdb.Circuit()
        circuit.name = 'TOP'
        netlist.add(circuit)
        for name in ('D', 'S', 'D', 'D$1', 'D', ''):
            circuit.connect_pin(circuit.create_pin(''), circuit.create_net(name))

        with tempfile.TemporaryDirectory() as tmp_dir:
            spice_path = os.path.join(tmp_dir, 'netlist.cir')
            writer = kdb.NetlistSpiceWriter()
            writer.use_net_names = True
            netlist.write(spice_path, writer)
            with open(spice_path, encoding='utf-8') as f:
                subckt_line = next(line for line in f if line.startswith('.SUBCKT'))
        spice_names = [name.replace('\\', '') for name in subckt_line.split()[2:]]

        KLayoutExtractionContext.make_net_names_unique(netlist)

        self.assertEqual(['D', 'S', 'D$1', 'D$1$1', 'D$2', '$0'], [n.expanded_name() for n in circuit.each_net()])
        self.assertEqual(spice_names, [n.expanded_name() for n in circuit.each_net()])

    def test_net_names_are_unique_regardless_of_case(self):
        # NOTE: SPICE reads names case-insensitively, ngspice joins the nets a and A
        netlist = kdb.Netlist()
        circuit = kdb.Circuit()
        circuit.name = 'TOP'
        netlist.add(circuit)
        for name in ('A', 'a', 'B', 'b$1', 'B'):
            circuit.create_net(name)

        KLayoutExtractionContext.make_net_names_unique(netlist)

        self.assertEqual(['A', 'a$1', 'B', 'b$1', 'B$2'], [n.expanded_name() for n in circuit.each_net()])

    def test_nets_without_label_keep_their_shapes(self):
        # NOTE: KLayout 0.30.4 (CI) reads the nets without a label from the LVSDB without a name
        #       (newer versions with the expanded one, e.g. $2), but the extraction finds the shapes of a net
        #       by the name on them, so the nets $2 and $3 of the nfet had no shapes and no resistor network
        testdata_dir = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata', 'klayout', 'lvs'))
        lvsdb = kdb.LayoutVsSchematic()
        lvsdb.read(os.path.join(testdata_dir, 'nfet_li1_redux_reordered_lvs_layers.lvsdb.gz'))
        for net in lvsdb.netlist().circuit_by_name('nfet_li1_redux').each_net():
            if net.name.startswith('$'):
                net.name = ''
        tech = TechInfo(tech=TechInfo.parse_tech_def(jsonpb_path=os.path.realpath(os.path.join(
                            __file__, '..', '..', '..', 'klayout_pex_protobuf', 'sky130A_tech.pb.json'))),
                        dielectric_filter=None)

        with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning'):
            pex_context = KLayoutExtractionContext.prepare_extraction(top_cell='nfet_li1_redux',
                                                                      lvsdb=lvsdb,
                                                                      tech=tech,
                                                                      blackbox_devices=False)

        circuit = pex_context.lvsdb.netlist().circuit_by_name('nfet_li1_redux')
        self.assertEqual(['G', '$2', '$3', 'sky130_gnd'], [n.name for n in circuit.each_net()])
        for net in circuit.each_net():
            if net.name in ('$2', '$3'):
                shape_count = sum(pex_context.shapes_of_net(gds_pair, net).count()
                                  for gds_pair in pex_context.extracted_layers)
                self.assertGreater(shape_count, 0, net.name)

    def test_shapes_of_net_are_a_copy(self):
        # NOTE: the shapes of all nets are taken in one pass over each layer, and kept,
        #       so a caller changing the shapes of a net must not change them for the next one
        testdata_dir = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata', 'klayout', 'lvs'))
        lvsdb = kdb.LayoutVsSchematic()
        lvsdb.read(os.path.join(testdata_dir, 'nfet_li1_redux_reordered_lvs_layers.lvsdb.gz'))
        tech = TechInfo(tech=TechInfo.parse_tech_def(jsonpb_path=os.path.realpath(os.path.join(
                            __file__, '..', '..', '..', 'klayout_pex_protobuf', 'sky130A_tech.pb.json'))),
                        dielectric_filter=None)
        with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning'):
            pex_context = KLayoutExtractionContext.prepare_extraction(top_cell='nfet_li1_redux',
                                                                      lvsdb=lvsdb,
                                                                      tech=tech,
                                                                      blackbox_devices=False)

        gds_pair, net_name = next((gds_pair, shape.property('net'))
                                  for gds_pair, lyr in pex_context.extracted_layers.items()
                                  for sl in lyr.source_layers
                                  for shape in sl.region.each())
        shapes = pex_context.shapes_of_net(gds_pair, net_name)
        count = shapes.count()
        self.assertGreater(count, 0)
        shapes.clear()
        self.assertEqual(count, pex_context.shapes_of_net(gds_pair, net_name).count())
        self.assertTrue(pex_context.shapes_of_net(gds_pair, 'no such net').is_empty())


def pattern_context(pdk_name: PDKName,
                    cell_name: str,
                    net_names: Mapping[NetName, NetName] = {}) -> Tuple[KLayoutExtractionContext, List[str]]:
    """
    :param net_names: new names of nets of the LVS netlist, given before the extraction
    :return: the extraction context of the test pattern, from its committed LVS database, and the warnings
    """
    lvsdb = kdb.LayoutVsSchematic()
    lvsdb.read(lvsdb_fixture_path(str(pdk_name), PDKTestConfig(pdk_name).gds_path('test_patterns',
                                                                                  f"{cell_name}.gds.gz")))
    for old_name, new_name in net_names.items():
        lvsdb.netlist().circuit_by_name(cell_name).net_by_name(old_name).name = new_name
    tech = TechInfo.from_json(PDK.from_string(str(pdk_name)).config.tech_pb_json_path, dielectric_filter=None)
    with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning') as warning:
        pex_context = KLayoutExtractionContext.prepare_extraction(top_cell=cell_name, lvsdb=lvsdb, tech=tech,
                                                                  blackbox_devices=False)
    return pex_context, [call.args[0] for call in warning.call_args_list]


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "LVSDB", "Net Names", "Pins")
class SubcellLabelNameTest(unittest.TestCase):
    def test_subcell_label_name(self):
        for net_name, labels, expected in (
                ('$1.D', {'D'}, 'D'),
                ('$1.$2.D', {'D'}, 'D'),
                ('$1.d', {'D'}, 'd'),
                ('$1.D$1', {'D'}, 'D'),
                ('$1.A,B', {'A', 'B'}, 'A,B'),
                ('$1.A,$2.B', {'A', 'B'}, 'A,B'),
                ('$1.VDD,X', {'VDD', 'X'}, 'VDD,X'),
                ('$1.a.b', {'a.b', 'b'}, 'a.b'),
                ('bus.0', {'bus.0'}, None),
                ('a.b', {'a.b', 'b'}, None),
                ('$1.D', set(), None),
                ('$1.D', {'G'}, None),
                ('$1.A,B', {'A'}, None),
        ):
            with self.subTest(net_name=net_name, labels=labels):
                self.assertEqual(expected, subcell_label_name(net_name, labels))

    def test_ports_of_labels_only_in_a_subcell_are_named_after_them(self):
        # NOTE: the PEX-LVS flattens the subcell SUBNFET, whose labels KLayout names the nets after
        #       with the path of the subcircuit, $1.D, $1.G and $1.S (#330), unlike the pins of a schematic (#417)
        pex_context, warnings = pattern_context(PDKName.SKY130A, 'nfet_li1_in_subcell')
        circuit = pex_context.top_circuit
        self.assertEqual(['sky130_gnd', 'S', 'G', 'D'], [net.name for net in circuit.each_net()])
        self.assertEqual(['D', 'G', 'S', 'sky130_gnd'], sorted(pin.name() for pin in circuit.each_pin()))
        self.assertIn("Ports named after labels in subcells: D, G, S "
                      "(label them in the top cell to name ports explicitly)", warnings)
        # NOTE: also on the shapes of the annotated layout, which the extraction finds the shapes of a net by
        self.assertTrue(any(not pex_context.shapes_of_net(gds_pair, 'D').is_empty()
                            for gds_pair in pex_context.extracted_layers))
        self.assertEqual({'D', 'G', 'S'}, {pin.net_name for pins in pex_context.pins_pb2_by_layer.values()
                                           for pin in pins})

    def test_pin_label_only_in_a_subcell_names_the_port_of_a_wire(self):
        # NOTE: a wire without devices, whose port the pin label makes later (see make_pins_of_pin_labels)
        pex_context, warnings = pattern_context(PDKName.IHP_SG13G2, 'label_only_in_child_cell')
        self.assertEqual(['inner'], [pin.name() for pin in pex_context.top_circuit.each_pin()])
        self.assertIn("Ports named after labels in subcells: inner "
                      "(label them in the top cell to name ports explicitly)", warnings)

    def test_labels_of_instances_of_a_cell_keep_their_paths(self):
        # NOTE: the cell of the nfet in 8 orientations, each with the label G
        pex_context, warnings = pattern_context(PDKName.SKY130A, 'nfet_li1_redux_orientations')
        self.assertEqual([f"${index}.G" for index in range(1, 9)],
                         sorted(pin.name() for pin in pex_context.top_circuit.each_pin() if '.' in pin.name()))
        self.assertFalse([w for w in warnings if 'labels in subcells' in w], warnings)

    def test_labels_of_subcells_name_the_ports_where_unique(self):
        # NOTE: the label MET4 is in one of the cells of the PDK only, the labels C0 and C1 in each of the 4 VPP caps
        pex_context, warnings = pattern_context(PDKName.SKY130A, 'cap_vpp_routing_across')
        pin_names = [pin.name() for pin in pex_context.top_circuit.each_pin()]
        self.assertIn('MET4', pin_names)
        self.assertEqual([f"${index}.{label}" for index in range(1, 5) for label in ('C0', 'C1')],
                         sorted(name for name in pin_names if '.' in name))
        self.assertIn("Ports named after labels in subcells: MET4 "
                      "(label them in the top cell to name ports explicitly)", warnings)

    def test_label_of_a_subcell_beside_a_net_of_its_name_keeps_its_path(self):
        # NOTE: regardless of case, as SPICE reads names
        pex_context, warnings = pattern_context(PDKName.SKY130A, 'nfet_li1_in_subcell', net_names={'sky130_gnd': 'd'})
        self.assertEqual(['$1.D', 'G', 'S', 'd'], sorted(net.name for net in pex_context.top_circuit.each_net()))
        self.assertIn("Ports named after labels in subcells: G, S "
                      "(label them in the top cell to name ports explicitly)", warnings)


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "LVSDB", "Pins")
class PinsTest(unittest.TestCase):
    def test_the_pins_of_a_pin_layer_with_several_lvs_layers(self):
        # NOTE: e.g. gf180mcuD, which has no pin layers (the pins are labels on the drawn layers),
        #       and splits Metal4 into the bottom plates of the MIM caps and the rest
        tech = tech_pb2.Technology(name='test')
        tech.layers.add(name='Metal4',
                        drw_gds_pair=tech_pb2.GDSPair(layer=46, datatype=0),
                        pin_gds_pair=tech_pb2.GDSPair(layer=46, datatype=0))

        def extracted_layer(lvs_layer_name: str, box: kdb.Box, net_name: str) -> KLayoutExtractedLayerInfo:
            region = kdb.Region()
            region.insert(kdb.PolygonWithProperties(kdb.Polygon(box), {'net': net_name}))
            return KLayoutExtractedLayerInfo(index=0, lvs_layer_name=lvs_layer_name, gds_pair=(46, 0), region=region)

        source_layers = [extracted_layer('metal4_n_cap', kdb.Box(0, 0, 100, 100), 'BOT'),
                         extracted_layer('metal4_cap', kdb.Box(100, 0, 300, 100), 'BOT'),
                         extracted_layer('metal4_n_cap', kdb.Box(400, 0, 500, 100), 'OTHER')]
        pex_context = KLayoutExtractionContext(
            lvsdb=None, tech=TechInfo(tech=tech, dielectric_filter=None), dbu=0.001,
            layer_index_map={}, lvsdb_regions={}, cell_mapping=None,
            annotated_top_cell=None, annotated_layout=None,
            extracted_layers={(46, 0): KLayoutMergedExtractedLayerInfo(source_layers=source_layers, gds_pair=(46, 0))},
            unnamed_layers=[], unmodeled_layers=[], blackbox_devices=False
        )

        pins = pex_context.pins_of_layer((46, 0))

        self.assertEqual([('BOT', kdb.Box(0, 0, 100, 100)), ('BOT', kdb.Box(100, 0, 300, 100)),
                          ('OTHER', kdb.Box(400, 0, 500, 100))],
                         sorted((p.property('net'), p.bbox()) for p in pins.each()))


def lvsdb_context(cell_name: str, tech_name: str) -> KLayoutExtractionContext:
    """
    The extraction context of the LVS database of the cell in testdata/klayout/lvs, with the tech info of the PDK
    """
    repo_dir = os.path.realpath(os.path.join(__file__, '..', '..', '..'))
    lvsdb = kdb.LayoutVsSchematic()
    lvsdb.read(os.path.join(repo_dir, 'testdata', 'klayout', 'lvs', f"{cell_name}.lvsdb.gz"))
    tech = TechInfo(tech=TechInfo.parse_tech_def(jsonpb_path=os.path.join(
                        repo_dir, 'klayout_pex_protobuf', f"{tech_name}_tech.pb.json")),
                    dielectric_filter=None)

    with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning'):
        return KLayoutExtractionContext.prepare_extraction(top_cell=cell_name,
                                                           lvsdb=lvsdb,
                                                           tech=tech,
                                                           blackbox_devices=False)


def nfet_li1_redux_orientations_context() -> KLayoutExtractionContext:
    """
    The nfet of nfet_li1_redux in the 8 orientations (r0 to m135), whose devices share one abstract
    """
    return lvsdb_context('nfet_li1_redux_orientations', 'sky130A')


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "LVSDB", "Devices")
class TerminalShapesTest(unittest.TestCase):
    def test_terminal_shapes_of_a_device_abstract_in_each_orientation(self):
        # NOTE: the devices share one abstract, so the shapes of its terminals are taken once and moved to each
        pex_context = nfet_li1_redux_orientations_context()

        devices = list(pex_context.top_circuit.each_device())
        self.assertEqual(set(range(8)), {d.trans.rot() for d in devices})
        for d in devices:
            terminals_with_shapes = set()
            for td in d.device_class().terminal_definitions():
                for nt in d.net_for_terminal(td.id()).each_terminal():
                    if nt.device().id() != d.id() or nt.terminal_id() != td.id():
                        continue
                    expected = pex_context.lvsdb.shapes_of_terminal(nt)
                    shapes = pex_context.shapes_of_terminal(d, nt)
                    self.assertEqual(sorted(expected.keys()), sorted(shapes.keys()))
                    for idx, region in expected.items():
                        self.assertTrue((region ^ shapes[idx]).is_empty(),
                                        f"device {d.expanded_name()} ({d.trans}), terminal {td.name}")
                        if not region.is_empty():
                            terminals_with_shapes.add(td.name)
            self.assertEqual({'S', 'G', 'D'}, terminals_with_shapes)  # NOTE: the bulk B has no shapes of its own
        self.assertEqual(4, len(pex_context.terminal_shapes_by_abstract))  # S, G, D, B of the one abstract


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "LVSDB", "Devices")
class TerminalOnNetTest(unittest.TestCase):
    def test_terminal_abutting_a_conductor_of_its_net_is_on_it(self):
        # The ports of an IHP inductor are within its marker (IND), where the LVS deck leaves out the TopMetal2
        # of the winding, and abut their TopMetal2 leads outside it, which LVS joins to them by IND.pin over both,
        # so they are on the ends of the leads, rather than without a node in the resistance network (#351)
        pex_context = lvsdb_context('inductor2_w2u_d15u48_1_turn', 'ihp-sg13g2')
        inductor, = pex_context.devices_by_name.values()
        self.assertEqual({'inductor_1': ['TopMetal2'], 'inductor_2': ['TopMetal2'], 'inductor_sub': ['PWell']},
                         {t.name: [r.layer.canonical_layer_name for r in t.region_by_layer]
                          for t in inductor.terminals})


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "LVSDB")
class ShapesOfLVSLayersTest(unittest.TestCase):
    def test_shapes_of_some_of_the_lvs_layers_of_a_gds_pair(self):
        # NOTE: e.g. sky130A met3, split into the bottom plates of the MIM caps (met3_cap) and the rest (met3_ncap),
        #       which are layers of the process stack of their own
        def extracted_layer(lvs_layer_name: LVSLayerName,
                            boxes_by_net: Dict[NetName, List[kdb.Box]]) -> KLayoutExtractedLayerInfo:
            region = kdb.Region()
            for net_name, boxes in boxes_by_net.items():
                for box in boxes:
                    region.insert(kdb.PolygonWithProperties(kdb.Polygon(box), {'net': net_name}))
            return KLayoutExtractedLayerInfo(index=0, lvs_layer_name=lvs_layer_name, gds_pair=(70, 20), region=region)

        source_layers = [extracted_layer('met3_ncap', {'A': [kdb.Box(0, 0, 100, 100)], 'B': [kdb.Box(200, 0, 300, 100)]}),
                         extracted_layer('met3_cap', {'A': [kdb.Box(400, 0, 500, 100)]})]
        pex_context = KLayoutExtractionContext(
            lvsdb=None, tech=TechInfo(tech=tech_pb2.Technology(name='test'), dielectric_filter=None), dbu=0.001,
            layer_index_map={}, lvsdb_regions={}, cell_mapping=None,
            annotated_top_cell=None, annotated_layout=None,
            extracted_layers={(70, 20): KLayoutMergedExtractedLayerInfo(source_layers=source_layers, gds_pair=(70, 20))},
            unnamed_layers=[], unmodeled_layers=[], blackbox_devices=False
        )

        def boxes(region: kdb.Region) -> List[kdb.Box]:
            return [p.bbox() for p in region.each()]

        self.assertEqual([kdb.Box(0, 0, 100, 100), kdb.Box(400, 0, 500, 100)],
                         boxes(pex_context.shapes_of_net((70, 20), 'A')))
        self.assertEqual([kdb.Box(400, 0, 500, 100)],
                         boxes(pex_context.shapes_of_net((70, 20), 'A', lvs_layer_names=['met3_cap'])))
        self.assertEqual([], boxes(pex_context.shapes_of_net((70, 20), 'B', lvs_layer_names=['met3_cap'])))
        self.assertIsNone(pex_context.shapes_of_net((70, 20), 'A', lvs_layer_names=['met4_cap']))
        self.assertEqual([('A', kdb.Box(0, 0, 100, 100)), ('B', kdb.Box(200, 0, 300, 100))],
                         [(p.property('net'), p.bbox())
                          for p in pex_context.shapes_of_layer((70, 20), lvs_layer_names=['met3_ncap']).each()])
        self.assertEqual(3, pex_context.shapes_of_layer((70, 20)).count())


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "LVSDB")
class MOSChannelsTest(unittest.TestCase):
    def test_channels_are_the_gates_of_the_transistors(self):
        # NOTE: the capacitances of the channels are the transistor models' (#290)
        pex_context = nfet_li1_redux_orientations_context()
        channels = pex_context.mos_channels
        self.assertEqual(8, channels.count())
        self.assertAlmostEqual(sum(d.parameter('W') * d.parameter('L') for d in pex_context.top_circuit.each_device()),
                               channels.area() * pex_context.dbu ** 2, places=6)
