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

from dataclasses import replace
import json
import math
from typing import Any, Dict, Optional

import allure
import klayout.db as kdb
import pytest

from klayout_pex.rcx25.c.device_capacitance_references import DeviceCapacitanceCheckError, DeviceCapacitanceReference
from tests.common.device_capacitance import REFERENCE, layout_context

from klayout_pex.klayout.lvsdb_extractor import DEVICE_CAPACITOR_PLATE_PROPERTY
from klayout_pex.rcx25.c.device_capacitance_checks import CHECK_DEVICE_PROPERTY, DeviceCapacitanceChecks, _DeviceMarker

pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('RCX25', 'Device Capacitance Observation')]


def observer(reference: DeviceCapacitanceReference = REFERENCE) -> DeviceCapacitanceChecks:
    return DeviceCapacitanceChecks(
        [reference, replace(reference, device='$2')],
        [_DeviceMarker(1, '$1', kdb.Region(kdb.Box(0, 0, 100, 100))),
         _DeviceMarker(2, '$2', kdb.Region(kdb.Box(200, 0, 300, 100)))],
        [1, 2], [frozenset(('A', 'B')), frozenset(('A', 'B'))])


def marked_shape(checks: DeviceCapacitanceChecks, net: str, left: int,
                 right: Optional[int] = None, plate: bool = True) -> kdb.PolygonWithProperties:
    shape = kdb.PolygonWithProperties(kdb.Box(left, 10, left + 10 if right is None else right, 90),
                                      {'net': net, DEVICE_CAPACITOR_PLATE_PROPERTY: plate})
    marked = checks.marked_plates(kdb.Region(shape))
    assert (marked ^ kdb.Region(shape)).is_empty()
    return next(marked.each())


def test_parallel_devices_keep_separate_measurements_and_routing_is_not_counted():
    checks = observer()
    a1, b1 = marked_shape(checks, 'A', 10), marked_shape(checks, 'B', 30)
    a2, b2 = marked_shape(checks, 'A', 210), marked_shape(checks, 'B', 230)
    wire = marked_shape(checks, 'X', 50)
    unmarked = marked_shape(checks, 'B', 50, plate=False)
    for kind, value in (('overlap', 1.0), ('sidewall', 2.0), ('fringe', 3.0)):
        checks.record(a1, 'A', b1, 'B', kind, value)
    checks.record(a2, 'A', b2, 'B', 'sidewall', 7.0)
    checks.record(a1, 'A', b2, 'B', 'sidewall', 100.0)  # cross-device coupling
    checks.record(a1, 'A', wire, 'X', 'fringe', 100.0)
    checks.record(a1, 'A', unmarked, 'B', 'fringe', 100.0)
    first, second = checks.records()
    assert first['extracted_capacitance_f'] == pytest.approx(6e-15, rel=1e-12, abs=0)
    assert second['extracted_capacitance_f'] == pytest.approx(7e-15, rel=1e-12, abs=0)
    assert first['contributions'] == pytest.approx(
        dict(overlap_f=1e-15, sidewall_f=2e-15, fringe_f=3e-15), rel=1e-12, abs=0)
    assert first['status'] == second['status'] == 'informational'


@pytest.mark.parametrize('low,high,status', [
    (None, None, 'informational'), (1.0, 1.0, 'passed'),
    (math.nextafter(1.0, 0.0), math.nextafter(1.0, 2.0), 'passed'),
    (math.nextafter(1.0, 2.0), None, 'failed'), (None, math.nextafter(1.0, 0.0), 'failed'),
    (0.0, 0.0, 'failed'),
])
def test_ratio_bounds_are_inclusive(low: Optional[float], high: Optional[float], status: str):
    checks = observer(replace(REFERENCE, min_ratio=low, max_ratio=high))
    first, second = marked_shape(checks, 'A', 10), marked_shape(checks, 'B', 30)
    checks.record(first, 'A', second, 'B', 'sidewall', 1.0)
    assert checks.records()[0]['ratio'] == 1.0
    assert checks.records()[0]['status'] == status


def test_missing_or_partial_plate_geometry_is_unevaluable():
    checks = observer()
    marked_shape(checks, 'A', 10)
    partial = marked_shape(checks, 'B', 90, 110)
    assert partial.property(CHECK_DEVICE_PROPERTY) is None
    assert checks.records()[0]['status'] == 'unevaluable'
    assert checks.records()[1]['status'] == 'unevaluable'


def test_plates_may_end_exactly_at_the_marker_boundary():
    checks = observer(replace(REFERENCE, min_ratio=0, max_ratio=0))
    marked_shape(checks, 'A', 0, 10)
    marked_shape(checks, 'B', 90, 100)
    record = checks.records()[0]
    assert record['status'] == 'passed'
    assert record['extracted_capacitance_f'] == 0
    assert record['ratio'] == 0


