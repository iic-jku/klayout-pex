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

"""Physical edge offsets preserve net topology and use the physical, not layout, grid."""

from pathlib import Path
from typing import Tuple
import shutil
from types import SimpleNamespace
from unittest.mock import patch

import allure
import klayout.db as kdb
import pytest

from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder
from klayout_pex.fastercap.pex25d_exporter import FasterCapModelOptions
from klayout_pex.fastercap.pex25d_model_builder import PEX25DFasterCapModelBuilder
from klayout_pex.klayout.pex25d_builder import BuildError, BuilderOptions
from klayout_pex.klayout.physical_geometry import PhysicalGeometryError, apply_width_bias, shape_region
from klayout_pex.pex25d.resolver import resolve
from klayout_pex.tech_info import TechInfo
from klayout_pex_protobuf.kpex.tech.process_stack_pb2 import ProcessStackInfo
from tests.klayout.pex25d_builder_test import TerminalFixture


pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('Physical Width Bias')]


def biased_fixture(bias: float) -> TerminalFixture:
    fixture = TerminalFixture()
    fixture.tech.process_stack_layer_by_name['met1'].metal_layer.line_width_bias = bias
    return fixture


@pytest.mark.parametrize('bias,expected', [(0.002, (-10, -10, 1010, 210)),
                                           (-0.002, (10, 10, 990, 190))])
def test_total_width_change_moves_each_boundary_by_half(bias: float, expected: Tuple[int, int, int, int]):
    file = biased_fixture(bias).build()
    box = file.shapes[0].box
    assert (box.lower_left.x, box.lower_left.y, box.upper_right.x, box.upper_right.y) == expected


def test_zero_bias_preserves_entire_file_bytes():
    fixture = TerminalFixture()
    before = fixture.build().SerializeToString(deterministic=True)
    fixture.tech.process_stack_layer_by_name['met1'].metal_layer.line_width_bias = 0.0
    after = fixture.build()
    assert after.SerializeToString(deterministic=True) == before
    apply_width_bias(after, {})
    assert after.SerializeToString(deterministic=True) == before


