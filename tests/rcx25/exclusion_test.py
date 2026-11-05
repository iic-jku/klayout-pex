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

from fnmatch import fnmatchcase
import math
from typing import *

import allure
import klayout.db as kdb
import pytest
from klayout_pex.pdk_config import PDK
from klayout_pex.rcx25.capacitance_distributor import CapacitanceDistributor
from klayout_pex.rcx25.exclusion import (
    ExclusionError,
    ExcludedBlock,
    Exclusions,
    MarkerLayer,
    NetPiece,
    RegionIndex,
    complemented_intervals,
    edge_part,
    intersected_intervals,
    intervals_within,
    listed_names,
    merged_intervals,
)
from klayout_pex.rcx25.extraction_results import (
    CellExtractionResults,
    add_distributed_capacitance,
    NetCoupleKey,
    OverlapCap,
    OverlapKey,
    SideOverlapCap,
    SideOverlapKey,
    SidewallCap,
    SidewallKey,
)
from klayout_pex.rcx25.r.r_extractor import port_of_cut
from klayout_pex.tech_info import TechInfo
import klayout_pex_protobuf.kpex.layout.location_pb2 as location_pb2
import klayout_pex_protobuf.kpex.r.r_network_pb2 as r_network_pb2

parent_suite = "kpex/2.5D exclusion markers"
tags = ("PEX", "2.5D", "Exclusion")

SUBSTRATE = 'VSUBS'


def markers(*boxes: kdb.Box) -> Exclusions:
    region = kdb.Region()
    for box in boxes:
        region.insert(box)
    return Exclusions.from_region(region, substrate_layer_name=SUBSTRATE)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_intervals():
    assert merged_intervals([(0.5, 0.6), (0.0, 0.2), (0.1, 0.3), (0.6, 0.7)]) == [(0.0, 0.3), (0.5, 0.7)]
    assert intersected_intervals([(0.0, 0.3), (0.5, 0.7)], [(0.2, 0.6)]) == [(0.2, 0.3), (0.5, 0.6)]
    assert intersected_intervals([(0.0, 0.3)], [(0.3, 0.6)]) == []
    assert complemented_intervals([]) == [(0.0, 1.0)]
    assert complemented_intervals([(0.0, 0.3), (0.5, 1.0)]) == [(0.3, 0.5)]
    assert complemented_intervals([(0.0, 1.0)]) == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('edge', [kdb.Edge(0, 0, 1000, 0), kdb.Edge(1000, 0, 0, 0)])
def test_intervals_within_are_along_the_edge(edge: kdb.Edge):
    intervals = intervals_within(edge, kdb.Region(kdb.Box(200, -10, 600, 10)))
    expected = (0.2, 0.6) if edge.x1 == 0 else (0.4, 0.8)
    assert len(intervals) == 1
    assert intervals[0] == pytest.approx(expected)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_edge_part():
    assert edge_part(kdb.Edge(0, 0, 1000, 2000), (0.25, 0.5)) == kdb.Edge(250, 500, 500, 1000)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_excluded_area():
    m = markers(kdb.Box(0, 0, 100, 100))
    assert m.excluded_area(kdb.Region(kdb.Box(50, 0, 150, 100)), 'A', 'B').area() == 50 * 100
    assert m.excluded_area(kdb.Region(kdb.Box(200, 0, 300, 100)), 'A', 'B').is_empty()


