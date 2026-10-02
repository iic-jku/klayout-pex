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

import os
from typing import *
import unittest
from unittest import mock

import allure
import klayout.db as kdb
import klayout.pex as klp

from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.rcx25.r.r_extractor import RExtractionTechError, RExtractor
from klayout_pex.tech_info import TechInfo
from klayout_pex_protobuf.kpex.klayout.r_extractor_tech_pb2 import RExtractorTech
import klayout_pex_protobuf.kpex.r.r_network_pb2 as r_network_pb2
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2


REPO_DIR = os.path.realpath(os.path.join(__file__, '..', '..', '..'))


def ihp_sg13g2_tech() -> tech_pb2.Technology:
    return TechInfo.parse_tech_def(jsonpb_path=os.path.join(REPO_DIR, 'klayout_pex_protobuf', 'ihp-sg13g2_tech.pb.json'))


def sky130a_tech() -> tech_pb2.Technology:
    return TechInfo.parse_tech_def(jsonpb_path=os.path.join(REPO_DIR, 'klayout_pex_protobuf', 'sky130A_tech.pb.json'))


def r_extractor(tech: tech_pb2.Technology,
                top_cell: str = 'rfnmos_w1u_l0u72',
                lvsdb_file_name: str = 'rfnmos_w1u_l0u72.lvsdb.gz',
                skip_simplify: bool = False) -> RExtractor:
    lvsdb = kdb.LayoutVsSchematic()
    lvsdb.read(os.path.join(REPO_DIR, 'testdata', 'klayout', 'lvs', lvsdb_file_name))
    pex_context = KLayoutExtractionContext.prepare_extraction(top_cell=top_cell,
                                                              lvsdb=lvsdb,
                                                              tech=TechInfo(tech=tech, dielectric_filter=None),
                                                              blackbox_devices=False)
    return RExtractor(pex_context=pex_context,
                      substrate_algorithm=RExtractorTech.Algorithm.ALGORITHM_TESSELATION,
                      wire_algorithm=RExtractorTech.Algorithm.ALGORITHM_SQUARE_COUNTING,
                      delaunay_b=0.5,
                      delaunay_amax=0.0,
                      via_merge_distance=0.0,
                      skip_simplify=skip_simplify)


@allure.parent_suite("Unit Tests")
@allure.tag("R", "Tech")
class RExtractorTechTest(unittest.TestCase):
    def assert_unmodeled_layers_error(self, tech: tech_pb2.Technology, *layers: str):
        with self.assertRaises(RExtractionTechError) as cm:
            r_extractor(tech).prepare_r_extractor_tech_pb(RExtractorTech())
        self.assertEqual("The tech info can't model these layers of the layout for the resistance extraction, "
                         "so their connections would be missing from the resistance network:\n" +
                         '\n'.join(f"  - {layer}" for layer in layers),
                         str(cm.exception))

    def test_lvs_layer_without_layer_in_the_tech_info_is_an_error(self):
        # NOTE: like gf180mcuD, whose tech info named the contacts differently than its LVS deck
        tech = ihp_sg13g2_tech()
        for layer in tech.lvs_computed_layers:
            if layer.original_layer_name == 'Cont':
                layer.layer_info.name += '_renamed'
        self.assert_unmodeled_layers_error(tech, "cont_drw (Cont): the tech info has no layer derived from it")

    def test_layer_without_model_is_an_error(self):
        tech = ihp_sg13g2_tech()
        del tech.process_parasitics.resistance.contacts[:]
        self.assert_unmodeled_layers_error(tech,
                                           "Cont (LVS cont_poly_con): no contact resistance for poly_con",
                                           "Cont (LVS cont_nsd_con): no contact resistance for nsd_fet")

    def test_metal_without_sheet_resistance_is_an_error(self):
        # NOTE: it crashed with an AttributeError on the missing resistance
        tech = ihp_sg13g2_tech()
        layers = tech.process_parasitics.resistance.layers
        layers.remove(next(r for r in layers if r.layer_name == 'Metal1'))
        self.assert_unmodeled_layers_error(tech, "Metal1 (LVS metal1_n_mom): no sheet resistance")

    def test_mim_cap_top_plate_is_a_conductor(self):
        # NOTE: the white-box extraction keeps the top plates of the MIM caps (e.g. sky130A capm, IHP cmim_top),
        #       which stopped it with "unhandled layer purpose PURPOSE_MIM_CAP", here Metal1 stands in for one
        tech = ihp_sg13g2_tech()
        for layer in tech.lvs_computed_layers:
            if layer.layer_info.name == 'metal1_n_mom':
                layer.layer_info.purpose = tech_pb2.LayerInfo.PURPOSE_MIM_CAP

        rex_tech = r_extractor(tech).prepare_r_extractor_tech_pb(RExtractorTech())

        self.assertEqual([0.11], [c.resistance for c in rex_tech.conductors if c.layer.lvs_layer_name == 'metal1_n_mom'])

    def test_layer_modeled_by_another_layer_of_its_gds_pair_is_no_error(self):
        # e.g. sky130A mcon_vpp (the vias within MOM caps), on the GDS pair of mcon_con:
        # the resistance extraction models the layer of the GDS pair, with the shapes of both
        tech = ihp_sg13g2_tech()
        layers = {layer.layer_info.name: layer for layer in tech.lvs_computed_layers}
        layers['cont_poly_con'].layer_info.drw_gds_pair.CopyFrom(layers['cont_nsd_con'].layer_info.drw_gds_pair)
        for layer in tech.process_stack.layers:
            if layer.metal_layer.contact_above.name == 'cont_poly_con':
                layer.metal_layer.contact_above.name = 'renamed'

        rex_tech = r_extractor(tech).prepare_r_extractor_tech_pb(RExtractorTech())

        self.assertIn('cont_nsd_con', [via.layer.lvs_layer_name for via in rex_tech.vias])
        self.assertNotIn('cont_poly_con', [via.layer.lvs_layer_name for via in rex_tech.vias])


