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

import allure
from typing import *
import unittest

import klayout.db as kdb

from klayout_pex.rcx25.capacitance_distributor import (
    CapacitanceDistributor,
    NodeSite,
    NodeSites,
    edge_parts,
)


def distributor(sites: Dict[Tuple[str, str], List[Tuple[float, float, str]]]) -> CapacitanceDistributor:
    """
    :param sites: (x, y, node name) by (net, layer)
    """
    sites_by_net: Dict[str, List[NodeSite]] = {}
    for (net, layer), net_sites in sites.items():
        sites_by_net.setdefault(net, []).extend(NodeSite(*s) for s in net_sites)
    return CapacitanceDistributor(
        sites_by_net_and_layer={key: NodeSites(NodeSite(*s) for s in net_sites) for key, net_sites in sites.items()},
        sites_by_net={net: NodeSites(net_sites) for net, net_sites in sites_by_net.items()}
    )


@allure.parent_suite("Unit Tests")
@allure.tag("RCX25", "Capacitance Distribution")
class Test(unittest.TestCase):
    # a wire of 100 µm x 1 µm (DBU 1 nm) on met1, with a node at each end
    WIRE = kdb.Box(0, 0, 100000, 1000)
    WIRE_SITES = {('W', 'met1'): [(0, 500, 'W'), (100000, 500, 'W.$1.met1')]}

    def assertFractions(self, expected: Dict[Tuple[str, str], float], obtained: Dict[Tuple[str, str], float]):
        self.assertEqual(set(expected), set(obtained))
        for pair, fraction in expected.items():
            self.assertAlmostEqual(fraction, obtained[pair], places=9, msg=f"fraction of {pair}")
        self.assertAlmostEqual(1.0, sum(obtained.values()), places=12)

    def test_edge_parts_are_split_halfway_between_the_nodes(self):
        sites = [NodeSite(0, 0, 'A'), NodeSite(25, 0, 'B'), NodeSite(100, 0, 'C')]
        parts = edge_parts((0, 0), (100, 0), sites)
        self.assertEqual(['A', 'B', 'C'], [p[2] for p in parts])
        self.assertEqual(0.0, parts[0][0])
        self.assertAlmostEqual(0.125, parts[0][1])
        self.assertAlmostEqual(0.625, parts[1][1])
        self.assertEqual(1.0, parts[2][1])

    def test_edge_parts_of_a_node_beside_the_edge(self):
        # NOTE: B is 30 off the edge, so the parts meet where both are equally far: x² = (x - 40)² + 30²
        sites = [NodeSite(0, 0, 'A'), NodeSite(40, 30, 'B')]
        parts = edge_parts((0, 0), (100, 0), sites)
        self.assertEqual(['A', 'B'], [p[2] for p in parts])
        self.assertAlmostEqual(31.25 / 100, parts[0][1])

    def test_edge_parts_of_nodes_with_the_same_name_are_one(self):
        sites = [NodeSite(0, 0, 'A'), NodeSite(50, 0, 'A'), NodeSite(100, 0, 'B')]
        self.assertEqual([(0.0, 0.75, 'A'), (0.75, 1.0, 'B')], edge_parts((0, 0), (100, 0), sites))

    def test_candidates_are_the_sites_that_can_be_nearest(self):
        sites = NodeSites(NodeSite(x, 0, f"N{x}") for x in range(0, 100001, 10000))
        candidates = sites.candidates(kdb.Box(42000, -500, 48000, 500))
        self.assertEqual(['N40000', 'N50000'], [s.node_name for s in candidates])

    def test_wire_area_is_split_between_its_end_nodes(self):
        # NOTE: the capacitance of a wire between 2 nodes is half on each (π model)
        fractions = distributor(self.WIRE_SITES).area_fractions('W', 'met1', 'VSUBS', 'VSUBS',
                                                                kdb.Region(self.WIRE))
        self.assertFractions({('W', 'VSUBS'): 0.5, ('W.$1.met1', 'VSUBS'): 0.5}, fractions)

    def test_wire_area_is_split_in_proportion_to_the_geometry(self):
        sites = {('W', 'met1'): [(0, 500, 'W'), (25000, 500, 'W.$1.met1'), (100000, 500, 'W.$2.met1')]}
        fractions = distributor(sites).area_fractions('W', 'met1', 'VSUBS', 'VSUBS', kdb.Region(self.WIRE))
        self.assertFractions({('W', 'VSUBS'): 0.125,
                              ('W.$1.met1', 'VSUBS'): 0.5,
                              ('W.$2.met1', 'VSUBS'): 0.375}, fractions)

    def test_area_of_a_polygon_with_a_hole(self):
        # a 100 x 100 frame (with a hole of 50 x 50 in its middle), with a node at its left and right side
        polygon = kdb.Polygon(kdb.Box(0, 0, 100, 100))
        polygon.insert_hole(kdb.Box(25, 25, 75, 75))
        sites = {('F', 'met1'): [(0, 50, 'L'), (100, 50, 'R')]}
        fractions = distributor(sites).area_fractions('F', 'met1', 'VSUBS', 'VSUBS', kdb.Region(polygon))
        self.assertFractions({('L', 'VSUBS'): 0.5, ('R', 'VSUBS'): 0.5}, fractions)

    def test_area_of_a_concave_polygon(self):
        # an L of a 100 x 10 bar (along x) and a 10 x 90 bar (along y, at x = 0..10),
        # with a node at the end of each bar and one at the corner
        polygon = kdb.Polygon([kdb.Point(0, 0), kdb.Point(0, 100), kdb.Point(10, 100),
                               kdb.Point(10, 10), kdb.Point(100, 10), kdb.Point(100, 0)])
        sites = {('L', 'met1'): [(5, 5, 'C'), (100, 5, 'X'), (5, 100, 'Y')]}
        fractions = distributor(sites).area_fractions('L', 'met1', 'VSUBS', 'VSUBS', kdb.Region(polygon))
        # NOTE: the bisectors are x = 52.5 and y = 52.5, so the corner node has both bars up to them
        self.assertFractions({('C', 'VSUBS'): (52.5 * 10 + 42.5 * 10) / 1900,
                              ('X', 'VSUBS'): 47.5 * 10 / 1900,
                              ('Y', 'VSUBS'): 47.5 * 10 / 1900}, fractions)

    def test_overlap_of_two_wires_goes_to_the_node_pairs_on_top_of_each_other(self):
        # met2 wire V on top of met1 wire W, with nodes at the same ends
        sites = dict(self.WIRE_SITES)
        sites[('V', 'met2')] = [(0, 500, 'V'), (100000, 500, 'V.$1.met2')]
        fractions = distributor(sites).area_fractions('W', 'met1', 'V', 'met2', kdb.Region(self.WIRE))
        self.assertFractions({('W', 'V'): 0.5, ('W.$1.met1', 'V.$1.met2'): 0.5}, fractions)

    def test_sidewall_goes_to_the_node_pairs_facing_each_other(self):
        # wire V beside wire W (2 µm apart), V has its nodes at x = 0 and x = 50 µm
        sites = dict(self.WIRE_SITES)
        sites[('V', 'met1')] = [(0, 3500, 'V'), (50000, 3500, 'V.$1.met1')]
        fractions = distributor(sites).edge_fractions('W', 'met1', kdb.Edge(0, 1000, 100000, 1000),
                                                      'V', 'met1', kdb.Edge(0, 3000, 100000, 3000))
        self.assertFractions({('W', 'V'): 0.25,
                              ('W', 'V.$1.met1'): 0.25,
                              ('W.$1.met1', 'V.$1.met1'): 0.5}, fractions)

    def test_net_without_resistor_network_keeps_its_capacitance(self):
        fractions = distributor({}).edge_fractions('W', 'met1', kdb.Edge(0, 1000, 100000, 1000),
                                                   'V', 'met1', kdb.Edge(0, 3000, 100000, 3000))
        self.assertEqual({('W', 'V'): 1.0}, fractions)

    def test_capacitance_without_geometry_stays_on_the_nets(self):
        self.assertEqual({('W', 'VSUBS'): 1.0},
                         distributor(self.WIRE_SITES).area_fractions('W', 'met1', 'VSUBS', 'VSUBS', None))

    def test_nodes_on_other_layers_if_none_on_the_layer_of_the_capacitance(self):
        fractions = distributor(self.WIRE_SITES).area_fractions('W', 'poly', 'VSUBS', 'VSUBS',
                                                                kdb.Region(kdb.Box(0, 0, 10000, 1000)))
        self.assertFractions({('W', 'VSUBS'): 1.0}, fractions)