@pytest.mark.parametrize('bias', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_bias_fails_before_reading_layout_shapes(bias: float):
    fixture = biased_fixture(bias)
    fixture.context.shapes_of_net = lambda **kwargs: pytest.fail('read layout before validating bias')
    with pytest.raises(BuildError, match='finite'):
        fixture.build()


@pytest.mark.parametrize('bias', [0.0001, -0.0001, 0.0207])
def test_half_grid_offsets_require_finer_grid_instead_of_rounding(bias: float):
    fixture = biased_fixture(bias)
    with pytest.raises(BuildError, match='Choose a finer physical grid'):
        fixture.build()
    file = fixture.build(BuilderOptions(grid_um='0.00001'))
    box = file.shapes[0].box
    assert box.lower_left.x == -round(bias/2/0.00001)


@pytest.mark.parametrize('bias,accepted', [(-0.0198, True), (-0.02, False), (-0.0202, False)])
def test_erosion_boundary_cannot_silently_remove_conductors(bias: float, accepted: bool):
    fixture = biased_fixture(bias)
    if accepted:
        assert shape_region(fixture.build().shapes[0]).area() > 0
    else:
        with pytest.raises(BuildError, match='collapses or disconnects'):
            fixture.build()


def test_erosion_cannot_disconnect_a_narrow_neck():
    fixture = biased_fixture(-0.01)
    fixture.geometry['met1'] = kdb.Region(kdb.Box(0, 0, 40, 40)) + kdb.Region(kdb.Box(60, 0, 100, 40)) \
        + kdb.Region(kdb.Box(40, 16, 60, 24))
    with pytest.raises(BuildError, match='disconnects'):
        fixture.build()


@pytest.mark.parametrize('bias,accepted', [(0.0038, True), (0.004, False), (0.0042, False)])
def test_new_net_contact_boundary_is_rejected_including_zero_area_touch(bias: float, accepted: bool):
    fixture = biased_fixture(bias)
    fixture.add_net('other', {'met1': kdb.Region(kdb.Box(104, 0, 204, 20))})
    if accepted:
        assert len(fixture.build().conductors) == 2
    else:
        with pytest.raises(BuildError, match='joins different conductors'):
            fixture.build()


@pytest.mark.parametrize('bias', [-0.002, 0.002])
def test_nonmanhattan_edges_and_holes_remain_polygons(bias: float):
    fixture = biased_fixture(bias)
    diamond = kdb.Polygon([kdb.Point(0, 50), kdb.Point(50, 100), kdb.Point(100, 50), kdb.Point(50, 0)])
    diamond.insert_hole([kdb.Point(40, 50), kdb.Point(50, 60), kdb.Point(60, 50), kdb.Point(50, 40)])
    fixture.geometry['met1'] = kdb.Region(diamond)
    file = fixture.build()
    assert len(file.shapes) == 1
    assert len(file.shapes[0].polygon.holes) == 1
    scaled_area = fixture.geometry['met1'].area()*100
    area = shape_region(file.shapes[0]).area()
    assert area > scaled_area if bias > 0 else area < scaled_area


def test_bias_does_not_apply_to_device_contact_cuts_or_change_contact_anchors():
    fixture = TerminalFixture(diffusion=True)
    fixture.geometry['cont_nsd'] = kdb.Region(kdb.Box(40, 5, 60, 15))
    fixture.tech.process_stack_layer_by_name['met1'].metal_layer.line_width_bias = -0.002
    file = fixture.build()
    contact = next(shape for shape in file.shapes if shape.layer == 'cont_nsd')
    assert (contact.box.lower_left.x, contact.box.upper_right.x) == (400, 600)
    assert next(metal for metal in file.metals if metal.name == 'nsd').zhigh == 0


def test_bias_rejects_loss_of_device_contact_overlap():
    fixture = TerminalFixture(diffusion=True)
    fixture.geometry['cont_nsd'] = kdb.Region(kdb.Box(0, 0, 2, 2))
    fixture.tech.process_stack_layer_by_name['met1'].metal_layer.line_width_bias = -0.01
    with pytest.raises(BuildError, match="disconnects contact 'cont_nsd'"):
        fixture.build()


def test_bias_rejects_loss_of_device_terminal_overlap():
    fixture = biased_fixture(-0.01)
    fixture.device('gate', kdb.Region(kdb.Box(0, 0, 2, 2)))
    with pytest.raises(BuildError, match='disconnects terminal'):
        fixture.build()


def test_failed_bias_leaves_input_file_unchanged():
    file = TerminalFixture().build()
    before = file.SerializeToString(deterministic=True)
    with pytest.raises(PhysicalGeometryError, match='collapses'):
        apply_width_bias(file, {'met1': -100})
    assert file.SerializeToString(deterministic=True) == before


@pytest.mark.slow
@pytest.mark.fastercap
@pytest.mark.skipif(shutil.which('FasterCap') is None, reason='FasterCap is not installed')
def test_biased_plate_field_solver_capacitance_has_expected_monotonic_order(tmp_path: Path):
    from klayout_pex.fastercap.fastercap_runner import run_fastercap, fastercap_parse_capacitance_matrix
    from klayout_pex.fastercap.pex25d_exporter import FasterCapSceneExporter

    capacitances = []
    for bias in (-0.2, 0.0, 0.2):
        fixture = biased_fixture(bias)
        fixture.geometry['met1'] = kdb.Region(kdb.Box(0, 0, 20000, 5000))
        scene = resolve(fixture.build(BuilderOptions(include_resistance=False)))
        directory = tmp_path / str(bias)
        paths = FasterCapSceneExporter().export(scene, output_dir_path=str(directory))
        log = str(directory / 'solve.log')
        run_fastercap(shutil.which('FasterCap'), paths[0], log, 0.005, 0.1, 0, True, False, False)
        matrix = fastercap_parse_capacitance_matrix(log)
        plate = next(i for i, name in enumerate(matrix.conductor_names) if name.endswith('_N'))
        ground = next(i for i, name in enumerate(matrix.conductor_names) if name.endswith('_subs'))
        assert matrix[plate][ground] == pytest.approx(matrix[ground][plate], rel=0.02, abs=0)
        capacitances.append(-(matrix[plate][ground]+matrix[ground][plate])/2)
    assert 0 < capacitances[0] < capacitances[1] < capacitances[2]


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


def test_finite_bias_cannot_overflow_the_physical_coordinate_range():
    fixture = biased_fixture(1e30)
    fixture.context.shapes_of_net = lambda **kwargs: pytest.fail('read layout before validating range')
    with pytest.raises(BuildError, match='coordinate range'):
        fixture.build()


@pytest.mark.parametrize('bias', [429496.7294, 429496.7296])
def test_native_coordinate_limits_cannot_wrap_or_leak_kernel_errors(bias: float):
    with pytest.raises(BuildError, match='coordinate range'):
        biased_fixture(bias).build()


@pytest.mark.parametrize('room,accepted', [(2, True), (1, True), (0, False)])
def test_coordinate_plus_offset_boundary_is_atomic(room: int, accepted: bool):
    file = TerminalFixture().build()
    del file.terminals[:]
    box = file.shapes[0].box
    box.upper_right.x = (1 << 31)-1-room
    box.lower_left.x = box.upper_right.x-100
    before = file.SerializeToString(deterministic=True)
    if accepted:
        apply_width_bias(file, {'met1': 1})
        assert file.shapes[0].box.upper_right.x == (1 << 31)-room
    else:
        with pytest.raises(PhysicalGeometryError, match='coordinate range'):
            apply_width_bias(file, {'met1': 1})
        assert file.SerializeToString(deterministic=True) == before


def test_erosion_preserves_contact_across_same_conductor_coheight_profiles():
    fixture = TerminalFixture(metal_names=('met1', 'met2'))
    fixture.geometry['met2'] = kdb.Region(kdb.Box(100, 0, 200, 20))
    for metal in fixture.tech.process_metal_layers:
        metal.metal_layer.line_width_bias = -.002
    with pytest.raises(BuildError, match='disconnects touching profiles'):
        fixture.build()


def test_one_surviving_seam_cannot_hide_another_lost_profile_connection():
    fixture = TerminalFixture(metal_names=('met1', 'met2'))
    fixture.geometry['met1'] = kdb.Region(kdb.Box(0, 0, 100, 20))+kdb.Region(kdb.Box(0, 100, 100, 120))
    fixture.geometry['met2'] = kdb.Region(kdb.Box(100, 0, 200, 20))+kdb.Region(kdb.Box(90, 100, 200, 120)) \
        +kdb.Region(kdb.Box(150, 0, 170, 120))
    for metal in fixture.tech.process_metal_layers:
        metal.metal_layer.line_width_bias = -.002
    with pytest.raises(BuildError, match='disconnects touching profiles'):
        fixture.build()


@pytest.mark.parametrize('overlap,accepted', [(4, False), (5, False), (6, True)])
def test_contact_overlap_below_at_and_above_erosion_boundary(overlap: int, accepted: bool):
    fixture = TerminalFixture(diffusion=True)
    fixture.tech.process_stack_layer_by_name['met1'].metal_layer.line_width_bias = -.01
    fixture.geometry['cont_nsd'] = kdb.Region(kdb.Box(100-overlap, 5, 110, 15))
    if accepted:
        assert fixture.build().vias
    else:
        with pytest.raises(BuildError, match='disconnects contact'):
            fixture.build()


def test_nonmanhattan_offsets_round_vertices_within_one_grid_unit():
    fixture = biased_fixture(.002)
    fixture.geometry['met1'] = kdb.Region(kdb.Polygon([kdb.Point(0, 50), kdb.Point(50, 0),
                                                     kdb.Point(100, 50), kdb.Point(50, 100)]))
    file = fixture.build()
    polygon, = list(shape_region(file.shapes[0]).each())
    # A 10-grid normal offset of 45-degree edges moves a vertex by sqrt(2)*10.
    # Integer vertex snapping is explicit and bounded, not an exact angle-independent shift.
    assert abs(polygon.bbox().left + 10*2**.5) <= 1


def test_label_terminal_extent_cannot_leak_native_coordinate_errors():
    fixture = biased_fixture(.0002)
    fixture.geometry['met1'] = kdb.Region(kdb.Box(214748264, 0, 214748364, 20))
    fixture.pins = fixture.geometry['met1']
    fixture.pin('P', 214748364, 10)
    with pytest.raises(BuildError, match='Terminal.*coordinate range'):
        fixture.build()


def test_different_floating_conductors_must_not_be_shortened_together():
    fixture = TerminalFixture()
    fixture.add_net('other', {'met1': kdb.Region(kdb.Box(104, 0, 204, 20))})
    file = fixture.build()
    for conductor in file.conductors:
        conductor.net = 'FLOATING'
    with pytest.raises(PhysicalGeometryError, match='joins different conductors'):
        apply_width_bias(file, {'met1': 20})


@pytest.mark.parametrize('bias,accepted', [(.0048, True), (.005, False), (.0052, False)])
def test_hole_closure_must_not_touch_an_enclosed_different_conductor(bias: float, accepted: bool):
    fixture = biased_fixture(bias)
    ring = kdb.Polygon(kdb.Box(0, 0, 100, 100))
    ring.insert_hole(kdb.Box(40, 40, 60, 60))
    fixture.geometry['met1'] = kdb.Region(ring)
    fixture.add_net('inside', {'met1': kdb.Region(kdb.Box(45, 45, 55, 55))})
    if accepted:
        assert fixture.build().conductors
    else:
        with pytest.raises(BuildError, match='joins different conductors'):
            fixture.build()


def test_touching_different_net_profiles_at_same_height_are_not_ignored():
    fixture = TerminalFixture(metal_names=('met1', 'met2'))
    fixture.add_net('other', {'met2': kdb.Region(kdb.Box(104, 0, 204, 20))})
    for metal in fixture.tech.process_metal_layers:
        metal.metal_layer.line_width_bias = .004
    with pytest.raises(BuildError, match='joins different conductors'):
        fixture.build()
