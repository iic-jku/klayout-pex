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

import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2
import klayout_pex_protobuf.kpex.tech.process_stack_pb2 as stack_pb2


def tech_with_two_metals() -> tech_pb2.Technology:
    """
    met1 (1/0) and met2 (2/0), with the LVS layer met1_con (101/7) derived from met1,
    in a stack of met1 (with via1 up to met2), its conformal liner, wrapped by the conformal coat,
    ild, met2 and air
    """
    tech = tech_pb2.Technology(name='test')
    for gds_layer, name in enumerate(('met1', 'met2'), start=1):
        tech.layers.add(name=name, drw_gds_pair=tech_pb2.GDSPair(layer=gds_layer, datatype=0))
    tech.lvs_computed_layers.add(layer_info=tech_pb2.LayerInfo(name='met1_con',
                                                               drw_gds_pair=tech_pb2.GDSPair(layer=101, datatype=7)),
                                 original_layer_name='met1')
    LT = stack_pb2.ProcessStackInfo
    stack = tech.process_stack
    met1 = stack.layers.add(name='met1', metal_layer=stack_pb2.ProcessStackInfo.MetalLayer())
    met1.metal_layer.z = 1.0
    met1.metal_layer.thickness = 0.2
    met1.metal_layer.contact_above.CopyFrom(LT.Contact(name='via1', layer_below='met1', metal_above='met2', width=0.2))
    for name, reference, k in (('liner', 'met1', 4.0), ('coat', 'liner', 5.0)):
        film = stack.layers.add(name=name, conformal_dielectric_layer=stack_pb2.ProcessStackInfo.ConformalDielectricLayer())
        film.conformal_dielectric_layer.reference = reference
        film.conformal_dielectric_layer.dielectric_k = k
    stack.layers.add(name='ild', simple_dielectric_layer=stack_pb2.ProcessStackInfo.SimpleDielectricLayer()).simple_dielectric_layer.dielectric_k = 3.5
    met2 = stack.layers.add(name='met2', metal_layer=stack_pb2.ProcessStackInfo.MetalLayer())
    met2.metal_layer.z = 2.5
    met2.metal_layer.thickness = 0.3
    stack.layers.add(name='air', simple_dielectric_layer=stack_pb2.ProcessStackInfo.SimpleDielectricLayer()).simple_dielectric_layer.dielectric_k = 1.0
    return tech
