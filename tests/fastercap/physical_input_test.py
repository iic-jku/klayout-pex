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

"""Direct physical recipes preserve the existing solver's options and device geometry."""

from collections import defaultdict
from typing import Any, Dict, Tuple
from pathlib import Path
import shutil
from unittest.mock import patch

import allure
import klayout.db as kdb
import pytest

from klayout_pex.fastercap.fastercap_error import FasterCapError
from klayout_pex.fastercap.fastercap_input_builder import FasterCapInputBuilder
from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder
from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.klayout.pex25d_builder import PEX25DBuilder, BuilderOptions
from klayout_pex.klayout.physical_geometry import shape_region
from klayout_pex.tech_info import TechInfo
from klayout_pex.fastercap.physical_input import _PhysicalExclusions
from klayout_pex.rcx25.exclusion import Exclusions, ExcludedBlock, BlockKind, ConductorPart
from tests.common.pdk_test_config import PDKName
from tests.fastercap.fastercap_input_builder_test import context_of_layout


pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('Physical FasterCap Input')]


def capture(context: KLayoutExtractionContext, technology: TechInfo, **options: Any) -> FasterCapModelBuilder:
    with patch.object(FasterCapModelBuilder, 'generate', autospec=True, side_effect=lambda model: model):
        return FasterCapInputBuilder(context, technology, 'VSS', **options).build()


def physical_volumes(model: FasterCapModelBuilder, dielectric: bool = False) -> Dict[Tuple[str, float, float], kdb.Region]:
    result = defaultdict(kdb.Region)
    # Compare on one grid in physical units, not database-coordinate integers.
    transform = kdb.ICplxTrans(model.dbu/.0001)
    for name, regions in (model.dlayers if dielectric else model.clayers).items():
        for region, low, high in regions:
            result[name, round(low*model.dbu, 9), round(high*model.dbu, 9)] += region.transformed(transform)
    return result


def assert_volumes_equal(first: Dict[Tuple[str, float, float], kdb.Region],
                         second: Dict[Tuple[str, float, float], kdb.Region]):
    assert set(first) == set(second)
    for key in first:
        assert (first[key] ^ second[key]).is_empty(), key


@pytest.mark.parametrize('bias', [-.0002, .0002])
def test_bias_on_absent_metal_is_identity_for_every_direct_solver_input(bias: float):
    context, technology = context_of_layout(PDKName.IHP_SG13G2, 'nmos_diode2', 'nmos_diode2.gds.gz')
    options = dict(k_void=7.25, delaunay_amax=.09, delaunay_b=.7)
    nominal = capture(context, technology, **options)
    technology.process_stack_layer_by_name['TopMetal2'].metal_layer.line_width_bias = bias
    adjusted = capture(context, technology, **options)
    assert adjusted.dbu == nominal.dbu
    assert adjusted.k_void == nominal.k_void == 7.25
    assert adjusted.delaunay_amax == nominal.delaunay_amax == .09
    assert adjusted.delaunay_b == nominal.delaunay_b == .7
    assert adjusted.materials == nominal.materials
    assert_volumes_equal(physical_volumes(nominal), physical_volumes(adjusted))
    assert_volumes_equal(physical_volumes(nominal, True), physical_volumes(adjusted, True))


@pytest.mark.parametrize('k_void', [3.5, 3.9, 7.25])
def test_present_bias_preserves_diffusion_contacts_substrate_and_direct_options(k_void: float):
    context, technology = context_of_layout(PDKName.IHP_SG13G2, 'nmos_diode2', 'nmos_diode2.gds.gz')
    nominal = capture(context, technology, k_void=k_void, delaunay_amax=.09, delaunay_b=.7)
    technology.process_stack_layer_by_name['Metal1'].metal_layer.line_width_bias = .0002
    adjusted = capture(context, technology, k_void=k_void, delaunay_amax=.09, delaunay_b=.7)
    assert adjusted.k_void == k_void
    assert adjusted.delaunay_amax == .09
    assert adjusted.delaunay_b == .7
    assert adjusted.materials == nominal.materials
    before, after = physical_volumes(nominal), physical_volumes(adjusted)
    assert set(before) == set(after)
    changed = []
    for key in before:
        if not (before[key] ^ after[key]).is_empty():
            changed.append(key)
            assert key[1:] == (1.04, 1.46), key
    assert changed
    # These diffusion blocks are part of direct FasterCap's existing contract,
    # even though compact-device geometry is deliberately absent from PEX25D.
    assert {key[0] for key in after if key[1:] == (0.0, .1)} >= {'VDD', 'VSS'}
    assert 'subs' not in {key[0] for key in after}
    file = PEX25DBuilder(context, technology, context.top_circuit.name,
                        BuilderOptions(include_resistance=False)).build()
    shared_metals = defaultdict(kdb.Region)
    for shape in file.shapes:
        if shape.layer == 'Metal1':
            shared_metals[shape.conductor] += shape_region(shape)
    assert shared_metals
    for net, region in shared_metals.items():
        assert (region ^ after[net, 1.04, 1.46]).is_empty()


