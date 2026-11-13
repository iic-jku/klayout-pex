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
from __future__ import annotations

from collections import defaultdict
from typing import *
from unittest import mock

import allure
import pytest

import klayout.db as kdb
import klayout_pex_protobuf.kpex.tech.process_stack_pb2 as stack_pb2

from klayout_pex.fastercap.fastercap_input_builder import FasterCapInputBuilder
from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder
from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.rcx25.exclusion import Exclusions
from klayout_pex.tech_info import TechInfo
from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.fastercap_geometry import context_from_shapes, fastercap_input
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.common.technology import tech_with_two_metals


parent_suite = "kpex/FasterCap Input Tests"
tags = ("PEX", "FasterCap")


def context_of_layout(pdk_name: PDKName, *path_components) -> Tuple[KLayoutExtractionContext, TechInfo]:
    """
    :return: the extraction context and the tech info of the LVS database of a run (whose engine is left out)
    """
    pdk = PDKTestConfig(pdk_name)
    with mock.patch.object(KpexCLI, 'run_kpex_2_5d_engine', autospec=True) as run_kpex_2_5d_engine:
        KpexCLI().main(['main', 'extract',
                        '--pdk', pdk.name,
                        '--lvsdb', lvsdb_fixture_path(pdk.name, pdk.gds_path(*path_components)),
                        '--out-dir', pdk.output_dir,
                        '--2.5D',
                        '--blackbox', 'n'])
    return run_kpex_2_5d_engine.call_args.kwargs['pex_context'], run_kpex_2_5d_engine.call_args.kwargs['tech_info']


def dielectric_areas_um2(pdk_name: PDKName, *path_components) -> Dict[str, float]:
    """
    The areas of the FasterCap input dielectrics of a layout (in µm², with the white-box devices),
    built from the LVS database of a run (whose engine is left out)
    """
    pex_context, tech_info = context_of_layout(pdk_name, *path_components)

    regions_by_material: Dict[str, kdb.Region] = defaultdict(kdb.Region)
    for material, layers in fastercap_input(pex_context, tech_info).dlayers.items():
        for region, _, _ in layers:
            regions_by_material[material] += region

    return {material: round(region.merged().area() * pex_context.dbu ** 2, 4)
            for material, region in regions_by_material.items()}


# NOTE: the process stacks have a metal that's split into the bottom plates of the MIM caps and the rest,
#       two layers of the stack on the same GDS pair, which have different dielectrics above them,
#       so each one has the shapes of its own LVS layer: the MIM dielectric is on the bottom plates only,
#       not on all of the metal (nor are both layers all of the metal)

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mim_dielectric_of_ihp_sg13g2():
    # MIM 6.99 µm x 6.99 µm, over Metal5 8.19 µm x 8.19 µm (67.0761 µm²)
    areas = dielectric_areas_um2(PDKName.IHP_SG13G2, 'sg13g2_pr__cmim', 'cmim.gds.gz')
    assert areas['ismim'] == 48.8601


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mim_dielectric_of_ihp_sg13g2_rfcmim():
    # MIM 7 µm x 7 µm, over Metal5 of 82.24 µm² (with the feed)
    areas = dielectric_areas_um2(PDKName.IHP_SG13G2, 'sg13g2_pr__rfcmim', 'rfcmim.gds.gz')
    assert areas['ismim'] == 49.0


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mim_dielectric_of_sky130A():
    # capm 18.9 µm x 5.1 µm, over met3 of 147.36 µm² (with the interconnect), no capm2 over met4
    areas = dielectric_areas_um2(PDKName.SKY130A, 'cap_mim_m3_w18p9_l5p1', 'cap_mim_m3_w18p9_l5p1.gds.gz')
    assert areas['capild3'] == 96.39
    assert 'capild4' not in areas


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mim_dielectric_of_gf180mcuD():
    # FuseTop 5 µm x 5 µm and 20 µm x 10 µm, over Metal4 of 275.88 µm²
    areas = dielectric_areas_um2(PDKName.GF180MCUD, 'test_patterns', 'cap_mim_m4m5.gds.gz')
    assert areas['capild'] == 225.0


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_net_across_a_block_has_a_conductor_per_part_which_have_one_surface():
    # NOTE: a Metal3 wire of 40 µm x 2 µm, whose half ends within the marker (at x from 0 on)
    pex_context, tech_info = context_of_layout(PDKName.IHP_SG13G2, 'test_patterns', 'exclusion_wire_end.gds.gz')
    exclusions = Exclusions.from_region(kdb.Region(kdb.Box(0, -5000, 30000, 7000)),
                                        substrate_layer_name=tech_info.internal_substrate_layer_name)
    generator = FasterCapInputBuilder(pex_context=pex_context,
                                      tech_info=tech_info,
                                      substrate_net_name=pex_context.substrate_net_name,
                                      delaunay_amax=50.0,  # NOTE: few triangles, as the check is quadratic in them
                                      delaunay_b=0.5,
                                      exclusions=exclusions).build()

    assert sorted(generator.net_names) == ['W', 'W#x0', 'sub!#substrate']
    assert exclusions.conductor_parts['W#x0'].net_name == 'W'
    assert exclusions.conductor_parts['sub!#substrate'].is_substrate
    with mock.patch('klayout_pex.fastercap.fastercap_model_generator.error') as error_mock:
        generator.check()
    assert [c.args[0] for c in error_mock.call_args_list] == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('ports', [False, True])
