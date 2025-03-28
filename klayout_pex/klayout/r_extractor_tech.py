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
        canonical_layer_name = tech.canonical_layer_name_by_gds_pair[gds_pair]
        layer_resistance = tech.layer_resistance_by_layer_name.get(canonical_layer_name, None)
        if layer_resistance is None:  # it's a via or contact!
            via_resistance = tech.via_resistance_by_layer_name.get(canonical_layer_name, None)
            if via_resistance is None:
                contact_resistance = tech.contact_resistance_by_layer_name.get(canonical_layer_name, None)
                if contact_resistance is None:
                    # TODO: might be nwell, etc
                    ## raise Exception(f"unknown layer {canonical_layer_name}, neither a via nor a metal layer")
                    warning(f"TODO: ignoring layer {canonical_layer_name}")
                    continue
                else:   # it's a contact
                    for source_layer in li.source_layers:
                        cond = klp.RExtractorTechConductor()
                        cond.triangulation_min_b = delaunay_b
                        cond.triangulation_max_area = delaunay_amax

                        if canonical_layer_name == tech.internal_substrate_layer_name:
                            cond.algorithm = substrate_algorithm
                        else:
                            cond.algorithm = wire_algorithm
                        cond.layer = extraction_context.annotated_layout.layer(*source_layer.gds_pair)
                        cond.resistance = contact_resistance.resistance
                        rex_tech.add_conductor(cond)
            else:
                for source_layer in li.source_layers:
                    via = klp.RExtractorTechVia()

                    (bot, top) = tech.bottom_and_top_layer_name_by_via_layer_name.get(canonical_layer_name, None)
                    bot_gds_pair = tech.gds_pair(bot)
                    top_gds_pair = tech.gds_pair(top)

                    via.bottom_conductor = extraction_context.annotated_layout.layer(*bot_gds_pair)
                    via.cut_layer = extraction_context.annotated_layout.layer(*source_layer.gds_pair)
                    via.top_conductor = extraction_context.annotated_layout.layer(*top_gds_pair)

                    contact = extraction_context.tech.contact_by_contact_layer_name[canonical_layer_name]

                    via.resistance = via_resistance.resistance * contact.width**2
                    via.merge_distance = via_merge_distance
                    rex_tech.add_via(via)
        else:
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

    return rex_tech
