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
import math
import unittest
from typing import Any, Callable, Dict, List, Optional
from unittest import mock

import klayout.db as kdb

from klayout_pex.klayout.lvsdb_extractor import DEVICE_CAPACITOR_PLATE_PROPERTY
from klayout_pex.rcx25.c.device_capacitor_plates import DeviceCapacitorPlates
from klayout_pex.rcx25.c.device_capacitance_references import DeviceCapacitanceReference
from klayout_pex.rcx25.c.device_capacitance_checks import (
    CHECK_DEVICE_PROPERTY, DeviceCapacitanceChecks, _DeviceMarker,
)
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
    node = kdb.CompoundRegionOperationNode.new_edge_neighborhood(
        children=[kdb.CompoundRegionOperationNode.new_secondary(secondary)],
        visitor=visitor, bext=-1, eext=-1, din=-1, dout=200)
    visitor._manage()
    primary.complex_op(node)
    return sorted(recorded)


def fringe_visitor(overlap_capacitance: float,
                   scale_ratio_to_fit_halo: bool,
                   dbu: float = DBU) -> SidewallAndFringeExtractor.PEXEdgeNeighborhoodVisitor:
    tech = tech_pb2.Technology()
    tech.process_parasitics.side_halo = SIDE_HALO
    caps = tech.process_parasitics.capacitance
    caps.overlaps.add(top_layer_name='inside', bottom_layer_name='outside', capacitance=overlap_capacitance)
    caps.sideoverlaps.add(in_layer_name='inside', out_layer_name='outside', capacitance=SIDE_OVERLAP_CAPACITANCE)
    return SidewallAndFringeExtractor.PEXEdgeNeighborhoodVisitor(
        all_layer_names=['inside', 'outside'],
        inside_layer_index=0,
        dbu=dbu,
        tech_info=TechInfo(tech=tech, dielectric_filter=None),
        scale_ratio_to_fit_halo=scale_ratio_to_fit_halo,
        device_capacitor_plates=DeviceCapacitorPlates(),
        mos_channels=kdb.Shapes(),
        results=CellExtractionResults(cell_name='TOP'),
        report=ExtractionReporter(cell_name='TOP', dbu=dbu, report_caps=False))


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


def integrate_strips(function: Callable[[float], float], start: float, stop: float) -> float:
    """Independent Simpson integration of narrow rectangular contributions."""
    steps = 2048
    step = (stop - start) / steps
    return step / 3.0 * math.fsum(
        [function(start), function(stop)] +
        [(4 if index % 2 else 2) * function(start + index * step) for index in range(1, steps)])


def emitted_fringe(visitor: SidewallAndFringeExtractor.PEXEdgeNeighborhoodVisitor,
                   polygon: kdb.Polygon,
                   shield: Optional[kdb.Region] = None,
                   properties: Optional[Dict[str, Any]] = None) -> float:
    visitor.report = mock.Mock(spec=ExtractionReporter)
    visitor.emit_fringe('inside', 'outside',
                        kdb.EdgeWithProperties(kdb.Edge(0, 0, 4000, 0), {'net': 'inside_net', **(properties or {})}),
                        (0, 4000), [kdb.PolygonWithProperties(polygon, {'net': 'outside_net', **(properties or {})})],
                        shield if shield is not None else kdb.Region(),
                        None, GeometryRestorer(kdb.IMatrix3d()))
    return math.fsum(call.kwargs['sideoverlap_cap'].cap_value
                     for call in visitor.report.output_sideoverlap.call_args_list)


