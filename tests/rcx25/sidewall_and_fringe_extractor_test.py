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
from unittest import mock

import klayout.db as kdb

from klayout_pex.rcx25.c.device_capacitor_plates import DeviceCapacitorPlates
from klayout_pex.rcx25.c.geometry_restorer import GeometryRestorer
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


def comb_region(teeth: int, margin: int = 0) -> kdb.Region:
    region = kdb.Region(kdb.Box(0, 0, teeth * 20 + margin, 10))
    for index in range(teeth):
        x = margin + index * 20
        region.insert(kdb.Box(x, 10, x + 10, 100))
    return region.merged()


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


def fringe_visitor(overlap_capacitance: float,
                   scale_ratio_to_fit_halo: bool) -> SidewallAndFringeExtractor.PEXEdgeNeighborhoodVisitor:
    tech = tech_pb2.Technology()
    tech.process_parasitics.side_halo = SIDE_HALO
    caps = tech.process_parasitics.capacitance
    caps.overlaps.add(top_layer_name='inside', bottom_layer_name='outside', capacitance=overlap_capacitance)
    caps.sideoverlaps.add(in_layer_name='inside', out_layer_name='outside', capacitance=SIDE_OVERLAP_CAPACITANCE)
    return SidewallAndFringeExtractor.PEXEdgeNeighborhoodVisitor(
        all_layer_names=['inside', 'outside'],
        inside_layer_index=0,
        dbu=DBU,
        tech_info=TechInfo(tech=tech, dielectric_filter=None),
        scale_ratio_to_fit_halo=scale_ratio_to_fit_halo,
        device_capacitor_plates=DeviceCapacitorPlates(),
        mos_channels=kdb.Shapes(),
        results=CellExtractionResults(cell_name='TOP'),
        report=ExtractionReporter(cell_name='TOP', dbu=DBU, report_caps=False))


def fringe_cap(overlap_capacitance: float,
               scale_ratio_to_fit_halo: bool,
               distance_near_um: float = 0.0,
               distance_far_um: float = SIDE_HALO) -> float:
    """
    The fringe (in fF) of a 1 µm edge to the part of a layer from distance_near_um to distance_far_um beside it
    """
    visitor = fringe_visitor(overlap_capacitance, scale_ratio_to_fit_halo)
    return visitor.fringe_cap(edge_interval_length=round(1.0 / DBU),
                              distance_near=round(distance_near_um / DBU),
                              distance_far=round(distance_far_um / DBU),
                              overlap_cap_spec=CapacitanceInfo.OverlapCapacitance(capacitance=overlap_capacitance),
                              sideoverlap_cap_spec=CapacitanceInfo.SideOverlapCapacitance(
                                  capacitance=SIDE_OVERLAP_CAPACITANCE))