def test_unavailable_mim_geometry_fails_before_direct_model_generation():
    context, technology = context_of_layout(PDKName.IHP_SG13G2, 'test_patterns',
                                            'cap_cmim_20um_x_20um_over_m4_wire.gds.gz')
    technology.process_stack_layer_by_name['cmim_top'].metal_layer.physical_geometry_unavailable = True
    with patch.object(FasterCapModelBuilder, 'generate', side_effect=AssertionError('partial output')):
        with pytest.raises(FasterCapError, match='no qualified geometry'):
            FasterCapInputBuilder(context, technology, 'VSS').build()


@pytest.mark.parametrize('kind', [BlockKind.MARKER, BlockKind.CUT])
def test_exclusion_masks_keep_overlaps_layer_filters_and_original_registry(kind: BlockKind):
    first = kdb.Region(kdb.Box(0, 0, 100, 100))
    second = kdb.Region(kdb.Box(50, 0, 150, 100))
    original = Exclusions([
        ExcludedBlock('first', first, layer_regions={'Metal1': first, 'Metal2': first}, kind=kind, ports=True),
        ExcludedBlock('second', second, layer_regions={'Metal1': second}, kind=kind, ports=True)])
    original.excluded_net_names.add('POWER')
    view = _PhysicalExclusions(original, kdb.ICplxTrans(10))
    # Biased wire edges retain their sub-DBU offset while masks keep exact layout positions.
    wire = kdb.Region(kdb.Box(-1, 100, 1601, 200))
    parts = view.conductor_parts_of_shapes(wire, 'N', 'Metal1')
    by_blocks = {original.conductor_parts[name].block_indexes: region for region, name in parts}
    assert set(by_blocks) == {frozenset(), frozenset({0}), frozenset({1}), frozenset({0, 1})}
    assert sum(region.area() for region in by_blocks.values()) == wire.area()
    assert by_blocks[frozenset()].bbox().left == -1
    metal2 = view.conductor_parts_of_shapes(wire, 'N', 'Metal2')
    assert {original.conductor_parts[name].block_indexes for _, name in metal2} == {frozenset(), frozenset({0})}
    assert original.blocks[0].region.bbox() == kdb.Box(0, 0, 100, 100)
    assert original.blocks[1].layer_regions['Metal1'].bbox() == kdb.Box(50, 0, 150, 100)
    assert original.excluded_net_names == {'POWER'}
    assert view.conductor_name(ConductorPart('VSS', is_substrate=True)) in original.conductor_parts


@pytest.mark.parametrize('left,right', [(-2, 1), (-1, 2), (0, 3), (1, 4)])
def test_unchanged_via_center_membership_uses_original_grid(left: int, right: int):
    mask = kdb.Region(kdb.Box(0, 0, 100, 100))
    original = Exclusions.from_region(mask)
    cut = kdb.Region(kdb.Box(left, 10, right, 13))
    expected = original.conductor_parts_of_vias(cut, 'N', 'Metal1', 'Metal2')
    view = _PhysicalExclusions(original, kdb.ICplxTrans(10))
    actual = view.conductor_parts_of_vias(cut.transformed(kdb.ICplxTrans(10)), 'N', 'Metal1', 'Metal2')
    assert [name for _, name in actual] == [name for _, name in expected]
    for (source, _), (physical, _) in zip(expected, actual):
        assert (source.transformed(kdb.ICplxTrans(10)) ^ physical).is_empty()


