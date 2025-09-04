#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024 Martin Jan Köhler and Harald Pretl
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

import klayout.pex as klp

from klayout_pex_protobuf.kpex.klayout.r_extractor_tech_pb2 import RExtractorTech as pb_RExtractorTech


def klayout_r_extractor_tech(pb_tech: pb_RExtractorTech) -> klp.RExtractorTech:
    kly_tech = klp.RExtractorTech()
    kly_tech.skip_simplify = pb_tech.skip_simplify

    for pb_c in pb_tech.conductors:
        kly_c = klp.RExtractorTechConductor()
        kly_c.layer = pb_c.layer.id
        match pb_c.algorithm:
            case pb_RExtractorTech.Algorithm.ALGORITHM_SQUARE_COUNTING:
                kly_c.algorithm = klp.Algorithm.SquareCounting
            case pb_RExtractorTech.Algorithm.ALGORITHM_TESSELATION:
                kly_c.algorithm = klp.Algorithm.Tesselation
        kly_c.triangulation_min_b = pb_c.triangulation_min_b
        kly_c.triangulation_max_area = pb_c.triangulation_max_area
        kly_c.resistance = pb_c.resistance
        kly_tech.add_conductor(kly_c)

    for pb_v in pb_tech.vias:
        kly_v = klp.RExtractorTechVia()
        kly_v.cut_layer = pb_v.layer.id
        kly_v.bottom_conductor = pb_v.bottom_conductor.id
        kly_v.top_conductor = pb_v.top_conductor.id
        kly_v.resistance = pb_v.resistance
        kly_v.merge_distance = pb_v.merge_distance
        kly_tech.add_via(kly_v)

    return kly_tech
