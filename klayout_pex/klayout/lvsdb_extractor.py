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

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import cached_property
import re
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
from ..types import GDSPair, Label, LayerName, LVSLayerName, NetName
import klayout_pex_protobuf.kpex.geometry.shapes_pb2 as shapes_pb2
import klayout_pex_protobuf.kpex.layout.device_pb2 as device_pb2
import klayout_pex_protobuf.kpex.layout.pin_pb2 as pin_pb2
import klayout_pex_protobuf.kpex.layout.location_pb2 as location_pb2
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2


LayerIndexMap = Dict[int, int]  # maps layer indexes of LVSDB to annotated_layout
LVSDBRegions = Dict[int, kdb.Region]  # maps layer index of annotated_layout to LVSDB region
PortLabelKey = Tuple[int, int, int, Label]  # annotated layer ID, x, y, label, in extraction DBU
PORT_LABEL_MODES = ('auto', 'top')

# the property of the shapes of the plates of a device capacitor (see KLayoutExtractionContext.shapes_of_layer)
DEVICE_CAPACITOR_PLATE_PROPERTY = 'device_capacitor_plate'


class LVSDBError(Exception):
    """
    The LVS database lacks what the extraction depends on.
    """
    pass


def unique_name(name: str, present_names: Set[str], separator: str = '$') -> str:
    """
    The name, or if it's present, the name with a number (e.g. vss$1),
    like KLayout's tl::unique_name, which its SPICE writer names the nets with,
    but regardless of case, as SPICE reads names (ngspice joins the nets a and A)

    :param present_names: the names taken, case-folded
    """
    if name.casefold() not in present_names:
        return name
    j = 0
    m = 1 << 30
    while m > 0:
        j += m
        if f"{name}{separator}{j}".casefold() not in present_names:
            j -= m
        m >>= 1
    return f"{name}{separator}{j + 1}"


def subcell_label_name(net_name: NetName, labels: Collection[Label]) -> Optional[NetName]:
    """
    The name of the labels in subcells on a net of their parent, which KLayout named the net after,
    with the path of the subcircuit, as it flattens it (e.g. $1.D of the label D in the subcircuit $1, #330),
    or left unnamed, where the parent joins the net, whose empty name the flattening keeps (e.g. $I1)

    NOTE: like label_names_net, regardless of case and of a number that makes the name unique (e.g. $1.D$1),
          and of several labels, as KLayout names a net after all of them (e.g. A,B of $1.A,B or $1.A,$2.B),
          after each name once (e.g. VDD of the labels VDD of abutting cells)

    :param labels: the labels on the net
    :return: the name of the labels (e.g. D), None if the net has no such name,
             also if labels of its own circuit name it (e.g. bus.0, or $1)
    """
    folded_labels = {label.casefold() for label in labels}

    # NOTE: the name KLayout gives a net without a name (Net.expanded_name)
    if re.fullmatch(r'\$I?\d+', net_name):
        if not labels or net_name.casefold() in folded_labels:
            return None
        return ','.join(sorted(set(labels)))

    def label_of(part: str) -> Optional[Label]:
        # NOTE: the longest one, e.g. a.b of $1.a.b
        for start in [0, *(match.end() for match in re.finditer(r'\.', part))]:
            if part[start:].casefold() in folded_labels:
                return part[start:]
        return None

    parts = [re.sub(r'\$\d+$', '', part) for part in net_name.split(',')]
    part_labels = [label_of(part) for part in parts]
    if None in part_labels or part_labels == parts:
        return None
    return ','.join(part_labels)


def device_list(device_names: List[str]) -> str:
    """
    The first device names, for a message (e.g. 'M1, M2, M3 and 7 more')
    """
    listed = ', '.join(device_names[:3])
    return listed if len(device_names) <= 3 else f"{listed} and {len(device_names) - 3} more"


