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
from typing import List

import klayout.db as kdb

from klayout_pex.rcx25.c.device_capacitor_plates import DeviceCapacitorPlates
from klayout_pex.rcx25.c.sidewall_and_fringe_extractor import SidewallAndFringeExtractor, sidewall_separation
from klayout_pex.rcx25.extraction_reporter import ExtractionReporter
from klayout_pex.rcx25.extraction_results import CellExtractionResults
from klayout_pex.rcx25.types import EdgeNeighborhood
from klayout_pex.tech_info import TechInfo
from klayout_pex_protobuf.kpex.tech.process_parasitics_pb2 import CapacitanceInfo
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2

DBU = 0.001  # µm
SIDE_HALO = 8.0  # µm
SIDE_OVERLAP_CAPACITANCE = 40.0  # aF/µm


def neighborhoods(primary: kdb.Region, secondary: kdb.Region) -> List[str]:
    """The exact geometry and properties received by an edge visitor, independent of callback order."""
    recorded: List[str] = []

    class Visitor(kdb.EdgeNeighborhoodVisitor):
        def on_edge(self, layout: kdb.Layout, cell: kdb.Cell, edge: kdb.EdgeWithProperties,
                     neighborhood: EdgeNeighborhood):
            for interval, by_child in neighborhood:
                for child, polygons in by_child.items():
                    recorded.append(f"{edge} {interval} {child} {sorted(str(polygon) for polygon in polygons)}")

    visitor = Visitor()
    primary.complex_op(kdb.CompoundRegionOperationNode.new_edge_neighborhood(
        children=[kdb.CompoundRegionOperationNode.new_secondary(secondary)],
        visitor=visitor, bext=-1, eext=-1, din=-1, dout=200))
    return sorted(recorded)


def fringe_cap(overlap_capacitance: float,
               scale_ratio_to_fit_halo: bool,
               distance_near_um: float = 0.0,
               distance_far_um: float = SIDE_HALO) -> float:
    """
    The fringe (in fF) of a 1 µm edge to the part of a layer from distance_near_um to distance_far_um beside it
    """
    tech = tech_pb2.Technology()
    tech.process_parasitics.side_halo = SIDE_HALO
    visitor = SidewallAndFringeExtractor.PEXEdgeNeighborhoodVisitor(
        all_layer_names=['inside', 'outside'],
        inside_layer_index=0,
        dbu=DBU,
        tech_info=TechInfo(tech=tech, dielectric_filter=None),
        scale_ratio_to_fit_halo=scale_ratio_to_fit_halo,
        device_capacitor_plates=DeviceCapacitorPlates(),
        mos_channels=kdb.Shapes(),
        results=CellExtractionResults(cell_name='TOP'),
        report=ExtractionReporter(cell_name='TOP', dbu=DBU, report_caps=False))
    return visitor.fringe_cap(edge_interval_length=round(1.0 / DBU),
                              distance_near=round(distance_near_um / DBU),
                              distance_far=round(distance_far_um / DBU),
                              overlap_cap_spec=CapacitanceInfo.OverlapCapacitance(capacitance=overlap_capacitance),
                              sideoverlap_cap_spec=CapacitanceInfo.SideOverlapCapacitance(
                                  capacitance=SIDE_OVERLAP_CAPACITANCE))


@allure.parent_suite("Unit Tests")
@allure.tag("RCX25", "Capacitance", "Fringe")
class FringeCapTest(unittest.TestCase):
    def test_large_neighbors_are_split_without_changing_geometry_or_properties(self):
        comb = kdb.Region(kdb.Box(0, 0, 2560, 10))
        for x in range(0, 2560, 20):
            comb.insert(kdb.Box(x, 10, x + 10, 100))
        region = kdb.Region()
        region.enable_properties()
        for polygon in comb.merged().each():
            region.insert(kdb.PolygonWithProperties(polygon, {'net': 'VSS', 'device_capacitor_plate': 7}))
        neighbors = SidewallAndFringeExtractor.bounded_neighbors(region)
        self.assertGreater(neighbors.size(), region.size())
        self.assertTrue((neighbors ^ region).is_empty())
        self.assertFalse(neighbors.merged_semantics)
        self.assertTrue(all(polygon.num_points() <= 256 for polygon in neighbors.each()))
        self.assertTrue(all(polygon.properties() == {'net': 'VSS', 'device_capacitor_plate': 7}
                            for polygon in neighbors.each()))
        primary = kdb.Region(kdb.Box(10, 110, 2500, 130))
        self.assertEqual(neighborhoods(primary, region), neighborhoods(primary, neighbors))

    def test_slanted_neighbors_are_not_split(self):
        points = [kdb.Point(0, 0), kdb.Point(2560, 0)]
        points.extend(kdb.Point(x, 100 + x % 20) for x in range(2560, -1, -5))
        polygon = kdb.Polygon(points)
        self.assertGreater(polygon.num_points(), 256)
        self.assertFalse(polygon.is_rectilinear())
        region = kdb.Region(polygon)
        self.assertIs(region, SidewallAndFringeExtractor.bounded_neighbors(region))

    def test_scaled_fringe_over_the_halo_is_the_side_overlap_capacitance(self):
        self.assertAlmostEqual(fringe_cap(overlap_capacitance=30.0, scale_ratio_to_fit_halo=True),
                               SIDE_OVERLAP_CAPACITANCE / 1000.0)

    def test_no_fringe_without_an_overlap_capacitance(self):
        # The overlap capacitance sets how fast the fringe reaches the layer (MAGIC's overlap multiplier):
        # without one, none of it is within any distance, so there is nothing to scale to the halo either
        for scale_ratio_to_fit_halo in (True, False):
            with self.subTest(scale_ratio_to_fit_halo=scale_ratio_to_fit_halo):
                assert fringe_cap(overlap_capacitance=0.0,
                                  scale_ratio_to_fit_halo=scale_ratio_to_fit_halo,
                                  distance_near_um=1.0,
                                  distance_far_um=2.0) == 0.0


@allure.parent_suite("Unit Tests")
@allure.tag("RCX25", "Capacitance", "Sidewall")
class SidewallSeparationTest(unittest.TestCase):
    def test_the_fit_where_it_is_valid(self):
        # Poly2 of gf180mcuD at its minimum space, and an offset > 0
        self.assertAlmostEqual(sidewall_separation(0.24, -0.082), 0.158)
        self.assertAlmostEqual(sidewall_separation(0.1, 0.3), 0.4)

    def test_half_the_distance_where_the_fit_diverges_or_turns_negative(self):
        # From twice -offset down, where the fit gives 0, then negative separations
        for distance in (0.164, 0.1, 0.082, 0.05):
            with self.subTest(distance=distance):
                self.assertAlmostEqual(sidewall_separation(distance, -0.082), distance / 2.0)