@allure.parent_suite("Unit Tests")
@allure.tag("RCX25", "Capacitance", "Fringe")
class FringeCapTest(unittest.TestCase):
    def test_device_fringe_observes_integrated_polygons_without_exporting_them(self):
        # The same geometry must produce the same measurement after blackboxing.
        # Shield cuts and decomposition must retain the device's ownership, and
        # a polygon above the cutoff must keep pieces below that cutoff.
        rectangle = kdb.Polygon(kdb.Box(0, 500, 4000, 6500))
        triangle = kdb.Polygon([kdb.Point(0, 1000), kdb.Point(4000, 5000), kdb.Point(4000, 1000)])
        hole = kdb.Region(kdb.Polygon([kdb.Point(1000, 1500), kdb.Point(3000, 3500), kdb.Point(3000, 1500)]))
        slanted_shield = kdb.Region(kdb.Polygon([kdb.Point(0, 0), kdb.Point(0, 6000),
                                               kdb.Point(4000, 6000), kdb.Point(4000, 4000)]))
        narrow = kdb.Polygon([kdb.Point(0, 0), kdb.Point(0, 5000), kdb.Point(2, 5000),
                              kdb.Point(2, 2500), kdb.Point(4, 2500), kdb.Point(4, 5000),
                              kdb.Point(6, 5000), kdb.Point(6, 0)])
        for polygon, shield, coefficient in ((rectangle, None, 30), (triangle, None, 30),
                                             (rectangle, hole, 30), (rectangle, slanted_shield, 30),
                                             (narrow, None, 1e-12)):
            for scale in (False, True):
                with self.subTest(polygon=str(polygon), shield=str(shield), scale=scale):
                    expected = emitted_fringe(fringe_visitor(coefficient, scale), polygon, shield)
                    checks = DeviceCapacitanceChecks(
                        [DeviceCapacitanceReference('$1', 'metal_cap', ('A', 'B'), 1e-15)],
                        [_DeviceMarker(1, '$1', kdb.Region(kdb.Box(-1000, -2000, 5000, 9000)))],
                        [1], [frozenset(('inside_net', 'outside_net'))])
                    for net, shape in (('inside_net', kdb.Polygon(kdb.Box(0, -1000, 4000, 0))),
                                       ('outside_net', polygon)):
                        checks.marked_plates(kdb.Region(kdb.PolygonWithProperties(
                            shape, {'net': net, DEVICE_CAPACITOR_PLATE_PROPERTY: True})))
                    visitor = fringe_visitor(coefficient, scale)
                    visitor.device_capacitor_plates = DeviceCapacitorPlates(
                        {frozenset(('inside_net', 'outside_net'))}, checks)
                    exported = emitted_fringe(visitor, polygon, shield,
                                               {DEVICE_CAPACITOR_PLATE_PROPERTY: True, CHECK_DEVICE_PROPERTY: 1})
                    self.assertEqual(exported, 0)
                    self.assertFalse(visitor.results.sideoverlap_table)
                    record, = checks.records()
                    self.assertEqual(record['status'], 'informational')
                    self.assertAlmostEqual(record['extracted_capacitance_f'], expected * 1e-15,
                                           delta=expected * 1e-27)

    def test_rotated_edge_neighborhoods_match_the_integrated_model(self):
        # Exercise real neighborhood callbacks, including diagonal source edges.
        # A fine grid bounds rotation rounding independently of the model error.
        dbu = 1e-5
        primary_polygon = kdb.Polygon(kdb.Box(0, -100000, 400000, 0))
        secondary_polygon = kdb.Polygon([kdb.Point(0, 100000), kdb.Point(400000, 500000),
                                         kdb.Point(400000, 100000)])
        expected = integrate_strips(
            lambda x: 0.04 * (math.atan(0.6 * (1 + x)) - math.atan(0.6)) / math.atan(0.6 * SIDE_HALO),
            0, 4)
        # At most two grid steps of motion along both polygon boundaries, times
        # the maximum fringe density, bounds the diagonal rounding contribution.
        alpha = 0.6
        maximum_density = 0.04 * alpha / math.atan(alpha * SIDE_HALO)
        rounding_bound = 2 * dbu * (primary_polygon.perimeter() + secondary_polygon.perimeter()) * dbu * maximum_density
        for angle in (0, 45, 90, 135, 180, 225, 270, 315):
            with self.subTest(angle=angle):
                transform = kdb.ICplxTrans(1.0, angle, False, 0, 0)
                primary = kdb.Region(kdb.PolygonWithProperties(primary_polygon.transformed(transform), {'net': 'inside_net'}))
                secondary = kdb.Region(kdb.PolygonWithProperties(secondary_polygon.transformed(transform), {'net': 'outside_net'}))
                primary.enable_properties()
                secondary.enable_properties()
                visitor = fringe_visitor(30.0, True, dbu)
                visitor.report = mock.Mock(spec=ExtractionReporter)
                node = kdb.CompoundRegionOperationNode.new_edge_neighborhood(
                    children=[kdb.CompoundRegionOperationNode.new_foreign(),
                              kdb.CompoundRegionOperationNode.new_secondary(secondary),
                              kdb.CompoundRegionOperationNode.new_primary()],
                    visitor=visitor, bext=-1, eext=-1, din=-1, dout=round(SIDE_HALO / dbu) + 1)
                visitor._manage()
                primary.complex_op(node)
                actual = math.fsum(call.kwargs['sideoverlap_cap'].cap_value
                                   for call in visitor.report.output_sideoverlap.call_args_list)
                self.assertAlmostEqual(actual, expected,
                                       delta=rounding_bound if angle % 90 else expected * 1e-11)

    def test_polygon_cutoff_is_applied_before_internal_decomposition(self):
        # The narrow notched polygon exceeds the cutoff, but every vertical
        # piece is below it. Decomposition must preserve its total contribution.
        polygon = kdb.Polygon([kdb.Point(0, 0), kdb.Point(0, 5000), kdb.Point(2, 5000),
                               kdb.Point(2, 2500), kdb.Point(4, 2500), kdb.Point(4, 5000),
                               kdb.Point(6, 5000), kdb.Point(6, 0)])
        visitor = fringe_visitor(1e-12, True)
        expected = polygon.area() * DBU ** 2 * (SIDE_OVERLAP_CAPACITANCE / 1000.0) / SIDE_HALO
        assert expected > 0.0001
        actual = emitted_fringe(visitor, polygon)
        self.assertAlmostEqual(actual, expected, delta=expected * 1e-12)
        caps = [call.kwargs['sideoverlap_cap'].cap_value for call in visitor.report.output_sideoverlap.call_args_list]
        assert len(caps) == 3
        assert all(0 < value < 0.0001 for value in caps)

    def test_slanted_fringe_matches_integrated_rectangular_model(self):
        # A triangle's bounding box includes material that is not there. Vary
        # both boundaries as well, so accounting for area alone cannot pass.
        shapes = [
            ([(0, 1000), (4000, 5000), (4000, 1000)], lambda x: 1000, lambda x: 1000 + x),
            ([(0, 1000), (0, 5000), (4000, 1000)], lambda x: 1000, lambda x: 5000 - x),
            ([(0, 1000), (0, 3000), (4000, 4000), (4000, 3000)],
             lambda x: 1000 + x / 2, lambda x: 3000 + x / 4),
            ([(0, 1000), (0, 3000), (4000, 3001), (4000, 1001)],
             lambda x: 1000 + x / 4000, lambda x: 3000 + x / 4000)]
        for scale in (False, True):
            for points, near, far in shapes:
                with self.subTest(scale=scale, points=points):
                    visitor = fringe_visitor(30.0, scale)
                    visitor.results.keep_capacitance_geometry = True
                    polygon = kdb.Polygon([kdb.Point(x, y) for x, y in points])
                    contribution = lambda x: visitor.fringe_cap(
                        1, near(x), far(x), CapacitanceInfo.OverlapCapacitance(capacitance=30.0),
                        CapacitanceInfo.SideOverlapCapacitance(capacitance=40.0))
                    expected = integrate_strips(contribution, 0, 4000)
                    with self.assertNoLogs('__kpex__', level='WARNING'):
                        actual = emitted_fringe(visitor, polygon)
                    self.assertAlmostEqual(actual, expected, delta=expected * 1e-11)
                    cap, = [cap for caps in visitor.results.sideoverlap_table.values() for cap in caps]
                    self.assertAlmostEqual(cap.profile.between(0.0, 0.5),
                                           integrate_strips(contribution, 0, 2000), delta=expected * 1e-11)

    def test_slanted_shield_shortens_the_coupled_part_of_the_edge(self):
        # The shield crosses both horizontal boundaries within one interval.
        # Its remainder starts at x=1000, not at the source interval's x=0.
        visitor = fringe_visitor(30.0, True)
        shield = kdb.Region(kdb.Polygon([kdb.Point(0, 0), kdb.Point(0, 6000),
                                       kdb.Point(4000, 6000), kdb.Point(4000, 4000)]))
        contribution = lambda x: visitor.fringe_cap(
            1, 1000, min(x, 3000), CapacitanceInfo.OverlapCapacitance(capacitance=30.0),
            CapacitanceInfo.SideOverlapCapacitance(capacitance=40.0))
        expected = integrate_strips(contribution, 1000, 3000) + integrate_strips(contribution, 3000, 4000)
        actual = emitted_fringe(visitor, kdb.Polygon(kdb.Box(0, 1000, 4000, 3000)), shield)
        self.assertAlmostEqual(actual, expected, delta=expected * 1e-11)

    def test_hole_in_fringe_polygon_subtracts_only_its_own_contribution(self):
        visitor = fringe_visitor(30.0, True)
        shield = kdb.Region(kdb.Polygon([kdb.Point(1000, 1500), kdb.Point(3000, 3500),
                                       kdb.Point(3000, 1500)]))
        overlap = CapacitanceInfo.OverlapCapacitance(capacitance=30.0)
        fringe = CapacitanceInfo.SideOverlapCapacitance(capacitance=40.0)
        outer = visitor.fringe_cap(4000, 500, 6500, overlap, fringe)
        hole = integrate_strips(lambda x: visitor.fringe_cap(1, 1500, 500 + x, overlap, fringe), 1000, 3000)
        actual = emitted_fringe(visitor, kdb.Polygon(kdb.Box(0, 500, 4000, 6500)), shield)
        self.assertAlmostEqual(actual, outer - hole, delta=outer * 1e-11)

    def test_slanted_fringe_zero_and_small_overlap_limits(self):
        # Normalization has a finite uniform-field limit as the overlap
        # coefficient approaches zero, while exactly zero still means no fringe.
        triangle = kdb.Polygon([kdb.Point(0, 0), kdb.Point(4000, 4000), kdb.Point(4000, 0)])
        for coefficient in (0.0, 1e-12, 30.0):
            for scale in (False, True):
                with self.subTest(coefficient=coefficient, scale=scale):
                    visitor = fringe_visitor(coefficient, scale)
                    expected = integrate_strips(
                        lambda x: visitor.fringe_cap(1, 0, x,
                                                     CapacitanceInfo.OverlapCapacitance(capacitance=coefficient),
                                                     CapacitanceInfo.SideOverlapCapacitance(capacitance=40.0)),
                        0, 4000)
                    actual = emitted_fringe(visitor, triangle)
                    # The emitted network retains the existing per-polygon cutoff.
                    expected = expected if expected > 0.0001 else 0.0
                    self.assertAlmostEqual(actual, expected, delta=max(expected * 1e-11, 1e-15))

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

    def test_rectangular_shields_preserve_exact_subtraction_and_cutoffs(self):
        # A one-grid-step sliver must survive at both ends. Overlapping, nested,
        # touching and repeated shields must act as their union, in either order.
        target = kdb.Box(0, 100, 200000, 1000)
        cases = [[(0, end)] for end in (99, 100, 101, 999, 1000, 1001)]
        cases += [[(start, 1100)] for start in (99, 100, 101, 999, 1000, 1001)]
        cases += [[(200, 400), (300, 500)], [(200, 500), (300, 400)],
                  [(200, 400), (400, 600)], [(200, 400), (200, 400)],
                  [(200, 400), (600, 800)], [(-100, 1100)], []]
        for intervals in cases:
            for reverse in (False, True):
                with self.subTest(intervals=intervals, reverse=reverse):
                    ordered = list(reversed(intervals)) if reverse else intervals
                    shield = kdb.Region([kdb.Box(-1, near, 200001, far) for near, far in ordered])
                    reference = kdb.Region(target) - shield
                    visitor = fringe_visitor(30.0, True)
                    visitor.report = mock.Mock(spec=ExtractionReporter)
                    overlap = visitor.tech_info.overlap_cap_by_layer_names['inside']['outside']
                    side = visitor.tech_info.side_overlap_cap_by_layer_names['inside']['outside']
                    expected = []
                    for polygon in reference.each():
                        box = polygon.bbox()
                        value = visitor.fringe_cap(box.width(), box.bottom, box.top, overlap, side)
                        if value > 0.0001:
                            expected.append((str(box), value))
                    # A full-width rectangular shield only cuts the vertical
                    # interval. It must not allocate a general polygon region
                    # for every candidate in a large edge neighborhood (#501).
                    with mock.patch('klayout_pex.rcx25.c.sidewall_and_fringe_extractor.kdb.Region',
                                    wraps=kdb.Region) as region_factory:
                        visitor.emit_fringe('inside', 'outside',
                                            kdb.EdgeWithProperties(kdb.Edge(0, 0, 200000, 0), {'net': 'inside_net'}),
                                            (0, 200000),
                                            [kdb.PolygonWithProperties(target, {'net': 'A'})], shield,
                                            None, GeometryRestorer(kdb.IMatrix3d()))
                    actual = [(str(call.kwargs['outside_polygon'].bbox()),
                               call.kwargs['sideoverlap_cap'].cap_value)
                              for call in visitor.report.output_sideoverlap.call_args_list]
                    self.assertEqual(actual, expected)
                    self.assertEqual(region_factory.call_count, 0)

    def test_partial_width_and_slanted_shields_keep_general_subtraction(self):
        # A shield that stops one grid step short, or has a diagonal boundary,
        # cannot be represented by full-width vertical intervals.
        polygon = kdb.Polygon(kdb.Box(0, 100, 4000, 6000))
        cases = [(polygon, kdb.Region(kdb.Box(1, 500, 4000, 1500))),
                 (polygon, kdb.Region(kdb.Box(0, 500, 3999, 1500))),
                 (polygon, kdb.Region(kdb.Polygon([kdb.Point(0, 500), kdb.Point(0, 1500), kdb.Point(4000, 500)]))),
                 (kdb.Polygon([kdb.Point(0, 100), kdb.Point(0, 6000), kdb.Point(4000, 6000)]),
                  kdb.Region(kdb.Box(0, 500, 4000, 1500))),
                 (kdb.Polygon(kdb.Box(-1, 100, 4000, 6000)), kdb.Region(kdb.Box(0, 500, 4000, 1500))),
                 (kdb.Polygon(kdb.Box(0, 100, 4001, 6000)), kdb.Region(kdb.Box(0, 500, 4000, 1500)))]
        for polygon, shield in cases:
            with self.subTest(polygon=str(polygon), shield=str(shield)):
                reference = kdb.Region(polygon) - shield
                expected = math.fsum(emitted_fringe(fringe_visitor(30.0, True), part)
                                     for part in reference.each())
                with mock.patch('klayout_pex.rcx25.c.sidewall_and_fringe_extractor.kdb.Region',
                                wraps=kdb.Region) as region_factory:
                    actual = emitted_fringe(fringe_visitor(30.0, True), polygon, shield)
                self.assertAlmostEqual(actual, expected, delta=expected * 1e-14)
                self.assertGreater(region_factory.call_count, 0)

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
            # Both the general subtraction and full-width interval path must
            # preserve each source polygon's cutoff, even for touching shapes.
            for shield in (kdb.Box(10, 0, 20, 8000), kdb.Box(0, -2, 3, -1)):
                with self.subTest(intervals=intervals, shield=str(shield)):
                    visitor = fringe_visitor(30.0, True)
                    visitor.report = mock.Mock(spec=ExtractionReporter)
                    visitor.emit_fringe('inside', 'outside',
                                        kdb.EdgeWithProperties(kdb.Edge(0, 0, 3, 0), {'net': 'inside_net'}),
                                        (0, 3),
                                        [kdb.PolygonWithProperties(kdb.Box(0, near, 3, far), {'net': 'A'})
                                         for near, far in intervals],
                                        kdb.Region(shield),
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
    def test_sloping_sidewall_matches_integrated_separation(self):
        # Include constant separation, both slope signs, and crossings of the
        # negative-offset fit boundary at d=-2*offset, including either endpoint.
        for offset, first, last in ((0.1, 200, 200), (0.1, 200, 600), (0.1, 0, 400),
                                    (-0.1, 100, 300), (-0.1, 199, 201),
                                    (-0.1, 100, 200), (-0.1, 200, 300)):
            for start, end in ((first, last), (last, first)):
                with self.subTest(offset=offset, start=start, end=end):
                    visitor = fringe_visitor(30.0, True)
                    visitor.results.keep_capacitance_geometry = True
                    visitor.tech_info.tech.process_parasitics.capacitance.sidewalls.add(
                        layer_name='inside', capacitance=50.0, offset=offset)
                    visitor.report = mock.Mock(spec=ExtractionReporter)
                    polygon = kdb.PolygonWithProperties(kdb.Polygon([
                        kdb.Point(0, start), kdb.Point(0, start + 1000),
                        kdb.Point(4000, end + 1000), kdb.Point(4000, end)]), {'net': 'outside_net'})
                    visitor.emit_sidewall('inside',
                                          kdb.EdgeWithProperties(kdb.Edge(0, 0, 4000, 0), {'net': 'inside_net'}),
                                          (0, 4000), polygon, GeometryRestorer(kdb.IMatrix3d()))
                    contribution = lambda x: DBU * 50.0 / 4000.0 / sidewall_separation(
                        (start + (end - start) * x / 4000) * DBU, offset)
                    intervals = [0.0, 4000.0]
                    if start != end:
                        boundary = (-2 * offset / DBU - start) * 4000 / (end - start)
                        if 0 < boundary < 4000:
                            intervals.insert(1, boundary)
                    expected = math.fsum(integrate_strips(contribution, a, b)
                                         for a, b in zip(intervals, intervals[1:]))
                    actual = visitor.report.output_sidewall.call_args.kwargs['sidewall_cap'].cap_value
                    self.assertAlmostEqual(actual, expected, delta=expected * 1e-11)
                    cap, = [cap for caps in visitor.results.sidewall_table.values() for cap in caps]
                    if start == end:
                        self.assertIsNone(cap.profile)
                    else:
                        half = sorted({0.0, 2000.0, *(x for x in intervals if 0 < x < 2000)})
                        expected_half = math.fsum(integrate_strips(contribution, a, b)
                                                  for a, b in zip(half, half[1:]))
                        self.assertAlmostEqual(cap.profile.between(0.0, 0.5), expected_half,
                                               delta=expected * 1e-11)

    def test_the_fit_where_it_is_valid(self):
        # Poly2 of gf180mcuD at its minimum space, and an offset > 0
        self.assertAlmostEqual(sidewall_separation(0.24, -0.082), 0.158)
        self.assertAlmostEqual(sidewall_separation(0.1, 0.3), 0.4)

    def test_half_the_distance_where_the_fit_diverges_or_turns_negative(self):
        # From twice -offset down, where the fit gives 0, then negative separations
        for distance in (0.164, 0.1, 0.082, 0.05):
            with self.subTest(distance=distance):
                self.assertAlmostEqual(sidewall_separation(distance, -0.082), distance / 2.0)
