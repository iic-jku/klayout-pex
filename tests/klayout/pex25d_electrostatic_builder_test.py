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

"""Canonical electrostatic geometry preserves the extraction stack and source extent."""
from typing import Any, Tuple
from unittest.mock import patch

import allure
import klayout.db as kdb
import pytest

from klayout_pex.klayout.pex25d_builder import BuildError, BuilderOptions, GeometryScope, PEX25DBuilder
from klayout_pex.pdk_config import PDK
from klayout_pex.pex25d.resolver import resolve
from klayout_pex.tech_info import TechInfo
from klayout_pex.util.multiple_choice import MultipleChoicePattern
from klayout_pex_protobuf.kpex.tech.process_stack_pb2 import ProcessStackInfo
from tests.common.fastercap_geometry import context_from_shapes
from tests.klayout.pex25d_builder_test import TerminalFixture

pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('PEX25D', 'Electrostatic Builder')]


def electrostatic_fixture(contact: bool = True) -> TerminalFixture:
    fixture = TerminalFixture(diffusion=True, contact=contact)
    fixture.context.top_cell_bbox = lambda: kdb.Box(-10, -20, 200, 40)
    fixture.geometry['nsd'] = kdb.Region(kdb.Box(20, 5, 80, 15))
    if contact:
        fixture.geometry['cont_nsd'] = kdb.Region(kdb.Box(40, 6, 60, 14))
    return fixture


def electrostatic_options(**kwargs: Any) -> BuilderOptions:
    return BuilderOptions(geometry_scope=GeometryScope.ELECTROSTATIC,
                          include_terminals=False, include_resistance=False,
                          background_permittivity=3.5, domain_margin_um=8, **kwargs)


def xy_bounds(box: Any) -> Tuple[int, int, int, int]:
    return box.lower_left.x, box.lower_left.y, box.upper_right.x, box.upper_right.y


@pytest.mark.parametrize('contact', [False, True])
def test_diffusion_and_tap_solids_are_opt_in_and_anchors_stay_empty(contact: bool):
    fixture = electrostatic_fixture(contact)
    default = fixture.build()
    assert not any(shape.layer == 'nsd' for shape in default.shapes)
    file = fixture.build(electrostatic_options())
    scene = resolve(file)
    layers = {layer.name: layer for layer in scene.layers}
    assert (layers['nsd'].zlow, layers['nsd'].zhigh) == (0, 1000)
    assert any(shape.layer == 'nsd' for shape in file.shapes)
    assert not any(shape.layer.startswith('__electrostatic_') for shape in file.shapes)
    if contact:
        assert (layers['cont_nsd'].zlow, layers['cont_nsd'].zhigh) == (0, 10000)
    assert not file.terminals and not file.metal_resistances and not file.via_resistances
    assert scene.ground_plane.zhigh == -1000
    assert scene.ground_plane.cutouts


def test_contact_height_is_retained_when_it_differs_from_upper_metal_position():
    fixture = electrostatic_fixture()
    fixture.tech.process_diffusion_layers[0].diffusion_layer.contact_above.thickness = 0.8
    scene = resolve(fixture.build(electrostatic_options()))
    layers = {layer.name: layer for layer in scene.layers}
    assert (layers['cont_nsd'].zlow, layers['cont_nsd'].zhigh) == (0, 8000)
    assert (layers['met1'].zlow, layers['met1'].zhigh) == (10000, 11000)


@pytest.mark.parametrize('filter_text,finite_band', [('all', True), ('none', False)])
def test_finite_top_dielectric_and_background_are_independent(filter_text: str, finite_band: bool):
    fixture = electrostatic_fixture()
    fixture.tech = TechInfo(fixture.tech.tech, MultipleChoicePattern(filter_text))
    scene = resolve(fixture.build(electrostatic_options()))
    assert scene.background.permittivity == 3.5
    air = [dielectric for dielectric in scene.dielectrics if dielectric.name == 'air']
    assert bool(air) == finite_band
    if finite_band:
        assert (air[0].zlow, air[0].zhigh, air[0].permittivity) == (10000, 60000, 1.0)