@allure.parent_suite("Unit Tests")
@allure.tag("R", "Tech")
class RExtractorWellTest(unittest.TestCase):
    # NOTE: the IHP pwell stands in for a well, unless the tech info names the substrate (pwell_sub, on its GDS pair)
    @staticmethod
    def pwell_conductors(resistance: Optional[float], substrate: bool) -> List[Tuple[str, float]]:
        tech = ihp_sg13g2_tech()
        if not substrate:
            del tech.substrate.lvs_layer_names[:]
        if resistance is not None:
            tech.process_parasitics.resistance.layers.add(layer_name='PWell', resistance=resistance)
        rex_tech = r_extractor(tech).prepare_r_extractor_tech_pb(RExtractorTech())
        return sorted((c.layer.lvs_layer_name, c.resistance) for c in rex_tech.conductors
                      if c.layer.canonical_layer_name == 'PWell')

    def test_well_is_a_conductor(self):
        # NOTE: it was left out without a word, so the device terminals on it were ideally on their nets
        self.assertEqual([('pwell', 3000.0), ('pwell_sub', 3000.0)],
                         self.pwell_conductors(resistance=3000000, substrate=False))

    def test_substrate_is_no_conductor(self):
        # NOTE: the substrate is ideal, as it is 3D bulk rather than a sheet
        with mock.patch('klayout_pex.rcx25.r.r_extractor.warning') as warning_mock:
            self.assertEqual([], self.pwell_conductors(resistance=3000000, substrate=True))
        warning_mock.assert_not_called()

    def test_well_without_sheet_resistance_is_no_conductor(self):
        with mock.patch('klayout_pex.rcx25.r.r_extractor.warning') as warning_mock:
            self.assertEqual([], self.pwell_conductors(resistance=None, substrate=False))
        self.assertEqual([
            "The resistance network leaves out these wells, as the tech info has no sheet resistance for them, "
            "so the device terminals on them (e.g. the PMOS bulks) are ideally on their nets:\n"
            "  - PWell (LVS pwell)\n"
            "  - PWell (LVS pwell_sub)"
        ], [c.args[0] for c in warning_mock.call_args_list])


def network_of_metal_and_well(joined_by_via: bool, with_metal: bool = True) -> klp.RNetwork:
    """
    A wire (layer 0) with a pin, and a well (layer 1) with a device terminal (e.g. a PMOS bulk),
    joined by a contact (layer 2), or not
    """
    tech = klp.RExtractorTech()
    tech.skip_simplify = True
    for layer in (0, 1):
        conductor = klp.RExtractorTechConductor()
        conductor.layer = layer
        conductor.algorithm = klp.Algorithm.SquareCounting
        conductor.resistance = 1.0
        tech.add_conductor(conductor)
    regions = {1: kdb.Region(kdb.Box(0, 0, 10000, 1000))}
    vertex_ports = {}
    if with_metal:
        regions[0] = kdb.Region(kdb.Box(9000, 0, 20000, 1000))
        vertex_ports[0] = [kdb.Point(19500, 500)]
    if joined_by_via:
        via = klp.RExtractorTechVia()
        via.cut_layer = 2
        via.bottom_conductor = 1
        via.top_conductor = 0
        via.resistance = 1.0
        tech.add_via(via)
        regions[2] = kdb.Region(kdb.Box(9400, 400, 9600, 600))
    polygon_ports = {1: [kdb.Polygon(kdb.Box(1000, 0, 1200, 1000))]}
    return klp.RNetExtractor(0.001).extract(tech, regions, vertex_ports, polygon_ports)


