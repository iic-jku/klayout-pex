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

"""Verify source-pinned coefficients and preserve unavailable capabilities explicitly."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Callable, List, Tuple

import allure
import pytest

from klayout_pex.pdk_config import PDK
from klayout_pex.tech_catalog import load_technology_catalog, write_nominal_catalog
from klayout_pex.tech_info import TechDefError, TechInfo
from scripts.gen_tech_pb.provenance import nominal_provenance
from scripts.gen_tech_pb.corner_data import (
    TABLE_DIRECTORY, load_corner_capacitances, write_bundled_corner_catalog,
)
from tests.common.tech_catalog import add_scenario, read_catalog


pytestmark = allure.parent_suite('Unit Tests')


@pytest.mark.parametrize('pdk', list(PDK), ids=str)
def test_imported_components_preserve_nominal_and_have_complete_corner_coverage(pdk: PDK, tmp_path: Path):
    technology = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    path = tmp_path / 'catalog.pb.json'
    written = write_bundled_corner_catalog(technology, path)
    assert len(written) == len(set(written))
    assert load_technology_catalog(path).tech == technology
    catalog = read_catalog(path)
    provenance, components = nominal_provenance(str(pdk))
    baseline_path = tmp_path / 'baseline' / 'catalog.pb.json'
    baseline_files = write_nominal_catalog(
        technology, baseline_path, provenance, f'Nominal extraction scenarios for {pdk}', components)
    for baseline_file in baseline_files:
        if baseline_file != baseline_path:
            assert baseline_file.read_bytes() == (path.parent / baseline_file.relative_to(baseline_path.parent)).read_bytes()
    assert catalog.provenance.history[0] == provenance.history[0]
    ihp = pdk in (PDK.IHP_SG13G2, PDK.IHP_SG13CMOS5L)
    sky130 = pdk == PDK.SKY130A
    expected_revision = {PDK.SKY130A: '3', PDK.IHP_SG13G2: '3', PDK.IHP_SG13CMOS5L: '4'}.get(pdk, '2')
    assert catalog.provenance.data_revision == catalog.provenance.history[-1].revision
    assert expected_revision in [entry.revision for entry in catalog.provenance.history]
    # Repeated builds must not duplicate records, change bytes or remove unrelated files.
    before = {p: p.read_bytes() for p in written}
    unrelated = path.parent / 'keep.txt'
    unrelated.write_text('keep', encoding='utf-8')
    assert write_bundled_corner_catalog(technology, path) == written
    assert {p: p.read_bytes() for p in written} == before
    assert unrelated.read_text(encoding='utf-8') == 'keep'
    # These tables are empirical C data. An R law, matched physical recipe and device
    # reference are separate evidence, so packaging C must not silently authorize them.
    expected_scenarios = ['nominal']
    if ihp:
        expected_scenarios.extend(['gatpoly-low-sheet', 'gatpoly-high-sheet'])
    elif sky130:
        expected_scenarios.extend(['hrhc-mim-bound', 'hrlc-mim-bound', 'lrhc-mim-bound', 'lrlc-mim-bound'])
    if pdk == PDK.IHP_SG13CMOS5L:
        expected_scenarios.extend(['fixed-layout-low-r', 'fixed-layout-high-r'])
    assert [scenario.id for scenario in catalog.scenarios][:len(expected_scenarios)] == expected_scenarios
    for dataset in catalog.datasets:
        component = path.parent / dataset.file.path
        assert component in written
        assert hashlib.sha256(component.read_bytes()).hexdigest() == dataset.file.sha256
    for corner in ('low', 'high'):
        add_scenario(path, name=f'test-{corner}-c', capacitance=corner)
        resolved = load_technology_catalog(path, f'test-{corner}-c')
        assert resolved.tech.process_parasitics.resistance == technology.process_parasitics.resistance
        assert resolved.selection.capacitance.id == corner
        evidence = resolved.selection.capacitance.provenance
        assert evidence['data_revision'] == evidence['history'][-1]['revision'] == '1'
        assert evidence['assumptions']
        source = next(s for s in evidence['sources'] if s['id'] == 'extraction-table')
        expected_variants = 'hrlc,lrlc' if corner == 'low' else 'hrhc,lrhc'
        assert source['options']['variants'] == expected_variants
        assert len(source['revision']) == 40 and len(source['sha256']) == 64
        assert resolved.selection.device_references is None
        with pytest.raises(TechDefError, match='no matching physical stack'):
            resolved.selection.require_physical_stack()


@pytest.mark.parametrize('pdk, top_layer, low, high', [
    (PDK.SKY130A, 'met5', (5.783, 33.265), (8.136, 41.443)),
    (PDK.GF180MCUD, 'Metal5', (5.414, 29.818), (6.240, 32.324)),
    (PDK.IHP_SG13G2, 'TopMetal2', (2.922, 31.892), (3.543, 36.817)),
    (PDK.IHP_SG13CMOS5L, 'TopMetal1', (6.104, 35.946), (7.338, 41.957)),
])
def test_corrected_upstream_top_layer_coefficients(pdk: PDK, top_layer: str, low: Tuple[float, float], high: Tuple[float, float]):
    technology = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    for dataset, expected in zip(load_corner_capacitances(technology, TABLE_DIRECTORY / f'{pdk}.json'), (low, high)):
        row = next(row for row in dataset.capacitance.capacitance.substrates if row.layer_name == top_layer)
        assert (row.area_capacitance, row.perimeter_capacitance) == expected


@pytest.mark.parametrize('pdk, plates, areas, edges', [
    (PDK.SKY130A, [('capm', 'met3'), ('capm2', 'met4')], [1778.0, 2231.0], [30.0, 350.0]),
    (PDK.GF180MCUD, [('FuseTop', 'Metal4')], [1791.0, 2189.0], [214.47, 262.13]),
    (PDK.IHP_SG13G2, [('MIM', 'Metal5')], [1350.0, 1650.0], [40.0, 40.0]),
])
def test_mim_device_laws_and_shielding_use_the_selected_corner(pdk: PDK, plates: List[Tuple[str, str]],
                                                               areas: List[float], edges: List[float]):
    technology = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    datasets = load_corner_capacitances(technology, TABLE_DIRECTORY / f'{pdk}.json')
    for dataset, area, edge in zip(datasets, areas, edges):
        capacitance = dataset.capacitance.capacitance
        overlap = {(row.top_layer_name, row.bottom_layer_name): row.capacitance for row in capacitance.overlaps}
        fringe = {(row.in_layer_name, row.out_layer_name): row.capacitance for row in capacitance.sideoverlaps}
        substrate = {row.layer_name: row for row in capacitance.substrates}
        for top, bottom in plates:
            assert overlap[top, bottom] == area
            assert fringe[top, bottom] == edge
            assert fringe[bottom, top] == edge
            assert substrate[top].area_capacitance == substrate[bottom].area_capacitance
            # The extended bottom plate shields the top-plate edge, even at the high-C
            # corner. Zero is an intentional physical value, not an absent coefficient.
            assert substrate[top].perimeter_capacitance == 0.0
    # IHP's cap_cpara factor belongs to another parasitic device. The literal CJSW of
    # cmim_core stays 40 aF/um and must not be scaled with cap_carea.


def test_missing_gf180_low_c_well_fringe_is_derived_from_same_corner_substrate():
    technology = TechInfo.parse_tech_def(PDK.GF180MCUD.config.tech_pb_json_path)
    low = load_corner_capacitances(technology, TABLE_DIRECTORY / 'gf180mcuD.json')[0].capacitance.capacitance
    row = next(row for row in low.substrates if row.layer_name == 'Metal2')
    assert row.perimeter_capacitance == 32.657
    for well in ('Nwell', 'LVPWELL'):
        fringe = next(row for row in low.sideoverlaps if row.in_layer_name == 'Metal2' and row.out_layer_name == well)
        assert fringe.capacitance == row.perimeter_capacitance


def test_fitted_sidewall_numerator_is_not_mistaken_for_monotonic_capacitance():
    technology = TechInfo.parse_tech_def(PDK.GF180MCUD.config.tech_pb_json_path)
    values = []
    for dataset in load_corner_capacitances(technology, TABLE_DIRECTORY / 'gf180mcuD.json'):
        row = next(row for row in dataset.capacitance.capacitance.sidewalls if row.layer_name == 'Poly2')
        values.append((row.capacitance, row.offset))
    # A fit changes numerator and spacing offset together. Sorting/scaling coefficients
    # by a presumed high >= low rule would corrupt a valid upstream corner law.
    assert values == [(11.799, -0.074), (10.455, -0.090)]


@pytest.mark.parametrize('edit, message', [
    (lambda d: d.__setitem__('schema_version', True), 'Unexpected technology'),
    (lambda d: d['capacitance']['low']['base']['overlaps'].__setitem__(0, 42), 'Invalid corner coefficient row'),
    (lambda d: d['capacitance']['low']['base']['overlaps'].pop(0), 'Incomplete low'),
    (lambda d: d['capacitance']['low']['base']['sidewalls'].append(
        d['capacitance']['low']['base']['sidewalls'][0]), 'Duplicate sidewalls'),
    (lambda d: d['capacitance']['nominal']['base']['substrates'][0].__setitem__(1, 1.0), 'Imported nominal'),
    (lambda d: d['capacitance']['low']['base']['substrates'][0].__setitem__(1, -math.ulp(0.0)), 'Invalid substrates'),
    (lambda d: d['capacitance']['high']['base']['sidewalls'][0].__setitem__(2, math.inf), 'Invalid sidewalls'),
    (lambda d: d['capacitance']['low']['base']['substrates'][0].__setitem__(1, False), 'must be numbers'),
    (lambda d: d['capacitance']['high']['mim'][0].__setitem__(2, 'false'), 'must be numbers'),
])
def test_incomplete_or_invalid_corner_imports_fail_before_writing(edit: Callable, message: str, tmp_path: Path):
    document = json.loads((TABLE_DIRECTORY / 'sky130A.json').read_text(encoding='utf-8'))
    edit(document)
    path = tmp_path / 'tables.json'
    path.write_text(json.dumps(document), encoding='utf-8')
    technology = TechInfo.parse_tech_def(PDK.SKY130A.config.tech_pb_json_path)
    with pytest.raises(ValueError, match=message):
        load_corner_capacitances(technology, path)
