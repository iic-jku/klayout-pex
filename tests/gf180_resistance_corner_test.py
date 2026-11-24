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

"""GF180 sensitivity inputs preserve missing values and explicit source assumptions."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Dict

import allure
import pytest

from kpex.pdk_config import PDK
from kpex.tech_catalog import load_technology_catalog
from kpex.tech_info import TechDefError, TechInfo
from tests.common.tech_catalog import read_catalog

pytestmark = allure.parent_suite('Unit Tests')
CATALOG = Path(PDK.GF180MCUD.config.tech_catalog_path)
SOURCES = Path(__file__).resolve().parents[1] / 'testdata/tech_sources/gf180-resistance'
SCENARIOS = ('fixed-layout-low-r-ideal-contacts', 'fixed-layout-reference-r', 'fixed-layout-high-r')
SOURCE_HASHES = {
    '5_General_Specification1.csv': 'a20ccbc509cefd992e733472b96a6712efc65793b823a2ccd1aa90d7727c25af',
    '5_General_Specification2.csv': 'eb9a9e7983bd4f83205a329b99e9a0516cba079d9067357d5e899c73b584980e',
    '5_Sheet_Rho_table.csv': '98e9a330fcfea7e1918fa9b90ca7cac457456f29174447337a3c793794e1ce17',
    'gf180mcuD.tech': 'e8ab78e8f3c61b43d00ef493d247700ff76477ad6e9b84d2aebafde62be61fb8',
}


def primary_rows(filename: str) -> Dict[str, Dict[str, str]]:
    with (SOURCES / filename).open(encoding='utf-8', newline='') as stream:
        return {row['PARAMETERS']: row for row in csv.DictReader(stream)}


@pytest.mark.parametrize('filename,digest', SOURCE_HASHES.items())
def test_primary_source_fixtures_are_exact_pinned_bytes(filename: str, digest: str):
    assert hashlib.sha256((SOURCES / filename).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize('scenario,column', list(zip(SCENARIOS, ('MIN', 'TYP', 'MAX'))))
def test_complete_sheet_rows_match_primary_units_and_selected_11ka_stack(scenario: str, column: str):
    rows = primary_rows('5_General_Specification1.csv')
    mapping = {'Poly2': 'Wide P+ Poly (salicided)', 'Nwell': 'Wide Nwell (unsalicided)',
               **{f'Metal{i}': f'Metal {i}' for i in range(1, 5)}, 'Metal5': 'Top metal (11kA)'}
    expected = {}
    for layer, key in mapping.items():
        row = rows[key]
        assert row['UNITS'] in ('Ω/sq', 'mΩ/sq')
        expected[layer] = float(row[column]) * (1000 if row['UNITS'] == 'Ω/sq' else 1)
    with (SOURCES / '5_Sheet_Rho_table.csv').open(encoding='utf-8', newline='') as stream:
        plate = next(row for row in csv.DictReader(stream) if row['Layer'] == 'MIM Top Plate')
    assert plate['Stack'] == 'TiN600AMIMAL2000ATiN350A'
    mean, spread = (float(value) for value in plate['Rs(ohm/Squre)'].split('+/-'))
    expected['FuseTop'] = (mean + {'MIN': -1, 'TYP': 0, 'MAX': 1}[column] * spread) * 1000
    actual = load_technology_catalog(CATALOG, scenario).tech.process_parasitics.resistance
    assert {row.layer_name: row.resistance for row in actual.layers} == pytest.approx(expected)
    assert expected['Metal5'] != float(rows['Metal 5'][column])


@pytest.mark.parametrize('scenario,column', list(zip(SCENARIOS[1:], ('TYP', 'MAX'))))
def test_reference_and_high_contact_rows_use_primary_values_without_magic(scenario: str, column: str):
    rows = primary_rows('5_General_Specification2.csv')
    selected = load_technology_catalog(CATALOG, scenario)
    resistance = selected.tech.process_parasitics.resistance
    mapping = {'contact_nsd_con': 'M1-N+ (salicided)', 'contact_psd_con': 'M1-P+ (salicided)',
               'contact_poly_con': 'M1-Poly (salicided)', 'contact_ntap_con': 'M1-N+ (salicided)'}
    assert {row.contact_name: row.resistance for row in resistance.contacts} == {
        key: float(rows[source][column]) * 1000 for key, source in mapping.items()}
    assert {row.via_name: row.resistance for row in resistance.vias} == {
        f'Via{i}': float(rows[f'Via {i}'][column]) * 1000 for i in range(1, 5)}
    evidence = selected.selection.resistance.provenance
    assert 'magic-ideal-contact' not in {source['id'] for source in evidence['sources']}
    assert 'ideal-low-contacts' not in {assumption['id'] for assumption in evidence['assumptions']}


def test_ideal_contact_zeros_have_explicit_extraction_rows_not_missing_primary_defaults():
    primary = primary_rows('5_General_Specification2.csv')
    assert all(row['MIN'] == '--' for name, row in primary.items() if name != 'Contact Resistance')
    # Restrict the source to its actual low-R block. A missing alias, a nonzero
    # value, or an accidental nominal block must fail instead of falling back.
    source = (SOURCES / 'gf180mcuD.tech').read_text(encoding='utf-8')
    block = source.split('variants (lrhc),(lrlc)', 1)[1].split('variants *', 1)[0]
    contacts = {}
    for line in block.splitlines():
        fields = line.split()
        if fields and fields[0] == 'contact':
            for alias in fields[1].split(','):
                assert alias not in contacts
                contacts[alias] = float(fields[2])
    selected = load_technology_catalog(CATALOG, SCENARIOS[0])
    resistance = selected.tech.process_parasitics.resistance
    aliases = {'contact_nsd_con': 'ndc', 'contact_psd_con': 'pdc',
               'contact_poly_con': 'pc', 'contact_ntap_con': 'nndic'}
    for row in resistance.contacts:
        assert row.resistance == contacts[aliases[row.contact_name]] == 0
    for row, alias in zip(resistance.vias, ('m2c', 'm3c', 'via3', 'via4')):
        assert row.resistance == contacts[alias] == 0
    assert contacts['mimcc'] == 0  # The MIM top landing uses the same contact resistance as Via4.
    evidence = selected.selection.resistance.provenance
    assumption = next(a for a in evidence['assumptions'] if a['id'] == 'ideal-low-contacts')
    assert assumption['source_ids'] == ['contact-limits', 'magic-ideal-contact']
    assert 'unspecified' in assumption['reason']
    assert 'not specified physical minima' in next(
        item.description for item in read_catalog(CATALOG).scenarios if item.id == SCENARIOS[0])


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_scenarios_change_only_resistance_and_do_not_claim_other_corners(scenario: str):
    nominal = load_technology_catalog(CATALOG)
    selected = load_technology_catalog(CATALOG, scenario)
    assert selected.selection.capacitance == nominal.selection.capacitance
    assert selected.selection.process_stack == nominal.selection.process_stack
    assert selected.selection.device_references is None
    assert not selected.selection.physical_stack_matches
    with pytest.raises(TechDefError, match='no matching physical stack'):
        selected.selection.require_physical_stack()
    with pytest.raises(TechDefError, match='no device-capacitance reference dataset'):
        selected.selection.require_device_references()
    selected.tech.process_parasitics.resistance.CopyFrom(nominal.tech.process_parasitics.resistance)
    for mapping in nominal.tech.device_models.device_model_mappings:
        mapping.capacitance_references.clear()
    assert selected.tech == nominal.tech


def test_default_nominal_is_preserved_and_reference_is_not_silently_selected():
    nominal = load_technology_catalog(CATALOG)
    assert nominal.tech == TechInfo.parse_tech_def(PDK.GF180MCUD.config.tech_pb_json_path)
    info = TechInfo(nominal.tech, dielectric_filter=None)
    assert info.layer_resistance_by_layer_name['FuseTop'].resistance == 500
    assert info.contact_resistance_by_device_layer_name['Poly2'].resistance == 5900
    reference = load_technology_catalog(CATALOG, SCENARIOS[1]).tech
    next(row for row in reference.process_parasitics.resistance.layers if row.layer_name == 'FuseTop').resistance = 500
    assert reference.process_parasitics.resistance == nominal.tech.process_parasitics.resistance
    with pytest.raises(TechDefError, match='valid corners'):
        load_technology_catalog(CATALOG, 'fixed-layout-low-r')


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_source_assumptions_and_revision_history_expose_unqualified_density_mapping(scenario: str):
    selected = load_technology_catalog(CATALOG, scenario)
    evidence = selected.selection.resistance.provenance
    assumptions = {entry['id']: entry for entry in evidence['assumptions']}
    assert 'not a foundry-qualified 2 fF resistance limit' in assumptions['mim-density-mapping']['reason']
    assert '180 mOhm/square reference' in assumptions['reference-not-default']['reason']
    assert 'No correlation' in assumptions['noncorrelated-capacitance']['reason']
    sources = {entry['id']: entry for entry in evidence['sources']}
    for identity, filename in [('sheet-limits', '5_General_Specification1.csv'),
                               ('contact-limits', '5_General_Specification2.csv'),
                               ('mim-stack-sheet', '5_Sheet_Rho_table.csv')]:
        assert sources[identity]['sha256'] == SOURCE_HASHES[filename]
        assert sources[identity]['revision'] == '25ed9c64b64b8e1b93cc4d2d5cade4cd82383a9a'
    catalog = read_catalog(CATALOG)
    record = next(entry for entry in catalog.provenance.history if entry.revision == '3')
    assert record.references == ['https://github.com/iic-jku/klayout-pex/issues/547']
    assert [entry.revision for entry in catalog.provenance.history][:2] == ['1', '2']
    assert catalog.provenance.history[-1].revision == catalog.provenance.data_revision == '3'
    dates = [entry.date for entry in catalog.provenance.history]
    assert dates == sorted(dates)


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_cut_area_conversion_keeps_contact_and_mim_via_units(scenario: str):
    info = TechInfo.from_catalog(str(CATALOG), None, scenario_id=scenario)
    contact = info.contact_by_contact_lvs_layer_name['contact_poly_con']
    resistance = info.contact_resistance_by_device_layer_name['Poly2']
    assert info.milliohm_per_cut_to_ohm_um2_for_contact(contact, resistance) == pytest.approx(
        resistance.resistance * 1e-3 * .22 ** 2)
    via = info.contact_by_contact_lvs_layer_name['top_via_cap']
    resistance = info.via_resistance_by_layer_name['Via4']
    assert info.milliohm_per_cut_to_ohm_um2_for_via(via, resistance) == pytest.approx(
        resistance.resistance * 1e-3 * .26 ** 2)