# NOTE: the plate of an edge is on its right, what it faces on its left, so these edges go along x: the plate
#       of edge_a is below it, and the edge_b faces it from above
@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('edge_a, edge_b, kept', [
    # both plates within the marker
    (kdb.Edge(0, 10, 100, 10), kdb.Edge(0, 20, 100, 20), []),
    # a plate outside the marker, on its left, up to its edge
    (kdb.Edge(-100, 10, 0, 10), kdb.Edge(-100, 20, 0, 20), [(0.0, 1.0)]),
    # half of both is within the marker
    (kdb.Edge(-100, 10, 100, 10), kdb.Edge(-100, 20, 100, 20), [(0.0, 0.5)]),
    # what the edge within the marker faces is outside it
    (kdb.Edge(0, 90, 100, 90), kdb.Edge(0, 110, 100, 110), [(0.0, 1.0)]),
    # the edge of a plate within the marker, up to its upper edge, which faces a plate outside
    (kdb.Edge(0, 100, 100, 100), kdb.Edge(0, 110, 100, 110), [(0.0, 1.0)]),
    # the edge of a plate outside the marker, above it, up to its upper edge, faces a plate above: both outside
    # (edge_a shifted into its plate is on the marker's edge, which counts, but the edge_b is not within it)
    (kdb.Edge(100, 100, 0, 100), kdb.Edge(100, 90, 0, 90), [(0.0, 1.0)]),
    # the substrate is in the model of the plate within the marker, also beyond the marker
    (kdb.Edge(0, 100, 100, 100), None, []),
    # but not of a plate outside it, below the marker
    (kdb.Edge(100, -10, 0, -10), None, [(0.0, 1.0)]),
])
def test_kept_edge_parts(edge_a: kdb.Edge, edge_b: Optional[kdb.Edge], kept):
    m = markers(kdb.Box(0, 0, 100, 100))
    if edge_b is None:
        assert m.kept_edge_parts(edge_a, 'A', kdb.Edge(0, -500, 100, -500), SUBSTRATE) == pytest.approx(kept)
    else:
        assert m.kept_edge_parts(edge_a, 'A', edge_b, 'A') == pytest.approx(kept)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_edges_within_different_blocks_are_kept():
    m = markers(kdb.Box(0, 0, 100, 100), kdb.Box(0, 150, 100, 250))
    assert m.kept_edge_parts(kdb.Edge(0, 100, 100, 100), 'A', kdb.Edge(0, 150, 100, 150), 'A') == [(0.0, 1.0)]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_from_layout_flattens_and_merges_markers_of_child_cells():
    layout = kdb.Layout()
    top = layout.create_cell('TOP')
    child = layout.create_cell('child')
    child.shapes(layout.layer(148, 0)).insert(kdb.Box(0, 0, 100, 100))
    top.insert(kdb.CellInstArray(child.cell_index(), kdb.Trans(1000, 0)))
    top.shapes(layout.layer(148, 0)).insert(kdb.Box(900, 0, 1000, 100))
    top.shapes(layout.layer(1, 0)).insert(kdb.Box(0, 0, 5000, 5000))

    m = Exclusions.from_layout(layout, 'TOP',
                               marker_layers=[MarkerLayer('a', (148, 0)), MarkerLayer('b', (149, 0))],
                               dbu=layout.dbu)
    assert [b.region.bbox() for b in m.blocks] == [kdb.Box(900, 0, 1100, 100)]
    assert [b.name for b in m.blocks] == ['m0']


def results(*boxes: kdb.Box, keep_capacitance_geometry: bool = True) -> CellExtractionResults:
    return CellExtractionResults(cell_name='TOP',
                                 keep_capacitance_geometry=keep_capacitance_geometry,
                                 substrate_layer_name=SUBSTRATE,
                                 exclusions=markers(*boxes))