def test_field_oxide_starts_at_silicon_surface_despite_substrate_clearance():
    fixture = electrostatic_fixture()
    fox = fixture.tech.tech.process_stack.layers.add(name='fox', layer_type=ProcessStackInfo.LAYER_TYPE_FIELD_OXIDE)
    fox.field_oxide_layer.dielectric_k = 3.9
    scene = resolve(fixture.build(electrostatic_options()))
    oxide = next(layer for layer in scene.dielectrics if layer.name == 'fox')
    assert (oxide.zlow, oxide.zhigh) == (0, 10000)
    assert scene.ground_plane.zhigh == -1000


@pytest.mark.parametrize('bias,expected', [(0.002, (-80010, -80010, 81010, 80210)),
                                           (-0.002, (-80000, -80000, 81000, 80200))])
def test_domain_unions_original_cell_with_manufactured_shapes(bias: float, expected: Tuple[int, int, int, int]):
    fixture = electrostatic_fixture()
    fixture.context.top_cell_bbox = lambda: kdb.Box(0, 0, 100, 20)
    fixture.tech.process_metal_layers[0].metal_layer.line_width_bias = bias
    file = fixture.build(electrostatic_options())
    assert xy_bounds(file.domain_box.box) == expected
    # Classification of original source-grid cuts must not change with metal bias.
    cut = next(shape for shape in file.shapes if shape.layer == 'cont_nsd')
    assert xy_bounds(cut.box) == (400, 60, 600, 140)
    resolve(file)


def test_empty_cell_bounds_use_conductor_geometry_and_empty_scene_fails_clearly():
    fixture = electrostatic_fixture()
    fixture.context.top_cell_bbox = kdb.Box
    file = fixture.build(electrostatic_options())
    assert xy_bounds(file.domain_box.box) == (-80000, -80000, 81000, 80200)
    fixture.geometry.clear()
    with pytest.raises(BuildError, match='nonempty layout bounds or conductor geometry'):
        fixture.build(electrostatic_options())


@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('edge', [-(2**31), 2**31-1])
def test_native_original_endpoint_is_rejected_before_reading_geometry(axis: str, edge: int):
    fixture = electrostatic_fixture()
    lo, hi = (edge, edge+10) if edge < 0 else (edge-10, edge)
    fixture.context.top_cell_bbox = lambda: kdb.Box(lo, 0, hi, 10) if axis == 'x' else kdb.Box(0, lo, 10, hi)
    fixture.context.shapes_of_net = lambda **kwargs: pytest.fail('unsafe geometry was read')
    with pytest.raises(BuildError, match='Original cell bounds'):
        fixture.build(electrostatic_options())


@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf'), True, '3.5'])
def test_background_rejects_invalid_values_before_reading_layout(value: Any):
    fixture = electrostatic_fixture()
    with pytest.raises(BuildError, match='Background permittivity'):
        fixture.build(BuilderOptions(background_permittivity=value))


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), True, '8'])
def test_domain_rejects_invalid_margins_before_reading_layout(value: Any):
    fixture = electrostatic_fixture()
    with pytest.raises(BuildError, match='Domain margin'):
        fixture.build(BuilderOptions(domain_margin_um=value))


def test_unknown_geometry_scope_fails_before_reading_layout():
    with pytest.raises(BuildError, match='Unknown geometry scope'):
        electrostatic_fixture().build(BuilderOptions(geometry_scope='electrostatic'))


def test_generated_anchor_names_do_not_shadow_technology_profiles():
    fixture = electrostatic_fixture()
    air = fixture.tech.tech.process_stack.layers[-1]
    air.name = '__electrostatic_surface'
    scene = resolve(fixture.build(electrostatic_options()))
    assert any(layer.name == '__electrostatic_surface_2' for layer in scene.layers)
    assert any(layer.name == '__electrostatic_surface' for layer in scene.dielectrics)


