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

"""Check the catalog's field identities independently of generated descriptors."""

from typing import Any, Dict

import allure
import pytest
from google.protobuf.json_format import MessageToDict
from klayout_pex_protobuf.kpex.tech import tech_catalog_pb2


pytestmark = allure.parent_suite('Unit Tests')

# Fixed wire samples cover every message, the map field and every dataset oneof.
# Empty-but-present payloads and tags crossing the one-byte boundary are intentional.
# These are wire-contract samples, not complete loadable catalogs.
@pytest.mark.parametrize('message_name, wire_hex, expected', [
    ('TechnologyCatalog', '0801520170a2010164f201030a0172c202016e9203030a0173e203030a0164b204030a016e',
     {'schema_version': 1,
      'technology_id': 'p',
      'description': 'd',
      'provenance': {'data_revision': 'r'},
      'default_scenario': 'n',
      'shared': {'path': 's'},
      'datasets': [{'id': 'd'}],
      'scenarios': [{'id': 'n'}]}),
    ('TechnologyFile', '0a0170520168',
     {'path': 'p', 'sha256': 'h'}),
    ('TechnologyDatasetFile', '0a01645001a201030a0170',
     {'id': 'd', 'kind': 'RESISTANCE', 'file': {'path': 'p'}}),
    ('TechnologyScenario', '0a016e520164a2010172f2010163c202017092030164e00301',
     {'id': 'n',
      'description': 'd',
      'resistance': 'r',
      'capacitance': 'c',
      'process_stack': 'p',
      'device_references': 'd',
      'physical_stack_matches': True}),
    ('TechnologyProvenance', '0a017252030a0173a201030a0161f201030a0172',
     {'data_revision': 'r',
      'sources': [{'id': 's'}],
      'assumptions': [{'id': 'a'}],
      'history': [{'revision': 'r'}]}),
    ('TechnologySource', '0a0173520164a2010175f2010172c20201689203080a034d494d120131',
     {'id': 's',
      'description': 'd',
      'uri': 'u',
      'revision': 'r',
      'sha256': 'h',
      'options': {'MIM': '1'}}),
    ('TechnologyAssumption', '0a0161520164a2010172f2010173',
     {'id': 'a', 'description': 'd', 'reason': 'r', 'source_ids': ['s']}),
    ('TechnologyRevision', '0a0172520164a2010173f2010172c202017392030175',
     {'revision': 'r',
      'date': 'd',
      'summary': 's',
      'reason': 'r',
      'source_ids': ['s'],
      'references': ['u']}),
    ('CapacitanceDataset', '0900000000000020405200',
     {'side_halo': 8.0, 'capacitance': {}}),
    ('DeviceReferenceDataset', '0a030a0164',
     {'devices': [{'lvs_device_class_name': 'd'}]}),
    ('DeviceCapacitanceReferences', '0a01645200',
     {'lvs_device_class_name': 'd', 'capacitance_references': [{}]}),
    ('TechnologyDataset', '0a016e520164a201030a0172a20600',
     {'id': 'n', 'description': 'd', 'provenance': {'data_revision': 'r'}, 'resistance': {}}),
    ('TechnologyDataset', '0a016e520164a201030a0172f20600',
     {'id': 'n', 'description': 'd', 'provenance': {'data_revision': 'r'}, 'capacitance': {}}),
    ('TechnologyDataset', '0a016e520164a201030a0172c20700',
     {'id': 'n', 'description': 'd', 'provenance': {'data_revision': 'r'}, 'process_stack': {}}),
    ('TechnologyDataset', '0a016e520164a201030a0172920800',
     {'id': 'n',
      'description': 'd',
      'provenance': {'data_revision': 'r'},
      'device_references': {}}),
])
def test_catalog_binary_field_numbers_remain_stable(message_name: str, wire_hex: str, expected: Dict[str, Any]):
    payload = bytes.fromhex(wire_hex)
    message = getattr(tech_catalog_pb2, message_name).FromString(payload)
    assert MessageToDict(message, preserving_proto_field_name=True) == expected
    assert message.SerializeToString(deterministic=True) == payload
