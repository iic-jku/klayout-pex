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
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
import tempfile
from typing import *

from klayout.dbcore import PolygonWithProperties
from rich.pretty import pprint

import klayout.db as kdb

import klayout_pex_protobuf.tech_pb2 as tech_pb2
from ..log import (
    console,
    debug,
    info,
    warning,
    error,
    rule
)

from ..tech_info import TechInfo


GDSPair = Tuple[int, int]

LayerIndexMap = Dict[int, int]  # maps layer indexes of LVSDB to annotated_layout
LVSDBRegions = Dict[int, kdb.Region]  # maps layer index of annotated_layout to LVSDB region


@dataclass
class KLayoutExtractedLayerInfo:
    index: int
    lvs_layer_name: str        # NOTE: this can be computed, so gds_pair is preferred
    gds_pair: GDSPair
    region: kdb.Region


@dataclass
class KLayoutMergedExtractedLayerInfo:
    source_layers: List[KLayoutExtractedLayerInfo]
    gds_pair: GDSPair


@dataclass
class KLayoutDeviceTerminal:
    id: int
    name: str
    regions_by_layer_name: Dict[str, kdb.Region]
    net_name: str

    # internal data access
    net_terminal_ref: Optional[kdb.NetTerminalRef]
    net: Optional[kdb.Net]


@dataclass
class KLayoutDeviceTerminalList:
    terminals: List[KLayoutDeviceTerminal]


@dataclass
class KLayoutDeviceInfo:
    id: str
    name: str   # expanded name
    class_name: str
    abstract_name: str

    terminals: KLayoutDeviceTerminalList
    params: Dict[str, str]

    # internal data access
    device: kdb.Device


