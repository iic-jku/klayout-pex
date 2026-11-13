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

"""Adapt validated physical regions while retaining direct FasterCap solver semantics."""

from collections import defaultdict
from fractions import Fraction
from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

import klayout.db as kdb

from .fastercap_error import FasterCapError
from .fastercap_input_builder import FasterCapInputBuilder
from .fastercap_model_generator import FasterCapModelGenerator
from ..klayout.pex25d_builder import PEX25DBuilder, BuilderOptions, BuildError
from ..klayout.physical_geometry import shape_region, PhysicalGeometryError
from ..klayout.native_coordinates import (NATIVE_COORDINATE_MIN, NATIVE_COORDINATE_MAX,
                                          is_supported_native_coordinate)
from ..rcx25.exclusion import Exclusions, ConductorPart
from ..tech_info import TechInfo
from ..types import LayerName
from klayout_pex_protobuf.kpex.tech.process_stack_pb2 import ProcessStackInfo


def _scaled_region(region: kdb.Region, scale: kdb.ICplxTrans) -> kdb.Region:
    box = region.bbox()
    if not box.empty():
        if min(box.left, box.bottom)*scale.mag < NATIVE_COORDINATE_MIN or \
                max(box.right, box.top)*scale.mag > NATIVE_COORDINATE_MAX:
            raise FasterCapError('Physical FasterCap geometry exceeds the native KLayout coordinate range')
        # Check the actual integer rounding before any region operation. A
        # fractional transformed bound inside the range can round onto an endpoint.
        scaled = box.transformed(scale)
        if not all(is_supported_native_coordinate(value)
                   for value in (scaled.left, scaled.bottom, scaled.right, scaled.top)):
            raise FasterCapError('Physical FasterCap geometry exceeds the native KLayout coordinate range')
    return region.transformed(scale)


class _PhysicalExclusions(Exclusions):
    """Fresh physical-grid masks with the original conductor-name registry."""

    def __init__(self, original: Exclusions, scale: kdb.ICplxTrans):
        self.original = original
        self.scale = scale
        blocks = [replace(
            block, region=_scaled_region(block.region, scale),
            layer_regions={name: _scaled_region(region, scale) for name, region in block.layer_regions.items()}
            if block.layer_regions is not None else None,
            labels=[replace(label, position=scale*label.position) for label in block.labels],
            cell_instance=replace(block.cell_instance,
                                  top_trans=scale*block.cell_instance.top_trans,
                                  cell_trans=scale*block.cell_instance.cell_trans)
            if block.cell_instance is not None else None) for block in original.blocks]
        super().__init__(blocks, original.substrate_layer_name)

    def conductor_name(self, part: ConductorPart) -> str:
        # The original object performs the later matrix filtering, so every new
        # part must be registered there using exactly the existing naming rules.
        return self.original.conductor_name(part)

    def conductor_parts_of_vias(self, shapes: kdb.Region, net_name: str,
                                bottom_layer_name: str, top_layer_name: str) -> List[Tuple[kdb.Region, str]]:
        # Cuts are never biased. Preserve source-grid bbox-center rounding and
        # its one-DBU strict-inside margin; neither rule may change with grid.
        source = shapes.transformed(self.scale.inverted())
        if not (source.transformed(self.scale) ^ shapes).is_empty():
            raise FasterCapError('Physical via cuts are not exactly representable on the original layout grid')
        return [(_scaled_region(region, self.scale), name) for region, name in
                self.original.conductor_parts_of_vias(source, net_name, bottom_layer_name, top_layer_name)]


def _available_technology(original: TechInfo, builder: PEX25DBuilder) -> TechInfo:
    technology = type(original.tech)()
    technology.CopyFrom(original.tech)
    excluded = builder.unavailable_profiles | builder.unavailable_dielectrics
    for index in reversed(range(len(technology.process_stack.layers))):
        layer = technology.process_stack.layers[index]
        if layer.name in excluded:
            del technology.process_stack.layers[index]
            continue
        match layer.layer_type:
            case ProcessStackInfo.LAYER_TYPE_METAL:
                parameters = layer.metal_layer
            case ProcessStackInfo.LAYER_TYPE_DIFFUSION:
                parameters = layer.diffusion_layer
            case ProcessStackInfo.LAYER_TYPE_NWELL:
                parameters = layer.nwell_layer
            case (ProcessStackInfo.LAYER_TYPE_SUBSTRATE | ProcessStackInfo.LAYER_TYPE_FIELD_OXIDE |
                  ProcessStackInfo.LAYER_TYPE_SIMPLE_DIELECTRIC | ProcessStackInfo.LAYER_TYPE_CONFORMAL_DIELECTRIC):
                continue
            case _:
                raise NotImplementedError(f'Physical FasterCap profile type {layer.layer_type} is not implemented')
        if parameters.contact_above.name in excluded:
            parameters.ClearField('contact_above')
    return TechInfo(technology, original.dielectric_filter, selection=original.selection)