def overlap_cap(net_top: str, net_bot: str, layer_bot: str, area: kdb.Box, cap_value: float = 10.0) -> OverlapCap:
    return OverlapCap(key=OverlapKey(layer_top='Metal3', net_top=net_top, layer_bot=layer_bot, net_bot=net_bot),
                      cap_value=cap_value,
                      shielded_area=0.0,
                      unshielded_area=0.0,
                      tech_spec=None,
                      area=kdb.Region(area))


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_overlap_within_a_marker_is_left_out():
    r = results(kdb.Box(0, 0, 100, 100))
    r.add_overlap_cap(overlap_cap('A', SUBSTRATE, SUBSTRATE, kdb.Box(0, 0, 100, 100)))
    assert r.overlap_table == {}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_overlap_keeps_its_part_outside_a_marker():
    r = results(kdb.Box(0, 0, 100, 100))
    cap = overlap_cap('A', 'B', 'Metal2', kdb.Box(50, 0, 250, 100))
    r.add_overlap_cap(cap)
    kept = r.overlap_table[cap.key][0]
    assert kept.cap_value == pytest.approx(7.5)
    assert kept.area.area() == 150 * 100
    assert kept.area.bbox() == kdb.Box(100, 0, 250, 100)
    assert cap.cap_value == pytest.approx(7.5)  # NOTE: for the report


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sidewall_keeps_clipped_part_outside_a_marker():
    r = results(kdb.Box(0, 0, 100, 100))
    key = SidewallKey(layer='Metal3', net1='A', net2='B')
    r.add_sidewall_cap(SidewallCap(key=key, cap_value=4.0, distance=0.1, length=0.2, tech_spec=None,
                                   inside_edge=kdb.Edge(-100, 50, 100, 50),
                                   outside_edge=kdb.Edge(-100, 60, 100, 60)))
    assert len(r.sidewall_table[key]) == 1
    kept = r.sidewall_table[key][0]
    assert kept.cap_value == pytest.approx(2.0)
    assert (kept.inside_edge, kept.outside_edge) == (kdb.Edge(-100, 50, 0, 50), kdb.Edge(-100, 60, 0, 60))


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sideoverlap_to_the_substrate_is_left_out_by_its_plate_alone():
    r = results(kdb.Box(0, 0, 100, 100))
    key = SideOverlapKey(layer_inside='Metal3', net_inside='A', layer_outside=SUBSTRATE, net_outside=SUBSTRATE)
    # NOTE: the fringe of a plate within the marker ends on the substrate beyond it
    r.add_sideoverlap_cap(SideOverlapCap(key=key, cap_value=4.0,
                                         inside_edge=kdb.Edge(0, 100, 100, 100),
                                         outside_edge=kdb.Edge(0, 150, 100, 150),
                                         near_edge=kdb.Edge(0, 100, 100, 100)))
    assert r.sideoverlap_table == {}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_capacitances_of_floating_nets_within_a_marker_go_to_the_substrate():
    r = results(kdb.Box(0, 0, 100, 100), keep_capacitance_geometry=False)
    r.exclusions.floating_net_names = {'F'}

    r.add_overlap_cap(overlap_cap('N', 'F', 'Metal2', kdb.Box(-100, 0, 0, 100)))
    r.add_sidewall_cap(SidewallCap(key=SidewallKey(layer='Metal3', net1='F', net2='N'), cap_value=1.0,
                                   distance=0.1, length=0.2, tech_spec=None,
                                   inside_edge=kdb.Edge(0, 100, 100, 100),
                                   outside_edge=kdb.Edge(0, 110, 100, 110)))
    r.add_sideoverlap_cap(SideOverlapCap(key=SideOverlapKey(layer_inside='Metal3', net_inside='N',
                                                            layer_outside='Metal2', net_outside='F'),
                                         cap_value=1.0,
                                         inside_edge=kdb.Edge(100, 110, 0, 110),
                                         outside_edge=kdb.Edge(100, 50, 0, 50)))
    assert [k.net_bot for k in r.overlap_table] == [SUBSTRATE]
    assert [(k.net1, k.net2) for k in r.sidewall_table] == [(SUBSTRATE, 'N')]
    assert [(k.net_inside, k.net_outside) for k in r.sideoverlap_table] == [('N', SUBSTRATE)]
    # NOTE: and they are summed up like the others, without the geometry
    assert math.isclose(sum(r.summarize().capacitances.values()), 12.0)


