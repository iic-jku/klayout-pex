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

from typing import List, Optional, Tuple

import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2
import klayout_pex_protobuf.kpex.tech.device_models_pb2 as device_models_pb2
import klayout_pex_protobuf.kpex.tech.process_stack_pb2 as process_stack_pb2
import klayout_pex_protobuf.kpex.tech.process_parasitics_pb2 as process_parasitics_pb2
import klayout_pex_protobuf.kpex.tech.substrate_pb2 as substrate_pb2

Technology = tech_pb2.Technology
LayerInfo = tech_pb2.LayerInfo
ComputedLayerInfo = tech_pb2.ComputedLayerInfo
ProcessStackInfo = process_stack_pb2.ProcessStackInfo
ProcessParasiticsInfo = process_parasitics_pb2.ProcessParasiticsInfo
ResistanceInfo = process_parasitics_pb2.ResistanceInfo
CapacitanceInfo = process_parasitics_pb2.CapacitanceInfo
DeviceModelsInfo = device_models_pb2.DeviceModelsInfo
DeviceModelMapping = device_models_pb2.DeviceModelMapping
DeviceModelParameter = device_models_pb2.DeviceModelParameter
LVSAreaPerimeterSide = device_models_pb2.LVSAreaPerimeterSide
SubstrateInfo = substrate_pb2.SubstrateInfo

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
KPLT = ComputedLayerInfo.KIND_DEVICE_CAPACITOR_PLATE
KRES = ComputedLayerInfo.KIND_DEVICE_RESISTOR
KPIN = ComputedLayerInfo.KIND_PIN
KLBL = ComputedLayerInfo.KIND_LABEL

# device kinds
METAL_CAP = DeviceModelMapping.KIND_METAL_CAPACITOR


def _gds_pair(gds: GDSPair) -> tech_pb2.GDSPair:
    layer, datatype = gds
    return tech_pb2.GDSPair(layer=layer, datatype=datatype)

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


def _um(length: float) -> float:
    """
    Round a length (in µm) to 1 pm.

    The tables give lengths with at most 4 decimals, but derived ones carry the rounding error
    of the float64 arithmetic, e.g. 5.090000000000001 for the z of IHP Metal5, which is the sum
    of the thicknesses below it. Rounded, it's stored as 5.09 (i.e. the float64 nearest to it),
    while the literals stay as they are.
    """
    return round(length, 6)


def add_substrate_layer(psi: ProcessStackInfo,
                        layer_name: str,
                        height: float,
                        thickness: float,
                        reference: str):
    psi.layers.add(name=layer_name,
                   layer_type=ProcessStackInfo.LAYER_TYPE_SUBSTRATE,
                   substrate_layer=ProcessStackInfo.SubstrateLayer(height=_um(height),
                                                                   thickness=_um(thickness),
                                                                   reference=reference))


def add_nwell_layer(psi: ProcessStackInfo,
                    layer_name: str,
                    z: float,
                    reference: str) -> ProcessStackInfo.NWellLayer:
    li = psi.layers.add(name=layer_name,
                        layer_type=ProcessStackInfo.LAYER_TYPE_NWELL,
                        nwell_layer=ProcessStackInfo.NWellLayer(z=_um(z), reference=reference))
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
    co.thickness = _um(thickness)
    co.width = _um(width)
    co.spacing = _um(spacing)
    co.border = _um(border)


def add_diffusion_layer(psi: ProcessStackInfo,
                        layer_name: str,
                        z: float,
                        reference: str) -> ProcessStackInfo.DiffusionLayer:
    li = psi.layers.add(name=layer_name,
                        layer_type=ProcessStackInfo.LAYER_TYPE_DIFFUSION,
                        diffusion_layer=ProcessStackInfo.DiffusionLayer(z=_um(z), reference=reference))
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
                        metal_layer=ProcessStackInfo.MetalLayer(z=_um(z), thickness=_um(thickness)))
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
                       thickness_over_metal=_um(thickness_over_metal),
                       thickness_where_no_metal=_um(thickness_where_no_metal),
                       thickness_sidewall=_um(thickness_sidewall),
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
                      area_capacitance=area_cap,
                      perimeter_capacitance=perimeter_cap)


def add_overlap_cap(ci: CapacitanceInfo,
                    top_layer: str,
                    bottom_layer: str,
                    cap: float):
    ci.overlaps.add(top_layer_name=top_layer,
                    bottom_layer_name=bottom_layer,
                    capacitance=cap)


def add_sidewall_cap(ci: CapacitanceInfo,
                     layer_name: str,
                     cap: float,
                     offset: float):
    ci.sidewalls.add(layer_name=layer_name,
                     capacitance=cap,
                     offset=offset)


def add_sidewall_overlap_cap(ci: CapacitanceInfo,
                             in_layer: str,
                             out_layer: str,
                             cap: float):
    ci.sideoverlaps.add(in_layer_name=in_layer,
                        out_layer_name=out_layer,
                        capacitance=cap)