@allure.parent_suite("Unit Tests")
@allure.tag("RCX25", "Capacitance", "Fringe")
class FringeCapTest(unittest.TestCase):
    def test_intervening_shields_stay_between_layers_and_within_their_interval(self):
        visitor = fringe_visitor(30.0, True)
        visitor.all_layer_names = ['bottom', 'lower', 'inside', 'upper', 'top']
        visitor.inside_layer_index = 2
        visitor.emit_fringe = mock.Mock()
        edge = kdb.EdgeWithProperties(kdb.Edge(0, 0, 4000, 0), {'net': 'inside_net'})
        lower = kdb.Box(0, 1000, 2000, 1500)
        upper = kdb.Box(0, 500, 2000, 1000)
        neighborhood = [((0, 2000), {
            idx: [kdb.PolygonWithProperties(box, {'net': str(idx)})]
            for idx, box in ((0, kdb.Box(0, 100, 2000, 2000)), (1, lower),
                             (3, upper), (4, kdb.Box(0, 100, 2000, 2000)))}),
            ((2000, 4000), {4: [kdb.PolygonWithProperties(kdb.Box(2000, 100, 4000, 2000), {'net': '4'})]})]
        # An opposing part of the source polygon shields both directions, in
        # addition to their separate intervening layers, only in this interval.
        neighborhood[0][1][len(visitor.all_layer_names)] = [
            kdb.PolygonWithProperties(kdb.Box(0, 1800, 2000, 2000), {'net': 'inside_net'})]
        layout = kdb.Layout()
        with mock.patch('klayout_pex.rcx25.c.sidewall_and_fringe_extractor.kdb.Region',
                        wraps=kdb.Region) as region_factory:
            visitor.on_edge(layout, layout.create_cell('TOP'), edge, neighborhood)
        # Two empty-region constructions per interval suffice for the running
        # shields. Reconstructing every layer and target shield was costly.
        assert region_factory.call_count <= 4
        expected = {'bottom': kdb.Region(lower), 'lower': kdb.Region(),
                    'upper': kdb.Region(), 'top': kdb.Region(upper)}
        for shield in expected.values():
            shield.insert(kdb.Box(0, 1800, 2000, 18000))
        calls = visitor.emit_fringe.call_args_list
        assert len(calls) == 5
        for call in calls[:4]:
            assert (call.kwargs['shield'] ^ expected[call.kwargs['outside_layer_name']]).is_empty()
        # A later interval must not inherit any of the previous interval's shields.
        assert calls[-1].kwargs['shield'].is_empty()

    def test_shielding_preserves_source_polygons_and_net_ownership(self):
        # Touching polygons on one net must not merge, and coincident polygons on
        # different nets must not lose their owner during shield subtraction.
        visitor = fringe_visitor(30.0, True)
        visitor.report = mock.Mock(spec=ExtractionReporter)
        polygons = [kdb.PolygonWithProperties(kdb.Box(0, near, 2000, far), {'net': net})
                    for net, near, far in [('A', 100, 2000), ('A', 2000, 4000),
                                          ('B', 100, 2000), ('hidden', 600, 900),
                                          ('inside_net', 100, 2000)]]
        visitor.emit_fringe('inside', 'outside',
                            kdb.EdgeWithProperties(kdb.Edge(0, 0, 2000, 0), {'net': 'inside_net'}),
                            (0, 2000), polygons, kdb.Region(kdb.Box(0, 500, 2000, 1000)),
                            None, GeometryRestorer(kdb.IMatrix3d()))
        obtained = [(call.kwargs['sideoverlap_cap'].key.net_outside,
                     str(call.kwargs['outside_polygon'].bbox()))
                    for call in visitor.report.output_sideoverlap.call_args_list]
        assert obtained == [('A', '(0,100;2000,500)'), ('A', '(0,1000;2000,2000)'),
                            ('A', '(0,2000;2000,4000)'),
                            ('B', '(0,100;2000,500)'), ('B', '(0,1000;2000,2000)')]

    def test_shield_boundary_leaves_only_the_uncovered_part(self):
        # One grid step below, at, and above complete coverage catches lost slivers
        # and shapes incorrectly retained when a shield exactly covers them.
        for shield_top, expected in ((999, ['(0,999;200000,1000)']), (1000, []), (1001, [])):
            with self.subTest(shield_top=shield_top):
                visitor = fringe_visitor(30.0, True)
                visitor.report = mock.Mock(spec=ExtractionReporter)
                visitor.emit_fringe('inside', 'outside',
                                    kdb.EdgeWithProperties(kdb.Edge(0, 0, 200000, 0), {'net': 'inside_net'}),
                                    (0, 200000),
                                    [kdb.PolygonWithProperties(kdb.Box(0, 100, 200000, 1000), {'net': 'A'})],
                                    kdb.Region(kdb.Box(0, 0, 200000, shield_top)),
                                    None, GeometryRestorer(kdb.IMatrix3d()))
                assert [str(call.kwargs['outside_polygon'].bbox())
                        for call in visitor.report.output_sideoverlap.call_args_list] == expected

    def test_adjacent_contributions_keep_their_individual_cutoff(self):
        # At this edge length both pieces fall below the 0.0001 fF cutoff, while
        # their union exceeds it. Shielding must not create that extra capacitor.
        for intervals, count in (([(0, 1000), (1000, 8000)], 0), ([(0, 8000)], 1)):
            with self.subTest(intervals=intervals):
                visitor = fringe_visitor(30.0, True)
                visitor.report = mock.Mock(spec=ExtractionReporter)
                visitor.emit_fringe('inside', 'outside',
                                    kdb.EdgeWithProperties(kdb.Edge(0, 0, 3, 0), {'net': 'inside_net'}),
                                    (0, 3),
                                    [kdb.PolygonWithProperties(kdb.Box(0, near, 3, far), {'net': 'A'})
                                     for near, far in intervals],
                                    kdb.Region(kdb.Box(10, 0, 20, 8000)),
                                    None, GeometryRestorer(kdb.IMatrix3d()))
                assert visitor.report.output_sideoverlap.call_count == count

    def test_large_neighbors_are_split_without_changing_geometry_or_properties(self):
        comb = comb_region(128)
        region = kdb.Region()
        region.enable_properties()
        for polygon in comb.merged().each():
            region.insert(kdb.PolygonWithProperties(polygon, {'net': 'VSS', 'device_capacitor_plate': 7}))
        neighbors = SidewallAndFringeExtractor.bounded_neighbors(region)
        self.assertGreater(neighbors.size(), region.size())
        self.assertTrue((neighbors ^ region).is_empty())
        self.assertFalse(neighbors.merged_semantics)
        self.assertTrue(all(polygon.num_points() <= 64 for polygon in neighbors.each()))
        self.assertTrue(all(polygon.properties() == {'net': 'VSS', 'device_capacitor_plate': 7}
                            for polygon in neighbors.each()))
        primary = kdb.Region(kdb.Box(10, 110, 2500, 130))
        self.assertEqual(neighborhoods(primary, region), neighborhoods(primary, neighbors))

    def test_neighbor_chunk_limit_keeps_small_polygons_whole(self):
        # These rectilinear combs have 60, 64 and 68 vertices: the valid shapes
        # immediately around the limit. Splitting must preserve net properties.
        for teeth in (14, 15, 16):
            with self.subTest(teeth=teeth):
                polygon, = list(comb_region(teeth, margin=1).each())
                assert polygon.num_points() == 4 * teeth + 4
                region = kdb.Region(kdb.PolygonWithProperties(polygon, {'net': 'N'}))
                region.enable_properties()
                neighbors = SidewallAndFringeExtractor.bounded_neighbors(region)
                if teeth <= 15:
                    assert neighbors is region
                else:
                    assert neighbors.size() > 1
                    assert all(part.num_points() <= 64 for part in neighbors.each())
                assert (neighbors ^ region).is_empty()
                assert all(part.property('net') == 'N' for part in neighbors.each())

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