def results_with_pieces() -> CellExtractionResults:
    """
    The net N, with a piece left of the marker, a piece right of it, and a piece within it, on the layer Metal3
    """
    r = results(kdb.Box(0, 0, 100, 100))
    r.exclusions.pieces_by_net['N'] = [
        NetPiece('N#left', {'Metal3': kdb.Region(kdb.Box(-200, 0, 0, 100))}),
        NetPiece('N#right', {'Metal3': kdb.Region(kdb.Box(100, 0, 300, 100))}),
        NetPiece('N#within', {'Metal3': kdb.Region(kdb.Box(0, 0, 100, 100))}),
    ]
    return r


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_area_parts_by_piece():
    m = results_with_pieces().exclusions
    parts = m.area_parts(kdb.Region(kdb.Box(-100, 0, 200, 200)), 'N', 'Metal3')
    assert sorted((name, part.area()) for part, name in parts) == [('N', 300 * 100), ('N#left', 100 * 100),
                                                                   ('N#right', 100 * 100), ('N#within', 100 * 100)]
    # NOTE: the substrate has no pieces, nor has another net
    assert [name for _, name in m.area_parts(kdb.Region(kdb.Box(0, 0, 10, 10)), 'N', 'VSUBS')] == ['N']
    assert [name for _, name in m.area_parts(kdb.Region(kdb.Box(0, 0, 10, 10)), 'X', 'Metal3')] == ['X']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_edge_parts_by_piece():
    m = results_with_pieces().exclusions
    # NOTE: the metal is below the edge, on its right
    parts = m.edge_parts(kdb.Edge(-100, 100, 300, 100), -1, 'N', 'Metal3')
    assert [name for _, name in parts] == ['N#left', 'N#within', 'N#right']
    assert [interval for interval, _ in parts] == [pytest.approx((0.0, 0.25)), pytest.approx((0.25, 0.5)),
                                                   pytest.approx((0.5, 1.0))]
    # NOTE: above the edge, off the pieces
    assert m.edge_parts(kdb.Edge(-100, 100, 300, 100), 1, 'N', 'Metal3') == [((0.0, 1.0), 'N')]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_overlap_within_a_net_counts_between_its_pieces_only():
    r = results_with_pieces()
    r.exclusions.pieces_by_net['N'][0].region_by_layer['Metal2'] = kdb.Region(kdb.Box(-200, 0, -150, 100))
    r.exclusions.pieces_by_net['N'][1].region_by_layer['Metal2'] = kdb.Region(kdb.Box(-150, 0, -100, 100))
    # NOTE: the Metal3 of the left piece over the Metal2 of both pieces
    cap = overlap_cap('N', 'N', 'Metal2', kdb.Box(-200, 0, -100, 100))
    r.add_overlap_cap(cap)
    assert list(r.overlap_table) == [OverlapKey(layer_top='Metal3', net_top='N#left',
                                                layer_bot='Metal2', net_bot='N#right')]
    assert cap.cap_value == pytest.approx(5.0)  # NOTE: for the report


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_overlap_of_a_piece_on_the_substrate_of_its_net_stays_left_out():
    # NOTE: e.g. VDD over its nwell, the nwell has no pieces
    r = results_with_pieces()
    r.add_overlap_cap(overlap_cap('N', 'N', 'VSUBS', kdb.Box(-100, 0, -50, 100)))
    assert r.overlap_table == {}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sidewall_within_a_net_counts_between_its_pieces_only():
    r = results_with_pieces()
    key = SidewallKey(layer='Metal3', net1='N', net2='N')
    # NOTE: the upper edge of the piece to the left faces a part of the same piece, and of the piece within the marker
    r.exclusions.pieces_by_net['N'][0].region_by_layer['Metal3'].insert(kdb.Box(-200, 200, -50, 300))
    r.exclusions.pieces_by_net['N'][2].region_by_layer['Metal3'].insert(kdb.Box(-50, 200, -1, 300))
    r.add_sidewall_cap(SidewallCap(key=key, cap_value=1.0, distance=0.1, length=0.1, tech_spec=None,
                                   inside_edge=kdb.Edge(-100, 100, 0, 100),
                                   outside_edge=kdb.Edge(-100, 200, 0, 200)))
    kept_key, = r.sidewall_table
    assert (kept_key.net1, kept_key.net2) == ('N#left', 'N#within')
    assert sum(c.cap_value for c in r.sidewall_table[kept_key]) == pytest.approx(0.49, abs=0.01)


def network_with_pieces() -> r_network_pb2.RNetwork:
    network = r_network_pb2.RNetwork(net_name='N')
    for node_id, x, piece_name in ((1, 0, 'N#a'), (2, 100, 'N#b')):
        node = network.nodes.add(node_id=node_id, node_name=f"n{node_id}", layer_name='Metal3',
                                 node_kind=r_network_pb2.RNode.Kind.KIND_WIRE_JUNCTION)
        node.location.kind = location_pb2.Location.Kind.LOCATION_KIND_BOX
        node.location.box.lower_left.x, node.location.box.upper_right.x = x, x
        node.piece_names.append(piece_name)
    return network


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_capacitance_of_a_piece_goes_to_its_own_nodes_also_if_another_one_is_nearer():
    network = network_with_pieces()
    distributor = CapacitanceDistributor.from_networks([(network, {1: 'n1', 2: 'n2'})])
    # NOTE: nearer to the node of the other piece
    area = kdb.Region(kdb.Box(90, 0, 110, 10))
    assert distributor.area_fractions('N#a', 'Metal3', 'X', 'Metal3', area) == {('n1', 'X'): 1.0}
    assert distributor.area_fractions('N#b', 'Metal3', 'X', 'Metal3', area) == {('n2', 'X'): 1.0}
    assert distributor.area_fractions('N', 'Metal3', 'X', 'Metal3', area) == {('n2', 'X'): 1.0}
    # NOTE: and a piece is no node of the netlist, also without geometry to go by
    assert distributor.area_fractions('N#b', 'Metal3', 'X', 'Metal3', None) == {('n2', 'X'): 1.0}
    assert distributor.edge_fractions('N#a', 'Metal3', None, 'X', 'Metal3', None) == {('n1', 'X'): 1.0}
    assert distributor.area_fractions('N', 'Metal3', 'X', 'Metal3', None) == {('N', 'X'): 1.0}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_capacitance_between_parts_of_a_net_on_one_node_is_dropped():
    table = {NetCoupleKey('a', 'b'): 0.0}
    add_distributed_capacitance(table, 2.0, {('a', 'a'): 0.5, ('a', 'b'): 0.5})
    assert table == {NetCoupleKey('a', 'b'): 1.0}


