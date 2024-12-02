#! /usr/bin/env python3
from collections import defaultdict
from dataclasses import dataclass
from typing import *

import klayout.db as kdb
from rich.region import Region

from ..klayout.lvsdb_extractor import KLayoutExtractionContext, KLayoutExtractedLayerInfo, GDSPair
from ..log import (
    console,
    debug,
    info,
    warning,
    error
)
from ..tech_info import TechInfo

import process_stack_pb2


NetName = str
LayerName = str


class RCExtractor:
    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 tech_info: TechInfo):
        self.pex_context = pex_context
        self.tech_info = tech_info

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

    def extract(self):
        lvsdb = self.pex_context.lvsdb
        netlist: kdb.Netlist = lvsdb.netlist()
        dbu = self.pex_context.dbu

        def format_terminal(t: kdb.NetTerminalRef) -> str:
            td = t.terminal_def()
            d = t.device()
            return f"{d.expanded_name()}/{td.name}/{td.description}"

        circuit = netlist.circuit_by_name(self.pex_context.top_cell.name)
        # https://www.klayout.de/doc-qt5/code/class_Circuit.html
        if not circuit:
            circuits = [c.name for c in netlist.each_circuit()]
            raise Exception(f"Expected circuit called {self.pex_context.top_cell.name} in extracted netlist, "
                            f"only available circuits are: {circuits}")

        # determine regions
        # __________________
        # for all nets
        #    for all layers
        #       region
        layer2net2regions = defaultdict(dict)
        net2layer2regions = defaultdict(dict)
        layer_by_name: Dict[LayerName, process_stack_pb2.ProcessStackInfo.LayerInfo] = {}

        layer_regions_by_name: Dict[LayerName, kdb.Region] = {}
        all_region = kdb.Region()

        for metal_layer in self.tech_info.process_metal_layers:
            layer_name = metal_layer.name
            all_layer_shapes = self.shapes_of_layer(layer_name) or kdb.Region()
            layer_regions_by_name[layer_name] = all_layer_shapes
            all_region += all_layer_shapes

            for net in circuit.each_net():
                net_name = net.expanded_name()

                shapes = self.shapes_of_net(layer_name=layer_name, net=net)
                if shapes:
                    gds_pair = self.gds_pair(layer_name)
                    canonical_layer_name = self.tech_info.layer_info_by_gds_pair.get(gds_pair).name
                    layer2net2regions[canonical_layer_name][net_name] = shapes
                    net2layer2regions[net_name][canonical_layer_name] = shapes
                    layer_by_name[canonical_layer_name] = metal_layer

        for net in circuit.each_net():
            # https://www.klayout.de/doc-qt5/code/class_Net.html
            debug(f"Net name={net.name}, expanded_name={net.expanded_name()}, pin_count={net.pin_count()}, "
                  f"is_floating={net.is_floating()}, is_passive={net.is_passive()}, "
                  f"terminals={list(map(lambda t: format_terminal(t), net.each_terminal()))}")

            net_name = net.expanded_name()

            layer2regions = net2layer2regions.get(net_name, None)
            if not layer2regions:
                continue

            for layer_name in layer2regions.keys():
                shapes: Optional[kdb.Region] = layer2regions.get(layer_name, None)
                if shapes:
                    if shapes.count() >= 1:
                        substrate_cap_spec = self.tech_info.substrate_cap_by_layer_name.get(layer_name, None)
                        if not substrate_cap_spec:
                            warning(f"No substrate cap specified for layer {layer_name}")
                            continue

                        area_shapes_unshielded = shapes.dup()
                        for shielding_layer_name, shielding_region in layer_regions_by_name.items():
                            if layer_name == shielding_layer_name:
                                break
                            area_shapes_unshielded -= shielding_region

                        # (1) SUBSTRATE CAPACITANCE
                        # area caps ... aF/µm^2
                        # perimeter / sidewall ... aF/µm

                        area = area_shapes_unshielded.area() * dbu**2         # in µm^2
                        perimeter = shapes.perimeter() * dbu  # in µm

                        cap_area_femto = area * substrate_cap_spec.area_capacitance / 1000
                        cap_perimeter_femto = perimeter * substrate_cap_spec.perimeter_capacitance / 1000

                        info(f"net {net_name} layer {layer_name}: "
                             f"area {area} µm^2, perimeter {perimeter}, "
                             f"cap_area {round(cap_area_femto, 2)}fF, "
                             f"cap_peri {round(cap_perimeter_femto, 2)}fF, "
                             f"sum {round(cap_area_femto + cap_perimeter_femto, 2)}fF")

                        # TODO: shielding of layers below
                        #  - hinders area
                        #  - hinders fringe / perimeter ... which "halo"?

        #
        # (2) OVERLAP CAPACITANCE
        #
        # TODO

        space_markers = all_region.space_check(
            round(self.tech_info.tech.extraction.side_halo / dbu),  # min space in um
            True,  # whole edges
            kdb.Metrics.Projection,  # metrics
            None,  # ignore angle
            None,  # min projection
            None,  # max projection
            True,  # shielding
            kdb.Region.NoOppositeFilter,  # error filter for opposite sides
            kdb.Region.NoRectFilter,  # error filter for rect input shapes
            False,  # negative
            kdb.Region.IgnoreProperties,  # property_constraint
            kdb.Region.IncludeZeroDistanceWhenTouching  # zero distance mode
        )

        for layer_name in layer2net2regions.keys():
            # (3) SIDEWALL CAPACITANCE
            #
            sidewall_cap_spec = self.tech_info.sidewall_cap_by_layer_name.get(layer_name, None)
            if not sidewall_cap_spec:
                warning(f"No substrate cap specified for layer {layer_name}")
                continue

            # layer_thickness = layer_by_name[layer_name].metal_layer.thickness

            net2regions = layer2net2regions.get(layer_name, None)
            if not net2regions:
                continue

            for i, net1 in enumerate(net2regions.keys()):
                for j, net2 in enumerate(net2regions.keys()):
                    if i < j:

                        # info(f"Sidewall on {layer_name}: Nets {net1} <-> {net2}")
                        shapes1: kdb.Region = net2regions[net1]
                        shapes2: kdb.Region = net2regions[net2]

                        markers_net1 = space_markers.interacting(shapes1)
                        sidewall_edge_pairs = markers_net1.interacting(shapes2)

                        info(sidewall_edge_pairs)
                        for pair in sidewall_edge_pairs:
                            edge1: kdb.Edge = pair.first
                            edge2: kdb.Edge = pair.second

                            avg_length = (edge1.length() + edge2.length()) / 2
                            avg_distance = (pair.polygon(0).perimeter() - edge1.length() - edge2.length()) / 2

                            debug(f"Edge pair distance {avg_distance}, symmetric? {pair.symmetric}, "
                                 f"perimeter {pair.perimeter()}, parallel? {edge1.is_parallel(edge2)}")

                            # (3) SIDEWALL CAPACITANCE
                            #
                            # C = Csidewall * l * t / s
                            # C = Csidewall * l / s

                            cap_femto = (avg_length * dbu * sidewall_cap_spec.capacitance) / \
                                        (avg_distance * dbu + sidewall_cap_spec.offset) / 1000

                            info(f"Sidewall on {layer_name}: Nets {net1} <-> {net2}: {round(cap_femto, 2)}fF")

