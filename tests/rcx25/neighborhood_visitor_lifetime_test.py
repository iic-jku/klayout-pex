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

import gc
from typing import Any, List
import weakref

import allure
import klayout.db as kdb
import pytest

from klayout_pex.rcx25.c.device_capacitor_plates import DeviceCapacitorPlates
from klayout_pex.rcx25.c.overlap_extractor import OverlapExtractor
from klayout_pex.rcx25.c.sidewall_and_fringe_extractor import SidewallAndFringeExtractor
from klayout_pex.rcx25.extraction_reporter import ExtractionReporter
from klayout_pex.rcx25.extraction_results import CellExtractionResults
from klayout_pex.tech_info import TechInfo
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2


@allure.parent_suite('Unit Tests')
@allure.tag('RCX25', 'Capacitance', 'Lifetime')
@pytest.mark.parametrize('kind', ['overlap', 'edge'])
@pytest.mark.parametrize('case', ['empty', 'normal', 'callback_error'])
@pytest.mark.parametrize('runs', [1, 3])
@pytest.mark.parametrize('keep_geometry', [False, True])
def test_completed_extractions_release_visitors_and_results(
        kind: str, case: str, runs: int, keep_geometry: bool, monkeypatch: pytest.MonkeyPatch):
    # Empty regions still construct nodes. A callback failure must release them
    # too. Repeated calls expose accumulating ownership, in both C-only and RC
    # storage modes. Weak references observe collection without retaining data.
    extractor_class = OverlapExtractor if kind == 'overlap' else SidewallAndFringeExtractor
    visitor_class = (OverlapExtractor.PEXPolygonNeighborhoodVisitor if kind == 'overlap'
                     else SidewallAndFringeExtractor.PEXEdgeNeighborhoodVisitor)
    callback_name = 'neighbors' if kind == 'overlap' else 'on_edge'
    original_init = visitor_class.__init__
    original_callback = getattr(visitor_class, callback_name)
    visitors: List[weakref.ReferenceType] = []
    results_refs: List[weakref.ReferenceType] = []
    report_refs: List[weakref.ReferenceType] = []
    calls = 0

    def observe_init(visitor: Any, *args: Any, **kwargs: Any):
        original_init(visitor, *args, **kwargs)
        visitors.append(weakref.ref(visitor))

    def observe_callback(visitor: Any, *args: Any, **kwargs: Any):
        nonlocal calls
        calls += 1
        original_callback(visitor, *args, **kwargs)
        if case == 'callback_error':
            raise RuntimeError('callback failed')

    monkeypatch.setattr(visitor_class, '__init__', observe_init)
    monkeypatch.setattr(visitor_class, callback_name, observe_callback)
    tech = tech_pb2.Technology()
    tech.process_parasitics.side_halo = 8.0
    caps = tech.process_parasitics.capacitance
    caps.overlaps.add(top_layer_name='upper', bottom_layer_name='lower', capacitance=10.0)
    for inside, outside in [('lower', 'upper'), ('upper', 'lower')]:
        caps.substrates.add(layer_name=inside, area_capacitance=10.0, perimeter_capacitance=40.0)
        caps.sidewalls.add(layer_name=inside, capacitance=50.0, offset=0.1)
        caps.sideoverlaps.add(in_layer_name=inside, out_layer_name=outside, capacitance=40.0)
    tech_info = TechInfo(tech, None)
    substrate = kdb.Region()
    substrate.enable_properties()
    if case != 'empty':
        substrate.insert(kdb.PolygonWithProperties(kdb.Polygon(kdb.Box(0, 0, 4000, 4000)), {'net': 'VSUBS'}))
    regions = {'VSUBS': substrate}
    for index, name in enumerate(['lower', 'upper']):
        region = kdb.Region()
        region.enable_properties()
        if case != 'empty':
            offset = index * 1000
            region.insert(kdb.PolygonWithProperties(
                kdb.Polygon(kdb.Box(offset, offset, offset + 2000, offset + 2000)), {'net': name}))
        regions[name] = region

    for _ in range(runs):
        results = CellExtractionResults(cell_name='TOP', keep_capacitance_geometry=keep_geometry)
        report = ExtractionReporter(cell_name='TOP', dbu=0.001, report_caps=True)
        results_refs.append(weakref.ref(results))
        report_refs.append(weakref.ref(report))
        arguments = dict(all_layer_names=list(regions), layer_regions_by_name=regions, dbu=0.001,
                         tech_info=tech_info, device_capacitor_plates=DeviceCapacitorPlates(),
                         results=results, report=report)
        if kind == 'edge':
            arguments.update(scale_ratio_to_fit_halo=False, mos_channels=kdb.Region())
        extractor = extractor_class(**arguments)
        if case == 'callback_error':
            with pytest.raises(RuntimeError, match='callback failed'):
                extractor.extract()
        else:
            extractor.extract()
        gc.collect()
        # Keeping the extractor and its results must not retain finished visitors.
        assert all(reference() is None for reference in visitors)
        assert (calls > 0) == (case != 'empty')
        if case == 'normal':
            summary = results.summarize()
            assert summary.capacitances
            if kind == 'overlap':
                # Areas of 4, 3 and 1 square micrometres at 10 aF per square
                # micrometre: lower shields one square micrometre of upper.
                assert sum(summary.capacitances.values()) == pytest.approx(0.08)
        del extractor, results, report, arguments
        gc.collect()
        assert all(reference() is None for reference in results_refs)
        assert all(reference() is None for reference in report_refs)
    expected_per_run = 1 if case == 'callback_error' else (3 if kind == 'overlap' else 2)
    assert len(visitors) == runs * expected_per_run
