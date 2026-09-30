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
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property
import tempfile
from typing import *

from rich.pretty import pprint

import klayout.db as kdb

from ..log import (
    console,
    debug,
    info,
    warning,
    error,
    rule
)

from .shapes_pb2_converter import ShapesConverter

from ..tech_info import TechInfo
import klayout_pex_protobuf.kpex.geometry.shapes_pb2 as shapes_pb2
import klayout_pex_protobuf.kpex.layout.device_pb2 as device_pb2
import klayout_pex_protobuf.kpex.layout.pin_pb2 as pin_pb2
import klayout_pex_protobuf.kpex.layout.location_pb2 as location_pb2
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2

GDSPair = Tuple[int, int]

LayerIndexMap = Dict[int, int]  # maps layer indexes of LVSDB to annotated_layout
LVSDBRegions = Dict[int, kdb.Region]  # maps layer index of annotated_layout to LVSDB region


class LVSDBError(Exception):
    """
    The LVS database lacks what the extraction depends on.
    """
    pass


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
class KLayoutNonemptyExtractedLayers:
    extracted_layers: Dict[GDSPair, KLayoutMergedExtractedLayerInfo]
    unnamed_layers: List[KLayoutExtractedLayerInfo]   # not in the tech info
    unmodeled_layers: List[str]                        # unnamed layers the tech info has no layer for


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
    # unnamed layers the tech info has no layer for (derived from the same original layer)
    unmodeled_layers: List[str]

    @classmethod
    def prepare_extraction(cls,
                           lvsdb: kdb.LayoutToNetlist,
                           top_cell: str,
                           tech: TechInfo,
                           blackbox_devices: bool) -> KLayoutExtractionContext:
        # NOTE: e.g. the abstract of a device the LVS script removed from the netlist is left as a top cell
        internal_top_cell = lvsdb.internal_top_cell()
        extra_top_cells = [c.name for c in lvsdb.internal_layout().top_cells()
                           if c.cell_index() != internal_top_cell.cell_index()]
        if extra_top_cells:
            warning(f"Ignoring the LVS database top cells besides {internal_top_cell.name}: "
                    f"{', '.join(extra_top_cells)}")

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

        nonempty_layers = cls.nonempty_extracted_layers(lvsdb=lvsdb,
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
            extracted_layers=nonempty_layers.extracted_layers,
            unnamed_layers=nonempty_layers.unnamed_layers,
            unmodeled_layers=nonempty_layers.unmodeled_layers
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
                                  blackbox_devices: bool) -> KLayoutNonemptyExtractedLayers:
        # https://www.klayout.de/doc-qt5/code/class_LayoutToNetlist.html#method18
        nonempty_layers: Dict[GDSPair, KLayoutMergedExtractedLayerInfo] = {}

        unnamed_layers: List[KLayoutExtractedLayerInfo] = []
        original_gds_pair_by_unnamed_layer_name: Dict[str, GDSPair] = {}
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
                    gds_pair = (1000 + idx, 20)
                    linfo = KLayoutExtractedLayerInfo(
                        index=idx,
                        lvs_layer_name=ln,
                        gds_pair=gds_pair,
                        region=layer
                    )
                    unnamed_layers.append(linfo)
                    original_info = annotated_layout.get_info(li)
                    original_gds_pair_by_unnamed_layer_name[ln] = (original_info.layer, original_info.datatype)
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

        unmodeled_layers = KLayoutExtractionContext.check_unnamed_layers(
            lvsdb=lvsdb,
            tech=tech,
            annotated_layout=annotated_layout,
            layer_index_map=layer_index_map,
            unnamed_layers=unnamed_layers,
            original_gds_pair_by_unnamed_layer_name=original_gds_pair_by_unnamed_layer_name
        )

        return KLayoutNonemptyExtractedLayers(extracted_layers=nonempty_layers,
                                              unnamed_layers=unnamed_layers,
                                              unmodeled_layers=unmodeled_layers)

    @staticmethod
    def check_unnamed_layers(lvsdb: kdb.LayoutToNetlist,
                             tech: TechInfo,
                             annotated_layout: kdb.Layout,
                             layer_index_map: LayerIndexMap,
                             unnamed_layers: List[KLayoutExtractedLayerInfo],
                             original_gds_pair_by_unnamed_layer_name: Dict[str, GDSPair]) -> List[str]:
        """
        An LVS layer the tech info doesn't know is left out of the extraction.
        That's fine where the tech info has layers derived from the same original layer
        that cover it (e.g. the raw contact layer, and the contacts to diffusion and poly).

        :return: the layers the tech info has no derived layer for, which the LVS deck defines
        """
        lvsdb_layer_index_by_name = {lvsdb.layer_name(li): li for li in lvsdb.layer_indexes()}

        def region(lvs_layer_name: str) -> kdb.Region:
            li = layer_index_map.get(lvsdb_layer_index_by_name[lvs_layer_name], None)
            if li is None:
                return kdb.Region()
            return kdb.Region(annotated_layout.top_cell().begin_shapes_rec(li))

        unmodeled_layers: List[str] = []
        partly_covered_layers: List[str] = []

        for ul in unnamed_layers:
            gds_pair = original_gds_pair_by_unnamed_layer_name[ul.lvs_layer_name]
            original_layer = tech.layer_info_by_gds_pair.get(gds_pair, None)
            description = f"{ul.lvs_layer_name} ({original_layer.name if original_layer else '%d/%d' % gds_pair})"

            # NOTE: the LVS deck may not define the layers the tech info derives (e.g. differently named ones)
            derived_layer_names = [] if original_layer is None else [
                name for name, info in tech.computed_layer_info_by_name.items()
                if info.original_layer_name == original_layer.name and name in lvsdb_layer_index_by_name
            ]
            if not derived_layer_names:
                unmodeled_layers.append(f"{description}: the tech info has no layer derived from it")
                continue

            covered = kdb.Region()
            for name in derived_layer_names:
                covered += region(name)
            uncovered = ul.region.dup()
            uncovered.remove_properties()
            uncovered -= covered
            if uncovered.is_empty():
                debug(f"The LVS layer {description} is covered by {', '.join(derived_layer_names)}")
            else:
                partly_covered_layers.append(f"{description}: {uncovered.count()} of {ul.region.count()} shapes "
                                             f"are not within {', '.join(derived_layer_names)}")

        if unmodeled_layers or partly_covered_layers:
            warning("The extraction leaves out these LVS layers, as the tech info doesn't know them:\n" +
                    '\n'.join(f"  - {layer}" for layer in unmodeled_layers + partly_covered_layers))

        return unmodeled_layers

    def top_cell_bbox(self) -> kdb.Box:
        b1: kdb.Box = self.annotated_layout.top_cell().bbox()
        b2: kdb.Box = self.lvsdb.internal_top_cell().bbox()
        if b1.area() > b2.area():
            return b1
        else:
            return b2

    def shapes_of_net(self, gds_pair: GDSPair, net: kdb.Net | str) -> Optional[kdb.Region]:
        lyr = self.extracted_layers.get(gds_pair, None)
        if not lyr:
            return None

        shapes = kdb.Region()
        shapes.enable_properties()

        requested_net_name = net.name if isinstance(net, kdb.Net) else net

        def add_shapes_from_region(source_region: kdb.Region):
            iter, transform = source_region.begin_shapes_rec()
            while not iter.at_end():
                shape = iter.shape()
                net_name = shape.property('net')
                if net_name == requested_net_name:
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
                        p = kdb.PolygonWithProperties(iter.shape().polygon, {'net': iter.shape().property('net')})
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

        lay: kdb.Layout = self.annotated_layout
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
    def devices_by_name(self) -> Dict[str, device_pb2.Device]:
        # NOTE: a device the LVS script created, rather than extracted, has no abstract,
        #       so no terminal geometry to connect it to the resistor network
        #       (e.g. a model mapping that replaces extracted devices with ones of another class)
        created_devices = [f"{d.expanded_name()} ({d.device_class().name})"
                           for d in self.top_circuit.each_device() if d.device_abstract is None]
        if created_devices:
            raise LVSDBError(f"The LVS database has devices without layout geometry, "
                             f"which the resistance extraction depends on: {', '.join(created_devices)}. "
                             f"They were created by the LVS script rather than extracted from the layout, "
                             f"e.g. to replace extracted devices with another device class")

        dd = {}

        shapes_converter = ShapesConverter(dbu=self.dbu)

        # (device class, terminal, LVS layer) -> device names
        devices_by_unknown_terminal_layer: Dict[Tuple[str, str, str], List[str]] = defaultdict(list)

        for d_kly in self.top_circuit.each_device():
            # https://www.klayout.de/doc-qt5/code/class_Device.html
            d_kly: kdb.Device

            d = device_pb2.Device()
            d.id = d_kly.id()
            d.device_name = d_kly.expanded_name()
            d.device_class_name = d_kly.device_class().name
            d.device_abstract_name = d_kly.device_abstract.name

            for pd in d_kly.device_class().parameter_definitions():
                p = d.parameters.add()
                p.id = pd.id()
                p.name = pd.name
                p.value = d_kly.parameter(pd.id())

            for td in d_kly.device_class().terminal_definitions():
                n: kdb.Net = d_kly.net_for_terminal(td.id())
                net_name = n.name or f"${n.cluster_id}"
                if n is None:
                    warning(f"Skipping terminal {td.name} of device {d.name} ({d.device_class}) "
                            f"is not connected to any net")
                    terminal = d.terminals.add()
                    terminal.id = td.id()
                    terminal.name = td.name
                    terminal.net_name = ''  # TODO
                    continue

                for nt in n.each_terminal():
                    nt: kdb.NetTerminalRef

                    if nt.device().expanded_name() != d_kly.expanded_name():
                        continue
                    if nt.terminal_id() != td.id():
                        continue

                    shapes_by_lyr_idx = self.lvsdb.shapes_of_terminal(nt)

                    terminal = d.terminals.add()
                    terminal.device_id = d.id
                    terminal.terminal_id = td.id()
                    terminal.name = td.name
                    terminal.net_name = net_name

                    for idx, shapes in shapes_by_lyr_idx.items():
                        lyr_idx = self.layer_index_map.get(idx, None)
                        if lyr_idx is None:
                            key = (d.device_class_name, td.name, self.lvsdb.layer_name(idx))
                            devices_by_unknown_terminal_layer[key].append(d.device_name)
                            continue

                        lyr_info: kdb.LayerInfo = self.annotated_layout.layer_infos()[lyr_idx]

                        region_by_layer = terminal.region_by_layer.add()
                        # NOTE: the annotated layout has a layer for each LVS layer, so several for a GDS pair
                        #       (e.g. poly_con and poly_vpp), but the resistance extraction has the wires
                        #       of a GDS pair on one of them, so the terminal must be on that one to be a port
                        region_by_layer.layer.id = self.annotated_layout.layer(lyr_info.layer, lyr_info.datatype)
                        region_by_layer.layer.canonical_layer_name = self.tech.canonical_layer_name_by_gds_pair[lyr_info.layer, lyr_info.datatype]

                        shapes_converter.klayout_region_to_pb(shapes, region_by_layer.region)

            dd[d.device_name] = d

        # NOTE: once devices are connected to the resistance network (#211, item 6),
        #       a terminal without a node must be an error (or get a fallback node)
        if devices_by_unknown_terminal_layer:
            def device_list(device_names: List[str]) -> str:
                listed = ', '.join(device_names[:3])
                return listed if len(device_names) <= 3 else f"{listed} and {len(device_names) - 3} more"

            warning("The resistance network has no nodes for these device terminals, "
                    "as the tech info has no layer for their LVS layer:\n" +
                    '\n'.join(f"  - {device_class} terminal {terminal} on LVS layer {lvs_layer}: "
                              f"{device_list(device_names)}"
                              for (device_class, terminal, lvs_layer), device_names
                              in sorted(devices_by_unknown_terminal_layer.items())))

        return dd

    @cached_property
    def pins_pb2_by_layer(self) -> Dict[GDSPair, List[pin_pb2.Pin]]:
        d = defaultdict(list)

        for lvs_gds_pair, lyr_info in self.extracted_layers.items():
            canonical_layer_name = self.tech.canonical_layer_name_by_gds_pair[lvs_gds_pair]
            # NOTE: LVS GDS Pair differs from real GDS Pair,
            #       as in some cases we want to split a layer into different regions (ptap vs ntap, cap vs ncap)
            #       so invent new datatype numbers, like adding 100 to the real GDS datatype
            gds_pair = self.tech.gds_pair_for_layer_name.get(canonical_layer_name, None)
            if gds_pair is None:
                continue
            if gds_pair not in self.tech.layer_info_by_gds_pair:
                continue

            for lyr in lyr_info.source_layers:
                klayout_index = self.annotated_layout.layer(*lyr.gds_pair)

                pins = self.pins_of_layer(gds_pair)
                labels = self.labels_of_layer(gds_pair)

                pin_labels: kdb.Texts = labels & pins
                for l in pin_labels:
                    l: kdb.Text
                    # NOTE: because we want more like a point as a junction
                    #       and folx create huge pins (covering the whole metal)
                    #       we create our own "mini squares"
                    #    (ResistorExtractor will subtract the pins from the metal polygons,
                    #     so in the extreme case the polygons could become empty)

                    pin = pin_pb2.Pin()
                    pin.label = l.string

                    pos = l.position()

                    # is there more elegant / faster way to do this?
                    for p in pins:
                        p: kdb.PolygonWithProperties
                        if p.inside(pos):
                            pin.net_name = p.property('net')
                            break

                    canonical_layer_name = self.tech.canonical_layer_name_by_gds_pair[lyr.gds_pair]
                    lvs_layer_name = self.tech.computed_layer_info_by_gds_pair[lyr.gds_pair].layer_info.name
                    pin.layer.id = klayout_index
                    pin.layer.canonical_layer_name = canonical_layer_name
                    pin.layer.lvs_layer_name = lvs_layer_name

                    pin.label_point.x = pos.x
                    pin.label_point.y = pos.y
                    pin.label_point.net = pin.net_name

                    d[gds_pair].append(pin)

        return d
