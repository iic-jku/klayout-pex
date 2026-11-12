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

"""Corner selection is explicit, complete, traceable and independent of earlier loads."""

from __future__ import annotations

from pathlib import Path

import allure
import pytest

from klayout_pex.tech_catalog import load_technology_catalog
from klayout_pex.tech_info import TechDefError, TechInfo
from klayout_pex_protobuf.kpex.tech.process_stack_pb2 import ProcessStackInfo
from klayout_pex_protobuf.kpex.tech.tech_pb2 import Technology
from tests.common.tech_catalog import edit_dataset, small_catalog


pytestmark = allure.parent_suite('Unit Tests')
LT = ProcessStackInfo.LayerType
LAYER_CASES = [
    (LT.LAYER_TYPE_SUBSTRATE, 'substrate_layer'),
    (LT.LAYER_TYPE_NWELL, 'nwell_layer'),
    (LT.LAYER_TYPE_DIFFUSION, 'diffusion_layer'),
    (LT.LAYER_TYPE_FIELD_OXIDE, 'field_oxide_layer'),
    (LT.LAYER_TYPE_SIMPLE_DIELECTRIC, 'simple_dielectric_layer'),
    (LT.LAYER_TYPE_CONFORMAL_DIELECTRIC, 'conformal_dielectric_layer'),
    (LT.LAYER_TYPE_METAL, 'metal_layer'),
]


@pytest.fixture
def technology() -> Technology:
    tech = Technology(name='layer-validation')
    tech.process_parasitics.side_halo = 1.0
    return tech


@pytest.mark.parametrize('layer_type,expected_field', LAYER_CASES)
@pytest.mark.parametrize('payload_field', [field for _, field in LAYER_CASES])
def test_enum_and_payload_pairing(layer_type: ProcessStackInfo.LayerType, expected_field: str,
                                  payload_field: str, technology: Technology):
    # Every pairing matters: an enum must never route a different payload through
    # a valid handler. Empty-but-present messages also distinguish presence from value.
    layer = technology.process_stack.layers.add(name='sample', layer_type=layer_type)
    getattr(layer, payload_field).SetInParent()
    if payload_field == expected_field:
        TechInfo.validate_tech_def(technology, 'pairing.pb.json')
        # The known non-conductors are intentional exclusions, not unsupported variants.
        assert TechInfo(technology, None).contact_by_contact_lvs_layer_name == {}
    else:
        with pytest.raises(TechDefError, match=f"layer 'sample'.*declares.*has {payload_field}.*expected {expected_field}"):
            TechInfo.validate_tech_def(technology, 'pairing.pb.json')


@pytest.mark.parametrize('layer_type,payload_field', LAYER_CASES)
def test_known_type_without_payload_is_rejected(layer_type: ProcessStackInfo.LayerType, payload_field: str,
                                                technology: Technology):
    technology.process_stack.layers.add(name='sample', layer_type=layer_type)
    with pytest.raises(TechDefError, match="layer 'sample'.*exactly one parameter payload"):
        TechInfo.validate_tech_def(technology, 'missing.pb.json')


@pytest.mark.parametrize('layer_type', [-1, LT.LAYER_TYPE_UNSPECIFIED, 9, 11, 79, 81, 2**31 - 1])
def test_unspecified_and_unknown_enum_values_are_input_errors(layer_type: int, technology: Technology):
    # Proto3 preserves unknown enum integers. Cover the sentinel, negative values,
    # gaps beside the first/last supported kinds and the largest representable value.
    layer = technology.process_stack.layers.add(name='sample', layer_type=layer_type)
    layer.metal_layer.SetInParent()
    with pytest.raises(TechDefError, match="layer 'sample'.*unsupported layer_type"):
        TechInfo.validate_tech_def(technology, 'unknown.pb.json')


@pytest.mark.parametrize('operation', ['lvs_layer_names_by_process_layer_name', 'contact_by_contact_lvs_layer_name'])
@pytest.mark.parametrize('layer_type', [LT.LAYER_TYPE_UNSPECIFIED, 81])
def test_unhandled_internal_dispatch_fails_explicitly(operation: str, layer_type: int, technology: Technology):
    # Direct in-memory construction can bypass file validation. It must not silently
    # lose a conductor or contact when the consumer has no handler for its type.
    layer = technology.process_stack.layers.add(name='sample', layer_type=layer_type)
    layer.metal_layer.SetInParent()
    with pytest.raises(NotImplementedError, match=f"layer type {layer_type}.*'sample'"):
        getattr(TechInfo(technology, None), operation)


def test_catalog_checks_enum_against_payload_before_extraction(tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'process_stack',
                 lambda dataset: setattr(dataset.process_stack.layers[0], 'layer_type', LT.LAYER_TYPE_DIFFUSION))
    with pytest.raises(TechDefError, match="layer 'met1'.*LAYER_TYPE_DIFFUSION.*metal_layer.*expected diffusion_layer"):
        load_technology_catalog(path)


def test_layer_enum_and_payload_survive_binary_serialization():
    # Independently encoded name='M', layer_type=METAL and an empty metal payload.
    payload = bytes.fromhex('0a014d1050b20400')
    layer = ProcessStackInfo.LayerInfo.FromString(payload)
    assert layer.layer_type == LT.LAYER_TYPE_METAL
    assert layer.HasField('metal_layer')
    assert layer.SerializeToString(deterministic=True) == payload
