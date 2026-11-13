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
"""Ground openings retain original stack heights and independent net ownership."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import klayout.db as kdb
import pytest

from klayout_pex import pex25d
from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder
from klayout_pex.fastercap.pex25d_exporter import FasterCapModelOptions
from klayout_pex.fastercap.pex25d_model_builder import PEX25DFasterCapModelBuilder
from klayout_pex.plugin_api.v1 import retained_ground_region


from tests.common.pex25d_ground import GROUND_CUTOUT_TEXT as BASE


def test_overlapping_cutouts_are_unioned_and_holes_retain_ground_islands():
    text = BASE.replace('GROUND_CUTOUT subs OUTER -1 -1 2 -1 2 2 -1 2',
                        'GROUND_CUTOUT subs OUTER -2 -2 2 -2 2 2 -2 2 HOLE -1 -1 -1 1 1 1 1 -1\n'
                        'GROUND_CUTOUT subs OUTER 1.5 -1 4 -1 4 1 1.5 1')
    ground = pex25d.resolve(pex25d.read_text(text.encode('utf-8'))).ground_plane
    field = kdb.Region(kdb.Box(-3000, -3000, 3000, 3000))
    before = field.dup()
    # Independent rectangle arithmetic: 36 - (16 - 4 + 2) square micrometers.
    result = retained_ground_region(ground, field)
    assert result.area() == 22_000_000
    assert (result & kdb.Region(kdb.Box(-500, -500, 500, 500))).area() == 1_000_000
    assert (field ^ before).is_empty()


def test_actual_solver_prisms_use_ground_openings_and_net():
    scene = pex25d.resolve(pex25d.read_text(BASE.encode('utf-8')))
    with patch.object(FasterCapModelBuilder, 'generate', autospec=True) as generate:
        PEX25DFasterCapModelBuilder(scene, FasterCapModelOptions()).build()
    model = generate.call_args.args[0]
    ground, zlow, zhigh = model.clayers['VSS'][0]
    assert (zlow, zhigh) == (-100, 0)
    assert ground.area() == 27_000_000  # 6x6 field minus 3x3 opening.
    assert 'subs' not in model.clayers
    signal, signal_low, signal_high = model.clayers['signal'][0]
    assert signal.area() == 1_000_000
    assert (signal_low, signal_high) == (0, 200)
    assert ground.interacting(signal).is_empty()


def test_ground_rooted_film_wraps_retained_ground():
    text = BASE.replace('CONDUCTOR pin signal',
                        'DIELECTRIC_CONFORMAL ox WRAPS subs PERMITTIVITY 4 '
                        'THICKNESS_OVER_WRAPPED 0.1 THICKNESS_BESIDE_WRAPPED 0 '
                        'THICKNESS_ON_FIELD 0\nCONDUCTOR pin signal')
    scene = pex25d.resolve(pex25d.read_text(text.encode('utf-8')))
    with patch.object(FasterCapModelBuilder, 'generate', autospec=True) as generate:
        PEX25DFasterCapModelBuilder(scene, FasterCapModelOptions()).build()
    model = generate.call_args.args[0]
    ground = model.clayers['VSS'][0][0]
    coating = model.dlayers['ox'][0][0]
    assert (ground ^ coating).is_empty()


def test_native_coordinate_limit_rejected_before_wraparound():
    scene = pex25d.resolve(pex25d.read_text(BASE.encode('utf-8')))
    scene.ground_plane.cutouts[0].polygon.outer.points[0].x = 2 ** 31
    with pytest.raises(ValueError, match='signed 32-bit'):
        retained_ground_region(scene.ground_plane, kdb.Region(kdb.Box(0, 0, 10, 10)))


@pytest.mark.parametrize('edge,accepted', [(-0.001, True), (0.0, False), (0.001, False)])
def test_contact_clearance_at_cutout_edge(edge: float, accepted: bool):
    # Contact is inside the opening only with strictly positive clearance.
    # Exact shared side/edge is already an electrical touch, despite zero area.
    text = BASE.replace('OUTER -1 -1 2 -1 2 2 -1 2',
                        f'OUTER {edge} -1 2 -1 2 2 {edge} 2')
    scene = pex25d.resolve(pex25d.read_text(text.encode('utf-8')))
    from klayout_pex.pex25d.exporters import validate_export_scene
    if accepted:
        validate_export_scene(scene)
    else:
        with pytest.raises(pex25d.InvalidSceneError):
            validate_export_scene(scene)


def test_ground_island_inside_cutout_remains_an_electrical_body():
    text = BASE.replace('OUTER -1 -1 2 -1 2 2 -1 2',
                        'OUTER -1 -1 2 -1 2 2 -1 2 HOLE 0.2 0.2 0.2 0.8 0.8 0.8 0.8 0.2')
    scene = pex25d.resolve(pex25d.read_text(text.encode('utf-8')))
    from klayout_pex.pex25d.exporters import validate_export_scene
    with pytest.raises(pex25d.InvalidSceneError):
        validate_export_scene(scene)


@pytest.mark.parametrize('net', ['VSS', 'FLOATING'])
def test_only_explicit_reference_net_can_touch_ground(net: str):
    scene = pex25d.resolve(pex25d.read_text(BASE.replace('CONDUCTOR pin signal',
        f'CONDUCTOR pin {net}').replace('GROUND_CUTOUT subs OUTER -1 -1 2 -1 2 2 -1 2\n', '').encode('utf-8')))
    from klayout_pex.pex25d.exporters import validate_export_scene
    if net == 'VSS':
        validate_export_scene(scene)
    else:
        with pytest.raises(pex25d.InvalidSceneError):
            validate_export_scene(scene)


def test_floating_shortname_matching_ground_keeps_distinct_solver_body(tmp_path: Path):
    import json
    from klayout_pex.pex25d.electrical import BodyKind, write_solver_body_map
    text = BASE.replace('CONDUCTOR pin signal', 'CONDUCTOR VSS FLOATING').replace('CONDUCTOR pin LAYER', 'CONDUCTOR VSS LAYER')
    scene = pex25d.resolve(pex25d.read_text(text.encode('utf-8')))
    model = PEX25DFasterCapModelBuilder(scene, FasterCapModelOptions())
    with patch.object(FasterCapModelBuilder, 'generate', autospec=True) as generate:
        model.build()
    raw = generate.call_args.args[0]
    assert set(raw.clayers) == {'VSS', 'FLOATING:VSS'}
    assert len(model.body_names) == 2
    mapping_path = tmp_path / 'body_names.json'
    assert write_solver_body_map(scene, mapping_path) == str(mapping_path)
    mapping = json.loads(mapping_path.read_text(encoding='utf-8'))
    floating = next(row for row in mapping['bodies'] if row['kind'] == BodyKind.FLOATING_BODY.value)
    assert floating == dict(kind='floating-body', name='VSS', solver_name='FLOATING:VSS')


def test_complete_reference_removal_is_rejected_before_meshing():
    text = BASE.replace('OUTER -1 -1 2 -1 2 2 -1 2', 'OUTER -4 -4 4 -4 4 4 -4 4')
    scene = pex25d.resolve(pex25d.read_text(text.encode('utf-8')))
    with patch.object(FasterCapModelBuilder, 'generate') as generate:
        with pytest.raises(pex25d.ExportError, match='complete reference body'):
            PEX25DFasterCapModelBuilder(scene, FasterCapModelOptions()).build()
    generate.assert_not_called()


def test_no_ground_scene_has_no_phantom_electrical_net():
    from klayout_pex.pex25d.electrical import BodyKind, ElectricalBody, solver_body_names
    scene = pex25d.resolve(pex25d.read_text(BASE.encode('utf-8')))
    scene.ClearField('ground_plane')
    assert solver_body_names(scene) == {ElectricalBody(BodyKind.NET, 'signal'): 'signal'}
    with patch.object(FasterCapModelBuilder, 'generate', autospec=True) as generate:
        PEX25DFasterCapModelBuilder(scene, FasterCapModelOptions()).build()
    assert set(generate.call_args.args[0].clayers) == {'signal'}


@pytest.mark.parametrize('coordinate,accepted', [(-(2 ** 31), False),
                                               (-(2 ** 31) + 1, True),
                                               (2 ** 31 - 2, True),
                                               (2 ** 31 - 1, False),
                                               (-(2 ** 31) - 1, False),
                                               (2 ** 31, False)])
def test_cutout_native_grid_limits_report_domain_diagnostics(coordinate: int, accepted: bool):
    from klayout_pex.pex25d.exporters import validate_export_scene
    scene = pex25d.resolve(pex25d.read_text(BASE.encode('utf-8')))
    # Isolate representability from contact topology; this conductor clears z.
    scene.layers[0].zlow = 1
    points = scene.ground_plane.cutouts[0].polygon.outer.points
    offset = coordinate - (min(p.x for p in points) if coordinate < 0 else max(p.x for p in points))
    for point in points:
        point.x += offset
    report = pex25d.DiagnosticsReport()
    if accepted:
        validate_export_scene(scene, report=report)
        assert not report.num_errors
    else:
        with pytest.raises(pex25d.InvalidSceneError):
            validate_export_scene(scene, report=report)
        assert {d.code for d in report.diagnostics} == {'PEX25D-E0311'}


@pytest.mark.parametrize('right,accepted', [(2 ** 31 - 3, True),
                                          (2 ** 31 - 2, False),
                                          (2 ** 31 - 1, False)])
def test_ground_contact_envelope_limit_is_checked_before_native_arithmetic(right: int, accepted: bool):
    from klayout_pex.pex25d.exporters import validate_export_scene
    scene = pex25d.resolve(pex25d.read_text(BASE.encode('utf-8')))
    points = scene.ground_plane.cutouts[0].polygon.outer.points
    for point in points:
        point.x = (2 ** 31 - 101) if point.x < 0 else (2 ** 31 - 2)
    box = scene.conductors[0].regions[0].boxes[0]
    box.lower_left.x = 2 ** 31 - 51
    box.upper_right.x = right
    report = pex25d.DiagnosticsReport()
    if accepted:
        validate_export_scene(scene, report=report)
    else:
        with pytest.raises(pex25d.InvalidSceneError):
            validate_export_scene(scene, report=report)
        assert {d.code for d in report.diagnostics} == {'PEX25D-E0311'}


@pytest.mark.parametrize('left,accepted', [(-(2 ** 31) + 2, True),
                                          (-(2 ** 31) + 1, False),
                                          (-(2 ** 31), False)])
def test_lower_contact_envelope_limit(left: int, accepted: bool):
    from klayout_pex.pex25d.exporters import validate_export_scene
    scene = pex25d.resolve(pex25d.read_text(BASE.encode('utf-8')))
    for point in scene.ground_plane.cutouts[0].polygon.outer.points:
        point.x = -(2 ** 31) + 1 if point.x < 0 else -(2 ** 31) + 100
    box = scene.conductors[0].regions[0].boxes[0]
    box.lower_left.x = left
    box.upper_right.x = -(2 ** 31) + 50
    report = pex25d.DiagnosticsReport()
    if accepted:
        validate_export_scene(scene, report=report)
    else:
        with pytest.raises(pex25d.InvalidSceneError):
            validate_export_scene(scene, report=report)
        assert {d.code for d in report.diagnostics} == {'PEX25D-E0311'}


@pytest.mark.parametrize('coordinate,accepted', [(-(2 ** 31), False),
                                               (-(2 ** 31) + 1, True),
                                               (2 ** 31 - 2, True),
                                               (2 ** 31 - 1, False),
                                               (2 ** 31, False)])
def test_export_field_range_checked_before_native_construction(coordinate: int, accepted: bool):
    # The source format carries int64 coordinates. A native backend must reject
    # its unsupported endpoint before kdb.Box wraps or a later Boolean hangs:
    # https://github.com/KLayout/klayout/issues/2552
    scene = pex25d.resolve(pex25d.read_text(BASE.encode('utf-8')))
    box = scene.domain.box
    if coordinate < 0:
        box.lower_left.x, box.upper_right.x = coordinate, coordinate + 100
    else:
        box.lower_left.x, box.upper_right.x = coordinate - 100, coordinate
    builder = PEX25DFasterCapModelBuilder(scene, FasterCapModelOptions())
    if accepted:
        assert builder.field.bbox().left == box.lower_left.x
        assert builder.field.bbox().right == box.upper_right.x
    else:
        with pytest.raises(pex25d.ExportError, match='cannot be represented'):
            _ = builder.field


@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('offset,code', [(10000, 'PEX25D-E0310'),
                                         (-(2 ** 31) + 1, 'PEX25D-E0311'),
                                         (-(2 ** 31) + 2, 'PEX25D-E0310')])
def test_ground_overlap_near_lower_native_limit_is_never_silently_accepted(
        axis: str, offset: int, code: str):
    from klayout_pex.pex25d.exporters import validate_export_scene
    scene = pex25d.resolve(pex25d.read_text(BASE.encode('utf-8')))
    scene.ClearField('domain')
    # The contact is far from the opening, so all its XY area touches ground.
    # At MIN+1 the one-grid envelope reaches MIN: native `interacting` returns
    # a false negative there, even though the translated MIN+2 control overlaps.
    # https://github.com/KLayout/klayout/issues/2552
    for point in (scene.conductors[0].regions[0].boxes[0].lower_left,
                  scene.conductors[0].regions[0].boxes[0].upper_right):
        if axis == 'x':
            point.x += offset
            point.y += 5000
        else:
            point.y += offset
            point.x += 5000
    report = pex25d.DiagnosticsReport()
    with pytest.raises(pex25d.InvalidSceneError):
        validate_export_scene(scene, report=report)
    assert {diagnostic.code for diagnostic in report.diagnostics} == {code}


@pytest.mark.parametrize('coordinate', [-(2 ** 31), 2 ** 31 - 1])
@pytest.mark.parametrize('polygon', [False, True])
def test_no_ground_scene_checks_native_conductor_coordinates_before_meshing(
        coordinate: int, polygon: bool):
    scene = pex25d.resolve(pex25d.read_text(BASE.encode('utf-8')))
    scene.ClearField('ground_plane')
    scene.ClearField('domain')
    region = scene.conductors[0].regions[0]
    box = region.boxes[0]
    lo, hi = (coordinate, coordinate+1000) if coordinate < 0 else (coordinate-1000, coordinate)
    box.lower_left.x, box.upper_right.x = lo, hi
    if polygon:
        shape = region.polygons.add()
        for x, y in ((lo, 0), (hi, 0), (hi, 1000), (lo, 1000)):
            shape.outer.points.add(x=x, y=y)
        del region.boxes[:]
    with patch.object(FasterCapModelBuilder, 'generate') as generate:
        with pytest.raises(pex25d.ExportError, match='Native export geometry cannot be represented'):
            PEX25DFasterCapModelBuilder(scene, FasterCapModelOptions()).build()
    generate.assert_not_called()


@pytest.mark.parametrize('resolved', [False, True])
@pytest.mark.parametrize('opening', ['clear', 'touch', 'absent'])
def test_strict_validation_checks_ground_contacts_while_structural_validation_keeps_intermediates(
        resolved: bool, opening: str):
    text = BASE
    if opening == 'touch':
        text = text.replace('OUTER -1 -1 2 -1 2 2 -1 2', 'OUTER 0 -1 2 -1 2 2 0 2')
    elif opening == 'absent':
        text = text.replace('GROUND_CUTOUT subs OUTER -1 -1 2 -1 2 2 -1 2\n', '')
    file = pex25d.read_text(text.encode('utf-8'))
    message = pex25d.resolve(file) if resolved else file
    assert not pex25d.validate(message).num_errors
    report = pex25d.validate(message, strict=True)
    assert {d.code for d in report.diagnostics} == (set() if opening == 'clear' else {'PEX25D-E0310'})


@pytest.mark.parametrize('invalid', ['net', 'ring'])
@pytest.mark.parametrize('operation', ['strict-file', 'strict-scene', 'export'])
def test_invalid_cutout_definition_never_reaches_native_ground_geometry(invalid: str, operation: str):
    from klayout_pex.pex25d.exporters import validate_export_scene
    from klayout_pex.pex25d.validator import Validator
    file = pex25d.read_text(BASE.encode('utf-8'))
    if invalid == 'net':
        file.ground_plane.net = ''
    else:
        del file.ground_plane.cutouts[0].polygon.outer.points[2:]
    message = file if operation == 'strict-file' else pex25d.resolve(file)
    report = pex25d.DiagnosticsReport()
    with patch.object(Validator, 'check_ground_contacts',
                      side_effect=AssertionError('invalid cutout reached native geometry')) as ground_check:
        if operation == 'export':
            with pytest.raises(pex25d.InvalidSceneError):
                validate_export_scene(message, report=report)
        else:
            pex25d.validate(message, strict=True, report=report)
    assert report.num_errors > 0
    ground_check.assert_not_called()


@pytest.mark.parametrize('operation', ['strict', 'export'])
def test_prior_report_errors_do_not_suppress_new_ground_contact(operation: str):
    from klayout_pex.pex25d.exporters import validate_export_scene
    from klayout_pex.pex25d.validator import Validator
    text = BASE.replace('GROUND_CUTOUT subs OUTER -1 -1 2 -1 2 2 -1 2\n', '')
    scene = pex25d.resolve(pex25d.read_text(text.encode('utf-8')))
    report = pex25d.DiagnosticsReport()
    Validator(report).diagnose('prior-input', 'An earlier input failed')
    if operation == 'strict':
        pex25d.validate(scene, strict=True, report=report)
    else:
        with pytest.raises(pex25d.InvalidSceneError):
            validate_export_scene(scene, report=report)
    assert {d.code for d in report.diagnostics} == {'prior-input', 'PEX25D-E0310'}
