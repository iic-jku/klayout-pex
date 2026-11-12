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

"""Authored evidence is checked and recorded without changing the numerical model."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Tuple

import allure
import pytest
from google.protobuf.json_format import MessageToDict

from klayout_pex.pdk_config import PDK
from klayout_pex.tech_catalog import COMPONENT_KINDS, load_technology_catalog, write_nominal_catalog
from klayout_pex.tech_info import TechDefError
from klayout_pex_protobuf.kpex.tech.tech_catalog_pb2 import TechnologyDataset
from tests.common.tech_catalog import (
    add_scenario, edit_dataset, read_catalog, sample_provenance, small_catalog, small_technology,
    write_message,
)


pytestmark = allure.parent_suite('Unit Tests')


def test_sources_assumptions_and_history_reach_result_without_mutable_aliases(tmp_path: Path):
    path = small_catalog(tmp_path)
    selected = load_technology_catalog(path).selection
    result = selected.to_json()
    expected = MessageToDict(sample_provenance(), preserving_proto_field_name=True)
    assert result['catalog_provenance'] == expected
    assert result['datasets']['resistance']['provenance'] == expected
    assert result['catalog_description'] == 'Synthetic two-metal test technology'
    result['catalog_provenance']['sources'].clear()
    result['datasets']['resistance']['provenance']['history'].clear()
    assert selected.to_json()['catalog_provenance'] == expected
    assert selected.to_json()['datasets']['resistance']['provenance'] == expected


def test_reviewed_metadata_changes_identity_of_file_but_not_numerical_payload(tmp_path: Path):
    path = small_catalog(tmp_path)
    before = load_technology_catalog(path)

    def clarify(dataset: TechnologyDataset):
        dataset.description = 'Reviewed description with µm and Ω'
        dataset.provenance.data_revision = 'test-2'
        dataset.provenance.history.add(revision='test-2', date='2026-11-12',
                                       summary='Clarify source assumptions', reason='Explain the existing recipe',
                                       source_ids=['recipe'], references=['https://example.org/review/2'])
        dataset.provenance.assumptions[0].reason = 'Document the existing synthetic coefficients more precisely'

    edit_dataset(path, 'resistance', clarify)
    after = load_technology_catalog(path)
    assert before.tech == after.tech
    assert before.selection.resistance.sha256 == after.selection.resistance.sha256
    assert before.selection.resolved_technology_sha256 == after.selection.resolved_technology_sha256
    assert before.selection.catalog_sha256 != after.selection.catalog_sha256
    assert after.selection.resistance.provenance['data_revision'] == 'test-2'
    assert before.selection.resistance.provenance['data_revision'] == 'test-1'


@pytest.mark.parametrize('location', ['catalog', 'dataset'])
@pytest.mark.parametrize('edit, message', [
    (lambda p: setattr(p, 'data_revision', ''), 'data revision'),
    (lambda p: p.sources.clear(), 'at least one source'),
    (lambda p: p.sources.add().CopyFrom(p.sources[0]), 'Duplicate .* source ID'),
    (lambda p: setattr(p.sources[0], 'description', '  '), 'description must not be empty'),
    (lambda p: setattr(p.sources[0], 'uri', 'relative/source.tech'), 'absolute URI'),
    (lambda p: setattr(p.sources[0], 'uri', 'https://'), 'absolute URI'),
    (lambda p: setattr(p.sources[0], 'uri', 'https://example.org/a b'), 'absolute URI'),
    (lambda p: setattr(p.sources[0], 'revision', ''), 'revision or SHA256'),
    (lambda p: setattr(p.sources[0], 'sha256', 'a' * 63), '64 lowercase'),
    (lambda p: setattr(p.sources[0], 'sha256', 'a' * 65), '64 lowercase'),
    (lambda p: setattr(p.sources[0], 'sha256', 'A' * 64), '64 lowercase'),
    (lambda p: p.sources[0].options.update({' ': '1'}), 'option name'),
    (lambda p: p.assumptions.add().CopyFrom(p.assumptions[0]), 'Duplicate .* assumption ID'),
    (lambda p: setattr(p.assumptions[0], 'description', ''), 'description must not be empty'),
    (lambda p: setattr(p.assumptions[0], 'reason', ''), 'reason must not be empty'),
    (lambda p: p.assumptions[0].source_ids.append('unknown'), 'unknown sources: unknown'),
    (lambda p: p.assumptions[0].source_ids.append('recipe'), 'Duplicate .* source reference'),
    (lambda p: p.history.clear(), 'data-revision history'),
    (lambda p: p.history.add().CopyFrom(p.history[0]), 'Duplicate .* history revision'),
    (lambda p: setattr(p.history[0], 'date', '2025-02-29'), 'valid YYYY-MM-DD'),
    (lambda p: setattr(p.history[0], 'date', '2026-13-01'), 'valid YYYY-MM-DD'),
    (lambda p: setattr(p.history[0], 'date', '20261112'), 'valid YYYY-MM-DD'),
    (lambda p: setattr(p.history[0], 'summary', ''), 'summary must not be empty'),
    (lambda p: setattr(p.history[0], 'reason', ''), 'reason must not be empty'),
    (lambda p: p.history[0].source_ids.append('unknown'), 'unknown sources: unknown'),
    (lambda p: p.history[0].references.append('../issue/1'), 'absolute URI'),
    (lambda p: setattr(p.history[0], 'revision', 'different'), 'last history entry'),
])
def test_incomplete_or_contradictory_provenance_is_rejected(location: str, edit: Callable,
                                                          message: str, tmp_path: Path):
    path = small_catalog(tmp_path)
    if location == 'catalog':
        catalog = read_catalog(path)
        edit(catalog.provenance)
        write_message(path, catalog)
        # Catalog evidence is cheap to check and must fail before any data files are loaded.
        (path.parent / 'shared.pb.json').unlink()
    else:
        edit_dataset(path, 'resistance', lambda d: edit(d.provenance))
    with pytest.raises(TechDefError, match=message):
        load_technology_catalog(path)


@pytest.mark.parametrize('days, valid', [
    (('2024-02-28', '2024-02-29', '2024-03-01'), True),
    (('2026-11-12', '2026-11-12', '2026-11-12'), True),
    (('2026-11-12', '2026-11-11', '2026-11-13'), False),
])
def test_history_date_boundaries_allow_same_day_revisions_without_sorting_ids(
        days: Tuple[str, str, str], valid: bool, tmp_path: Path):
    path = small_catalog(tmp_path)
    catalog = read_catalog(path)
    catalog.provenance.history.clear()
    # IDs are opaque, not semantic versions or sortable corner names.
    for revision, day in zip(('z', 'b', 'a'), days):
        catalog.provenance.history.add(revision=revision, date=day, summary='Reviewed data', reason='Document evidence')
    catalog.provenance.data_revision = 'a'
    write_message(path, catalog)
    if valid:
        assert load_technology_catalog(path).selection.catalog_provenance['data_revision'] == 'a'
    else:
        with pytest.raises(TechDefError, match='oldest first'):
            load_technology_catalog(path)


def test_exact_source_hash_can_identify_an_unversioned_local_recipe(tmp_path: Path):
    path = small_catalog(tmp_path)
    catalog = read_catalog(path)
    catalog.provenance.sources[0].revision = ''
    catalog.provenance.sources[0].sha256 = 'a' * 64
    catalog.provenance.sources[0].options.update({'MIM': '1', 'OPTIONAL': ''})
    catalog.provenance.assumptions.clear()
    write_message(path, catalog)
    assert load_technology_catalog(path).selection.catalog_provenance['sources'][0]['sha256'] == 'a' * 64


def test_scenario_records_the_selected_components_own_revision(tmp_path: Path):
    path = small_catalog(tmp_path)

    def revise(dataset: TechnologyDataset):
        dataset.provenance.data_revision = 'r-2'
        dataset.provenance.history.add(revision='r-2', date='2026-11-13', summary='Replace resistance law',
                                       reason='Use a separately reviewed synthetic scenario')
        dataset.resistance.layers[0].resistance = 200

    edit_dataset(path, 'resistance', revise, new_id='other-r')
    add_scenario(path, resistance='other-r')
    result = load_technology_catalog(path, 'alternate').selection.to_json()
    assert result['catalog_provenance']['data_revision'] == 'test-1'
    assert result['datasets']['resistance']['provenance']['data_revision'] == 'r-2'
    assert result['datasets']['capacitance']['provenance']['data_revision'] == 'test-1'


def test_writer_checks_evidence_before_creating_output(tmp_path: Path):
    path = tmp_path / 'output/catalog.pb.json'
    with pytest.raises(TechDefError, match='cover exactly'):
        write_nominal_catalog(small_technology(), path, sample_provenance(), 'Test', {})
    assert not path.parent.exists()

@pytest.mark.parametrize('pdk', list(PDK), ids=str)
def test_bundled_sources_keep_corrected_capacitance_separate_from_nominal_recipes(pdk: PDK):
    selected = load_technology_catalog(Path(pdk.config.tech_catalog_path)).selection
    sources = {source['id']: source for source in selected.capacitance.provenance['sources']}
    # The corrected IHP fit is on the reviewed PR revision, not its older upstream main.
    expected = ('14b1ab845696960a0a1881ec8614acba0f7b8eb7' if str(pdk).startswith('ihp-')
                else '5740c4a81c42f9fe4af5ef2ee258a99151053d28')
    assert sources['extraction-table']['revision'] == expected
    assert expected in sources['extraction-table']['uri']
    assert len(sources['extraction-table']['sha256']) == 64
    # A build must not rewrite the identity of the existing numerical recipe.
    assert sources['recipe']['revision'] == '1b923ea54d8d9b1028de1043afd654c9e1838049'
    assert 'extraction-table' not in {source['id'] for source in selected.resistance.provenance['sources']}
    if str(pdk).startswith('ihp-'):
        devices = {source['id']: source for source in selected.device_references.provenance['sources']}
        assert devices['cap_cmomf']['revision'] == '5e6d592e4002946a4616f798c357f0f3c06cf3b6'


def test_rebuilding_equivalent_option_maps_preserves_every_file_and_catalog_hash(tmp_path: Path):
    options = {f'OPTION_{index:02d}': str(index) for index in range(32)}
    generations = []
    for index, names in enumerate((list(options), list(reversed(options)))):
        evidence = sample_provenance()
        for name in names:
            evidence.sources[0].options[name] = options[name]
        directory = tmp_path / str(index)
        catalog = directory / 'catalog.pb.json'
        written = write_nominal_catalog(small_technology(), catalog, evidence, 'Test',
                                        {kind: evidence for kind in COMPONENT_KINDS})
        # Equivalent source options must not create false review changes or stale file hashes.
        generations.append({str(path.relative_to(directory)): path.read_bytes() for path in written})
        load_technology_catalog(catalog)
    assert generations[0] == generations[1]