@dataclass
class KLayoutExtractionContext:
    lvsdb: kdb.LayoutToNetlist
    tech: TechInfo
    dbu: float
    layer_index_map: LayerIndexMap
    lvsdb_regions: LVSDBRegions
    cell_mapping: kdb.CellMapping
    annotated_top_cell: kdb.Cell
    annotated_layout: kdb.Layout
    extracted_layers: Dict[GDSPair, KLayoutMergedExtractedLayerInfo]
    unnamed_layers: List[KLayoutExtractedLayerInfo]

    @classmethod
    def prepare_extraction(cls,
                           lvsdb: kdb.LayoutToNetlist,
                           top_cell: str,
                           tech: TechInfo,
                           blackbox_devices: bool) -> KLayoutExtractionContext:
        dbu = lvsdb.internal_layout().dbu
        annotated_layout = kdb.Layout()
        annotated_layout.dbu = dbu
        top_cell = annotated_layout.create_cell(top_cell)

        # CellMapping
        #   mapping of internal layout to target layout for the circuit mapping
        #   https://www.klayout.de/doc-qt5/code/class_CellMapping.html
        # ---
        # https://www.klayout.de/doc-qt5/code/class_LayoutToNetlist.html#method18
        # Creates a cell mapping for copying shapes from the internal layout to the given target layout
        cm = lvsdb.cell_mapping_into(annotated_layout,  # target layout
                                     top_cell,
                                     not blackbox_devices)  # with_device_cells

        lvsdb_regions, layer_index_map = cls.build_LVS_layer_map(annotated_layout=annotated_layout,
                                                                 lvsdb=lvsdb,
                                                                 tech=tech,
                                                                 blackbox_devices=blackbox_devices)

        # NOTE: GDS only supports integer properties to GDS,
        #       as GDS does not support string keys,
        #       like OASIS does.
        net_name_prop = "net"

        # Build a full hierarchical representation of the nets
        # https://www.klayout.de/doc-qt5/code/class_LayoutToNetlist.html#method14
        # hier_mode = None
        hier_mode = kdb.LayoutToNetlist.BuildNetHierarchyMode.BNH_Flatten
        # hier_mode = kdb.LayoutToNetlist.BuildNetHierarchyMode.BNH_SubcircuitCells

        lvsdb.build_all_nets(
            cmap=cm,               # mapping of internal layout to target layout for the circuit mapping
            target=annotated_layout,  # target layout
            lmap=lvsdb_regions,    # maps: target layer index => net regions
            hier_mode=hier_mode,   # hier mode
            netname_prop=net_name_prop,  # property name to which to attach the net name
            circuit_cell_name_prefix="CIRCUIT_", # NOTE: generates a cell for each circuit
            net_cell_name_prefix=None,    # NOTE: this would generate a cell for each net
            device_cell_name_prefix=None  # NOTE: this would create a cell for each device (e.g. transistor)
        )

        extracted_layers, unnamed_layers = cls.nonempty_extracted_layers(lvsdb=lvsdb,
                                                                         tech=tech,
                                                                         annotated_layout=annotated_layout,
                                                                         layer_index_map=layer_index_map,
                                                                         blackbox_devices=blackbox_devices)

        return KLayoutExtractionContext(
            lvsdb=lvsdb,
            tech=tech,
            dbu=dbu,
            annotated_top_cell=top_cell,
            layer_index_map=layer_index_map,
            lvsdb_regions=lvsdb_regions,
            cell_mapping=cm,
            annotated_layout=annotated_layout,
            extracted_layers=extracted_layers,
            unnamed_layers=unnamed_layers
        )

    @staticmethod
    def build_LVS_layer_map(annotated_layout: kdb.Layout,
                            lvsdb: kdb.LayoutToNetlist,
                            tech: TechInfo,
                            blackbox_devices: bool) -> Tuple[LVSDBRegions, LayerIndexMap]:
        # NOTE: currently, the layer numbers are auto-assigned
        # by the sequence they occur in the LVS script, hence not well defined!
        # build a layer map for the layers that correspond to original ones.

        # https://www.klayout.de/doc-qt5/code/class_LayerInfo.html
        lvsdb_regions: LVSDBRegions = {}
        layer_index_map: LayerIndexMap = {}

        if not hasattr(lvsdb, "layer_indexes"):
            raise Exception("Needs at least KLayout version 0.29.2")

        for layer_index in lvsdb.layer_indexes():
            lname = lvsdb.layer_name(layer_index)

            computed_layer_info = tech.computed_layer_info_by_name.get(lname, None)
            if computed_layer_info and blackbox_devices:
                match computed_layer_info.kind:
                    case tech_pb2.ComputedLayerInfo.Kind.KIND_DEVICE_RESISTOR:
                        continue
                    case tech_pb2.ComputedLayerInfo.Kind.KIND_DEVICE_CAPACITOR:
                        continue

            gds_pair = tech.gds_pair_for_computed_layer_name.get(lname, None)
            if not gds_pair:
                li = lvsdb.internal_layout().get_info(layer_index)
                if li != kdb.LayerInfo():
                    gds_pair = (li.layer, li.datatype)

            if gds_pair is not None:
                annotated_layer_index = annotated_layout.layer()  # creates new index each time!
                # Creates a new internal layer! because multiple layers with the same gds_pair are possible!
                annotated_layout.set_info(annotated_layer_index, kdb.LayerInfo(*gds_pair))
                region = lvsdb.layer_by_index(layer_index)
                lvsdb_regions[annotated_layer_index] = region
                layer_index_map[layer_index] = annotated_layer_index

        return lvsdb_regions, layer_index_map

    @staticmethod
    def nonempty_extracted_layers(lvsdb: kdb.LayoutToNetlist,
                                  tech: TechInfo,
                                  annotated_layout: kdb.Layout,
                                  layer_index_map: LayerIndexMap,
                                  blackbox_devices: bool) -> Tuple[Dict[GDSPair, KLayoutMergedExtractedLayerInfo], List[KLayoutExtractedLayerInfo]]:
        # https://www.klayout.de/doc-qt5/code/class_LayoutToNetlist.html#method18
        nonempty_layers: Dict[GDSPair, KLayoutMergedExtractedLayerInfo] = {}

        unnamed_layers: List[KLayoutExtractedLayerInfo] = []
        lvsdb_layer_indexes = lvsdb.layer_indexes()
        for idx, ln in enumerate(lvsdb.layer_names()):
            li = lvsdb_layer_indexes[idx]
            if li not in layer_index_map:
                continue
            li = layer_index_map[li]
            layer = kdb.Region(annotated_layout.top_cell().begin_shapes_rec(li))
            layer.enable_properties()
            if layer.count() >= 1:
                computed_layer_info = tech.computed_layer_info_by_name.get(ln, None)
                if not computed_layer_info:
                    warning(f"Unable to find info about extracted LVS layer '{ln}'")
                    gds_pair = (1000 + idx, 20)
                    linfo = KLayoutExtractedLayerInfo(
                        index=idx,
                        lvs_layer_name=ln,
                        gds_pair=gds_pair,
                        region=layer
                    )
                    unnamed_layers.append(linfo)
                    continue

                if blackbox_devices:
                    match computed_layer_info.kind:
                        case tech_pb2.ComputedLayerInfo.Kind.KIND_DEVICE_RESISTOR:
                            continue
                        case tech_pb2.ComputedLayerInfo.Kind.KIND_DEVICE_CAPACITOR:
                            continue

                gds_pair = (computed_layer_info.layer_info.drw_gds_pair.layer,
                            computed_layer_info.layer_info.drw_gds_pair.datatype)

                linfo = KLayoutExtractedLayerInfo(
                    index=idx,
                    lvs_layer_name=ln,
                    gds_pair=gds_pair,
                    region=layer
                )

                entry = nonempty_layers.get(gds_pair, None)
                if entry:
                    entry.source_layers.append(linfo)
                else:
                    nonempty_layers[gds_pair] = KLayoutMergedExtractedLayerInfo(
                        source_layers=[linfo],
                        gds_pair=gds_pair,
                    )

        return nonempty_layers, unnamed_layers

    def top_cell_bbox(self) -> kdb.Box:
        b1: kdb.Box = self.annotated_layout.top_cell().bbox()
        b2: kdb.Box = self.lvsdb.internal_layout().top_cell().bbox()
        if b1.area() > b2.area():
            return b1
        else:
            return b2

    def shapes_of_net(self, gds_pair: GDSPair, net: kdb.Net) -> Optional[kdb.Region]:
        lyr = self.extracted_layers.get(gds_pair, None)
        if not lyr:
            return None

        shapes = kdb.Region()
        shapes.enable_properties()

        def add_shapes_from_region(source_region: kdb.Region):
            iter, transform = source_region.begin_shapes_rec()
            while not iter.at_end():
                shape = iter.shape()
                net_name = shape.property('net')
                if net_name == net.name:
                    shapes.insert(transform *     # NOTE: this is a global/initial iterator-wide transformation
                                  iter.trans() *  # NOTE: this is local during the iteration (due to sub hierarchy)
                                  shape.polygon)
                iter.next()

        match len(lyr.source_layers):
            case 0:
                raise AssertionError('Internal error: Empty list of source_layers')
            case _:
                for sl in lyr.source_layers:
                    add_shapes_from_region(sl.region)

        return shapes

    def shapes_of_layer(self, gds_pair: GDSPair) -> Optional[kdb.Region]:
        lyr = self.extracted_layers.get(gds_pair, None)
        if not lyr:
            return None

        shapes: kdb.Region

        match len(lyr.source_layers):
            case 0:
                raise AssertionError('Internal error: Empty list of source_layers')
            case 1:
                shapes = lyr.source_layers[0].region
            case _:
                # NOTE: currently a bug, for now use polygon-per-polygon workaround
                # shapes = kdb.Region()
                # for sl in lyr.source_layers:
                #     shapes += sl.region
                shapes = kdb.Region()
                shapes.enable_properties()
                for sl in lyr.source_layers:
                    iter, transform = sl.region.begin_shapes_rec()
                    while not iter.at_end():
                        p = PolygonWithProperties(iter.shape().polygon, {'net': iter.shape().property('net')})
                        shapes.insert(transform *     # NOTE: this is a global/initial iterator-wide transformation
                                      iter.trans() *  # NOTE: this is local during the iteration (due to sub hierarchy)
                                      p)
                        iter.next()

        return shapes

    def pins_of_layer(self, gds_pair: GDSPair) -> kdb.Region:
        pin_gds_pair = self.tech.layer_info_by_gds_pair[gds_pair].pin_gds_pair
        pin_gds_pair = pin_gds_pair.layer, pin_gds_pair.datatype
        lyr = self.extracted_layers.get(pin_gds_pair, None)
        if lyr is None:
            return kdb.Region()
        if len(lyr.source_layers) != 1:
            raise NotImplementedError(f"currently only supporting 1 pin layer mapping, "
                                      f"but got {len(lyr.source_layers)}")
        return lyr.source_layers[0].region

    def labels_of_layer(self, gds_pair: GDSPair) -> kdb.Texts:
        labels_gds_pair = self.tech.layer_info_by_gds_pair[gds_pair].label_gds_pair
        labels_gds_pair = labels_gds_pair.layer, labels_gds_pair.datatype

        lay: kdb.Layout = self.lvsdb.internal_layout()
        label_layer_idx = lay.find_layer(labels_gds_pair)  # sky130 layer dt = 5
        if label_layer_idx is None:
            return kdb.Texts()

        sh_it = lay.begin_shapes(self.lvsdb.internal_top_cell(), label_layer_idx)
        labels: kdb.Texts = kdb.Texts(sh_it)
        return labels

    @cached_property
    def top_circuit(self) -> kdb.Circuit:
        return self.lvsdb.netlist().top_circuit()

    @cached_property
    def devices_by_name(self) -> Dict[str, KLayoutDeviceInfo]:
        dd = {}

        for d in self.top_circuit.each_device():
            # https://www.klayout.de/doc-qt5/code/class_Device.html
            d: kdb.Device

            param_defs = d.device_class().parameter_definitions()
            params_by_name = {pd.name: d.parameter(pd.id()) for pd in param_defs}

            terminals: List[KLayoutDeviceTerminal] = []

            for td in d.device_class().terminal_definitions():
                n: kdb.Net = d.net_for_terminal(td.id())
                if n is None:
                    warning(f"Skipping terminal {td.name} of device {d.expanded_name()} ({d.device_class().name}) "
                            f"is not connected to any net")
                    terminals.append(
                        KLayoutDeviceTerminal(
                            id=td.id(),
                            name=td.name,
                            regions_by_layer_name={},
                            net_name='',
                            net_terminal_ref=None,
                            net=None
                        )
                    )
                    continue

                for nt in n.each_terminal():
                    nt: kdb.NetTerminalRef

                    if nt.device().expanded_name() != d.expanded_name():
                        continue
                    if nt.terminal_id() != td.id():
                        continue

                    shapes_by_lyr_idx = self.lvsdb.shapes_of_terminal(nt)

                    def layer_name(idx: int) -> str:
                        lyr_info: kdb.LayerInfo = self.annotated_layout.layer_infos()[self.layer_index_map[idx]]
                        return self.tech.canonical_layer_name_by_gds_pair[lyr_info.layer, lyr_info.datatype]

                    shapes_by_lyr_name = {layer_name(idx): shapes for idx, shapes in shapes_by_lyr_idx.items()}

                    terminals.append(
                        KLayoutDeviceTerminal(
                            id=td.id(),
                            name=td.name,
                            regions_by_layer_name=shapes_by_lyr_name,
                            net_name=n.name,
                            net_terminal_ref=nt,
                            net=n
                        )
                    )

            dd[d.expanded_name()] = KLayoutDeviceInfo(
                id=d.id(),
                name=d.expanded_name(),
                class_name=d.device_class().name,
                abstract_name=d.device_abstract.name,
                params=params_by_name,
                terminals=KLayoutDeviceTerminalList(terminals=terminals),
                device=d
            )

        return dd
