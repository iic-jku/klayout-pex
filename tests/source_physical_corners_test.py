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
"""Process-stack corners export only layouts covered by their specified geometry and material parameters."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Tuple
from unittest.mock import patch

import allure
import klayout.db as kdb
import pytest

from klayout_pex.fastercap.fastercap_error import FasterCapError
from klayout_pex.fastercap.fastercap_input_builder import FasterCapInputBuilder
from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.klayout.pex25d_builder import BuildError, PEX25DBuilder
from klayout_pex.pdk_config import PDK
from klayout_pex.pex25d.protobuf import pex25d_file_pb2
from klayout_pex.pex25d.resolver import resolve
from klayout_pex.tech_info import TechInfo
from scripts.gen_tech_pb.corner_data import write_bundled_corner_catalog
from scripts.gen_tech_pb.physical_corners import load_corner_process_stacks
from scripts.gen_tech_pb.source_physical_corners import load_restricted_physical_corners
from tests.common.lvsdb_fixtures import lvsdb_fixture_path


pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('Physical Source Corners')]
ROOT = Path(__file__).resolve().parents[1]
PDKS = [PDK.SKY130A, PDK.GF180MCUD, PDK.IHP_SG13G2]


def selected(pdk: PDK, corner: str) -> TechInfo:
    technology = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    component = next(d for d in load_corner_process_stacks(technology) if d.id == 'capiche-'+corner)
    technology.process_stack.CopyFrom(component.process_stack)
    return TechInfo(technology, None)


def empty_physical_file(pdk: PDK, corner: str):
    builder = PEX25DBuilder(SimpleNamespace(dbu=.001, substrate_net_name='stack-reference'),
                            selected(pdk, corner), 'source-physical')
    file = pex25d_file_pb2().PEX25DFile()
    for step in (builder.build_units, builder.build_ground_plane, builder.build_layers, builder.build_dielectrics):
        step(file)
    return file, builder


@pytest.mark.parametrize('pdk', PDKS)
@pytest.mark.parametrize('corner', ['low', 'high'])
def test_unavailable_mim_profiles_and_descendant_coatings_never_reach_plugin_geometry(pdk: PDK, corner: str):
    file, builder = empty_physical_file(pdk, corner)
    scene = resolve(file)
    assert builder.unavailable_profiles
    assert not ({layer.name for layer in scene.layers} & builder.unavailable_profiles)
    assert not ({film.name for film in scene.dielectrics} & builder.unavailable_dielectrics)
    assert all(film.zlow < film.zhigh for film in scene.dielectrics)
    assert all(via.connects_below in {layer.name for layer in scene.layers}
               and via.connects_above in {layer.name for layer in scene.layers} for via in file.vias)


@pytest.mark.parametrize('pdk', list(PDK))
@pytest.mark.parametrize('corner', ['low', 'high'])
def test_source_ground_mapping_retains_declared_3d_device_clearance(pdk: PDK, corner: str):
    # The ideal source plane is at 0. SKY130's full 3D plane deliberately retains
    # a 0.1 um gap below device-contact anchors in the shared physical scene.
    file, builder = empty_physical_file(pdk, corner)
    clearance = .1 if pdk == PDK.SKY130A else 0
    assert file.ground_plane.zhigh == builder.to_grid(-clearance, 'ground')
    nominal = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    thickness = TechInfo(nominal, None).process_substrate_layer.substrate_layer.thickness
    assert file.ground_plane.zlow == builder.to_grid(-clearance-thickness, 'ground bottom')
    assert TechInfo(nominal, None).process_substrate_layer.substrate_layer.height == clearance


@pytest.mark.parametrize('pdk', list(PDK))
@pytest.mark.parametrize('corner', ['low', 'high'])
def test_source_interconnect_contact_lengths_reach_both_selected_metal_faces(pdk: PDK, corner: str):
    technology = selected(pdk, corner)
    file, _ = empty_physical_file(pdk, corner)
    metals = {metal.name: metal for metal in file.metals}
    contacts = {layer.metal_layer.contact_above.name: layer.metal_layer.contact_above
                for layer in technology.process_metal_layers if layer.metal_layer.contact_above.name}
    grid = file.units.grid_numerator/file.units.grid_denominator
    checked = 0
    for via in file.vias:
        if via.name not in contacts:
            continue  # Device-contact anchors have a separate retained contract.
        contact = contacts[via.name]
        gap = (metals[via.connects_above].zlow-metals[via.connects_below].zhigh)*grid
        assert gap > 0
        # The declared contact thickness must match the metal-face separation
        # used to construct the shared scene's vias.
        assert contact.thickness == pytest.approx(gap, abs=1e-12)
        checked += 1
    assert checked


@pytest.mark.parametrize('corner,oxide_top,nitride_top', [
    ('low', 8.5645, 8.8345), ('high', 8.2955, 8.6255),
])
def test_gf180_planar_passivation_boundaries_hold_over_metal_and_empty_field(
        corner: str, oxide_top: float, nitride_top: float):
    file, builder = empty_physical_file(PDK.GF180MCUD, corner)
    scene = resolve(file)
    films = {film.name: film for film in scene.dielectrics}
    root = next(layer for layer in scene.layers if layer.name == 'Metal5')
    # These source records are absolute planar boundaries, not conformal films
    # that droop in the field. Both representations must reach the same height.
    for name, height in [('pass', oxide_top), ('sin', nitride_top)]:
        film = films[name]
        expected = builder.to_grid(height, name+' top')
        assert film.zhigh == expected
        assert root.zlow+film.thickness_on_field == expected
        assert film.thickness_beside_wrapped == 0


@pytest.mark.parametrize('pattern,folder', [
    ('nmos_diode2', 'nmos_diode2'),
    ('r_nwell_pfet_ntap_li1', 'test_patterns'),
    ('r_ntap_pair_nwell_li1_m1', 'test_patterns'),
])
@pytest.mark.parametrize('corner', ['low', 'high'])
def test_sky130_real_device_and_tap_contacts_keep_clearance_from_full_ground(
        pattern: str, folder: str, corner: str):
    technology = selected(PDK.SKY130A, corner)
    gds = str(ROOT/'testdata/designs/sky130A'/folder/(pattern+'.gds.gz'))
    lvsdb = kdb.LayoutVsSchematic()
    lvsdb.read(lvsdb_fixture_path(PDK.SKY130A.value, gds))
    context = KLayoutExtractionContext.prepare_extraction(lvsdb, pattern, technology, blackbox_devices=False)
    scene = resolve(PEX25DBuilder(context, technology, pattern).build())
    layers = {layer.name: layer for layer in scene.layers}
    device_cuts = [layers[region.layer] for conductor in scene.conductors for region in conductor.regions
                   if region.layer.startswith('licon_') and region.layer != 'licon_poly_con']
    assert device_cuts
    assert all(layer.zlow > scene.ground_plane.zhigh for layer in device_cuts)


@pytest.mark.parametrize('pdk,corner,metal,bounds,bias', [
    (PDK.SKY130A, 'low', 'met1', (1.7295, .33), -.0206),
    (PDK.SKY130A, 'high', 'met1', (1.0137, .39), .0206),
    (PDK.GF180MCUD, 'low', 'Metal5', (6.5645, 1.125), 0),
    (PDK.GF180MCUD, 'high', 'Metal5', (5.6955, 1.375), 0),
    (PDK.IHP_SG13G2, 'low', 'TopMetal2', (11.23, 3), 0),
    (PDK.IHP_SG13G2, 'high', 'TopMetal2', (11.23, 3), 0),
])
def test_pinned_source_geometry_is_not_nominal_geometry_with_global_c_scaling(
        pdk: PDK, corner: str, metal: str, bounds: Tuple[float, float], bias: float):
    profile = selected(pdk, corner).process_stack_layer_by_name[metal].metal_layer
    assert (profile.z, profile.thickness) == bounds
    assert profile.line_width_bias == bias


@pytest.mark.parametrize('corner', ['low', 'high'])
def test_sky130_high_process_stack_omits_only_the_source_absent_low_k_sidewall_films(corner: str):
    scene = resolve(empty_physical_file(PDK.SKY130A, corner)[0])
    names = {film.name for film in scene.dielectrics}
    assert ('nild3c' in names) == (corner == 'low')
    assert ('nild4c' in names) == (corner == 'low')
    assert {'iox', 'spnit', 'lint', 'topox', 'topnit'} <= names
    assert scene.background.permittivity == (2.94 if corner == 'low' else 3.5)


@pytest.mark.parametrize('pdk,pattern', [
    (PDK.SKY130A, 'cap_mim_m3_20um_x_20um_over_m2_wire'),
    (PDK.GF180MCUD, 'cap_mim_m4m5'),
    (PDK.IHP_SG13G2, 'cap_cmim_20um_x_20um_over_m4_wire'),
])
@pytest.mark.parametrize('corner', ['low', 'high'])
@pytest.mark.parametrize('blackbox', [False, True])
def test_real_mim_layout_is_rejected_before_either_physical_exporter_builds_output(
        pdk: PDK, pattern: str, corner: str, blackbox: bool):
    technology = selected(pdk, corner)
    gds = str(ROOT/'testdata/designs'/pdk.value/'test_patterns'/(pattern+'.gds.gz'))
    lvsdb = kdb.LayoutVsSchematic()
    lvsdb.read(lvsdb_fixture_path(pdk.value, gds))
    context = KLayoutExtractionContext.prepare_extraction(lvsdb, pattern, technology, blackbox_devices=blackbox)
    with pytest.raises(BuildError, match='no supported geometry'):
        PEX25DBuilder(context, technology, pattern).build()
    with pytest.raises(FasterCapError, match='no supported geometry'):
        FasterCapInputBuilder(context, technology, 'VSUBS').build()


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'nonfinite', 'false-string', 'unknown-reference',
                                    'missing-substrate', 'nonfinite-substrate', 'negative-clearance'])
def test_source_tables_fail_closed_for_incomplete_or_invalid_geometry(tmp_path: Path, mutation: str):
    technology = TechInfo.parse_tech_def(PDK.SKY130A.config.tech_pb_json_path)
    source = ROOT/'scripts/gen_tech_pb/corners/sky130A-physical.json'
    document = json.loads(source.read_text(encoding='utf-8'))
    table = document['physical']['capiche-low']
    if mutation == 'missing-substrate':
        table['substrate'].clear()
    elif mutation == 'nonfinite-substrate':
        table['substrate'][0][1] = float('inf')
    elif mutation == 'negative-clearance':
        table['substrate'][0][2] = -.1
    elif mutation == 'missing':
        table['metals'].pop()
    elif mutation == 'duplicate':
        table['metals'].append(table['metals'][0])
    elif mutation == 'nonfinite':
        table['metals'][0][1] = float('nan')
    elif mutation == 'false-string':
        table['metals'][0][4] = 'false'
    elif mutation == 'unknown-reference':
        table['conformal'][0][-1] = 'missing'
    else:
        raise NotImplementedError(mutation)
    path = tmp_path/'invalid.json'
    path.write_text(json.dumps(document), encoding='utf-8')
    with pytest.raises(ValueError):
        load_restricted_physical_corners(technology, path)


@pytest.mark.parametrize('pdk', list(PDK))
def test_authored_source_scenarios_keep_resistance_and_device_capabilities_independent(tmp_path: Path, pdk: PDK):
    technology = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    path = tmp_path/'catalog.pb.json'
    write_bundled_corner_catalog(technology, path)
    for corner in ('low', 'high'):
        selected_tech = TechInfo.from_catalog(str(path), None, 'capiche-'+corner+'-c')
        selected_tech.selection.require_physical_stack()
        assert selected_tech.selection.resistance.id == 'nominal'
        assert selected_tech.selection.capacitance.id == corner
        assert selected_tech.selection.device_references is None
        assert selected_tech.tech.process_stack == selected(pdk, corner).tech.process_stack
