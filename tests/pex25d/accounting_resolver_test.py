#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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

"""Accounting partition invariants on actual native polygon operations.

A result mask may classify geometry, never move it or change electrical identity.
Tests distinguish boundary touching from area overlap and coarse-grid crossings
from exactly representable angled geometry; via cuts must remain indivisible.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, FrozenSet
from unittest.mock import patch

import klayout.db as kdb
import pytest

from klayout_pex.klayout.pex25d_accounting import (AccountingGridError, partition_accounting,
                                                 validate_accounting_geometry)
from klayout_pex.klayout.pex25d_ground import region_of
from klayout_pex.klayout.native_coordinates import NATIVE_COORDINATE_MIN, NATIVE_COORDINATE_MAX
from klayout_pex.pex25d.accounting_validation import validate_capacitance_accounting
from klayout_pex.pex25d.diagnostics import DiagnosticsReport
from klayout_pex.pex25d.reader import read_pex25d_text
from klayout_pex.pex25d.resolver import resolve, ResolveError


HEADER = '''\
PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING
UNITS LENGTH nm GRID 1
GROUND_PLANE substrate NET VSS Z_OFFSETS -10 -5
METAL m1 Z_OFFSETS 0 5
METAL m2 Z_OFFSETS 10 15
VIA v CONNECTS m1 m2
DIELECTRIC_BACKGROUND air PERMITTIVITY 1
DIELECTRIC_SIMPLE ox WRAPS substrate PERMITTIVITY 4 BETWEEN substrate m1
DIELECTRIC_SIMPLE ild WRAPS m1 PERMITTIVITY 4 BETWEEN m1 m2
'''


def file_of(*records: str) -> Any:
    return read_pex25d_text((HEADER + '\n'.join(records) + '\n').encode())


def area_by_membership(scene: Any, layer: str = 'm1') -> Dict[FrozenSet[str], int]:
    areas = defaultdict(int)
    for conductor in scene.conductors:
        for part in conductor.regions:
            if part.layer == layer:
                areas[frozenset(part.accounting_regions)] += region_of(part).area()
    return dict(areas)


def union(scene: Any, layer: str = 'm1') -> kdb.Region:
    result = kdb.Region()
    for conductor in scene.conductors:
        for part in conductor.regions:
            if part.layer == layer:
                result += region_of(part)
    return result.merged()


def assert_partition(scene: Any, expected: kdb.Region, layer: str = 'm1'):
    assert (union(scene, layer) ^ expected).is_empty()
    validate_accounting_geometry(scene)
    assert validate_capacitance_accounting(scene, DiagnosticsReport())
    ids = [part.accounting_part_id for conductor in scene.conductors for part in conductor.regions]
    assert all(ids) and len(ids) == len(set(ids))


def test_hole_stays_outside_mask_and_preserves_physical_conductor():
    scene = resolve(file_of('CONDUCTOR A sig', 'BOX CONDUCTOR A LAYER m1 LL 0 0 UR 10 10',
                            'CAP_REGION ring LAYER m1 OUTER 0 0 10 0 10 10 0 10 '
                            'HOLE 3 3 7 3 7 7 3 7'))
    assert area_by_membership(scene) == {frozenset({'ring'}): 84, frozenset(): 16}
    assert_partition(scene, kdb.Region(kdb.Box(0, 0, 10, 10)))
    assert scene.conductors[0].net == 'sig'


def test_overlapping_masks_keep_both_memberships_without_area_overlap():
    scene = resolve(file_of('CONDUCTOR A sig', 'BOX CONDUCTOR A LAYER m1 LL 0 0 UR 12 10',
                            'CAP_REGION left LAYER m1 OUTER 0 0 6 0 6 10 0 10',
                            'CAP_REGION right LAYER m1 OUTER 4 0 10 0 10 10 4 10'))
    assert area_by_membership(scene) == {frozenset({'left'}): 40, frozenset({'right'}): 40,
                                        frozenset({'left', 'right'}): 20, frozenset(): 20}
    assert_partition(scene, kdb.Region(kdb.Box(0, 0, 12, 10)))


def test_disconnected_mask_polygons_and_overlapping_source_shapes_union_once():
    scene = resolve(file_of('CONDUCTOR A sig', 'BOX CONDUCTOR A LAYER m1 LL 0 0 UR 6 10',
                            'BOX CONDUCTOR A LAYER m1 LL 4 0 UR 10 10',
                            'CAP_REGION ends LAYER m1 OUTER 0 0 2 0 2 10 0 10',
                            'CAP_REGION ends LAYER m1 OUTER 8 0 10 0 10 10 8 10'))
    assert area_by_membership(scene) == {frozenset({'ends'}): 40, frozenset(): 60}
    assert_partition(scene, kdb.Region(kdb.Box(0, 0, 10, 10)))


def test_absent_layer_mask_does_not_inherit_membership_from_other_layer():
    scene = resolve(file_of('CONDUCTOR A sig', 'BOX CONDUCTOR A LAYER m1 LL 0 0 UR 10 10',
                            'BOX CONDUCTOR A LAYER m2 LL 0 0 UR 10 10',
                            'CAP_REGION lower LAYER m1 OUTER 0 0 10 0 10 10 0 10'))
    assert area_by_membership(scene, 'm2') == {frozenset(): 100}
    assert_partition(scene, kdb.Region(kdb.Box(0, 0, 10, 10)), 'm2')


@pytest.mark.parametrize('boundary,inside', [(9, 10), (10, 0), (11, 0)])
def test_mask_just_inside_touching_and_just_outside_boundary(boundary, inside):
    scene = resolve(file_of('CONDUCTOR A sig', 'BOX CONDUCTOR A LAYER m1 LL 0 0 UR 10 10',
                            f'CAP_REGION side LAYER m1 OUTER {boundary} 0 20 0 20 10 {boundary} 10'))
    assert area_by_membership(scene).get(frozenset({'side'}), 0) == inside
    assert_partition(scene, kdb.Region(kdb.Box(0, 0, 10, 10)))


@pytest.mark.parametrize('limit,expected', [(1, 0), (2, 0), (3, None), (4, 4), (5, 4)])
def test_via_mask_below_at_and_above_cut_boundaries(limit, expected):
    message = file_of('CONDUCTOR A sig', 'BOX CONDUCTOR A LAYER v LL 2 2 UR 4 4',
                      f'CAP_REGION cut LAYER v OUTER 0 0 {limit} 0 {limit} 6 0 6')
    before = message.SerializeToString()
    if expected is None:
        report = DiagnosticsReport()
        with pytest.raises(ResolveError):
            resolve(message, report=report)
        assert any('clips a via cut' in d.message for d in report.diagnostics)
    else:
        scene = resolve(message)
        assert area_by_membership(scene, 'v').get(frozenset({'cut'}), 0) == expected
        assert_partition(scene, kdb.Region(kdb.Box(2, 2, 4, 4)), 'v')
    assert message.SerializeToString() == before


def test_touching_individual_via_cuts_can_have_different_accounting_membership():
    scene = resolve(file_of('CONDUCTOR A sig', 'BOX CONDUCTOR A LAYER v LL 0 0 UR 2 2',
                            'BOX CONDUCTOR A LAYER v LL 2 0 UR 4 2',
                            'CAP_REGION cut LAYER v OUTER 0 0 2 0 2 2 0 2'))
    assert area_by_membership(scene, 'v') == {frozenset({'cut'}): 4, frozenset(): 4}
    assert_partition(scene, kdb.Region(kdb.Box(0, 0, 4, 2)), 'v')


def test_partition_is_idempotent_and_same_layer_sources_get_unique_parts():
    message = file_of('CONDUCTOR A sig', 'BOX CONDUCTOR A LAYER m1 LL 0 0 UR 10 10',
                      'CAP_REGION side LAYER m1 OUTER 5 0 15 0 15 10 5 10')
    scene = resolve(message)
    before = scene.SerializeToString()
    # Already resolved parts are multiple source regions on one layer. Their
    # IDs must not reset to zero independently when the operation is repeated.
    partition_accounting(scene)
    assert scene.SerializeToString() == before
    assert_partition(scene, kdb.Region(kdb.Box(0, 0, 10, 10)))


def test_floating_and_connected_conductors_keep_distinct_electrical_ownership():
    scene = resolve(file_of('CONDUCTOR VSS FLOATING', 'CONDUCTOR A VSS',
                            'BOX CONDUCTOR VSS LAYER m1 LL 0 0 UR 4 4',
                            'BOX CONDUCTOR A LAYER m1 LL 6 0 UR 10 4',
                            'CAP_REGION all LAYER m1 OUTER -1 -1 11 -1 11 5 -1 5'))
    assert [(c.name, c.net, c.floating) for c in scene.conductors] == [
        ('VSS', 'FLOATING', True), ('A', 'VSS', False)]
    validate_accounting_geometry(scene)


@pytest.mark.parametrize('value', [NATIVE_COORDINATE_MIN - 1, NATIVE_COORDINATE_MIN,
                                  NATIVE_COORDINATE_MAX, NATIVE_COORDINATE_MAX + 1])
@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('location', ['mask', 'conductor'])
def test_unsupported_native_coordinates_fail_with_domain_diagnostic(value, axis, location):
    message = file_of('CONDUCTOR A sig', 'BOX CONDUCTOR A LAYER m1 LL 0 0 UR 10 10',
                      'CAP_REGION side LAYER m1 OUTER 0 0 10 0 10 10 0 10')
    if location == 'mask':
        polygon = message.capacitance_accounting.regions[0].masks[0].polygons[0]
        # Translate the whole rectangle, retaining a valid polygon for the
        # semantic check; the failure must come from the native coordinate gate.
        for point in polygon.outer.points:
            setattr(point, axis, getattr(point, axis) + value)
    else:
        box = message.shapes[0].box
        for point in (box.lower_left, box.upper_right):
            setattr(point, axis, getattr(point, axis) + value)
    report = DiagnosticsReport()
    with pytest.raises(ResolveError):
        resolve(message, report=report)
    assert any(d.code == 'PEX25D-E0285' and 'native' in d.message for d in report.diagnostics)


@pytest.mark.parametrize('near_upper', [False, True])
def test_adjacent_interior_native_endpoint_is_accepted(near_upper):
    start = NATIVE_COORDINATE_MAX - 11 if near_upper else NATIVE_COORDINATE_MIN + 1
    message = file_of('CONDUCTOR A sig', f'BOX CONDUCTOR A LAYER m1 LL {start} 0 UR {start + 10} 10',
                      f'CAP_REGION all LAYER m1 OUTER {start} 0 {start + 10} 0 '
                      f'{start + 10} 10 {start} 10')
    scene = resolve(message)
    assert area_by_membership(scene) == {frozenset({'all'}): 100}


@pytest.mark.parametrize('offset', [0, 100000, -100000])
def test_exact_angled_crossing_preserves_area_and_translation(offset):
    scene = resolve(file_of('CONDUCTOR A sig',
                            f'POLYGON CONDUCTOR A LAYER m1 OUTER {offset} 0 {offset + 4} 2 {offset} 4',
                            f'CAP_REGION side LAYER m1 OUTER {offset + 2} -1 {offset + 5} -1 '
                            f'{offset + 5} 5 {offset + 2} 5'))
    assert area_by_membership(scene) == {frozenset({'side'}): 2, frozenset(): 6}
    expected = kdb.Region(kdb.Polygon([kdb.Point(offset, 0), kdb.Point(offset + 4, 2),
                                      kdb.Point(offset, 4)]))
    assert_partition(scene, expected)


@pytest.mark.parametrize('records', [
    # A coarse-grid conductor/mask crossing previously lost one unit of area.
    ['POLYGON CONDUCTOR A LAYER m1 OUTER 0 0 4 2 0 4',
     'CAP_REGION side LAYER m1 OUTER 1 -1 5 -1 5 5 1 5'],
    # The opposite operand order must not hide the same fractional crossing.
    ['BOX CONDUCTOR A LAYER m1 LL 1 -1 UR 5 5',
     'CAP_REGION side LAYER m1 OUTER 0 0 4 2 0 4'],
    # Merging two polygons within one mask must not round before partitioning.
    ['BOX CONDUCTOR A LAYER m1 LL -1 -1 UR 6 6',
     'CAP_REGION side LAYER m1 OUTER 0 0 4 2 0 4',
     'CAP_REGION side LAYER m1 OUTER 1 -1 5 -1 5 5 1 5'],
    # Sequential, overlapping masks create crossings of their own boundaries.
    ['BOX CONDUCTOR A LAYER m1 LL -1 -1 UR 6 6',
     'CAP_REGION first LAYER m1 OUTER 0 0 4 2 0 4',
     'CAP_REGION second LAYER m1 OUTER 1 -1 5 -1 5 5 1 5'],
])
def test_fractional_intersections_fail_without_mutating_file(records):
    message = file_of('CONDUCTOR A sig', *records)
    before = message.SerializeToString()
    report = DiagnosticsReport()
    with pytest.raises(ResolveError):
        resolve(message, report=report)
    assert any('finer GRID' in d.message for d in report.diagnostics)
    assert message.SerializeToString() == before


def test_partition_failure_does_not_partially_replace_scene_geometry():
    valid = file_of('CONDUCTOR A sig', 'BOX CONDUCTOR A LAYER m1 LL 0 0 UR 10 10',
                    'CONDUCTOR B other', 'BOX CONDUCTOR B LAYER v LL 2 2 UR 4 4')
    scene = resolve(valid)
    policy = file_of('CAP_REGION metal LAYER m1 OUTER 5 -1 11 -1 11 11 5 11',
                     'CAP_REGION via LAYER v OUTER 0 0 3 0 3 5 0 5').capacitance_accounting
    scene.capacitance_accounting.CopyFrom(policy)
    before = scene.SerializeToString()
    with pytest.raises(ValueError, match='clips a via cut'):
        partition_accounting(scene)
    assert scene.SerializeToString() == before


def test_serialized_overlap_and_wrong_membership_are_rejected():
    scene = resolve(file_of('CONDUCTOR A sig', 'BOX CONDUCTOR A LAYER m1 LL 0 0 UR 10 10',
                            'CAP_REGION side LAYER m1 OUTER 5 -1 11 -1 11 11 5 11'))
    first = scene.conductors[0].regions[0]
    saved = list(first.accounting_regions)
    del first.accounting_regions[:]
    with pytest.raises(ValueError, match='disagrees'):
        validate_accounting_geometry(scene)
    first.accounting_regions.extend(saved)
    scene.conductors[0].regions.add().CopyFrom(first)
    with pytest.raises(ValueError, match='overlap'):
        validate_accounting_geometry(scene)


def test_unknown_required_feature_is_rejected_before_geometry_backend_import():
    message = file_of('CONDUCTOR A sig', 'BOX CONDUCTOR A LAYER m1 LL 0 0 UR 10 10',
                      'CAP_REGION side LAYER m1 OUTER 5 -1 11 -1 11 11 5 11')
    message.required_capabilities.append(99)
    import builtins
    original_import = builtins.__import__
    def checked_import(name, *args, **kwargs):
        assert 'pex25d_accounting' not in name, 'geometry import before required-capability gate'
        return original_import(name, *args, **kwargs)
    with patch('builtins.__import__', side_effect=checked_import), pytest.raises(ResolveError):
        resolve(message)


def test_missing_kernel_is_domain_error_only_when_masks_need_resolution():
    script = '''
import importlib.abc
import sys
class Forbidden(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'klayout':
            raise ImportError('test backend unavailable')
sys.meta_path.insert(0, Forbidden())
from klayout_pex.pex25d.reader import read_pex25d_text
from klayout_pex.pex25d.resolver import resolve, ResolveError
from klayout_pex.pex25d.diagnostics import DiagnosticsReport
message = read_pex25d_text(sys.stdin.buffer.read())
report = DiagnosticsReport()
try:
    resolve(message, report=report)
except ResolveError:
    assert any(d.code == 'PEX25D-E0285' and 'test backend unavailable' in d.message for d in report.diagnostics)
else:
    raise AssertionError('accounting masks were ignored')
message.ClearField('capacitance_accounting')
resolve(message)
'''
    text = HEADER + 'CONDUCTOR A sig\nBOX CONDUCTOR A LAYER m1 LL 0 0 UR 10 10\n' + \
           'CAP_REGION side LAYER m1 OUTER 5 -1 11 -1 11 11 5 11\n'
    result = subprocess.run([sys.executable, '-c', script], input=text,
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('scale', [10, 100])
def test_original_slanted_wire_uses_exact_finer_grid_when_crossing_requires_it(scale):
    path = Path(__file__).resolve().parents[2] / 'testdata/designs/ihp-sg13g2/test_patterns/exclusion_slanted_wire.gds.gz'
    layout = kdb.Layout()
    layout.read(str(path))
    polygon = next(kdb.Region(layout.top_cell().begin_shapes_rec(layout.layer(30, 0))).each())
    coordinates = ' '.join(f'{point.x * scale} {point.y * scale}' for point in polygon.each_point_hull())
    edge, extent = 5000 * scale, 30000 * scale
    message = file_of('CONDUCTOR wire W', f'POLYGON CONDUCTOR wire LAYER m1 OUTER {coordinates}',
                      f'CAP_REGION marker LAYER m1 OUTER {-edge} {-extent} {edge} {-extent} '
                      f'{edge} {extent} {-edge} {extent}')
    # Physical source DBU is 1nm. Ten/times finer grid cannot represent its
    # quarter-DBU crossings; hundred/times finer can, without moving an edge.
    message.units.grid_numerator = 1
    message.units.grid_denominator = scale
    if scale == 10:
        report = DiagnosticsReport()
        with pytest.raises(ResolveError) as failure:
            resolve(message, report=report)
        assert any('finer GRID' in d.message for d in report.diagnostics)
        assert isinstance(failure.value.__cause__, AccountingGridError)
        assert failure.value.__cause__.refinement_factor == 2
    else:
        scene = resolve(message)
        expected = kdb.Region(polygon.transformed(kdb.ICplxTrans(scale)))
        assert_partition(scene, expected)
        assert len(area_by_membership(scene)) == 2


def test_exact_grid_error_collects_lcm_of_distinct_crossing_denominators():
    message = file_of('CONDUCTOR A sig',
                      'POLYGON CONDUCTOR A LAYER m1 OUTER 0 0 4 2 0 4',
                      'POLYGON CONDUCTOR A LAYER m1 OUTER 10 0 16 2 10 4',
                      'CAP_REGION cuts LAYER m1 OUTER 1 -1 5 -1 5 5 1 5',
                      'CAP_REGION cuts LAYER m1 OUTER 11 -1 17 -1 17 5 11 5')
    before = message.SerializeToString()
    with pytest.raises(ResolveError) as failure:
        resolve(message)
    cause = failure.value.__cause__
    assert isinstance(cause, AccountingGridError)
    assert cause.refinement_factor == 6  # half-grid and third-grid crossings
    assert message.SerializeToString() == before

    # A direct caller can rebuild on that finer rational grid without changing
    # the physical dimensions. Authored resolve itself never changes the grid.
    factor = cause.refinement_factor
    for profile in [message.ground_plane, *message.metals]:
        profile.zlow *= factor
        profile.zhigh *= factor
    for shape in message.shapes:
        for point in shape.polygon.outer.points:
            point.x *= factor
            point.y *= factor
    for region in message.capacitance_accounting.regions:
        for mask in region.masks:
            for polygon in mask.polygons:
                for ring in [polygon.outer, *polygon.holes]:
                    for point in ring.points:
                        point.x *= factor
                        point.y *= factor
    message.units.grid_denominator *= factor
    scene = resolve(message)
    assert scene.units.grid_denominator == 6
    assert union(scene).area() == (8 + 12) * factor ** 2
    validate_accounting_geometry(scene)