def test_any_angle_wire_across_a_block_has_no_slivers_to_the_dielectrics(ports: bool):
    # NOTE: its cuts are vertices on the grid, off its edges, which leaves slivers that can't be triangulated otherwise
    pex_context, tech_info = context_of_layout(PDKName.IHP_SG13G2, 'test_patterns', 'exclusion_slanted_wire.gds.gz')
    exclusions = Exclusions.from_region(kdb.Region(kdb.Box(-5000, -30000, 5000, 30000)),
                                        ports=ports,
                                        substrate_layer_name=tech_info.internal_substrate_layer_name)
    generator = FasterCapInputBuilder(pex_context=pex_context,
                                      tech_info=tech_info,
                                      substrate_net_name=pex_context.substrate_net_name,
                                      delaunay_amax=50.0,
                                      delaunay_b=0.5,
                                      exclusions=exclusions).build()
    assert [name for name in generator.net_names if '#x' in name]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_vias_and_contacts_of_a_net_across_a_block_are_conductors_of_its_parts():
    # NOTE: the block is over the MOS, the contacts on its source and drain, and the Via1 over them, not the Via2
    pex_context, tech_info = context_of_layout(PDKName.IHP_SG13G2, 'nmos_diode2', 'nmos_diode2.gds.gz')
    block = kdb.Region(kdb.Box(-500, -700, 500, 700))
    exclusions = Exclusions.from_region(block, substrate_layer_name=tech_info.internal_substrate_layer_name)
    conductors = fastercap_input(pex_context, tech_info, exclusions).clayers

    # NOTE: on all layers, the conductors of the parts of the nets within the block are within it, the others outside
    for name, layers in conductors.items():
        part = exclusions.conductor_parts[name]
        if not part.is_substrate:
            for region, _, _ in layers:
                assert (region - block if part.block_indexes else region & block).is_empty(), name

    # NOTE: the conductors from z = 0, by their tops in nm: the source and the drain, and the contacts on them,
    #       up to the Metal1
    assert sorted((name, top) for name, layers in conductors.items() for _, bottom, top in layers if bottom == 0) == \
           [('VDD#x0', 100), ('VDD#x0', 1040), ('VSS#x0', 100), ('VSS#x0', 1040)]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk_name, cell_name, net_name, top', [
    (PDKName.SKY130A, 'r_ntap_pair_nwell_li1_m1', '$1', 936),  # NOTE: licon_ntap_con up to li1
    (PDKName.GF180MCUD, 'r_nwell_pfet_ntap_m1', 'VDD', 1230),  # NOTE: contact_ntap_con up to Metal1
], ids=['sky130A', 'gf180mcuD'])
def test_contacts_of_the_nwell_over_the_ntaps_are_conductors(pdk_name: PDKName, cell_name: str, net_name: str,
                                                            top: int):
    # NOTE: the contact of the nwell, where the resistance network lands it, from the silicon surface (#475)
    pex_context, tech_info = context_of_layout(pdk_name, 'test_patterns', f"{cell_name}.gds.gz")
    conductors = fastercap_input(pex_context, tech_info).clayers
    assert [(bottom, upper) for _, bottom, upper in conductors[net_name] if bottom == 0] == [(0, 100), (0, top)]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_taps_without_contact_are_no_layers_without_gds_pair(caplog: pytest.LogCaptureFixture):
    # NOTE: the taps have no contact in the process stack, whose GDS pair of an empty name was looked up,
    #       with a warning per net and tap (#460)
    pex_context, tech_info = context_of_layout(PDKName.SKY130A, 'test_patterns',
                                               'single_plate_100um_x_100um_li1_over_substrate.gds.gz')
    fastercap_input(pex_context, tech_info)
    assert [message for message in caplog.messages if "Can't find GDS pair" in message] == []


