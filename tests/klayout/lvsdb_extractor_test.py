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

from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext, LVSDBError
from klayout_pex.tech_info import TechInfo


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
