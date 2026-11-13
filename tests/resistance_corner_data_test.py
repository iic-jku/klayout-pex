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
"""Complete resistance tables distinguish missing data from explicit ideal connections."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable, Dict

import allure
import pytest
from google.protobuf.json_format import MessageToDict

from klayout_pex_protobuf.kpex.tech.tech_pb2 import Technology
from scripts.gen_tech_pb.resistance_corners import load_corner_resistances
from tests.common.tech_catalog import small_technology, sample_provenance

pytestmark = allure.parent_suite('Unit Tests')


def table_document() -> Dict:
    technology = technology_with_contact()
    return {
        'schema_version': 1, 'technology_id': technology.name,
        'resistance': {'low-r': {
            'description': 'Synthetic resistance data',
            'provenance': MessageToDict(sample_provenance(), preserving_proto_field_name=True),
            'layers': [['met1', 50], ['met2', 60]],
            'contacts': [['contact', 'poly', 'met1', 2]], 'vias': [['via1', 20]],
        }},
    }


def technology_with_contact() -> Technology:
    technology = small_technology()
    technology.process_parasitics.resistance.contacts.add(
        contact_name='contact', device_layer_name='poly', layer_above='met1', resistance=1)
    return technology


def test_resistance_tables_load_complete_values_without_nominal_inheritance(tmp_path: Path):
    path = tmp_path / 'tables.json'
    path.write_text(json.dumps(table_document()), encoding='utf-8')
    dataset, = load_corner_resistances(technology_with_contact(), path)
    assert dataset.id == 'low-r'
    assert [x.resistance for x in dataset.resistance.layers] == [50, 60]
    assert dataset.resistance.contacts[0].resistance == 2
    assert dataset.resistance.vias[0].resistance == 20


@pytest.mark.parametrize('edit, message', [
    (lambda d: d.__setitem__('schema_version', True), 'Unexpected technology'),
    (lambda d: d.__setitem__('technology_id', 'another-pdk'), 'Unexpected technology'),
    (lambda d: d['resistance'].__setitem__('nominal', d['resistance'].pop('low-r')), 'Invalid resistance dataset ID'),
    (lambda d: d['resistance'].__setitem__('../outside', d['resistance'].pop('low-r')), 'Invalid resistance dataset ID'),
    (lambda d: d['resistance']['low-r']['layers'].pop(), 'Incomplete or unknown'),
    (lambda d: d['resistance']['low-r']['contacts'][0].__setitem__(1, 'other-layer'), 'Incomplete or unknown'),
    (lambda d: d['resistance']['low-r']['vias'].append(d['resistance']['low-r']['vias'][0]), 'Duplicate'),
    (lambda d: d['resistance']['low-r']['layers'][0].__setitem__(-1, -math.ulp(0.0)), 'Invalid resistance value'),
    (lambda d: d['resistance']['low-r']['layers'][0].__setitem__(-1, math.inf), 'Invalid resistance value'),
    (lambda d: d['resistance']['low-r']['layers'][0].__setitem__(-1, math.nan), 'Invalid resistance value'),
    (lambda d: d['resistance']['low-r']['layers'][0].__setitem__(-1, True), 'Invalid resistance value'),
    (lambda d: d['resistance']['low-r']['layers'][0].__setitem__(-1, '6200'), 'Invalid resistance value'),
    (lambda d: d['resistance']['low-r']['layers'].__setitem__(0, 42), 'Invalid resistance layers row'),
])
def test_invalid_resistance_tables_are_rejected(edit: Callable, message: str, tmp_path: Path):
    document = table_document()
    edit(document)
    path = tmp_path / 'tables.json'
    path.write_text(json.dumps(document), encoding='utf-8')
    technology = technology_with_contact()
    with pytest.raises(ValueError, match=message):
        load_corner_resistances(technology, path)


@pytest.mark.parametrize('value', [0.0, math.ulp(0.0)])
def test_zero_and_small_positive_contact_values_remain_explicit(value: float, tmp_path: Path):
    document = table_document()
    document['resistance']['low-r']['contacts'][0][-1] = value
    path = tmp_path / 'tables.json'
    path.write_text(json.dumps(document), encoding='utf-8')
    technology = technology_with_contact()
    datasets = load_corner_resistances(technology, path)
    assert datasets[0].resistance.contacts[0].resistance == value
