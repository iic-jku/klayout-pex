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
    LVSDBError
)
from klayout_pex.tech_info import TechInfo
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2


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

    def tech_info(self, renamed_layers_derived_from: Optional[str] = None) -> TechInfo:
        tech = TechInfo.parse_tech_def(jsonpb_path=self.tech_info_json_path)
        # NOTE: e.g. like gf180mcuD, whose tech info names the contacts differently than its LVS deck
        for layer in tech.lvs_computed_layers:
            if layer.original_layer_name == renamed_layers_derived_from:
                layer.layer_info.name += '_renamed'
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
                      "  - cont_drw (Cont): 36 of 46 shapes are not within cont_nsd_con, cont_psd_con, cont_poly_con",
                      [call.args[0] for call in warning.call_args_list])
        self.assertEqual([], pex_context.unmodeled_layers)

    def test_unnamed_layer_without_derived_layers_is_unmodeled(self):
        pex_context = self.prepare_extraction(tech=self.tech_info(renamed_layers_derived_from='Cont'))
        self.assertEqual(['cont_drw (Cont): the tech info has no layer derived from it'],
                         pex_context.unmodeled_layers)

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
            with open(spice_path) as f:
                subckt_line = next(line for line in f if line.startswith('.SUBCKT'))
        spice_names = [name.replace('\\', '') for name in subckt_line.split()[2:]]

        KLayoutExtractionContext.make_net_names_unique(netlist)

        self.assertEqual(['D', 'S', 'D$1', 'D$1$1', 'D$2', '$0'], [n.expanded_name() for n in circuit.each_net()])
        self.assertEqual(spice_names, [n.expanded_name() for n in circuit.each_net()])

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


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "LVSDB", "Devices")
class TerminalShapesTest(unittest.TestCase):
    def test_terminal_shapes_of_a_device_abstract_in_each_orientation(self):
        # NOTE: the nfet of nfet_li1_redux in the 8 orientations (r0 to m135), whose devices share one abstract,
        #       so the shapes of its terminals are taken once and moved to each device
        testdata_dir = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata', 'klayout', 'lvs'))
        lvsdb = kdb.LayoutVsSchematic()
        lvsdb.read(os.path.join(testdata_dir, 'nfet_li1_redux_orientations.lvsdb.gz'))
        tech = TechInfo(tech=TechInfo.parse_tech_def(jsonpb_path=os.path.realpath(os.path.join(
                            __file__, '..', '..', '..', 'klayout_pex_protobuf', 'sky130A_tech.pb.json'))),
                        dielectric_filter=None)

        with mock.patch('klayout_pex.klayout.lvsdb_extractor.warning'):
            pex_context = KLayoutExtractionContext.prepare_extraction(top_cell='nfet_li1_redux_orientations',
                                                                      lvsdb=lvsdb,
                                                                      tech=tech,
                                                                      blackbox_devices=False)

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
