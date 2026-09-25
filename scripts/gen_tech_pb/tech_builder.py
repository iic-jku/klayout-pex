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
"""
Helpers to fill a kpex.tech.Technology message, one table row per call (see the PDK modules).
"""
from __future__ import annotations

import struct
from typing import Optional, Tuple

import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2
import klayout_pex_protobuf.kpex.tech.process_stack_pb2 as process_stack_pb2
import klayout_pex_protobuf.kpex.tech.process_parasitics_pb2 as process_parasitics_pb2

Technology = tech_pb2.Technology
LayerInfo = tech_pb2.LayerInfo
ComputedLayerInfo = tech_pb2.ComputedLayerInfo
ProcessStackInfo = process_stack_pb2.ProcessStackInfo
ProcessParasiticsInfo = process_parasitics_pb2.ProcessParasiticsInfo
ResistanceInfo = process_parasitics_pb2.ResistanceInfo
CapacitanceInfo = process_parasitics_pb2.CapacitanceInfo

GDSPair = Tuple[int, int]  # (layer, datatype)

# layer purposes
DNWELL = LayerInfo.PURPOSE_DNWELL
NWELL = LayerInfo.PURPOSE_NWELL
PWELL = LayerInfo.PURPOSE_PWELL
DIFF = LayerInfo.PURPOSE_DIFF
N_P_TAP = LayerInfo.PURPOSE_NTAP_OR_PTAP
NTAP = LayerInfo.PURPOSE_NTAP
PTAP = LayerInfo.PURPOSE_PTAP
PIMP = LayerInfo.PURPOSE_P_IMPLANT
NIMP = LayerInfo.PURPOSE_N_IMPLANT
CONT = LayerInfo.PURPOSE_CONTACT
METAL = LayerInfo.PURPOSE_METAL
VIA = LayerInfo.PURPOSE_VIA
MIM = LayerInfo.PURPOSE_MIM_CAP

# computed layer kinds
KREG = ComputedLayerInfo.KIND_REGULAR
KCAP = ComputedLayerInfo.KIND_DEVICE_CAPACITOR
KRES = ComputedLayerInfo.KIND_DEVICE_RESISTOR
KPIN = ComputedLayerInfo.KIND_PIN
KLBL = ComputedLayerInfo.KIND_LABEL


def _gds_pair(gds: GDSPair) -> tech_pb2.GDSPair:
    layer, datatype = gds
    return tech_pb2.GDSPair(layer=layer, datatype=datatype)


def _float32(value: float) -> float:
    """
    Round to the nearest float32, e.g. 106.13 to 106.12999725341797.

    NOTE: The C++ generator (gen_tech_pb) took the capacitance coefficients as float parameters,
          before storing them in double fields. This reproduces its output exactly;
          TODO: drop it (in a change of its own, as it changes each coefficient by up to 6e-8 relative).
    """
    return struct.unpack('f', struct.pack('f', value))[0]

#-------------------------------------------------------------------------


def add_layer(tech: Technology,
              purpose: LayerInfo.Purpose,
              name: str,
              drw_gds: GDSPair,
              pin_gds: Optional[GDSPair],    # None if not available
              label_gds: Optional[GDSPair],  # None if not available
              description: str):
    layer = tech.layers.add(purpose=purpose,
                            name=name,
                            description=description,
                            drw_gds_pair=_gds_pair(drw_gds))
    if pin_gds is not None:
        layer.pin_gds_pair.CopyFrom(_gds_pair(pin_gds))
    if label_gds is not None:
        layer.label_gds_pair.CopyFrom(_gds_pair(label_gds))


def add_computed_layer(tech: Technology,
                       purpose: LayerInfo.Purpose,
                       kind: ComputedLayerInfo.Kind,
                       name: str,
                       gds: GDSPair,
                       original_layer_name: str,
                       description: str):
    tech.lvs_computed_layers.add(kind=kind,
                                 original_layer_name=original_layer_name,
                                 layer_info=LayerInfo(purpose=purpose,
                                                      name=name,
                                                      description=description,
                                                      drw_gds_pair=_gds_pair(gds)))

#-------------------------------------------------------------------------


def add_substrate_layer(psi: ProcessStackInfo,
                        layer_name: str,
                        height: float,
                        thickness: float,
                        reference: str):
    psi.layers.add(name=layer_name,
                   layer_type=ProcessStackInfo.LAYER_TYPE_SUBSTRATE,
                   substrate_layer=ProcessStackInfo.SubstrateLayer(height=height,
                                                                   thickness=thickness,
                                                                   reference=reference))


def add_nwell_layer(psi: ProcessStackInfo,
                    layer_name: str,
                    z: float,
                    reference: str) -> ProcessStackInfo.NWellLayer:
    li = psi.layers.add(name=layer_name,
                        layer_type=ProcessStackInfo.LAYER_TYPE_NWELL,
                        nwell_layer=ProcessStackInfo.NWellLayer(z=z, reference=reference))
    return li.nwell_layer