def per_layer_exclusions() -> Exclusions:
    return Exclusions([ExcludedBlock(name='m0', region=kdb.Region(kdb.Box(0, 0, 100, 100)),
                                     layer_regions={'Metal3': kdb.Region(kdb.Box(0, 0, 100, 100))})],
                      substrate_layer_name=SUBSTRATE)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_marker_of_a_layer_leaves_out_only_what_is_on_it():
    e = per_layer_exclusions()
    area = kdb.Region(kdb.Box(0, 0, 100, 100))
    # NOTE: a plate on the layer and the substrate, but not the plate above it
    assert e.excluded_area(area, 'Metal3', SUBSTRATE).area() == 100 * 100
    assert e.excluded_area(area, 'Metal4', 'Metal3').is_empty()
    assert e.excluded_area(area, 'Metal4', SUBSTRATE).is_empty()

    edge = kdb.Edge(0, 100, 100, 100)
    outside_edge = kdb.Edge(0, 90, 100, 90)
    assert e.kept_edge_parts(edge, 'Metal3', outside_edge, SUBSTRATE) == []
    assert e.kept_edge_parts(edge, 'Metal3', outside_edge, 'Metal4') == [(0.0, 1.0)]
    assert e.kept_edge_parts(edge, 'Metal4', outside_edge, SUBSTRATE) == [(0.0, 1.0)]

    assert e.mask('Metal3').area() == 100 * 100
    assert e.mask('Metal4').is_empty()


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_capacitance_pair_marker_leaves_out_only_the_capacitances_between_its_layers():
    region = kdb.Region(kdb.Box(0, 0, 100, 100))
    e = Exclusions([ExcludedBlock(name='m0', region=region,
                                  layer_regions={'Metal2': region, 'Metal3': region},
                                  capacitance_pair=frozenset({'Metal2', 'Metal3'}))],
                   substrate_layer_name=SUBSTRATE)
    assert e.excluded_area(region, 'Metal3', 'Metal2').area() == 100 * 100
    assert e.excluded_area(region, 'Metal4', 'Metal3').is_empty()
    assert e.excluded_area(region, 'Metal3', SUBSTRATE).is_empty()
    edge_a, edge_b = kdb.Edge(0, 100, 100, 100), kdb.Edge(0, 90, 100, 90)
    assert e.kept_edge_parts(edge_a, 'Metal3', edge_b, 'Metal2') == []
    assert e.kept_edge_parts(edge_a, 'Metal3', edge_b, SUBSTRATE) == [(0.0, 1.0)]
    # NOTE: and the resistance extraction doesn't see it
    assert e.mask('Metal3').is_empty()

    e = Exclusions([ExcludedBlock(name='m0', region=region, layer_regions={'Metal1': region},
                                  capacitance_pair=frozenset({'Metal1', SUBSTRATE}))],
                   substrate_layer_name=SUBSTRATE)
    assert e.excluded_area(region, 'Metal1', SUBSTRATE).area() == 100 * 100
    assert e.excluded_area(region, 'Metal2', 'Metal1').is_empty()