def test_present_bias_with_exclusions_keeps_diffusion_and_substrate_parts_registered():
    context, technology = context_of_layout(PDKName.IHP_SG13G2, 'nmos_diode2', 'nmos_diode2.gds.gz')
    technology.process_stack_layer_by_name['Metal1'].metal_layer.line_width_bias = .0002
    box = context.top_cell_bbox()
    mask = kdb.Region(kdb.Box(box.left, box.bottom, box.center().x, box.top))
    exclusions = Exclusions.from_region(mask)
    exclusions.excluded_net_names.add('VDD')
    before = mask.dup()
    model = capture(context, technology, exclusions=exclusions, k_void=7.25)
    assert exclusions.conductor_parts
    assert all(name in exclusions.conductor_parts for name in model.clayers)
    assert any(part.is_substrate for part in exclusions.conductor_parts.values())
    assert (exclusions.blocks[0].region ^ before).is_empty()
    assert exclusions.excluded_net_names == {'VDD'}
    assert model.k_void == 7.25


def test_restriction_only_adapter_wraps_geometry_range_errors_without_partial_output():
    from tests.klayout.physical_geometry_test import restricted_fixture
    fixture = restricted_fixture()
    fixture.geometry['met1'] = kdb.Region(kdb.Box(214748364, 0, 214748464, 20))
    before = fixture.geometry['met1'].dup()
    with patch.object(FasterCapModelBuilder, 'generate', side_effect=AssertionError('partial output')):
        with pytest.raises(FasterCapError, match='coordinate range'):
            FasterCapInputBuilder(fixture.context, fixture.tech, 'subs').build()
    assert (fixture.geometry['met1'] ^ before).is_empty()


@pytest.mark.parametrize('bias', [-.01, 20.0])
def test_direct_field_extent_contains_large_growth_and_preserves_drawn_extent_on_erosion(bias: float):
    from tests.klayout.physical_geometry_test import biased_fixture
    from klayout_pex.klayout.pex25d_builder import PEX25DBuilder, BuilderOptions
    from klayout_pex.klayout.physical_geometry import shape_region
    from klayout_pex.fastercap.physical_input import _PhysicalInputBuilder
    fixture = biased_fixture(bias)
    original_box = kdb.Box(0, 0, 100, 20)
    fixture.context.top_cell_bbox = lambda: original_box
    physical = PEX25DBuilder(fixture.context, fixture.tech, 'extent', BuilderOptions(include_resistance=False))
    file = physical.build()
    original = FasterCapInputBuilder(fixture.context, fixture.tech, 'subs')
    adapted = _PhysicalInputBuilder(original, physical, file)
    box = adapted.top_cell_bbox()
    drawn = original_box.transformed(kdb.ICplxTrans(10))
    geometry = shape_region(file.shapes[0]).bbox()
    assert box == drawn+geometry
    assert (box & geometry) == geometry
    if bias < 0:
        assert box == drawn
    else:
        assert box.left < drawn.left-80000  # More than the old 8 um halo.


@pytest.mark.parametrize('edge,accepted', [(2147483646, True), (2147483647, False),
                                         (-2147483647, True), (-2147483648, False)])
def test_scaled_exclusion_masks_reject_native_endpoints_before_indexing(edge: int, accepted: bool):
    original = Exclusions.from_region(kdb.Region(kdb.Box(0, 0, 10, 10)))
    low, high = (edge, edge+10) if edge < 0 else (edge-10, edge)
    original.blocks[0].region = kdb.Region(kdb.Box(low, 0, high, 10))
    before = original.blocks[0].region.bbox()
    # A distant marker may extend beyond the layout field, so its own boundary
    # must be validated before the exclusion index can perform native booleans.
    with patch.object(Exclusions, '__init__', return_value=None) as index:
        if accepted:
            _PhysicalExclusions(original, kdb.ICplxTrans(1))
            index.assert_called_once()
        else:
            with pytest.raises(FasterCapError, match='coordinate range'):
                _PhysicalExclusions(original, kdb.ICplxTrans(1))
            index.assert_not_called()
    assert original.blocks[0].region.bbox() == before


@pytest.mark.parametrize('target,accepted', [(2147483646, True), (2147483646.75, False),
                                           (-2147483647, True), (-2147483647.75, False)])