def add_mim_cap(ci: CapacitanceInfo,
                top_plate: str,
                bottom_plate: str,
                area_cap: float,
                perimeter_cap: float):
    """
    The capacitances of a MIM cap's top plate, a thin metal just above the bottom plate metal,
    needed by the white-box extraction, which removes the MIM devices from the netlist.

    The magic techs have no parasitic coefficients for the top plate, as the device model has
    the capacitance between the plates. So the top plate couples to all other layers like the
    bottom plate (IHP's magic tech also lists *mimcap with allm5), and only the capacitance
    between the plates comes from the device model.
    Except for the fringe from the top plate's edge down to the layers below the bottom plate
    and the substrate: the bottom plate extends beyond that edge just below it, and shields it.

    NOTE: call this after all other capacitances are added, it copies those of the bottom plate

    :param area_cap: area capacitance of the device model (aF/µm²)
    :param perimeter_cap: perimeter capacitance of the device model (aF/µm),
                          the fringe between the top plate's edge and the bottom plate
    """
    def plate(layer_name: str) -> str:
        return top_plate if layer_name == bottom_plate else layer_name

    substrates = [(sc.layer_name, sc.area_capacitance, sc.perimeter_capacitance) for sc in ci.substrates]
    overlaps = [(oc.top_layer_name, oc.bottom_layer_name, oc.capacitance) for oc in ci.overlaps]
    sidewalls = [(sc.layer_name, sc.capacitance, sc.offset) for sc in ci.sidewalls]
    sideoverlaps = [(soc.in_layer_name, soc.out_layer_name, soc.capacitance) for soc in ci.sideoverlaps]
    layers_below = {bottom_layer for top_layer, bottom_layer, _ in overlaps if top_layer == bottom_plate}

    for layer_name, area, perimeter in substrates:
        if layer_name == bottom_plate:
            add_substrate_cap(ci, top_plate, area, 0.0)  # fringe shielded by the bottom plate
    for top_layer, bottom_layer, cap in overlaps:
        if bottom_plate in (top_layer, bottom_layer):
            add_overlap_cap(ci, plate(top_layer), plate(bottom_layer), cap)
    for layer_name, cap, offset in sidewalls:
        if layer_name == bottom_plate:
            add_sidewall_cap(ci, top_plate, cap, offset)
    for in_layer, out_layer, cap in sideoverlaps:
        if in_layer == bottom_plate and out_layer in layers_below:
            add_sidewall_overlap_cap(ci, top_plate, out_layer, 0.0)  # fringe shielded by the bottom plate
        elif bottom_plate in (in_layer, out_layer):
            add_sidewall_overlap_cap(ci, plate(in_layer), plate(out_layer), cap)

    add_overlap_cap(ci, top_plate, bottom_plate, area_cap)
    add_sidewall_overlap_cap(ci, top_plate, bottom_plate, perimeter_cap)
    add_sidewall_overlap_cap(ci, bottom_plate, top_plate, perimeter_cap)

#-------------------------------------------------------------------------


def lvs_param(name: str,
              lvs_parameter_name: str,
              factor: Optional[float] = None) -> DeviceModelParameter:
    """
    Model parameter from an LVS parameter (times factor, e.g. 1e-6 from µm to m)
    """
    parameter = DeviceModelParameter(name=name, lvs_parameter_name=lvs_parameter_name)
    if factor is not None:
        parameter.lvs_parameter_factor = factor
    return parameter


def const_param(name: str,
                value: float) -> DeviceModelParameter:
    return DeviceModelParameter(name=name, constant=value)


def lvs_area_perimeter_params(w_name: str,
                              l_name: str,
                              lvs_area_parameter_name: str,
                              lvs_perimeter_parameter_name: str,
                              factor: Optional[float] = None) -> List[DeviceModelParameter]:
    """
    Model parameters w and l from the rectangle with the area and perimeter of LVS parameters
    (times factor, e.g. 1e-6 from µm to m), w is the long side and l the short one
    """
    parameters = []
    for name, side in ((w_name, LVSAreaPerimeterSide.SIDE_LONG), (l_name, LVSAreaPerimeterSide.SIDE_SHORT)):
        area_perimeter_side = LVSAreaPerimeterSide(area_parameter_name=lvs_area_parameter_name,
                                                   perimeter_parameter_name=lvs_perimeter_parameter_name,
                                                   side=side)
        parameter = DeviceModelParameter(name=name, lvs_area_perimeter_side=area_perimeter_side)
        if factor is not None:
            parameter.lvs_parameter_factor = factor
        parameters.append(parameter)
    return parameters


def add_device_model_mapping(dmi: DeviceModelsInfo,
                             lvs_device_class_name: str,
                             spice_prefix: str,
                             terminal_names: List[str],
                             parameters: List[DeviceModelParameter],
                             model_name: str = '',  # empty if the same as the LVS device class name
                             kind: DeviceModelMapping.Kind = DeviceModelMapping.KIND_UNSPECIFIED):
    dmi.device_model_mappings.add(lvs_device_class_name=lvs_device_class_name,
                                  kind=kind,
                                  spice_prefix=spice_prefix,
                                  model_name=model_name,
                                  terminal_names=terminal_names,
                                  parameters=parameters)
