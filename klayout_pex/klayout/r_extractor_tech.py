#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/martinjankoehler/klayout-pex).
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
from typing import *

import klayout.pex as klp

from klayout_pex.klayout import KLayoutExtractionContext
from klayout_pex.tech_info import TechInfo

from klayout_pex.log import (
    warning,
)

import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2


def create_r_extractor_tech(extraction_context: KLayoutExtractionContext,
                            substrate_algorithm: klp.Algorithm,
                            wire_algorithm: klp.Algorithm,
                            delaunay_b: float,
                            delaunay_amax: float,
                            via_merge_distance: float,
                            skip_simplify: bool) -> klp.RExtractorTech:
    """
    Prepare KLayout PEXCore Technology Description based on the KPEX Tech Info data
    :param extraction_context: KPEX Extraction Context
    :param substrate_algorithm: The KLayout PEXCore Algorithm for decomposing polygons.
                                Either SquareCounting or Tesselation (recommended)
    :param wire_algorithm: The KLayout PEXCore Algorithm for decomposing polygons.
                           Either SquareCounting (recommended) or Tesselation
    :param delaunay_b: The "b" parameter for the Delaunay triangulation,
                       a ratio of shortest triangle edge to circle radius
    :param delaunay_amax: The "max_area" specifies the maximum area of the triangles
                          produced in square micrometers.
    :param via_merge_distance: Maximum distance where close vias are merged together
    :return: KLayout PEXCore Technology Description
    """
    rex_tech = klp.RExtractorTech()
    rex_tech.skip_simplify = skip_simplify

    tech = extraction_context.tech

    for gds_pair, li in extraction_context.extracted_layers.items():
        computed_layer_info = tech.computed_layer_info_by_gds_pair.get(gds_pair, None)
        if computed_layer_info is None:
            warning(f"ignoring layer {gds_pair}, no computed layer info found in tech info")
            continue

        canonical_layer_name = tech.canonical_layer_name_by_gds_pair[gds_pair]

        LP = tech_pb2.LayerInfo.Purpose

        if computed_layer_info.kind != tech_pb2.ComputedLayerInfo.Kind.KIND_PIN:
            match computed_layer_info.layer_info.purpose:
                case LP.PURPOSE_NWELL:
                    pass   # TODO!
                case LP.PURPOSE_N_IMPLANT | LP.PURPOSE_P_IMPLANT:
                    # device terminals
                    #   - source/drain (e.g. sky130A: nsdm, psdm)
                    #   - bulk (e.g. nwell)
                    #
                    # we will consider this only as an pin end-point, there are no wires at all on this layer,
                    # so the resistance does not matter for PEX
                    for source_layer in li.source_layers:
                        cond = klp.RExtractorTechConductor()
                        cond.triangulation_min_b = delaunay_b
                        cond.triangulation_max_area = delaunay_amax

                        cond.algorithm = substrate_algorithm
                        cond.layer = extraction_context.annotated_layout.layer(*source_layer.gds_pair)
                        cond.resistance = 0  # see comment above
                        rex_tech.add_conductor(cond)

                case LP.PURPOSE_METAL:
                    if computed_layer_info.kind == tech_pb2.ComputedLayerInfo.Kind.KIND_PIN:
                        continue

                    layer_resistance = tech.layer_resistance_by_layer_name.get(canonical_layer_name, None)
                    for source_layer in li.source_layers:
                        cond = klp.RExtractorTechConductor()
                        cond.triangulation_min_b = delaunay_b
                        cond.triangulation_max_area = delaunay_amax

                        if canonical_layer_name == tech.internal_substrate_layer_name:
                            cond.algorithm = substrate_algorithm
                        else:
                            cond.algorithm = wire_algorithm
                        cond.layer = extraction_context.annotated_layout.layer(*source_layer.gds_pair)
                        cond.resistance = layer_resistance.resistance
                        # TODO: ... = layer_resistance.corner_adjustment_fraction ????
                        rex_tech.add_conductor(cond)

                case LP.PURPOSE_CONTACT:
                    for source_layer in li.source_layers:
                        contact = tech.contact_by_contact_lvs_layer_name.get(source_layer.lvs_layer_name, None)
                        if contact is None:
                            warning(
                                f"ignoring LVS layer {source_layer.lvs_layer_name} (layer {canonical_layer_name}), "
                                f"no contact found in tech info")
                            continue

                        contact_resistance = tech.contact_resistance_by_device_layer_name.get(contact.layer_below, None)
                        if contact_resistance is None:
                            warning(f"ignoring layer {canonical_layer_name}, no contact resistance found in tech info")
                            continue

                        via = klp.RExtractorTechVia()

                        bot_gds_pair = tech.gds_pair(contact.layer_below)
                        top_gds_pair = tech.gds_pair(contact.metal_above)

                        via.bottom_conductor = extraction_context.annotated_layout.layer(*bot_gds_pair)
                        via.cut_layer = extraction_context.annotated_layout.layer(*source_layer.gds_pair)
                        via.top_conductor = extraction_context.annotated_layout.layer(*top_gds_pair)

                        via.resistance = contact_resistance.resistance * contact.width**2
                        via.merge_distance = via_merge_distance
                        rex_tech.add_via(via)

                case LP.PURPOSE_VIA:
                    via_resistance = tech.via_resistance_by_layer_name.get(canonical_layer_name, None)
                    if via_resistance is None:
                        warning(f"ignoring layer {canonical_layer_name}, no via resistance found in tech info")
                        continue
                    for source_layer in li.source_layers:
                        via = klp.RExtractorTechVia()

                        (bot, top) = tech.bottom_and_top_layer_name_by_via_computed_layer_name.get(source_layer.lvs_layer_name, None)
                        bot_gds_pair = tech.gds_pair(bot)
                        top_gds_pair = tech.gds_pair(top)

                        via.bottom_conductor = extraction_context.annotated_layout.layer(*bot_gds_pair)
                        via.cut_layer = extraction_context.annotated_layout.layer(*source_layer.gds_pair)
                        via.top_conductor = extraction_context.annotated_layout.layer(*top_gds_pair)

                        contact = extraction_context.tech.contact_by_contact_lvs_layer_name[source_layer.lvs_layer_name]

                        via.resistance = via_resistance.resistance * contact.width**2
                        via.merge_distance = via_merge_distance
                        rex_tech.add_via(via)
                # case _:
                #     raise NotImplementedError(f"unknown device purpose {computed_layer_info.layer_info.purpose}")

    return rex_tech