def conformal_field_model(root_shapes: Optional[kdb.Region], field_thickness: float,
                          with_exclusions: bool) -> FasterCapModelBuilder:
    """A two-film stack beside a lower metal, with an upper plate fixing the model domain."""
    tech = tech_with_two_metals()
    LT = stack_pb2.ProcessStackInfo
    substrate = LT.LayerInfo(name='substrate', layer_type=LT.LAYER_TYPE_SUBSTRATE)
    substrate.substrate_layer.height = 0.1
    substrate.substrate_layer.thickness = 0.1
    fox = LT.LayerInfo(name='fox', layer_type=LT.LAYER_TYPE_FIELD_OXIDE)
    fox.field_oxide_layer.dielectric_k = 3.9
    tech.process_stack.layers.insert(0, substrate)
    tech.process_stack.layers.insert(1, fox)
    by_name = {layer.name: layer for layer in tech.process_stack.layers}
    by_name['met1'].metal_layer.ClearField('contact_above')
    for name, over, on_field in (('liner', 0.1, field_thickness), ('coat', 0.2, field_thickness + 0.2)):
        film = by_name[name].conformal_dielectric_layer
        film.thickness_over_metal = over
        film.thickness_where_no_metal = on_field
        film.thickness_sidewall = 0.05

    upper_plate = kdb.Region(kdb.Box(0, 0, 1000, 1000))
    context = context_from_shapes({(1, 0): root_shapes, (2, 0): upper_plate}, upper_plate.bbox())
    exclusions = Exclusions.from_region(kdb.Region(kdb.Box(500, -1000, 2000, 2000))) \
        if with_exclusions else None
    return fastercap_input(context, TechInfo(tech, dielectric_filter=None), exclusions)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('root_state', ['absent', 'empty', 'present'])
@pytest.mark.parametrize('with_exclusions', [False, True])
@pytest.mark.parametrize('field_thickness', [0.0, 0.001, 0.1], ids=['no-field', 'one-grid-step', 'finite-field'])
def test_conformal_field_survives_missing_root_metal(root_state: str, with_exclusions: bool,
                                                    field_thickness: float):
    # Absence and an empty extracted layer must be equivalent. Zero field thickness
    # removes only that film's field slab, not a nonzero film that wraps it. One grid
    # step catches an accidentally discarded positive slab. Exclusions use another
    # geometry lookup, so cover that path and retain the populated-metal control.
    root_shapes = None if root_state == 'absent' else kdb.Region()
    if root_state == 'present':
        root_shapes.insert(kdb.Box(0, 0, 1000, 1000))
    model = conformal_field_model(root_shapes, field_thickness, with_exclusions)
    field_point = kdb.Point(-1000, -1000)
    on_field = {name: [(low, high) for region, low, high in prisms
                      if any(polygon.inside(field_point) for polygon in region.each_merged())]
                for name, prisms in model.dlayers.items()}
    field_height = round(field_thickness / model.dbu)
    assert on_field.get('liner', []) == ([(1000, 1000 + field_height)] if field_height else [])
    assert on_field['coat'] == [(1000, 1200 + field_height)]
    assert on_field['ild'] == [(1200 + field_height, 2500)]
    assert all(high > low and not region.is_empty()
               for prisms in model.dlayers.values() for region, low, high in prisms)
    if root_state == 'present':
        metal_point = kdb.Point(500, 500)
        above_metal = {name: [(low, high) for region, low, high in prisms
                             if any(polygon.inside(metal_point) for polygon in region.each_merged())]
                       for name, prisms in model.dlayers.items()}
        assert above_metal['liner'] == [(1000, 1300)]
        assert above_metal['coat'] == [(1000, 1500)]
        assert above_metal['ild'] == [(1500, 2500)]