TECH_MARKERS = {'NoRCX.drawing': MarkerLayer('NoRCX.drawing', (148, 0)),
                'Metal3.noqrc': MarkerLayer('Metal3.noqrc', (30, 28), frozenset({'Metal3'}))}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('specification, expected', [
    ('Metal3.noqrc', TECH_MARKERS['Metal3.noqrc']),
    ('235/5', MarkerLayer('235/5', (235, 5))),
    ('235/5:Metal2,Metal3', MarkerLayer('235/5:Metal2,Metal3', (235, 5), frozenset({'Metal2', 'Metal3'}))),
])
def test_marker_layer_specification(specification: str, expected: MarkerLayer):
    assert MarkerLayer.parse(specification, TECH_MARKERS, ['Metal2', 'Metal3']) == expected


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('specification, listed', [
    ('nope', 'NoRCX.drawing, Metal3.noqrc'),
    ('235/5:Metal9', 'Metal9, it has: Metal2, Metal3'),
])
def test_invalid_marker_layer_specification_lists_the_valid_values(specification: str, listed: str):
    with pytest.raises(ExclusionError, match=listed):
        MarkerLayer.parse(specification, TECH_MARKERS, ['Metal2', 'Metal3'])


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk_name', ['ihp-sg13g2', 'ihp-sg13cmos5l', 'sky130A', 'gf180mcuD'])
def test_tech_info_tells_the_layers_of_each_device_class_once(pdk_name: str):
    tech_info = TechInfo.from_json(PDK.from_string(pdk_name).config.tech_pb_json_path, dielectric_filter=None)
    patterns = [(pattern, device_layers) for device_layers in tech_info.tech.device_layers
                for pattern in device_layers.lvs_device_class_patterns]
    for mapping in tech_info.tech.device_models.device_model_mappings:
        matching = [pattern for pattern, _ in patterns if fnmatchcase(mapping.lvs_device_class_name, pattern)]
        assert len(matching) == 1, mapping.lvs_device_class_name
        assert tech_info.device_gds_pairs(mapping.lvs_device_class_name)
    assert tech_info.device_gds_pairs('nothing') is None


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_names_in_messages_are_limited():
    assert listed_names(['a', 'b']) == 'a, b'
    assert listed_names(['a', 'b', 'c'], listed_count=2) == 'a, b, and 1 more'


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_port_along_a_conductor_is_short():
    conductor = kdb.Region(kdb.Box(0, 0, 10000, 1000))
    strip = next(kdb.Region(kdb.Box(2000, 999, 8000, 1000)).each())
    port = port_of_cut(strip, lambda box: conductor, strip_width=1, port_length=500)
    assert port.bbox() == kdb.Box(4750, 999, 5250, 1000)
    across = next(kdb.Region(kdb.Box(0, 0, 1, 1000)).each())
    assert port_of_cut(across, lambda box: kdb.Region(kdb.Box(0, 0, 10000, 1000)), 1, 500).bbox() == across.bbox()


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_region_index_has_the_polygons_near_a_box():
    region = kdb.Region()
    region.insert(kdb.Box(0, 0, 10, 10))
    region.insert(kdb.Box(10, 0, 20, 10))  # NOTE: joined to the first, by the merged polygons
    region.insert(kdb.Box(100, 0, 110, 10))
    index = RegionIndex()
    assert index.near(region, kdb.Box(5, 5, 6, 6)).bbox() == kdb.Box(0, 0, 20, 10)
    assert index.near(region, kdb.Box(105, 5, 106, 6)).bbox() == kdb.Box(100, 0, 110, 10)
    assert index.near(region, kdb.Box(50, 50, 60, 60)).is_empty()


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_block_with_ports_is_found_beside_one_without():
    tie = ExcludedBlock('m0', kdb.Region(kdb.Box(0, 0, 100, 100)))
    ports = ExcludedBlock('m1', kdb.Region(kdb.Box(100, 0, 200, 100)), ports=True)
    e = Exclusions([tie, ports])
    assert e.block_index_with_ports_at(kdb.Box(90, 40, 100, 60), 'Metal1') == 1
    assert e.block_indexes_with_ports_within(kdb.Region(kdb.Box(150, 40, 160, 60)), 'Metal1') == [1]
    assert e.block_indexes_with_ports_within(kdb.Region(kdb.Box(50, 40, 60, 60)), 'Metal1') == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_edge_parts_of_overlapping_pieces_add_up_to_the_edge():
    # NOTE: a node of a piece can touch a polygon of another one, so that a polygon is in both of them
    e = Exclusions.from_region(kdb.Region(kdb.Box(0, 0, 100, 100)), ports=True)
    region = kdb.Region(kdb.Box(0, 0, 50, 20))
    e.pieces_by_net['N'] = [NetPiece('N#piece0', {'Metal1': region}), NetPiece('N#piece1', {'Metal1': region})]
    parts = e.edge_parts(kdb.Edge(0, 20, 100, 20), -1, 'N', 'Metal1')
    assert sum(interval[1] - interval[0] for interval, _ in parts) == pytest.approx(1.0)
    assert [name for _, name in parts] == ['N#piece0', 'N']