def test_scaled_geometry_endpoint_is_rejected_before_native_merge():
    fixture = electrostatic_fixture(contact=False)
    builder = PEX25DBuilder(fixture.context, fixture.tech, 'test', electrostatic_options())
    region = kdb.Region(kdb.Box(214748364, 0, 214748365, 10))
    with patch.object(kdb.Region, 'each_merged', side_effect=AssertionError('unsafe native merge')):
        with pytest.raises(BuildError, match='Export geometry'):
            builder.add_shapes(None, 'N', 'met1', region)


@pytest.mark.parametrize('pdk', list(PDK))
@pytest.mark.parametrize('filter_text', ['all', 'none'])
def test_real_stacks_resolve_with_independent_background(pdk: PDK, filter_text: str):
    tech = TechInfo.from_json(pdk.config.tech_pb_json_path, MultipleChoicePattern(filter_text))
    context = context_from_shapes({}, kdb.Box(0, 0, 100, 100))
    file = PEX25DBuilder(context, tech, 'plate', electrostatic_options()).build()
    scene = resolve(file)
    assert scene.background.permittivity == 3.5
    assert all(d.zhigh > d.zlow for d in scene.dielectrics)
    oxide = next(d for d in scene.dielectrics if d.name == tech.field_oxide_layer.name)
    assert oxide.zlow == 0
    if filter_text == 'none':
        assert [d.name for d in scene.dielectrics] == [tech.field_oxide_layer.name]


@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('offset,accepted', [(-1, True), (0, False), (1, False)])
def test_original_field_halo_obeys_open_native_endpoint(axis: str, offset: int, accepted: bool):
    fixture = electrostatic_fixture(contact=False)
    # Grid equals source DBU here, so this tests the halo itself, not scaling.
    edge = 2**31 - 1 - 8000 + offset
    fixture.context.top_cell_bbox = lambda: kdb.Box(0, 0, edge, 100) if axis == 'x' else kdb.Box(0, 0, 100, edge)
    if accepted:
        file = fixture.build(electrostatic_options(grid_um='0.001'))
        assert getattr(file.domain_box.box.upper_right, axis) == 2**31 - 2
    else:
        fixture.context.shapes_of_net = lambda **kwargs: pytest.fail('unsafe halo reached geometry')
        with pytest.raises(BuildError, match='Electrostatic field margin'):
            fixture.build(electrostatic_options(grid_um='0.001'))


def test_terminal_omission_does_not_query_pin_or_device_markers():
    fixture = electrostatic_fixture()
    fixture.context.pins_of_layer = lambda *_: pytest.fail('queried pin markers')
    fixture.context.labels_of_layer = lambda *_: pytest.fail('queried pin labels')
    fixture.context.lvsdb.shapes_of_terminal = lambda *_: pytest.fail('queried device terminal shapes')
    file = fixture.build(electrostatic_options())
    assert file.shapes and not file.terminals


def test_zero_margin_is_valid_and_preserves_original_extent():
    fixture = electrostatic_fixture()
    options = electrostatic_options()
    options.domain_margin_um = 0
    file = fixture.build(options)
    assert xy_bounds(file.domain_box.box) == (-100, -200, 2000, 400)
    resolve(file)



def test_scaled_ground_cutout_bounds_fail_before_native_sizing():
    fixture = electrostatic_fixture(contact=False)
    # Source coordinates fit, but the 1 um clearance at the finer export grid
    # does not. This must be caught before constructing downstream native masks.
    fixture.geometry['nsd'] = kdb.Region(kdb.Box(214747400, 0, 214747500, 10))
    with patch.object(kdb.Region, 'sized', side_effect=AssertionError('unsafe cutout sizing')):
        with pytest.raises(BuildError, match='Ground diffusion clearance'):
            fixture.build(electrostatic_options())
