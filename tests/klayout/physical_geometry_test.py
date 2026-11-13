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

"""Physical profile availability is explicit and checked against real layout shapes."""

from unittest.mock import patch

import allure
import klayout.db as kdb
import pytest

from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder
from klayout_pex.fastercap.pex25d_exporter import FasterCapModelOptions
from klayout_pex.fastercap.pex25d_model_builder import PEX25DFasterCapModelBuilder
from klayout_pex.klayout.pex25d_builder import BuildError
from klayout_pex.pex25d.resolver import resolve
from klayout_pex.tech_info import TechInfo
from klayout_pex_protobuf.kpex.tech.process_stack_pb2 import ProcessStackInfo
from tests.klayout.pex25d_builder_test import TerminalFixture


pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('Physical Width Bias')]


def restricted_fixture() -> TerminalFixture:
    fixture = TerminalFixture(metal_names=('met1', 'met2'))
    technology = fixture.tech.tech
    metal = fixture.tech.process_stack_layer_by_name['met2'].metal_layer
    metal.z = 2.0
    metal.physical_geometry_unavailable = True
    contact = fixture.tech.process_stack_layer_by_name['met1'].metal_layer.contact_above
    contact.name, contact.layer_below, contact.metal_above = 'via', 'met1', 'met2'
    contact.thickness = 0.9
    layer = technology.lvs_computed_layers.add(process_layer_name='via')
    layer.layer_info.name = 'via'
    layer.layer_info.drw_gds_pair.layer = 3
    coating = technology.process_stack.layers.add(name='unknown-coating',
                                                 layer_type=ProcessStackInfo.LAYER_TYPE_CONFORMAL_DIELECTRIC)
    coating.conformal_dielectric_layer.reference = 'met2'
    coating.conformal_dielectric_layer.dielectric_k = 999
    coating.conformal_dielectric_layer.thickness_over_metal = 1
    fixture.tech = TechInfo(technology, None)
    return fixture


@pytest.mark.parametrize('present_layer', ['met2', 'via'])
def test_present_unavailable_metal_or_contact_is_rejected_before_profiles(present_layer: str):
    fixture = restricted_fixture()
    fixture.geometry[present_layer] = kdb.Region(kdb.Box(20, 5, 30, 15))
    with pytest.raises(BuildError, match='no qualified geometry'):
        fixture.build()


def test_absent_unavailable_geometry_never_reaches_scene_or_plugin_geometry():
    fixture = restricted_fixture()
    file = fixture.build()
    assert {metal.name for metal in file.metals} == {'met1'}
    assert not file.vias
    assert 'unknown-coating' not in {dielectric.name for dielectric in file.dielectrics}
    scene = resolve(file)
    assert any(item.key == 'physical_geometry_unavailable' and item.value == 'met2,via' for item in scene.metadata)
    with patch.object(FasterCapModelBuilder, 'generate', autospec=True, side_effect=lambda model: model):
        model = PEX25DFasterCapModelBuilder(scene, FasterCapModelOptions()).build()
    assert 'unknown-coating' not in model.materials
    assert all(high < 20000 for name, regions in model.clayers.items()
               for _, low, high in regions)


def test_unverifiable_restricted_profile_mapping_fails_closed():
    fixture = restricted_fixture()
    del fixture.tech.tech.lvs_computed_layers[-1]
    fixture.tech = TechInfo(fixture.tech.tech, None)
    with pytest.raises(BuildError, match='no layout layer mapping'):
        fixture.build()


def test_invalid_restricted_contact_association_fails_closed():
    fixture = restricted_fixture()
    fixture.tech.process_stack_layer_by_name['met1'].metal_layer.contact_above.metal_above = 'missing'
    with pytest.raises(BuildError, match='Cannot verify physical contact association'):
        fixture.build()


def test_physical_fields_have_spaced_ids_and_round_trip_in_json():
    from google.protobuf.json_format import MessageToJson, Parse
    model = ProcessStackInfo.MetalLayer(z=1.0, thickness=0.1, line_width_bias=-0.0206,
                                        physical_geometry_unavailable=True)
    assert model.DESCRIPTOR.fields_by_name['line_width_bias'].number == 20
    assert model.DESCRIPTOR.fields_by_name['physical_geometry_unavailable'].number == 30
    assert Parse(MessageToJson(model), ProcessStackInfo.MetalLayer()) == model
