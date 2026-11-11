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

"""A two-metal stack with a top coating, independent of shipped process data."""

from typing import Any, Dict

import pytest

from klayout_pex.tech_info import TechInfo
from klayout_pex_protobuf.kpex.tech.tech_pb2 import Technology
from klayout_pex_protobuf.kpex.tech.process_stack_pb2 import ProcessStackInfo as Stack


@pytest.fixture
def tech_info() -> TechInfo:
    tech = Technology(name='test_stack')
    layers = tech.process_stack.layers
    substrate = layers.add(name='substrate', layer_type=Stack.LAYER_TYPE_SUBSTRATE)
    substrate.substrate_layer.height = 0.1
    substrate.substrate_layer.thickness = 0.2
    oxide = layers.add(name='oxide', layer_type=Stack.LAYER_TYPE_FIELD_OXIDE)
    oxide.field_oxide_layer.dielectric_k = 3.9
    first = layers.add(name='M1', layer_type=Stack.LAYER_TYPE_METAL)
    first.metal_layer.z, first.metal_layer.thickness = 1.0, 0.2
    fill = layers.add(name='fill', layer_type=Stack.LAYER_TYPE_SIMPLE_DIELECTRIC)
    fill.simple_dielectric_layer.dielectric_k = 4.1
    second = layers.add(name='M2', layer_type=Stack.LAYER_TYPE_METAL)
    second.metal_layer.z, second.metal_layer.thickness = 2.0, 0.3
    coat = layers.add(name='coat', layer_type=Stack.LAYER_TYPE_CONFORMAL_DIELECTRIC)
    coat.conformal_dielectric_layer.reference = 'M2'
    coat.conformal_dielectric_layer.dielectric_k = 7.3
    coat.conformal_dielectric_layer.thickness_over_metal = 0.1
    coat.conformal_dielectric_layer.thickness_sidewall = 0.08
    coat.conformal_dielectric_layer.thickness_where_no_metal = 0.05
    air = layers.add(name='air', layer_type=Stack.LAYER_TYPE_SIMPLE_DIELECTRIC)
    air.simple_dielectric_layer.dielectric_k = 1.0
    return TechInfo(tech, dielectric_filter=None)


@pytest.fixture
def pattern_data() -> Dict[str, Any]:
    return {
        'schema_version': 1,
        'grid_um': '0.001',
        'domain_margin_um': '2',
        'cases': [
            {'id': 'plates', 'family': 'parallel_plates', 'lower_layer': 'M1', 'upper_layer': 'M2',
             'width_um': '2', 'length_um': '4', 'role': 'training'},
            {'id': 'wires', 'family': 'parallel_wires', 'layer': 'M2', 'width_um': '0.4',
             'length_um': '8', 'gap_um': '0.2', 'role': 'validation'},
        ],
    }