def test_reference_ratio_overflow_is_an_explicit_failure():
    checks = observer(replace(REFERENCE, capacitance_f=math.ulp(0.0)))
    first, second = marked_shape(checks, 'A', 10), marked_shape(checks, 'B', 30)
    checks.record(first, 'A', second, 'B', 'overlap', 1e15)
    record = checks.records()[0]
    assert record['status'] == 'unevaluable'
    assert record['ratio'] is None
    json.dumps(record, allow_nan=False)


@pytest.mark.parametrize('capacitance_ff,reference_f', [
    (math.ulp(0.0), 1e-15),  # conversion from fF to F
    (1e-300, 1e300),  # ratio division
    (float('inf'), 1e-15), (float('nan'), 1e-15), (-1.0, 1e-15),
])
def test_invalid_or_underflowing_measurements_are_not_reported_as_zero(capacitance_ff: float, reference_f: float):
    checks = observer(replace(REFERENCE, capacitance_f=reference_f))
    first, second = marked_shape(checks, 'A', 10), marked_shape(checks, 'B', 30)
    checks.record(first, 'A', second, 'B', 'overlap', capacitance_ff)
    record = checks.records()[0]
    assert record['status'] == 'unevaluable'
    assert record['extracted_capacitance_f'] is None
    assert record['ratio'] is None
    json.dumps(record, allow_nan=False)


def test_recognition_markers_match_rotations_mirrors_and_feed_variants():
    context, layout, top = layout_context('cap_cmomi_w3u_l2u_m4_m5_orientations.gds.gz')
    references = [DeviceCapacitanceReference(device.expanded_name(), 'cap_cmomi', ('mim_top', 'mim_btm'), 1e-15)
                  for device in context.top_circuit.each_device()]
    checks = DeviceCapacitanceChecks.prepare(references, context, top)
    assert len(checks.markers) == len(references) == 24
    assert len(set(checks.owners)) == 24


@pytest.mark.parametrize('changes,reason', [
    (dict(device='missing'), 'valid devices'), (dict(device_class='wrong'), 'is of class cap_cmomf'),
    (dict(terminals=('mim_top', 'missing')), 'valid terminals'),
])
def test_device_and_terminal_names_are_checked(changes: Dict[str, Any], reason: str):
    context, layout, top = layout_context()
    reference = DeviceCapacitanceReference('$1', 'cap_cmomf', ('mim_top', 'mim_btm'), 228.75e-15)
    with pytest.raises(DeviceCapacitanceCheckError, match=reason):
        DeviceCapacitanceChecks.prepare([replace(reference, **changes)], context, top)


@pytest.mark.parametrize('shorted,reason', [(True, 'share net'), (False, 'is unconnected')])
def test_shorted_or_unconnected_terminals_cannot_define_mutual_capacitance(shorted: bool, reason: str):
    context, layout, top = layout_context()
    device = next(context.top_circuit.each_device())
    if shorted:
        device.connect_terminal('mim_btm', device.net_for_terminal('mim_top'))
    else:
        device.disconnect_terminal('mim_btm')
    reference = DeviceCapacitanceReference('$1', 'cap_cmomf', ('mim_top', 'mim_btm'), 228.75e-15)
    with pytest.raises(DeviceCapacitanceCheckError, match=reason):
        DeviceCapacitanceChecks.prepare([reference], context, top)


def test_missing_recognition_marker_is_not_replaced_by_an_abstract_box():
    context, layout, top = layout_context()
    layer = top.layout().find_layer(99, 40)
    for cell in top.layout().each_cell():
        cell.shapes(layer).clear()
    with pytest.raises(DeviceCapacitanceCheckError, match='found 0'):
        DeviceCapacitanceChecks.prepare(
            [DeviceCapacitanceReference('$1', 'cap_cmomf', ('mim_top', 'mim_btm'), 228.75e-15)], context, top)


def test_a_merged_marker_cannot_absorb_an_unselected_device():
    context, layout, top = layout_context('cap_cmomi_w3u_l2u_m4_m5_orientations.gds.gz')
    layer = top.layout().find_layer(99, 39)
    box = top.bbox()
    for cell in top.layout().each_cell():
        cell.shapes(layer).clear()
    top.shapes(layer).insert(box)
    device = next(context.top_circuit.each_device())
    with pytest.raises(DeviceCapacitanceCheckError, match='also contains terminals'):
        DeviceCapacitanceChecks.prepare(
            [DeviceCapacitanceReference(device.expanded_name(), 'cap_cmomi', ('mim_top', 'mim_btm'), 1e-15)],
            context, top)


def test_observer_records_reference_provenance():
    reference = replace(REFERENCE, source='test model', description='Nominal mutual capacitance')
    record = observer(reference).records()[0]
    assert record['reference_source'] == reference.source
    assert record['reference_description'] == reference.description