def test_scaled_bounds_cannot_round_onto_native_endpoint(target: float, accepted: bool):
    from klayout_pex.fastercap.physical_input import _scaled_region
    box = kdb.Box(1, 1, 2, 2) if target > 0 else kdb.Box(-2, -2, -1, -1)
    region = kdb.Region(box)
    scale = kdb.ICplxTrans(abs(target)/2)
    if accepted:
        scaled = _scaled_region(region, scale).bbox()
        assert (scaled.right if target > 0 else scaled.left) == target
    else:
        with patch.object(kdb.Region, 'transformed', side_effect=AssertionError('unsafe region transform')):
            with pytest.raises(FasterCapError, match='coordinate range'):
                _scaled_region(region, scale)
    assert region.bbox() == box


@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('side,offset,accepted', [
    ('upper', -1, True), ('upper', 0, False), ('upper', 1, False),
    ('lower', -1, False), ('lower', 0, False), ('lower', 1, True),
])
def test_field_halo_range_is_checked_before_exclusion_partitioning(
        axis: str, side: str, offset: int, accepted: bool):
    from tests.klayout.physical_geometry_test import biased_fixture
    from klayout_pex.fastercap.physical_input import _PhysicalInputBuilder
    from klayout_pex.klayout.native_coordinates import NATIVE_COORDINATE_MAX, NATIVE_COORDINATE_MIN

    fixture = biased_fixture(.002)
    fixture.context.top_cell_bbox = lambda: kdb.Box(0, 0, 100, 20)
    physical = PEX25DBuilder(fixture.context, fixture.tech, 'extent', BuilderOptions(include_resistance=False))
    file = physical.build()
    margin = 80000  # Existing 8 um field halo on the 0.0001 um physical grid.
    edge = (NATIVE_COORDINATE_MAX-margin if side == 'upper' else
            NATIVE_COORDINATE_MIN+margin) + offset
    low, high = (edge-10, edge) if side == 'upper' else (edge, edge+10)
    box = file.shapes[0].box
    if axis == 'x':
        box.lower_left.x, box.upper_right.x = low, high
    else:
        box.lower_left.y, box.upper_right.y = low, high
    before = file.SerializeToString(deterministic=True)
    exclusions = Exclusions.from_region(kdb.Region(kdb.Box(0, 0, 100, 20)))
    original = FasterCapInputBuilder(fixture.context, fixture.tech, 'subs', exclusions=exclusions)
    # Exact endpoints can hang booleans or lose contacts, unlike their neighbors. Check
    # before constructing the mask view, not after conductor partitioning.
    with patch('klayout_pex.fastercap.physical_input._PhysicalExclusions') as masks:
        if accepted:
            _PhysicalInputBuilder(original, physical, file)
            masks.assert_called_once()
        else:
            with pytest.raises(FasterCapError, match='field margin exceeds'):
                _PhysicalInputBuilder(original, physical, file)
            masks.assert_not_called()
    assert file.SerializeToString(deterministic=True) == before
    assert exclusions.blocks[0].region.bbox() == kdb.Box(0, 0, 100, 20)


@pytest.mark.slow
@pytest.mark.fastercap
@pytest.mark.skipif(shutil.which('FasterCap') is None, reason='FasterCap is not installed')
def test_direct_solver_preserves_expected_capacitance_order_under_physical_width_bias(tmp_path: Path):
    from klayout_pex.fastercap.fastercap_runner import run_fastercap, fastercap_parse_capacitance_matrix

    context, technology = context_of_layout(PDKName.IHP_SG13G2, 'test_patterns', 'r_single_wire_m1.gds.gz')
    capacitances = []
    for bias in (0.0, 0.2, 0.4):
        technology.process_stack_layer_by_name['Metal1'].metal_layer.line_width_bias = bias
        model = FasterCapInputBuilder(context, technology, 'SUB', k_void=3.0).build()
        directory = tmp_path/str(bias)
        directory.mkdir()
        paths = model.write_fastcap(str(directory), 'wire')
        log = str(directory/'solve.log')
        run_fastercap(shutil.which('FasterCap'), paths[0], log, 0.005, 0.1, 0, True, False, False)
        matrix = fastercap_parse_capacitance_matrix(log)
        assert len(matrix.conductor_names) == 2
        ground = next(i for i, name in enumerate(matrix.conductor_names) if name.endswith('_SUB'))
        wire = 1-ground
        assert matrix[wire][ground] == pytest.approx(matrix[ground][wire], rel=.02, abs=0)
        capacitances.append(-(matrix[wire][ground]+matrix[ground][wire])/2)
    assert 0 < capacitances[0] < capacitances[1] < capacitances[2]