class _PhysicalInputBuilder(FasterCapInputBuilder):
    def __init__(self, original: FasterCapInputBuilder, physical: PEX25DBuilder, file: Any):
        super().__init__(original.pex_context, _available_technology(original.tech_info, physical),
                         original.substrate_net_name, original.k_void, original.delaunay_amax,
                         original.delaunay_b, original.exclusions)
        self.original = original
        self._physical_dbu = float(Fraction(file.units.grid_numerator, file.units.grid_denominator))
        self._scale = kdb.ICplxTrans(original.dbu/self._physical_dbu)
        physical_metals = {layer.name for layer in original.tech_info.process_metal_layers}
        self._profiles = ({metal.name for metal in file.metals} & physical_metals) | {via.name for via in file.vias}
        self._regions: Dict[Tuple[str, str], kdb.Region] = defaultdict(kdb.Region)
        for shape in file.shapes:
            self._regions[shape.layer, shape.conductor] += shape_region(shape)
        # Validate the final field before exclusion masks can reach native
        # partitioning. Native booleans and contact checks cannot use either endpoint.
        self.top_cell_bbox()
        if original.exclusions is not None:
            self.exclusions = _PhysicalExclusions(original.exclusions, self._scale)

    @property
    def dbu(self) -> float:
        return self._physical_dbu

    def shapes_of_net(self, layer_name: str, net: kdb.Net) -> Optional[kdb.Region]:
        if layer_name in self._profiles:
            return self._regions[layer_name, net.expanded_name()]
        # Diffusion/device geometry follows the original direct solver contract,
        # independent of the interconnect-only PEX25D scene and its width law.
        shapes = self.original.shapes_of_net(layer_name, net)
        return _scaled_region(shapes, self._scale) if shapes is not None else None

    def shapes_of_layer(self, layer_name: str) -> Optional[kdb.Region]:
        if layer_name in self._profiles:
            region = kdb.Region()
            for (profile, _), shapes in self._regions.items():
                if profile == layer_name:
                    region += shapes
            return region
        shapes = self.original.shapes_of_layer(layer_name)
        return _scaled_region(shapes, self._scale) if shapes is not None else None

    def top_cell_bbox(self) -> kdb.Box:
        box = _scaled_region(kdb.Region(self.original.top_cell_bbox()), self._scale).bbox()
        for region in self._regions.values():
            box += region.bbox()
        margin = int(8/self.dbu)
        if not all(is_supported_native_coordinate(value) for value in (
                min(box.left, box.bottom)-margin, max(box.right, box.top)+margin)):
            raise FasterCapError('Physical FasterCap field margin exceeds the native KLayout coordinate range')
        return box

    def canonical_layer_name(self, layer_name: str) -> LayerName:
        return self.original.canonical_layer_name(layer_name)

    def build(self) -> FasterCapModelGenerator:
        return self.build_layout_input()


def build_physical_input(original: FasterCapInputBuilder) -> FasterCapModelGenerator:
    try:
        builder = PEX25DBuilder(original.pex_context, original.tech_info, original.pex_context.top_circuit.name,
                               BuilderOptions(include_resistance=False))
        file = builder.build()
        changed_profiles = {layer.name for layer in original.tech_info.process_metal_layers
                            if layer.metal_layer.line_width_bias}
        if not builder.unavailable_profiles and not any(shape.layer in changed_profiles for shape in file.shapes):
            # An unused biased profile must not alter DBU, mesh, material slabs,
            # diffusion, substrate clearance, options or output ordering.
            return original.build_layout_input()
        return _PhysicalInputBuilder(original, builder, file).build()
    except (BuildError, PhysicalGeometryError) as exc:
        raise FasterCapError(f'Cannot build physical FasterCap geometry: {exc}. For finer grid control, '
                             'use kpex pex25d --grid followed by export') from exc