@allure.parent_suite("Unit Tests")
@allure.tag("R", "Wells")
class RExtractorIsolatedWellTest(unittest.TestCase):
    def test_well_joined_by_no_contact_is_isolated(self):
        # NOTE: e.g. a well joined to its net by a label, its piece of the network would join nothing
        network = network_of_metal_and_well(joined_by_via=False)
        self.assertEqual({n.object_id() for n in network.each_node() if n.layer() == 1},
                         RExtractor.isolated_well_node_ids(network, well_layer_ids={1}))

    def test_well_joined_by_contact_is_not_isolated(self):
        network = network_of_metal_and_well(joined_by_via=True)
        self.assertEqual(set(), RExtractor.isolated_well_node_ids(network, well_layer_ids={1}))

    def test_network_of_a_well_only_is_not_isolated(self):
        # NOTE: e.g. the well of a standard cell, without taps (sky130_fd_sc_hd__inv_1, VPB)
        network = network_of_metal_and_well(joined_by_via=False, with_metal=False)
        self.assertEqual(set(), RExtractor.isolated_well_node_ids(network, well_layer_ids={1}))


def nfet_li1_redux_networks() -> Dict[str, r_network_pb2.RNetwork]:
    rex = r_extractor(sky130a_tech(),
                      top_cell='nfet_li1_redux',
                      lvsdb_file_name='nfet_li1_redux_reordered_lvs_layers.lvsdb.gz',
                      skip_simplify=True)  # like kpex
    result = rex.extract(rex.prepare_request())
    return {network.net_name: network for network in result.networks}


@allure.parent_suite("Unit Tests")
@allure.tag("R", "Device Terminals")
class RExtractorDeviceTerminalTest(unittest.TestCase):
    @staticmethod
    def ports_by_net() -> Dict[str, List[r_network_pb2.RNode]]:
        return {net_name: [n for n in network.nodes
                           if n.node_kind == r_network_pb2.RNode.Kind.KIND_DEVICE_TERMINAL]
                for net_name, network in nfet_li1_redux_networks().items()}

    def test_device_terminal_is_a_port_of_its_wire(self):
        # NOTE: the annotated layout has a layer for each LVS layer, e.g. poly_con and poly_vpp for poly,
        #       and KLayout doesn't create the LVS layers in the same order from run to run:
        #       in this LVS database, the gate terminal's layer (poly_con) comes after the other one
        self.assertEqual({'G': 1, '$2': 1, '$3': 1, 'sky130_gnd': 0},
                         {net_name: len(ports) for net_name, ports in self.ports_by_net().items()})

    def test_port_has_its_device_terminal(self):
        # NOTE: to connect the device to the node of its port (#211 §6)
        self.assertEqual({'G': [(1, 1, 'G')], '$2': [(1, 0, 'S')], '$3': [(1, 2, 'D')], 'sky130_gnd': []},
                         {net_name: [(p.device_terminal.device_id, p.device_terminal.terminal_id, p.device_terminal.name)
                                     for p in ports]
                          for net_name, ports in self.ports_by_net().items()})


@allure.parent_suite("Unit Tests")
@allure.tag("R", "Node Names")
class RExtractorNodeNameTest(unittest.TestCase):
    def test_node_names_have_the_layer_name(self):
        # NOTE: KLayout names a node after its layer index (e.g. $1.17),
        #       which depends on the order of the LVS layers (see RExtractorDeviceTerminalTest)
        self.assertEqual({'G': ['$0.poly', '$1.li1', 'G', 'P0.poly'],
                          '$2': ['$0.nsdm', '$1.li1', 'P0.nsdm'],
                          '$3': ['$0.nsdm', '$1.li1', 'P0.nsdm'],
                          'sky130_gnd': []},
                         {net_name: sorted(n.node_name for n in network.nodes)
                          for net_name, network in nfet_li1_redux_networks().items()})
