#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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

"""Serialize layout exclusion meaning into the shared physical-scene contract."""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Dict, Tuple
import itertools

import klayout.db as kdb

from .pex25d_ground import check_native_ground_coordinate
from .physical_geometry import shape_region
from ..pex25d.protobuf import pex25d_capacitance_accounting_pb2, pex25d_capabilities_pb2
from ..pex25d.format_version import ACCOUNTING_FORMAT_VERSION_SUFFIX
from ..rcx25.exclusion import Exclusions, polygons_by_center_inside


def scaled_region(region: kdb.Region, scale: kdb.ICplxTrans) -> kdb.Region:
    """Validate rounded bounds before a scaled mask reaches native indexing."""
    box = region.bbox()
    if not box.empty():
        from .native_coordinates import NATIVE_COORDINATE_MIN, NATIVE_COORDINATE_MAX
        for value in (box.left, box.bottom, box.right, box.top):
            scaled = value * scale.mag
            if not NATIVE_COORDINATE_MIN < scaled < NATIVE_COORDINATE_MAX:
                raise ValueError('Accounting geometry exceeds the native coordinate range')
        transformed = box.transformed(scale)
        for coordinate in (transformed.left, transformed.bottom, transformed.right, transformed.top):
            check_native_ground_coordinate(coordinate)
    return region.transformed(scale)


def add_mask(target: Any, layer: str, geometry: kdb.Region):
    if geometry.is_empty():
        return
    mask = target.masks.add(layer=layer)
    for polygon in geometry.each_merged():
        item = mask.polygons.add()
        for point in polygon.each_point_hull():
            item.outer.points.add(x=point.x, y=point.y)
        for hole_index in range(polygon.holes()):
            ring = item.holes.add()
            for point in polygon.each_point_hole(hole_index):
                ring.points.add(x=point.x, y=point.y)


def attach_layout_accounting(file: Any, builder: Any, exclusions: Exclusions):
    """Preserve source-grid via ownership while serializing physical-grid masks."""
    schema = pex25d_capacitance_accounting_pb2()
    file.required_capabilities.append(pex25d_capabilities_pb2().REQUIRED_CAPABILITY_CAPACITANCE_ACCOUNTING)
    file.format_version_suffix = ACCOUNTING_FORMAT_VERSION_SUFFIX
    policy = file.capacitance_accounting
    policy.SetInParent()
    net_names = {conductor.net for conductor in file.conductors}
    policy.excluded_substrate_nets.extend(sorted(exclusions.excluded_net_names & net_names))
    grid = Fraction(file.units.grid_numerator, file.units.grid_denominator)
    scale = kdb.ICplxTrans(float(Fraction(str(builder.pex_context.dbu)) / grid))
    tech = builder.tech_info

    def canonical(name: str) -> str:
        pair = tech.gds_pair(name)
        return tech.canonical_layer_name_by_gds_pair.get(pair, name)

    # Alias map is resolved here. Downstream exporters need no technology or LVS objects.
    aliases = {metal.name: canonical(metal.name) for metal in file.metals}
    aliases[file.ground_plane.name] = exclusions.substrate_layer_name
    contacts: Dict[str, Tuple[str, str]] = {}
    for layer in tech.process_metal_layers:
        contact = layer.metal_layer.contact_above
        if contact.name:
            contacts[contact.name] = (canonical(contact.layer_below or layer.name),
                                      canonical(contact.metal_above or layer.name))
    for layer in tech.process_diffusion_layers:
        contact = layer.diffusion_layer.contact_above
        if contact.name:
            contacts[contact.name] = (canonical(layer.name), canonical(contact.metal_above or layer.name))
    for layer in tech.process_nwell_layers:
        contact = layer.nwell_layer.contact_above
        if contact.name:
            contacts[contact.name] = (canonical(layer.name), canonical(contact.metal_above or layer.name))
    via_geometry: Dict[str, kdb.Region] = {via.name: kdb.Region() for via in file.vias}
    for shape in file.shapes:
        if shape.layer in via_geometry:
            via_geometry[shape.layer] += shape_region(shape)

    for index, block in enumerate(exclusions.blocks):
        region = policy.regions.add(name=f'block{index}')
        for profile, alias in aliases.items():
            if profile == file.ground_plane.name:
                continue
            source = block.region_of(alias)
            if source is not None:
                add_mask(region, profile, scaled_region(source, scale))
        if block.capacitance_pair is None:
            for via, physical in via_geometry.items():
                if physical.is_empty() or via not in contacts:
                    continue
                below, above = contacts[via]
                bottom, top = block.region_of(below), block.region_of(above)
                if bottom is None or top is None:
                    continue
                # Cuts are unchanged by width bias. Classify before rescaling so
                # integer bbox-center rounding and the one-DBU margin stay fixed.
                source = physical.transformed(scale.inverted())
                if not (source.transformed(scale) ^ physical).is_empty():
                    raise ValueError(f"Via '{via}' cannot be represented on its source grid")
                selected = polygons_by_center_inside(source, bottom & top)
                add_mask(region, via, scaled_region(selected, scale))
        if not region.masks:
            del policy.regions[-1]
            continue
        if block.capacitance_pair is None:
            policy.exclusions.add(name=f'exclude{index}', region=region.name,
                                  kind=schema.CapacitanceExclusion.KIND_ALL_LAYER_PAIRS)
        else:
            first, second = sorted(block.capacitance_pair)
            for ordinal, (a, b) in enumerate(itertools.product(
                    [name for name, alias in aliases.items() if alias == first],
                    [name for name, alias in aliases.items() if alias == second])):
                policy.exclusions.add(name=f'exclude{index}_{ordinal}', region=region.name,
                                      kind=schema.CapacitanceExclusion.KIND_LAYER_PAIR,
                                      layer_a=a, layer_b=b)

    if not (policy.regions or policy.exclusions or policy.excluded_substrate_nets):
        # An unused marker or excluded name must not manufacture a required
        # accounting contract for an otherwise ordinary geometry scene.
        file.ClearField('capacitance_accounting')
        file.ClearField('required_capabilities')
        from ..pex25d.format_version import FORMAT_VERSION_SUFFIX
        file.format_version_suffix = FORMAT_VERSION_SUFFIX
