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

"""CMOS5L fixed-layout resistance bounds retain explicit source and model boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import allure
import pytest

from klayout_pex.pdk_config import PDK
from klayout_pex.tech_catalog import load_technology_catalog
from klayout_pex.tech_info import TechDefError, TechInfo
from tests.common.tech_catalog import read_catalog


pytestmark = allure.parent_suite('Unit Tests')

CATALOG = Path(PDK.IHP_SG13CMOS5L.config.tech_catalog_path)
SOURCE_REVISION = 'e73adb4045731ddec21634146d536380057f6a26'

# Independent transcription of RPSQ (Ohm/square) and RPV (Ohm/cut) from
# sg13cmos5l_{min,typ,max}.itf at SOURCE_REVISION. The catalog stores milliohms.
SOURCE_ROWS = {
    'fixed-layout-low-r': ([6.2, .085, .073, .073, .073, .015], [8, 8, 8], [5, 5, 5, 1]),
    'nominal': ([7, .110, .088, .088, .088, .018], [17, 17, 15], [9, 9, 9, 2.2]),
    'fixed-layout-high-r': ([7.8, .135, .103, .103, .103, .021], [22, 22, 20], [20, 20, 20, 4]),
}
LAYER_NAMES = ['GatPoly', 'Metal1', 'Metal2', 'Metal3', 'Metal4', 'TopMetal1']
CONTACT_KEYS = [('cont_nsd_con', 'nsd_fet', 'metal1_n_mom'),
                ('cont_psd_con', 'psd_fet', 'metal1_n_mom'),
                ('cont_poly_con', 'poly_con', 'metal1_n_mom')]
VIA_NAMES = ['Via1', 'Via2', 'Via3', 'TopVia1']


@pytest.mark.parametrize('scenario', SOURCE_ROWS)
def test_complete_resistance_rows_match_own_variant_itf_in_milliohms(scenario: str):
    selected = load_technology_catalog(CATALOG, scenario)
    resistance = selected.tech.process_parasitics.resistance
    sheet, contacts, vias = SOURCE_ROWS[scenario]
    assert {r.layer_name: r.resistance for r in resistance.layers} == pytest.approx(
        dict(zip(LAYER_NAMES, (v * 1000 for v in sheet))))
    assert {(r.contact_name, r.device_layer_name, r.layer_above): r.resistance
            for r in resistance.contacts} == pytest.approx(
        dict(zip(CONTACT_KEYS, (v * 1000 for v in contacts))))
    assert {r.via_name: r.resistance for r in resistance.vias} == pytest.approx(
        dict(zip(VIA_NAMES, (v * 1000 for v in vias))))
    # A transfer from the seven-metal SG13G2 stack would add inapplicable rows.
    assert {'Metal5', 'TopMetal2', 'cmim_top', 'Activ'}.isdisjoint(
        r.layer_name for r in resistance.layers)


@pytest.mark.parametrize('scenario', ['fixed-layout-low-r', 'fixed-layout-high-r'])
def test_resistance_bounds_change_only_resistance_without_claiming_physical_or_device_corner(scenario: str):
    nominal = load_technology_catalog(CATALOG)
    selected = load_technology_catalog(CATALOG, scenario)
    selection = selected.selection
    assert selection.resistance.id == scenario
    assert selection.capacitance == nominal.selection.capacitance
    assert selection.process_stack == nominal.selection.process_stack
    assert selection.device_references is None
    assert not selection.physical_stack_matches
    with pytest.raises(TechDefError, match='no matching physical stack'):
        selection.require_physical_stack()
    with pytest.raises(TechDefError, match='no device-capacitance reference dataset'):
        selection.require_device_references()
    # Omitted device references remove only checking references, not models/mappings.
    selected.tech.process_parasitics.resistance.CopyFrom(nominal.tech.process_parasitics.resistance)
    for mapping in nominal.tech.device_models.device_model_mappings:
        mapping.capacitance_references.clear()
    assert selected.tech == nominal.tech


def test_nominal_and_gatpoly_choices_remain_available_after_complete_bounds_are_added():
    assert load_technology_catalog(CATALOG).tech == TechInfo.parse_tech_def(
        PDK.IHP_SG13CMOS5L.config.tech_pb_json_path)
    for scenario, expected in [('gatpoly-low-sheet', 6200), ('gatpoly-high-sheet', 7800)]:
        selected = load_technology_catalog(CATALOG, scenario).tech
        nominal = load_technology_catalog(CATALOG).tech
        rows = selected.process_parasitics.resistance.layers
        assert next(row.resistance for row in rows if row.layer_name == 'GatPoly') == expected
        next(row for row in rows if row.layer_name == 'GatPoly').resistance = 7000
        assert selected.process_parasitics.resistance == nominal.process_parasitics.resistance


def test_source_identity_assumptions_and_ordered_catalog_history_are_preserved():
    catalog = read_catalog(CATALOG)
    revisions = [entry.revision for entry in catalog.provenance.history]
    assert revisions[:4] == ['1', '2', '3', '4']
    assert catalog.provenance.data_revision == revisions[-1]
    assert '548' in catalog.provenance.history[2].references[0]
    assert '518' in catalog.provenance.history[3].references[0]
    hashes = {
        'itf-min': 'ad16a5ade248c7d87c7a6789887e5a99cf9431f639358c6c104643527f879e73',
        'itf-typ': '08d0de3413256b996b7b6c5a1816e02f8dae4151e0df12c7a8f081ccee415cea',
        'itf-max': '969f391818c63d3057bf4554067626f2ec65c4949bb9a3820cc05ba74e67cb86',
        'process-spec': '26e28c28024411a98b7f3dd586f2c4c8bba832904e5a75935cebeb3264b378cd',
    }
    for scenario in ('fixed-layout-low-r', 'fixed-layout-high-r'):
        component = next(record for record in catalog.datasets
                         if record.id == scenario)
        document = json.loads((CATALOG.parent / component.file.path).read_text(encoding='utf-8'))
        provenance = document['provenance']
        assert {source['id']: source['sha256'] for source in provenance['sources']} == hashes
        assert all(source['revision'] == SOURCE_REVISION for source in provenance['sources'])
        assert all(source['options'] == {'sheet_resistance_unit': 'ohm/square',
                                         'contact_resistance_unit': 'ohm/cut', 'cut_area_unit': 'um^2'}
                   for source in provenance['sources'] if source['id'].startswith('itf-'))
        assert all('/ihp-sg13cmos5l/' in source['uri'] for source in provenance['sources'])
        assumptions = {entry['id']: entry for entry in provenance['assumptions']}
        assert {'fixed-layout', 'device-ownership', 'diffusion-contacts', 'topvia-source',
                'noncorrelated-capacitance', 'diffusion-boundary', 'source-units'} == set(assumptions)
        assert 'Metal4 and TopMetal1' in assumptions['topvia-source']['description']
        assert '0.1764' in assumptions['topvia-source']['reason']


@pytest.mark.parametrize('scenario', SOURCE_ROWS)
def test_contact_and_via_resistivities_use_the_source_cut_areas(scenario: str):
    info = TechInfo.from_catalog(str(CATALOG), None, scenario_id=scenario)
    _, contact_values, via_values = SOURCE_ROWS[scenario]
    for (contact_name, device_layer, _), expected in zip(CONTACT_KEYS, contact_values):
        contact = info.contact_by_contact_lvs_layer_name[contact_name]
        resistance = info.contact_resistance_by_device_layer_name[device_layer]
        assert contact.width == pytest.approx(.16)
        assert info.milliohm_per_cut_to_ohm_um2_for_contact(contact, resistance) == pytest.approx(expected * .0256)
    for name, lvs_name, area, expected in zip(
            VIA_NAMES, ['via1_drw', 'via2_drw', 'via3_drw', 'topvia1_n_cap'], [.0361, .0361, .0361, .1764], via_values):
        contact = info.contact_by_contact_lvs_layer_name[lvs_name]
        resistance = info.via_resistance_by_layer_name[name]
        assert info.milliohm_per_cut_to_ohm_um2_for_via(contact, resistance) == pytest.approx(expected * area)