@dataclass
class KLayoutExtractedLayerInfo:
    index: int
    lvs_layer_name: LVSLayerName  # NOTE: this can be computed, so gds_pair is preferred
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
    # the devices are black-boxed (--blackbox), their models have their capacitances (see ComputedLayerInfo.Kind)
    blackbox_devices: bool
    # the names KLayout gave the nets named after labels in subcells, by their names
    # (see name_nets_after_subcell_labels)
    klayout_net_names: Dict[NetName, NetName] = field(default_factory=dict)
    # the labels on each net of the top circuit, of the whole hierarchy, by its name (see labels_of_nets)
    labels_by_net_name: Dict[NetName, Set[Label]] = field(default_factory=dict)
    # None allows labels of the whole hierarchy, otherwise only these top-level labels can be ports
    port_label_keys: Optional[Set[PortLabelKey]] = None
    # (device abstract cell index, terminal ID) -> shapes by LVS layer index, see shapes_of_terminal
    terminal_shapes_by_abstract: Dict[Tuple[int, int], Dict[int, kdb.Region]] = field(default_factory=dict,
                                                                                       init=False, repr=False)

    @classmethod
    def prepare_extraction(cls,
                           lvsdb: kdb.LayoutToNetlist,
                           top_cell: str,
                           tech: TechInfo,
                           blackbox_devices: bool,
                           source_top_cell: Optional[kdb.Cell] = None,
                           port_labels: str = 'auto') -> KLayoutExtractionContext:
        if port_labels not in PORT_LABEL_MODES:
            raise LVSDBError(f"Unknown port-label policy {port_labels!r}, choose from: {', '.join(PORT_LABEL_MODES)}")
        if port_labels == 'top' and source_top_cell is None:
            raise LVSDBError("The top port-label policy needs the original layout (--gds), "
                            "as the LVS database has flattened its labels")
        # NOTE: e.g. the abstract of a device the LVS script removed from the netlist is left as a top cell
        internal_top_cell = lvsdb.internal_top_cell()
        extra_top_cells = [c.name for c in lvsdb.internal_layout().top_cells()
                           if c.cell_index() != internal_top_cell.cell_index()]
        if extra_top_cells:
            warning(f"Ignoring the LVS database top cells besides {internal_top_cell.name}: "
                    f"{', '.join(extra_top_cells)}")

        cls.make_net_names_unique(lvsdb.netlist())
        labels_by_net_name = cls.labels_of_nets(lvsdb)
        klayout_net_names = cls.name_nets_after_subcell_labels(lvsdb, labels_by_net_name)
        new_net_names = {klayout_name: name for name, klayout_name in klayout_net_names.items()}
        labels_by_net_name = {new_net_names.get(name, name): labels for name, labels in labels_by_net_name.items()}

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

        context = KLayoutExtractionContext(
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
            unmodeled_layers=nonempty_layers.unmodeled_layers,
            blackbox_devices=blackbox_devices,
            klayout_net_names=klayout_net_names,
            labels_by_net_name=labels_by_net_name
        )
        context.select_port_labels(source_top_cell, port_labels)
        context.make_pins_of_pin_labels()

        # NOTE: a warning, as other tools (e.g. Magic, SPEF writers, commercial ones) make ports of the labels
        #       of the top cell only, and none drops the path of the subcell
        ports = sorted(name for name in klayout_net_names
                       if context.top_circuit.net_by_name(name).pin_count() > 0)
        if ports:
            warning(f"Ports named after labels in subcells: {', '.join(ports)} "
                    f"(label them in the top cell to name ports explicitly)")
        return context

    def select_port_labels(self, source_top_cell: Optional[kdb.Cell], policy: str):
        """
        Keeps ports of top-level labels, always for top, or for auto if the top has a pin label.
        Without the original layout, auto retains the labels of the whole hierarchy: the LVS database
        has flattened them and no longer records which cell they came from.
        Text-only labels preserve existing ports, but don't create ports of their own.
        """
        if source_top_cell is None:
            return
        source_layout = source_top_cell.layout()
        scale = kdb.ICplxTrans(source_layout.dbu / self.dbu)
        top_texts_by_layer: Dict[GDSPair, Set[Tuple[int, int, Label]]] = {}
        for gds_pair, _ in self.label_layers():
            if gds_pair in top_texts_by_layer:
                continue
            label_pair = self.tech.layer_info_by_gds_pair[gds_pair].label_gds_pair
            index = source_layout.find_layer(label_pair.layer, label_pair.datatype)
            texts: Set[Tuple[int, int, Label]] = set()
            if index is not None:
                for shape in source_top_cell.shapes(index).each(kdb.Shapes.STexts):
                    point = scale * shape.text.position()
                    texts.add((point.x, point.y, shape.text_string))
            top_texts_by_layer[gds_pair] = texts

        top_pins: List[pin_pb2.Pin] = []
        top_text_pins: List[pin_pb2.Pin] = []
        for by_layer, selected in ((self.pins_pb2_by_layer, top_pins),
                                   (self.text_label_pins_pb2_by_layer, top_text_pins)):
            for gds_pair, pins in by_layer.items():
                selected.extend(pin for pin in pins
                                if (pin.label_point.x, pin.label_point.y, pin.label) in top_texts_by_layer[gds_pair])
        if policy == 'auto' and not top_pins:
            return
        self.port_label_keys = {self.pin_label_key(pin) for pin in (*top_pins, *top_text_pins)}
        port_net_names = {pin.net_name for pin in (*top_pins, *top_text_pins)} | {self.substrate_net_name}
        for pin in list(self.top_circuit.each_pin()):
            if self.top_circuit.net_for_pin(pin.id()).name not in port_net_names:
                self.top_circuit.remove_pin(pin.id())

    @staticmethod
    def pin_label_key(pin: pin_pb2.Pin) -> PortLabelKey:
        return pin.layer.id, pin.label_point.x, pin.label_point.y, pin.label

    def pin_can_be_port(self, pin: pin_pb2.Pin) -> bool:
        return self.port_label_keys is None or self.pin_label_key(pin) in self.port_label_keys

    def make_pins_of_pin_labels(self):
        """
        Gives each net of the top circuit with a label on a pin shape a pin, if it has none,
        as KLayout's make_top_level_pins makes none for a net without devices (e.g. a wire between two pins)
        """
        circuit = self.top_circuit
        net_names = {pin.net_name for pins in self.pins_pb2_by_layer.values() for pin in pins
                     if pin.net_name and self.pin_can_be_port(pin)}
        for name in sorted(net_names):
            net = circuit.net_by_name(name)
            if net is not None and net.pin_count() == 0:
                circuit.connect_pin(circuit.create_pin(name), net)

    @staticmethod
    def make_net_names_unique(netlist: kdb.Netlist):
        """
        Names each net of a circuit uniquely, as KLayout's SPICE writer does (e.g. vss, vss$1),
        but regardless of case, as SPICE reads names (e.g. A, a$1)

        NOTE: nets can share a name, e.g. the metal islands of a supply, joined only in the parent
              (unless the LVS script connects them implicitly), but the extraction identifies a net by its name,
              and the annotated layout has the name on the shapes of the net (#211 §10)

        NOTE: a net without a label gets its expanded name (e.g. $2) as its name, as KLayout 0.30.4 reads it
              from the LVSDB without one (newer versions with the expanded name)
        """
        for circuit in netlist.each_circuit():
            names: Set[str] = set()  # NOTE: case-folded
            for net in list(circuit.each_net()):
                name = unique_name(net.expanded_name(), names)
                names.add(name.casefold())
                if name != net.name:
                    net.name = name

    @staticmethod
    def labels_of_nets(lvsdb: kdb.LayoutToNetlist) -> Dict[NetName, Set[Label]]:
        """
        The labels on each net of the top circuit, by its name, of the texts on its shapes

        NOTE: in one pass over the LVS layers with texts, rather than one for each net,
              as a large design has many nets (e.g. those without a name), and only these layers,
              as the other layers of a large net have many shapes
        """
        internal_top_cell = lvsdb.internal_top_cell()
        layout = kdb.Layout()
        layout.dbu = lvsdb.internal_layout().dbu
        top_cell = layout.create_cell(internal_top_cell.name)
        text_layers: LVSDBRegions = {}
        for layer_index in lvsdb.layer_indexes():
            texts = internal_top_cell.begin_shapes_rec(layer_index)
            texts.shape_flags = kdb.Shapes.STexts
            if not texts.at_end():
                text_layers[layout.layer()] = lvsdb.layer_by_index(layer_index)
        if not text_layers:
            return {}

        lvsdb.build_all_nets(cmap=lvsdb.cell_mapping_into(layout, top_cell, False),
                             target=layout,
                             lmap=text_layers,
                             hier_mode=kdb.LayoutToNetlist.BuildNetHierarchyMode.BNH_Flatten,
                             netname_prop='net',
                             circuit_cell_name_prefix=None,
                             net_cell_name_prefix=None,
                             device_cell_name_prefix=None)
        labels_by_net_name: Dict[NetName, Set[Label]] = defaultdict(set)
        for layer_index in text_layers:
            texts = top_cell.begin_shapes_rec(layer_index)
            texts.shape_flags = kdb.Shapes.STexts
            while not texts.at_end():
                labels_by_net_name[texts.shape().property('net')].add(texts.shape().text_string)
                texts.next()
        return labels_by_net_name

    @staticmethod
    def name_nets_after_subcell_labels(lvsdb: kdb.LayoutToNetlist,
                                       labels_by_net_name: Mapping[NetName, Set[Label]]) -> Dict[NetName, NetName]:
        """
        Names each net of the top circuit that KLayout named after labels in subcells (e.g. $1.D),
        or left unnamed, as the top cell joins them (e.g. $I1 of the labels VDD of abutting cells,
        see subcell_label_name), after the labels (D, VDD), so that its port is named like the pin of a schematic
        (#417), where that name is unique among the nets, regardless of case, as SPICE reads names,
        else it keeps its name (e.g. $1.D and $2.D of two instances of a cell, or $1.D beside a net D)

        A renamed net with devices gets a pin, if it has none (e.g. as it had no name), as KLayout's
        make_top_level_pins gives the named ones, so that it is a port (one without devices gets one of a pin label,
        see make_pins_of_pin_labels)

        NOTE: before the extraction takes the names (e.g. the annotated layout, see build_all_nets),
              so of the nets without a port too, as a pin label makes one later

        :param labels_by_net_name: the labels on each net (see labels_of_nets)
        :return: the names KLayout gave the renamed nets, by their new names
        """
        circuit = lvsdb.netlist().top_circuit()
        new_names: List[Tuple[kdb.Net, NetName]] = []
        for net in circuit.each_net():
            new_name = subcell_label_name(net.name, labels_by_net_name.get(net.name, ()))
            if new_name is not None:
                new_names.append((net, new_name))

        taken_names = {net.name.casefold() for net in circuit.each_net()}  # NOTE: case-folded
        counts = Counter(new_name.casefold() for _, new_name in new_names)
        klayout_net_names: Dict[NetName, NetName] = {}
        for net, new_name in new_names:
            if counts[new_name.casefold()] > 1 or new_name.casefold() in taken_names:
                continue
            klayout_net_names[new_name] = net.name
            for pin_ref in list(net.each_pin()):
                if circuit.pin_by_id(pin_ref.pin_id()).name() == net.name:
                    circuit.rename_pin(pin_ref.pin_id(), new_name)
            net.name = new_name
            if net.pin_count() == 0 and net.terminal_count() + net.subcircuit_pin_count() > 0:
                circuit.connect_pin(circuit.create_pin(new_name), net)
        return klayout_net_names

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

                if computed_layer_info.kind == tech_pb2.ComputedLayerInfo.Kind.KIND_DEVICE_INTERNAL:
                    continue  # NOTE: the device model has its resistance and capacitance

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

    @cached_property
    def shapes_by_net_name_by_lvs_layer(self) -> Dict[LVSLayerName, Dict[NetName, kdb.Region]]:
        """
        The shapes of each net on each extracted LVS layer
        (several of them can share a GDS pair, e.g. sky130A met3_cap and met3_ncap)

        NOTE: in one pass over the shapes of a layer, rather than one for each net,
              which is quadratic in the size of the layout (e.g. for the resistance extraction of each net)
        """
        shapes_by_net_name_by_lvs_layer: Dict[LVSLayerName, Dict[NetName, kdb.Region]] = {}

        for lyr in self.extracted_layers.values():
            if not lyr.source_layers:
                raise AssertionError('Internal error: Empty list of source_layers')
            for sl in lyr.source_layers:
                shapes_by_net_name: Dict[NetName, kdb.Region] = {}
                iter, transform = sl.region.begin_shapes_rec()
                while not iter.at_end():
                    shape = iter.shape()
                    net_name = shape.property('net')
                    shapes = shapes_by_net_name.get(net_name, None)
                    if shapes is None:
                        shapes = kdb.Region()
                        shapes.enable_properties()
                        shapes_by_net_name[net_name] = shapes
                    shapes.insert(transform *     # NOTE: this is a global/initial iterator-wide transformation
                                  iter.trans() *  # NOTE: this is local during the iteration (due to sub hierarchy)
                                  shape.polygon)
                    iter.next()
                shapes_by_net_name_by_lvs_layer[sl.lvs_layer_name] = shapes_by_net_name

        return shapes_by_net_name_by_lvs_layer

    def source_layers(self,
                      gds_pair: GDSPair,
                      lvs_layer_names: Optional[Collection[LVSLayerName]] = None) \
            -> List[KLayoutExtractedLayerInfo]:
        """
        The extracted LVS layers of a GDS pair

        :param lvs_layer_names: only these of them, default is all
        """
        lyr = self.extracted_layers.get(gds_pair, None)
        if not lyr:
            return []
        if lvs_layer_names is None:
            return lyr.source_layers
        return [sl for sl in lyr.source_layers if sl.lvs_layer_name in lvs_layer_names]

    def shapes_of_net(self,
                      gds_pair: GDSPair,
                      net: kdb.Net | NetName,
                      lvs_layer_names: Optional[Collection[LVSLayerName]] = None) -> Optional[kdb.Region]:
        """
        :param lvs_layer_names: only the shapes of these of the GDS pair's LVS layers, default is all of them
                                (e.g. a layer of the process stack sharing its GDS pair with another one)
        :return: a copy, as the caller may change it, None if the GDS pair has none of the LVS layers
        """
        source_layers = self.source_layers(gds_pair, lvs_layer_names)
        if not source_layers:
            return None

        requested_net_name = net.name if isinstance(net, kdb.Net) else net

        shapes = kdb.Region()
        shapes.enable_properties()
        for sl in source_layers:
            net_shapes = self.shapes_by_net_name_by_lvs_layer[sl.lvs_layer_name].get(requested_net_name, None)
            if net_shapes is not None:
                shapes += net_shapes
        return shapes

    def net_shapes_by_conductor_layer(self, net_name: NetName) -> Dict[LayerName, kdb.Region]:
        """
        :return: the shapes of the net by layer of the process stack (its diffusion and metal layers),
                 and by layer of its wells
        """
        LP = tech_pb2.LayerInfo.Purpose

        def is_well(layer_info: KLayoutExtractedLayerInfo) -> bool:
            return any(self.tech.computed_layer_info_by_name[source_layer.lvs_layer_name].layer_info.purpose
                       in (LP.PURPOSE_NWELL, LP.PURPOSE_PWELL, LP.PURPOSE_DNWELL)
                       for source_layer in layer_info.source_layers
                       if source_layer.lvs_layer_name in self.tech.computed_layer_info_by_name)

        well_gds_pairs = [gds_pair for gds_pair, layer_info in self.extracted_layers.items() if is_well(layer_info)]

        shapes_by_layer: Dict[LayerName, kdb.Region] = {}
        for gds_pair in [*self.tech.process_conductor_gds_pairs, *well_gds_pairs]:
            shapes = self.shapes_of_net(gds_pair, net_name)
            if shapes is not None and not shapes.is_empty():
                shapes_by_layer[self.tech.canonical_layer_name_by_gds_pair[gds_pair]] = shapes
        return shapes_by_layer

    def shapes_of_layer(self,
                        gds_pair: GDSPair,
                        mark_device_capacitor_plates: bool = False,
                        lvs_layer_names: Optional[Collection[LVSLayerName]] = None) -> Optional[kdb.Region]:
        """
        :param mark_device_capacitor_plates: give the shapes of the layers of KIND_DEVICE_CAPACITOR_PLATE
                                             (e.g. the fingers of a MOM cap) the property
                                             DEVICE_CAPACITOR_PLATE_PROPERTY, so that they are kept apart
                                             from the other shapes of their nets
        :param lvs_layer_names: only the shapes of these of the GDS pair's LVS layers, default is all of them
                                (e.g. a layer of the process stack sharing its GDS pair with another one)
        """
        source_layers = self.source_layers(gds_pair, lvs_layer_names)
        if not source_layers:
            return None

        def is_plate(sl: KLayoutExtractedLayerInfo) -> bool:
            return mark_device_capacitor_plates and \
                   self.tech.computed_layer_info_by_name[sl.lvs_layer_name].kind == \
                   tech_pb2.ComputedLayerInfo.Kind.KIND_DEVICE_CAPACITOR_PLATE

        shapes: kdb.Region

        match len(source_layers):
            case 1 if not is_plate(source_layers[0]):
                shapes = source_layers[0].region
            case _:
                # NOTE: currently a bug, for now use polygon-per-polygon workaround
                # shapes = kdb.Region()
                # for sl in source_layers:
                #     shapes += sl.region
                shapes = kdb.Region()
                shapes.enable_properties()
                for sl in source_layers:
                    plate_properties = {DEVICE_CAPACITOR_PLATE_PROPERTY: True} if is_plate(sl) else {}
                    iter, transform = sl.region.begin_shapes_rec()
                    while not iter.at_end():
                        p = kdb.PolygonWithProperties(iter.shape().polygon,
                                                      {'net': iter.shape().property('net'), **plate_properties})
                        shapes.insert(transform *     # NOTE: this is a global/initial iterator-wide transformation
                                      iter.trans() *  # NOTE: this is local during the iteration (due to sub hierarchy)
                                      p)
                        iter.next()

        return shapes

    def pins_of_layer(self, gds_pair: GDSPair) -> kdb.Region:
        pin_gds_pair = self.tech.layer_info_by_gds_pair[gds_pair].pin_gds_pair
        pin_gds_pair = pin_gds_pair.layer, pin_gds_pair.datatype
        # NOTE: the pin layer can have several LVS layers, where it's the drawn layer
        #       (e.g. gf180mcuD, without pin layers, with Metal4 split under the MIM caps)
        pins = self.shapes_of_layer(pin_gds_pair)
        if pins is None:
            return kdb.Region()
        return pins

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
    def substrate_net_name(self) -> str:
        """
        The net the capacitances to the substrate go to: the substrate net of the LVS netlist,
        by a name of the tech info (e.g. sky130_gnd), or by a shape on its LVS layers,
        when a label names it otherwise (e.g. VSS, through the taps), else the first name,
        for a port of its own (e.g. a metal test pattern without taps or transistors)
        """
        substrate = self.tech.tech.substrate
        for name in substrate.net_names:
            if self.top_circuit.net_by_name(name) is not None:
                return name

        lvs_layer_names = set(self.lvsdb.layer_names())
        for lvs_layer_name in substrate.lvs_layer_names:
            if lvs_layer_name not in lvs_layer_names:
                continue
            region = self.lvsdb.layer_by_name(lvs_layer_name)
            if region.is_empty():
                continue
            # NOTE: a point within the first shape, the vertices of a trapezoid surround their average
            trapezoid = next(iter(region.each())).decompose_trapezoids()[0]
            points = list(trapezoid.each_point())
            point = kdb.Point(sum(p.x for p in points) // len(points), sum(p.y for p in points) // len(points))
            subcircuit_path: List[kdb.SubCircuit] = []
            net = self.lvsdb.probe_net(region, point, subcircuit_path)
            # NOTE: the net of the shape may be within a subcircuit, the substrate is a pin of it
            for subcircuit in reversed(subcircuit_path):
                pins = list(net.each_pin()) if net is not None else []
                net = subcircuit.net_for_pin(pins[0].pin_id()) if pins else None
            if net is not None:
                return net.expanded_name()

        return substrate.net_names[0] if substrate.net_names else self.tech.internal_substrate_layer_name

    @cached_property
    def terminal_refs(self) -> Dict[Tuple[int, int], List[kdb.NetTerminalRef]]:
        """
        The references of the device terminals by (device ID, terminal ID)

        NOTE: in one pass over the nets, rather than one over the terminals of its net for each terminal,
              which is quadratic in the size of a net (e.g. the bulk terminals on a supply)
        """
        terminal_refs: Dict[Tuple[int, int], List[kdb.NetTerminalRef]] = defaultdict(list)
        for net in self.top_circuit.each_net():
            for nt in net.each_terminal():
                terminal_refs[(nt.device().id(), nt.terminal_id())].append(nt)
        return terminal_refs

    @cached_property
    def mos_channels(self) -> kdb.Region:
        """
        The channels of the MOS transistors, the shapes of their gate terminals on the gate poly
        (over the active area), whose capacitances (of the gate oxide, the overlap and the fringe)
        the transistor models have (#290)

        NOTE: by the shapes on the gate poly, as the device class doesn't tell
              (e.g. sky130A reads VPP caps with 4 terminals as MOS4, whose terminals are on the metal)
        """
        gate_poly_gds_pair = self.tech.gds_pair(self.tech.gate_poly_layer.name)
        channels = kdb.Region()
        for device in self.top_circuit.each_device():
            device_class = device.device_class()
            if not isinstance(device_class, kdb.DeviceClassMOS3Transistor):
                continue
            for nt in self.terminal_refs[(device.id(), device_class.terminal_id('G'))]:
                for layer_index, shapes in self.shapes_of_terminal(device, nt).items():
                    if self.tech.gds_pair_for_computed_layer_name.get(self.lvsdb.layer_name(layer_index)) == \
                            gate_poly_gds_pair:
                        channels += shapes
        return channels.merged()

    def shapes_of_terminal(self, device: kdb.Device, nt: kdb.NetTerminalRef) -> Dict[int, kdb.Region]:
        """
        The shapes of a device terminal by LVS layer index, like LayoutToNetlist.shapes_of_terminal

        NOTE: LayoutToNetlist.shapes_of_terminal takes long (e.g. 0.1 s for each terminal of gcd, sky130A),
              so the shapes of each terminal of a device abstract are taken once, and moved to each device of it,
              but for a device of several abstracts (combined devices), or a non-orthogonal or magnifying placement
        """
        trans = kdb.ICplxTrans(device.trans, self.dbu)
        if any(True for _ in device.each_combined_abstract()) or not trans.is_ortho() or trans.is_mag():
            return self.lvsdb.shapes_of_terminal(nt)
        key = (device.device_abstract.cell_index(), nt.terminal_id())
        shapes_by_lyr_idx = self.terminal_shapes_by_abstract.get(key, None)
        if shapes_by_lyr_idx is None:
            shapes_by_lyr_idx = self.lvsdb.shapes_of_terminal(nt, trans.inverted())  # of the abstract
            self.terminal_shapes_by_abstract[key] = shapes_by_lyr_idx
        return {idx: shapes.transformed(trans) for idx, shapes in shapes_by_lyr_idx.items()}

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
        # (device class, terminal) -> device names
        devices_by_unconnected_terminal: Dict[Tuple[str, str], List[str]] = defaultdict(list)

        terminal_refs = self.terminal_refs

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
                n: Optional[kdb.Net] = d_kly.net_for_terminal(td.id())
                if n is None:
                    # NOTE: the LVS netlist leaves the terminal unconnected, as its shapes touch no conductor
                    #       (e.g. the bulk of a sky130A varactor without a ptap ring around it),
                    #       so the RC netlist leaves it unconnected too
                    devices_by_unconnected_terminal[(d.device_class_name, td.name)].append(d.device_name)
                    continue
                net_name = n.name or f"${n.cluster_id}"

                for nt in terminal_refs[(d_kly.id(), td.id())]:
                    shapes_by_lyr_idx = self.shapes_of_terminal(d_kly, nt)

                    terminal = d.terminals.add()
                    terminal.device_id = d.id
                    terminal.terminal_id = td.id()
                    terminal.name = td.name
                    terminal.net_name = net_name

                    def add_region(gds_pair: GDSPair, region: kdb.Region):
                        region_by_layer = terminal.region_by_layer.add()
                        # NOTE: the annotated layout has a layer for each LVS layer, so several for a GDS pair
                        #       (e.g. poly_con and poly_vpp), but the resistance extraction has the wires
                        #       of a GDS pair on one of them, so the terminal must be on that one to be a port
                        region_by_layer.layer.id = self.annotated_layout.layer(*gds_pair)
                        region_by_layer.layer.canonical_layer_name = self.tech.canonical_layer_name_by_gds_pair[gds_pair]
                        shapes_converter.klayout_region_to_pb(region, region_by_layer.region)

                    for idx, shapes in shapes_by_lyr_idx.items():
                        lyr_idx = self.layer_index_map.get(idx, None)
                        if lyr_idx is None:
                            # NOTE: the tech info has no layer for the LVS layer of the terminal
                            #       (e.g. the ports of a MOM cap, the metal pins within its marker),
                            #       so the terminal is where it overlaps or abuts a conductor of its net,
                            #       which LVS connected it to (e.g. the metal of the pins)
                            gds_pair_and_region = self.terminal_region_on_net(shapes, net_name)
                            if gds_pair_and_region is None:
                                key = (d.device_class_name, td.name, self.lvsdb.layer_name(idx))
                                devices_by_unknown_terminal_layer[key].append(d.device_name)
                            else:
                                add_region(*gds_pair_and_region)
                            continue

                        lyr_info: kdb.LayerInfo = self.annotated_layout.layer_infos()[lyr_idx]
                        add_region((lyr_info.layer, lyr_info.datatype), shapes)

            dd[d.device_name] = d

        if devices_by_unconnected_terminal:
            warning("These device terminals are unconnected in the LVS netlist, "
                    "so they stay unconnected in the extracted netlist:\n" +
                    '\n'.join(f"  - {device_class} terminal {terminal}: {device_list(device_names)}"
                              for (device_class, terminal), device_names
                              in sorted(devices_by_unconnected_terminal.items())))

        # NOTE: a terminal without a node stays on its net, which a node of the resistance network carries
        #       (#211 §6), so it misses only the resistance to where it is
        if devices_by_unknown_terminal_layer:
            warning("The resistance network has no nodes for these device terminals, "
                    "as the tech info has no layer for their LVS layer, "
                    "and they neither overlap nor abut a conductor of their net "
                    "(e.g. a terminal on the substrate or a well):\n" +
                    '\n'.join(f"  - {device_class} terminal {terminal} on LVS layer {lvs_layer}: "
                              f"{device_list(device_names)}"
                              for (device_class, terminal, lvs_layer), device_names
                              in sorted(devices_by_unknown_terminal_layer.items())))

        return dd

    def terminal_region_on_net(self,
                               terminal_shapes: kdb.Region,
                               net_name: str) -> Optional[Tuple[GDSPair, kdb.Region]]:
        """
        :return: the part of the terminal shapes on the conductor of its net they overlap most,
                 the lowest of equals, else the strip of 1 dbu of the conductor of its net they abut most
                 (e.g. the ports of an IHP inductor, within its marker, at the ends of their leads outside it,
                 which LVS joins by a pin layer over both), or None if they neither overlap nor abut
                 a conductor of their net

        NOTE: one conductor, as the ports of a terminal are one node, which would short the resistance
              between the conductors (e.g. a pin on the top metal of a MOM cap, over the fingers below)
        """
        lvsdb_layer_indexes = self.lvsdb.layer_indexes()
        bbox = terminal_shapes.bbox()
        net_shapes_by_gds_pair: Dict[GDSPair, kdb.Region] = {}
        for gds_pair in self.tech.process_conductor_gds_pairs:
            lyr = self.extracted_layers.get(gds_pair, None)
            if lyr is None:
                continue
            net_shapes = kdb.Region()
            for sl in lyr.source_layers:
                computed_layer_info = self.tech.computed_layer_info_by_name[sl.lvs_layer_name]
                if computed_layer_info.kind == tech_pb2.ComputedLayerInfo.Kind.KIND_PIN:
                    continue
                annotated_layer_index = self.layer_index_map[lvsdb_layer_indexes[sl.index]]
                # NOTE: the shapes near the terminal only, the net may be huge (e.g. a supply)
                iter = self.annotated_top_cell.begin_shapes_rec_touching(annotated_layer_index, bbox)
                while not iter.at_end():
                    shape = iter.shape()
                    if shape.property('net') == net_name and not shape.is_text():
                        net_shapes.insert(iter.trans() * shape.polygon)
                    iter.next()
            net_shapes_by_gds_pair[gds_pair] = net_shapes

        def largest_overlap(shapes: kdb.Region) -> Optional[Tuple[GDSPair, kdb.Region]]:
            best: Optional[Tuple[float, GDSPair, kdb.Region]] = None
            for gds_pair, net_shapes in net_shapes_by_gds_pair.items():
                overlap = shapes & net_shapes
                area = overlap.area()
                if area > 0 and (best is None or area > best[0]):
                    best = (area, gds_pair, overlap)
            return None if best is None else (best[1], best[2])

        return largest_overlap(terminal_shapes) or largest_overlap(terminal_shapes.sized(1))

    def label_layers(self) -> Iterator[Tuple[GDSPair, KLayoutExtractedLayerInfo]]:
        """
        Each drawn layer of the tech info, of the labels (see labels_of_layer), with each of its extracted LVS layers,
        which the pins of the labels are on (see pin_pb2)
        """
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
                yield gds_pair, lyr

    def pin_pb2(self, label: kdb.Text, net_name: Optional[NetName], lyr: KLayoutExtractedLayerInfo) -> pin_pb2.Pin:
        """
        The label as a pin of the net, on the layer of the LVS layer
        """
        # NOTE: because we want more like a point as a junction
        #       and folx create huge pins (covering the whole metal)
        #       we create our own "mini squares"
        #    (ResistorExtractor will subtract the pins from the metal polygons,
        #     so in the extreme case the polygons could become empty)

        pin = pin_pb2.Pin()
        pin.label = label.string
        if net_name is not None:
            pin.net_name = net_name

        pos = label.position()

        canonical_layer_name = self.tech.canonical_layer_name_by_gds_pair[lyr.gds_pair]
        lvs_layer_name = self.tech.computed_layer_info_by_gds_pair[lyr.gds_pair].layer_info.name
        pin.layer.id = self.annotated_layout.layer(*lyr.gds_pair)
        pin.layer.canonical_layer_name = canonical_layer_name
        pin.layer.lvs_layer_name = lvs_layer_name

        pin.label_point.x = pos.x
        pin.label_point.y = pos.y
        pin.label_point.net = pin.net_name
        return pin

    @cached_property
    def pins_pb2_by_layer(self) -> Dict[GDSPair, List[pin_pb2.Pin]]:
        """
        The labels on pin shapes, as pins of the nets of the pin shapes
        """
        d = defaultdict(list)

        for gds_pair, lyr in self.label_layers():
            pins = self.pins_of_layer(gds_pair)
            labels = self.labels_of_layer(gds_pair)

            # NOTE: the pins at a label are found by their boxes, rather than by going through all pins
            #       for each label, which is quadratic in the number of pins (e.g. the ones of standard cells)
            pin_polygons: List[kdb.PolygonWithProperties] = list(pins.each())
            pin_boxes = kdb.Shapes()
            for pin_index, p in enumerate(pin_polygons):
                pin_boxes.insert(kdb.BoxWithProperties(p.bbox(), {'pin_index': pin_index}))

            pin_labels: kdb.Texts = labels & pins
            for l in pin_labels:
                l: kdb.Text
                pos = l.position()

                # NOTE: the first pin the label is inside of
                net_name: Optional[NetName] = None
                for pin_index in sorted(shape.property('pin_index')
                                        for shape in pin_boxes.each_touching(kdb.Shapes.SAll, kdb.Box(pos, pos))):
                    p = pin_polygons[pin_index]
                    if p.inside(pos):
                        net_name = p.property('net')
                        break

                d[gds_pair].append(self.pin_pb2(l, net_name, lyr))

        return d

    @cached_property
    def text_label_pins_pb2_by_layer(self) -> Dict[GDSPair, List[pin_pb2.Pin]]:
        """
        The labels without a pin shape (text labels) on metal, as pins of the nets of the metal they are on

        NOTE: a text label names its net, but makes no port of it (see make_pins_of_pin_labels),
              like a label of the text layer of Magic (e.g. MET1TXT of sky130A), rather than of its pin layer

        NOTE: on metal only: a label on a well joins it to its net by its name rather than at the label
              (e.g. VPB of a standard cell), so the well is ideal there (see RExtractor.isolated_well_node_ids)
        """
        d = defaultdict(list)

        for gds_pair, lyr in self.label_layers():
            if self.tech.layer_info_by_gds_pair[gds_pair].purpose != tech_pb2.LayerInfo.Purpose.PURPOSE_METAL:
                continue
            labels = self.labels_of_layer(gds_pair)
            pins = self.pins_of_layer(gds_pair)
            # NOTE: KLayout 0.30.12 takes out all texts, rather than none, where there are no polygons to take out
            text_labels: kdb.Texts = labels if pins.is_empty() else labels - pins
            for l in text_labels:
                l: kdb.Text
                d[gds_pair].append(self.pin_pb2(l, self.net_at(gds_pair, l.position()), lyr))

        return d

    def net_at(self, gds_pair: GDSPair, point: kdb.Point) -> Optional[NetName]:
        """
        :return: the net of the shape of the GDS pair that the point is inside of (e.g. of the metal at a label),
                 as the shapes of the layer have it (see shapes_of_layer), None if there is none

        NOTE: by the shapes at the point, rather than by going through all shapes of the layer,
              which a large layout has millions of
        """
        lvsdb_layer_indexes = self.lvsdb.layer_indexes()
        for sl in self.source_layers(gds_pair):
            annotated_layer_index = self.layer_index_map[lvsdb_layer_indexes[sl.index]]
            iter = self.annotated_top_cell.begin_shapes_rec_touching(annotated_layer_index, kdb.Box(point, point))
            while not iter.at_end():
                shape = iter.shape()
                if not shape.is_text() and (iter.trans() * shape.polygon).inside(point):
                    return shape.property('net')
                iter.next()
        return None