def set_contact(co: ProcessStackInfo.Contact,
                name: str,
                layer_below: str,
                metal_above: str,
                thickness: float,
                width: float,
                spacing: float,
                border: float):
    co.name = name
    co.layer_below = layer_below
    co.metal_above = metal_above
    co.thickness = thickness
    co.width = width
    co.spacing = spacing
    co.border = border


def add_diffusion_layer(psi: ProcessStackInfo,
                        layer_name: str,
                        z: float,
                        reference: str) -> ProcessStackInfo.DiffusionLayer:
    li = psi.layers.add(name=layer_name,
                        layer_type=ProcessStackInfo.LAYER_TYPE_DIFFUSION,
                        diffusion_layer=ProcessStackInfo.DiffusionLayer(z=z, reference=reference))
    return li.diffusion_layer


def add_field_oxide_layer(psi: ProcessStackInfo,
                          layer_name: str,
                          dielectric_k: float):
    psi.layers.add(name=layer_name,
                   layer_type=ProcessStackInfo.LAYER_TYPE_FIELD_OXIDE,
                   field_oxide_layer=ProcessStackInfo.FieldOxideLayer(dielectric_k=dielectric_k))


def add_metal_layer(psi: ProcessStackInfo,
                    layer_name: str,
                    z: float,
                    thickness: float) -> ProcessStackInfo.MetalLayer:
    li = psi.layers.add(name=layer_name,
                        layer_type=ProcessStackInfo.LAYER_TYPE_METAL,
                        metal_layer=ProcessStackInfo.MetalLayer(z=z, thickness=thickness))
    return li.metal_layer


def add_simple_dielectric(psi: ProcessStackInfo,
                          name: str,
                          dielectric_k: float,
                          reference: str):
    psi.layers.add(name=name,
                   layer_type=ProcessStackInfo.LAYER_TYPE_SIMPLE_DIELECTRIC,
                   simple_dielectric_layer=ProcessStackInfo.SimpleDielectricLayer(
                       dielectric_k=dielectric_k,
                       reference=reference))


def add_conformal_dielectric(psi: ProcessStackInfo,
                             name: str,
                             dielectric_k: float,
                             thickness_over_metal: float,
                             thickness_where_no_metal: float,
                             thickness_sidewall: float,
                             reference: str):
    psi.layers.add(name=name,
                   layer_type=ProcessStackInfo.LAYER_TYPE_CONFORMAL_DIELECTRIC,
                   conformal_dielectric_layer=ProcessStackInfo.ConformalDielectricLayer(
                       dielectric_k=dielectric_k,
                       thickness_over_metal=thickness_over_metal,
                       thickness_where_no_metal=thickness_where_no_metal,
                       thickness_sidewall=thickness_sidewall,
                       reference=reference))

#-------------------------------------------------------------------------


def add_layer_resistance(ri: ResistanceInfo,
                         layer_name: str,
                         resistance: float,
                         corner_adjustment_fraction: float = 0.0):
    ri.layers.add(layer_name=layer_name,
                  resistance=resistance,
                  corner_adjustment_fraction=corner_adjustment_fraction)


def add_contact_resistance(ri: ResistanceInfo,
                           contact_name: str,
                           device_layer_name: str,
                           layer_above: str,
                           resistance: float):
    ri.contacts.add(contact_name=contact_name,
                    device_layer_name=device_layer_name,
                    layer_above=layer_above,
                    resistance=resistance)


def add_via_resistance(ri: ResistanceInfo,
                       via_name: str,
                       resistance: float):
    ri.vias.add(via_name=via_name,
                resistance=resistance)


def add_substrate_cap(ci: CapacitanceInfo,
                      layer_name: str,
                      area_cap: float,
                      perimeter_cap: float):
    ci.substrates.add(layer_name=layer_name,
                      area_capacitance=_float32(area_cap),
                      perimeter_capacitance=_float32(perimeter_cap))


def add_overlap_cap(ci: CapacitanceInfo,
                    top_layer: str,
                    bottom_layer: str,
                    cap: float):
    ci.overlaps.add(top_layer_name=top_layer,
                    bottom_layer_name=bottom_layer,
                    capacitance=_float32(cap))


def add_sidewall_cap(ci: CapacitanceInfo,
                     layer_name: str,
                     cap: float,
                     offset: float):
    ci.sidewalls.add(layer_name=layer_name,
                     capacitance=_float32(cap),
                     offset=_float32(offset))


def add_sidewall_overlap_cap(ci: CapacitanceInfo,
                             in_layer: str,
                             out_layer: str,
                             cap: float):
    ci.sideoverlaps.add(in_layer_name=in_layer,
                        out_layer_name=out_layer,
                        capacitance=_float32(cap))
