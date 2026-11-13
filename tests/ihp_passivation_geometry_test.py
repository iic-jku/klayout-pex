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

"""Pinned passivation dimensions and the actual material above the IHP field."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest import mock

import allure
import klayout.db as kdb
import pytest

from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder
from klayout_pex.fastercap.pex25d_exporter import FasterCapModelOptions, build_fastercap_model
from klayout_pex.klayout.pex25d_builder import PEX25DBuilder
from klayout_pex.pdk_config import PDK
from klayout_pex.pex25d.protobuf import pex25d_file_pb2
from klayout_pex.pex25d.resolver import resolve
from klayout_pex.tech_catalog import load_technology_catalog
from klayout_pex.tech_info import TechInfo
from tests.common.fastercap_geometry import context_from_shapes, fastercap_input


pytestmark = allure.parent_suite('Unit Tests')
IHP_VARIANTS = [PDK.IHP_SG13G2, PDK.IHP_SG13CMOS5L]


def passivation_model(pdk: PDK, with_top_metal: bool, direct: bool) -> FasterCapModelBuilder:
    tech = TechInfo.from_json(pdk.config.tech_pb_json_path, dielectric_filter=None)
    top_name = 'TopMetal2' if pdk == PDK.IHP_SG13G2 else 'TopMetal1'
    plate = kdb.Region(kdb.Box(0, 0, 10000, 10000))
    layer_names = ['Metal1', top_name] if with_top_metal else ['Metal1']
    context = context_from_shapes({tech.gds_pair_for_layer_name[name]: plate for name in layer_names}, plate.bbox())
    if direct:
        return fastercap_input(context, tech)
    builder = PEX25DBuilder(context, tech, 'plate')
    file = pex25d_file_pb2().PEX25DFile()
    for step in (builder.build_units, builder.build_ground_plane, builder.build_layers, builder.build_dielectrics):
        step(file)
    file.conductors.add(name='wire', net='wire')
    for name in layer_names:
        shape = file.shapes.add(conductor='wire', layer=name, kind=pex25d_file_pb2().ShapeRecord.SHAPE_KIND_BOX)
        shape.box.upper_right.x = shape.box.upper_right.y = builder.to_grid(10.0, 'plate edge')
    with mock.patch.object(FasterCapModelBuilder, 'generate', autospec=True, side_effect=lambda model: model):
        return build_fastercap_model(resolve(file), FasterCapModelOptions(), 'fastercap')


def passivation_at(model: FasterCapModelBuilder, x: float, y: float, z: float) -> Optional[str]:
    point = kdb.Point(round(x / model.dbu), round(y / model.dbu))
    height = round(z / model.dbu)
    # The inner film owns the overlap of these cumulative prisms. Checking just
    # the outer prism's presence would miss a nitride slab hidden inside oxide.
    for name in ('pass1', 'pass2'):
        if any(low <= height < high and any(poly.inside(point) for poly in region.each_merged())
               for region, low, high in model.dlayers.get(name, [])):
            return name
    return None


@pytest.mark.parametrize('pdk', IHP_VARIANTS, ids=str)
@pytest.mark.parametrize('with_top_metal', [False, True], ids=['no-top-metal', 'top-metal'])
@pytest.mark.parametrize('direct', [False, True], ids=['pex25d', 'direct'])
def test_ihp_nitride_occupies_field_and_retains_incremental_top_coating(pdk: PDK, with_top_metal: bool,
                                                                    direct: bool):
    model = passivation_model(pdk, with_top_metal, direct)
    root_bottom, metal_thickness = (11.23, 3.0) if pdk == PDK.IHP_SG13G2 else (5.4, 2.0)
    assert model.materials['pass1'] == 4.1
    assert model.materials['pass2'] == 6.6
    # Probe below, at and above both material interfaces. This detects the old
    # 0.4 um field extent, a missing-metal omission, and accidental double-counting
    # of the root metal. The center switches from field to raised film only when
    # the optional top-metal plate is present.
    for x, y, bottom in ((-1.0, -1.0, root_bottom),
                         (5.0, 5.0, root_bottom + (metal_thickness if with_top_metal else 0.0))):
        for offset, expected in ((1.5 - model.dbu, 'pass1'), (1.5, 'pass2'),
                                 (1.5 + model.dbu, 'pass2'), (1.9 - model.dbu, 'pass2'),
                                 (1.9, None), (1.9 + model.dbu, None)):
            assert passivation_at(model, x, y, bottom + offset) == expected, (pdk, direct, x, y, offset)


@pytest.mark.parametrize('pdk', IHP_VARIANTS, ids=str)
def test_ihp_nominal_stack_records_passivation_correction_and_preserves_source_history(pdk: PDK):
    resolved = load_technology_catalog(Path(pdk.config.tech_catalog_path))
    stack = resolved.selection.process_stack
    evidence = stack.provenance
    assert evidence['data_revision'] == 'passivation-field-1'
    assert [entry['revision'] for entry in evidence['history']] == ['1', 'passivation-field-1']
    assert evidence['history'][0]['date'] == '2026-11-12'
    revision = evidence['history'][-1]
    assert revision['date'] == '2026-11-13'
    assert 'https://github.com/iic-jku/klayout-pex/issues/556' in revision['references']
    sources = {source['id']: source for source in evidence['sources']}
    expected_recipe_hash = ('f7a5ba53bf51b61602d7baf40fb20dffbeed13613482d8c6ab8cc9994345daf6'
                            if pdk == PDK.IHP_SG13G2 else
                            '291c5731174298c993adca376d391bc508800b0bfd709be0cb6e5ff48dcb61dd')
    assert sources['passivation-recipe']['sha256'] == expected_recipe_hash
    assert sources['conformal-mapping']['sha256'] == 'ef91dec393e1ac97bc1f491a8c605d1842533bc5a2deff5b53879f9fc8199ea7'
    for identity in ('passivation-recipe', 'conformal-mapping'):
        assert sources[identity]['revision'] == '85905e8810982bd89966cbf8b7e9d3fd1e922d42'
        assert len(sources[identity]['sha256']) == 64
    assumptions = {entry['id']: entry for entry in evidence['assumptions']}
    assert set(assumptions['cumulative-field-extent']['source_ids']) == {'passivation-recipe', 'conformal-mapping'}
    # The correction changes geometry, not analytical extraction coefficients or
    # the resistance/device-reference provenance.
    for component in (resolved.selection.capacitance, resolved.selection.resistance, resolved.selection.device_references):
        if component is not None:
            assert 'passivation-field-1' not in [entry['revision'] for entry in component.provenance['history']]
    layers = {layer.name: layer for layer in resolved.tech.process_stack.layers}
    pass2 = layers['pass2'].conformal_dielectric_layer
    assert pass2.thickness_where_no_metal == 1.9
    assert pass2.thickness_over_metal == 0.4
    assert pass2.thickness_sidewall == 0.3
