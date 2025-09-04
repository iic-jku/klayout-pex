#! /usr/bin/env python3
#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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


#
# Protocol Buffer Schema for FasterCap Input Files
# https://www.fastfieldsolvers.com/software.htm#fastercap
#

from typing import *
from functools import cached_property
import math

import klayout.db as kdb

from ..klayout.lvsdb_extractor import KLayoutExtractionContext, GDSPair
from .fastercap_model_generator import FasterCapModelBuilder, FasterCapModelGenerator
from ..log import (
    console,
    debug,
    info,
    warning,
    error
)
from ..tech_info import TechInfo

import klayout_pex_protobuf.kpex.tech.process_stack_pb2 as process_stack_pb2


class FasterCapInputBuilder:
    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 tech_info: TechInfo,
                 k_void: float = 3.5,
                 delaunay_amax: float = 0.0,
                 delaunay_b: float = 1.0):
        self.pex_context = pex_context
        self.tech_info = tech_info
        self.k_void = k_void
        self.delaunay_amax = delaunay_amax
        self.delaunay_b = delaunay_b

    @cached_property
    def dbu(self) -> float:
        return self.pex_context.dbu

    def gds_pair(self, layer_name) -> Optional[GDSPair]:
        gds_pair = self.tech_info.gds_pair_for_computed_layer_name.get(layer_name, None)
        if not gds_pair:
            gds_pair = self.tech_info.gds_pair_for_layer_name.get(layer_name, None)
        if not gds_pair:
            warning(f"Can't find GDS pair for layer {layer_name}")
            return None
        return gds_pair

    def shapes_of_net(self, layer_name: str, net: kdb.Net) -> Optional[kdb.Region]:
        gds_pair = self.gds_pair(layer_name=layer_name)
        if not gds_pair:
            return None

        shapes = self.pex_context.shapes_of_net(gds_pair=gds_pair, net=net)
        if not shapes:
            debug(f"Nothing extracted for layer {layer_name}")
        return shapes

    def shapes_of_layer(self, layer_name: str) -> Optional[kdb.Region]:
        gds_pair = self.gds_pair(layer_name=layer_name)
        if not gds_pair:
            return None

        shapes = self.pex_context.shapes_of_layer(gds_pair=gds_pair)
        if not shapes:
            debug(f"Nothing extracted for layer {layer_name}")
        return shapes

    def top_cell_bbox(self) -> kdb.Box:
        return self.pex_context.top_cell_bbox()

    def build(self) -> FasterCapModelGenerator:
        lvsdb = self.pex_context.lvsdb
        netlist: kdb.Netlist = lvsdb.netlist()

        def format_terminal(t: kdb.NetTerminalRef) -> str:
            td = t.terminal_def()
            d = t.device()
            return f"{d.expanded_name()}/{td.name}/{td.description}"

        model_builder = FasterCapModelBuilder(
            dbu=self.dbu,
            k_void=self.k_void,
            delaunay_amax=self.delaunay_amax,   # test/compare with smaller, e.g. 0.05 => more triangles
            delaunay_b=self.delaunay_b          # test/compare with 1.0 => more triangles at edges
        )

        fox_layer = self.tech_info.field_oxide_layer

        model_builder.add_material(name=fox_layer.name, k=fox_layer.field_oxide_layer.dielectric_k)
        for diel_name, diel_k in self.tech_info.dielectric_by_name.items():
            model_builder.add_material(name=diel_name, k=diel_k)

        circuit = netlist.circuit_by_name(self.pex_context.annotated_top_cell.name)
        # https://www.klayout.de/doc-qt5/code/class_Circuit.html
        if not circuit:
            circuits = [c.name for c in netlist.each_circuit()]
            raise Exception(f"Expected circuit called {self.pex_context.annotated_top_cell.name} in extracted netlist, "
                            f"only available circuits are: {circuits}")

        diffusion_regions: List[kdb.Region] = []

        for net in circuit.each_net():
            # https://www.klayout.de/doc-qt5/code/class_Net.html
            debug(f"Net name={net.name}, expanded_name={net.expanded_name()}, pin_count={net.pin_count()}, "
                  f"is_floating={net.is_floating()}, is_passive={net.is_passive()}, "
                  f"terminals={list(map(lambda t: format_terminal(t), net.each_terminal()))}")

            net_name = net.expanded_name()

            for metal_layer in self.tech_info.process_metal_layers:
                metal_layer_name = metal_layer.name
                metal_layer = metal_layer.metal_layer

                metal_z_bottom = metal_layer.z
                metal_z_top = metal_z_bottom + metal_layer.thickness

                shapes = self.shapes_of_net(layer_name=metal_layer_name, net=net)
                if shapes:
                    if shapes.count() >= 1:
                        info(f"Conductor {net_name}, metal {metal_layer_name}, "
                             f"z={metal_layer.z}, height={metal_layer.thickness}")
                        model_builder.add_conductor(net_name=net_name,
                                                    layer=shapes,
                                                    z=metal_layer.z,
                                                    height=metal_layer.thickness)

                if metal_layer.HasField('contact_above'):
                    contact = metal_layer.contact_above
                    shapes = self.shapes_of_net(layer_name=contact.name, net=net)
                    if shapes and not shapes.is_empty():
                        info(f"Conductor {net_name}, via {contact.name}, "
                             f"z={metal_z_top}, height={contact.thickness}")
                        model_builder.add_conductor(net_name=net_name,
                                                    layer=shapes,
                                                    z=metal_z_top,
                                                    height=contact.thickness)

                # diel_above = self.tech_info.process_stack_layer_by_name.get(metal_layer.reference_above, None)
                # if diel_above:
                #     #model_builder.add_dielectric(material_name=metal_layer.reference_above,
                #     #                             layer=kdb.Region().)
                #     pass
                # TODO: add stuff

            # DIFF / TAP
            for diffusion_layer in self.tech_info.process_diffusion_layers:
                diffusion_layer_name = diffusion_layer.name
                diffusion_layer = diffusion_layer.diffusion_layer
                shapes = self.shapes_of_net(layer_name=diffusion_layer_name, net=net)
                if shapes and not shapes.is_empty():
                    diffusion_regions.append(shapes)
                    info(f"Diffusion {net_name}, layer {diffusion_layer_name}, "
                         f"z={0}, height={0.1}")
                    model_builder.add_conductor(net_name=net_name,
                                                layer=shapes,
                                                z=0,  # TODO
                                                height=0.1)  # TODO: diffusion_layer.z

                contact = diffusion_layer.contact_above
                shapes = self.shapes_of_net(layer_name=contact.name, net=net)
                if shapes and not shapes.is_empty():
                    info(f"Diffusion {net_name}, contact {contact.name}, "
                         f"z={0}, height={contact.thickness}")
                    model_builder.add_conductor(net_name=net_name,
                                                layer=shapes,
                                                z=0.0,
                                                height=contact.thickness)

        enlarged_top_cell_bbox = self.top_cell_bbox().enlarged(math.floor(8 / self.dbu))  # 8µm fringe halo

        #
        # global substrate block below everything. independent of nets!
        #

        substrate_layer = self.tech_info.process_substrate_layer.substrate_layer
        substrate_region = kdb.Region()

        substrate_block = enlarged_top_cell_bbox.dup()
        substrate_region.insert(substrate_block)

        diffusion_margin = math.floor(1 / self.dbu)  # 1 µm
        for d in diffusion_regions:
            substrate_region -= d.sized(diffusion_margin)
        info(f"Substrate VSUBS, "
             f"z={0 - substrate_layer.height - substrate_layer.thickness}, height={substrate_layer.thickness}")
        model_builder.add_conductor(net_name="VSUBS",
                                    layer=substrate_region,
                                    z=0 - substrate_layer.height - substrate_layer.thickness,
                                    height=substrate_layer.thickness)

        #
        # add dielectrics
        #

        fox_region = kdb.Region()
        fox_block = enlarged_top_cell_bbox.dup()
        fox_region.insert(fox_block)

        # field oxide goes from substrate/diff/well up to below the gate-poly
        gate_poly_height = self.tech_info.gate_poly_layer.metal_layer.z
        fox_z = 0
        fox_height = gate_poly_height - fox_z
        info(f"Simple dielectric (field oxide) {fox_layer.name}: "
             f"z={fox_z}, height={fox_height}")
        model_builder.add_dielectric(material_name=fox_layer.name,
                                     layer=fox_region,
                                     z=fox_z,
                                     height=fox_height)

        for metal_layer in self.tech_info.process_metal_layers:
            metal_layer_name = metal_layer.name
            metal_layer = metal_layer.metal_layer

            metal_z_bottom = metal_layer.z

            extracted_shapes = self.shapes_of_layer(layer_name=metal_layer_name)

            sidewall_region: Optional[kdb.Region] = None
            sidewall_height = 0

            no_metal_region: Optional[kdb.Region] = None
            no_metal_height = 0

            #
            # add sidewall dielectrics
            #
            if extracted_shapes:
                sidewall_height = 0
                sidewall_region = extracted_shapes
                sidewallee = metal_layer_name

                while True:
                    sidewall = self.tech_info.sidewall_dielectric_layer(sidewallee)
                    if not sidewall:
                        break
                    match sidewall.layer_type:
                        case process_stack_pb2.ProcessStackInfo.LAYER_TYPE_SIDEWALL_DIELECTRIC:
                            d = math.floor(sidewall.sidewall_dielectric_layer.width_outside_sidewall / self.dbu)
                            sidewall_region = sidewall_region.sized(d)
                            h_delta = sidewall.sidewall_dielectric_layer.height_above_metal or metal_layer.thickness
                            # if h_delta == 0:
                            #     h_delta = metal_layer.thickness
                            sidewall_height += h_delta
                            info(f"Sidewall dielectric {sidewall.name}: z={metal_layer.z}, height={sidewall_height}")
                            model_builder.add_dielectric(material_name=sidewall.name,
                                                         layer=sidewall_region,
                                                         z=metal_layer.z,
                                                         height=sidewall_height)

                        case process_stack_pb2.ProcessStackInfo.LAYER_TYPE_CONFORMAL_DIELECTRIC:
                            conf_diel = sidewall.conformal_dielectric_layer
                            d = math.floor(conf_diel.thickness_sidewall / self.dbu)
                            sidewall_region = sidewall_region.sized(d)
                            h_delta = metal_layer.thickness + conf_diel.thickness_over_metal
                            sidewall_height += h_delta
                            info(f"Conformal dielectric (sidewall) {sidewall.name}: "
                                 f"z={metal_layer.z}, height={sidewall_height}")
                            model_builder.add_dielectric(material_name=sidewall.name,
                                                         layer=sidewall_region,
                                                         z=metal_layer.z,
                                                         height=sidewall_height)
                            if conf_diel.thickness_where_no_metal > 0.0:
                                no_metal_block = enlarged_top_cell_bbox.dup()
                                no_metal_region = kdb.Region()
                                no_metal_region.insert(no_metal_block)
                                no_metal_region -= sidewall_region
                                no_metal_height = conf_diel.thickness_where_no_metal
                                info(f"Conformal dielectric (where no metal) {sidewall.name}: "
                                     f"z={metal_layer.z}, height={no_metal_height}")
                                model_builder.add_dielectric(material_name=sidewall.name,
                                                             layer=no_metal_region,
                                                             z=metal_layer.z,
                                                             height=no_metal_height)

                    sidewallee = sidewall.name

            #
            # add simple dielectric
            #
            simple_dielectric, diel_height = self.tech_info.simple_dielectric_above_metal(metal_layer_name)
            if simple_dielectric:
                diel_block = enlarged_top_cell_bbox.dup()
                diel_region = kdb.Region()
                diel_region.insert(diel_block)
                if sidewall_region:
                    assert sidewall_height >= 0.0
                    diel_region -= sidewall_region
                    info(f"Simple dielectric (sidewall) {simple_dielectric.name}: "
                         f"z={metal_z_bottom + sidewall_height}, height={diel_height - sidewall_height}")
                    model_builder.add_dielectric(material_name=simple_dielectric.name,
                                                 layer=sidewall_region,
                                                 z=metal_z_bottom + sidewall_height,
                                                 height=diel_height - sidewall_height)
                if no_metal_region:
                    info(f"Simple dielectric (no metal) {simple_dielectric.name}: "
                         f"z={metal_z_bottom + no_metal_height}, height={diel_height - no_metal_height}")
                    model_builder.add_dielectric(material_name=simple_dielectric.name,
                                                 layer=diel_region,
                                                 z=metal_z_bottom + no_metal_height,
                                                 height=diel_height - no_metal_height)
                else:
                    info(f"Simple dielectric {simple_dielectric.name}: "
                         f"z={metal_z_bottom}, height={diel_height}")
                    model_builder.add_dielectric(material_name=simple_dielectric.name,
                                                 layer=diel_region,
                                                 z=metal_z_bottom,
                                                 height=diel_height)

        gen = model_builder.generate()
        return gen
