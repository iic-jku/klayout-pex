#! /usr/bin/env python3
import math
from asyncio import shield
from collections import defaultdict
from dataclasses import dataclass, field
from rich import pretty
from typing import *

import klayout.db as kdb
import klayout.rdb as rdb

import process_parasitics_pb2
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
CellName = str


CoupleKey = Tuple[NetName, NetName]

EdgeInterval = Tuple[float, float]
ChildIndex = int
EdgeNeighborhood = List[Tuple[EdgeInterval, Dict[ChildIndex, List[kdb.Polygon]]]]


@dataclass
class NodeRegion:
    layer_name: LayerName
    net_name: NetName
    cap_to_gnd: float
    perimeter: float
    area: float


@dataclass(frozen=True)
class SidewallKey:
    layer: LayerName
    net1: NetName
    net2: NetName


@dataclass
class SidewallCap:  # see Magic EdgeCap, extractInt.c L444
    key: SidewallKey
    cap_value: float   # femto farad
    distance: float    # distance in µm
    length: float      # length in µm
    tech_spec: process_parasitics_pb2.CapacitanceInfo.SidewallCapacitance


@dataclass(frozen=True)
class OverlapKey:
    layer_top: LayerName
    net_top: NetName
    layer_bot: LayerName
    net_bot: NetName


@dataclass
class OverlapCap:
    key: OverlapKey
    cap_value: float  # femto farad
    shielded_area: float  # in µm^2
    unshielded_area: float  # in µm^2
    tech_spec: process_parasitics_pb2.CapacitanceInfo.OverlapCapacitance


@dataclass(frozen=True)
class SideOverlapKey:
    layer_inside: LayerName
    net_inside: NetName
    layer_outside: LayerName
    net_outside: NetName


@dataclass
class SideOverlapCap:
    key: SideOverlapKey
    cap_value: float  # femto farad


@dataclass
class CellExtractionResults:
    cell_name: CellName
    # node_regions: Dict[NetName, NodeRegion] = field(default_factory=dict)
    overlap_coupling: Dict[OverlapKey, OverlapCap] = field(default_factory=dict)
    sidewall_table: Dict[SidewallKey, SidewallCap] = field(default_factory=dict)
    sideoverlap_table: Dict[SideOverlapKey, SideOverlapCap] = field(default_factory=dict)


@dataclass
class ExtractionResults:
    cell_extraction_results: Dict[CellName, CellExtractionResults] = field(default_factory=dict)


class RCExtractor:
    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 tech_info: TechInfo,
                 report_path: str):
        self.pex_context = pex_context
        self.tech_info = tech_info
        self.report_path = report_path

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

    def extract(self) -> ExtractionResults:
        extraction_results = ExtractionResults()

        # TODO: for now, we always flatten and have only 1 cell
        cell_name = self.pex_context.top_cell.name
        report = rdb.ReportDatabase(f"PEX {cell_name}")
        cell_extraction_result = self.extract_cell(cell_name=cell_name, report=report)
        extraction_results.cell_extraction_results[cell_name] = cell_extraction_result

        report.save(self.report_path)

        return extraction_results

    def extract_cell(self,
                     cell_name: CellName,
                     report: rdb.ReportDatabase) -> CellExtractionResults:
        lvsdb = self.pex_context.lvsdb
        netlist: kdb.Netlist = lvsdb.netlist()
        dbu = self.pex_context.dbu

        extraction_results = CellExtractionResults(cell_name=cell_name)

        rdb_cell = report.create_cell(cell_name)
        rdb_cat_common = report.create_category("Common")
        rdb_cat_sidewall = report.create_category("Sidewall")
        rdb_cat_overlap = report.create_category("Overlap")
        rdb_cat_fringe = report.create_category("Fringe / Side Overlap")
        rdb_cat_substrate = report.create_category("Substrate")
        def rdb_output(parent_category: rdb.RdbCategory,
                       category_name: str,
                       shapes: kdb.Shapes):
            rdb_cat = report.create_category(parent_category, category_name)
            report.create_items(rdb_cell.rdb_id(),  ## TODO: if later hierarchical mode is introduced
                                rdb_cat.rdb_id(),
                                kdb.CplxTrans(mag=dbu),
                                shapes)

        circuit = netlist.circuit_by_name(self.pex_context.top_cell.name)
        # https://www.klayout.de/doc-qt5/code/class_Circuit.html
        if not circuit:
            circuits = [c.name for c in netlist.each_circuit()]
            raise Exception(f"Expected circuit called {self.pex_context.top_cell.name} in extracted netlist, "
                            f"only available circuits are: {circuits}")

        #----------------------------------------------------------------------------------------
        layer2net2regions = defaultdict(lambda: defaultdict(kdb.Region))
        net2layer2regions = defaultdict(lambda: defaultdict(kdb.Region))
        layer_by_name: Dict[LayerName, process_stack_pb2.ProcessStackInfo.LayerInfo] = {}

        layer_regions_by_name: Dict[LayerName, kdb.Region] = defaultdict(kdb.Region)
        all_region = kdb.Region()
        regions_below_layer: Dict[LayerName, kdb.Region] = defaultdict(kdb.Region)
        regions_below_and_including_layer: Dict[LayerName, kdb.Region] = defaultdict(kdb.Region)
        all_layer_names: List[LayerName] = []
        layer_names_below: Dict[LayerName, List[LayerName]] = {}
        shielding_layer_names: Dict[Tuple[LayerName, LayerName], List[LayerName]] = defaultdict(list)
        previous_layer_name: Optional[str] = None
        for metal_layer in self.tech_info.process_metal_layers:
            layer_name = metal_layer.name
            gds_pair = self.gds_pair(layer_name)
            canonical_layer_name = self.tech_info.canonical_layer_name_by_gds_pair[gds_pair]

            all_layer_shapes = self.shapes_of_layer(layer_name) or kdb.Region()
            layer_regions_by_name[canonical_layer_name] += all_layer_shapes
            # NOTE: multiple LVS layers can be mapped to the same canonical name
            if previous_layer_name != canonical_layer_name:
                regions_below_layer[canonical_layer_name] += all_region
                layer_names_below[canonical_layer_name] = list(all_layer_names)
                for ln in all_layer_names:
                    lp = (canonical_layer_name, ln)
                    shielding_layer_names[lp] = [l for l in all_layer_names
                                                 if l != ln and l not in layer_names_below[ln]]
                    shielding_layer_names[ln, canonical_layer_name] = shielding_layer_names[lp]
                all_layer_names.append(canonical_layer_name)
            all_region += all_layer_shapes
            regions_below_and_including_layer[canonical_layer_name] += all_region

            previous_layer_name = canonical_layer_name

            for net in circuit.each_net():
                net_name = net.expanded_name()

                shapes = self.shapes_of_net(layer_name=layer_name, net=net)
                if shapes:
                    layer2net2regions[canonical_layer_name][net_name] += shapes
                    net2layer2regions[net_name][canonical_layer_name] += shapes
                    layer_by_name[canonical_layer_name] = metal_layer

        shielded_regions_between_layers: Dict[Tuple[LayerName, LayerName], kdb.Region] = {}
        for top_layer_name in layer2net2regions.keys():
            for bot_layer_name in reversed(layer_names_below[top_layer_name]):
                shielded_region = kdb.Region()
                shielding_layers = shielding_layer_names.get((top_layer_name, bot_layer_name), None)
                if shielding_layers:
                    for sl in shielding_layers:
                        shielded_region += layer_regions_by_name[sl]
                shielded_region.merge()
                shielded_regions_between_layers[(top_layer_name, bot_layer_name)] = shielded_region
                shielded_regions_between_layers[(bot_layer_name, top_layer_name)] = shielded_region
                if shielded_region:
                    rdb_output(rdb_cat_common, f"Shielded ({top_layer_name}-{bot_layer_name})", shielded_region)

        #----------------------------------------------------------------------------------------

        side_halo_um = self.tech_info.tech.process_parasitics.side_halo
        side_halo_dbu = int(side_halo_um / dbu) + 1  # add 1 nm to halo

        space_markers = all_region.space_check(
            int(side_halo_um / dbu),  # min space in um
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

        rdb_output(rdb_cat_sidewall, "All Space Markers", space_markers)

        #
        # (1) OVERLAP CAPACITANCE
        #
        for top_layer_name in layer2net2regions.keys():
            top_net2regions = layer2net2regions.get(top_layer_name, None)
            if not top_net2regions:
                continue

            top_overlap_specs = self.tech_info.overlap_cap_by_layer_names.get(top_layer_name, None)
            if not top_overlap_specs:
                warning(f"No overlap cap specified for layer top={top_layer_name}")
                continue

            rdb_cat_top_layer = report.create_category(rdb_cat_overlap, f"top_layer={top_layer_name}")

            shapes_top_layer = layer_regions_by_name[top_layer_name]

            for bot_layer_name in reversed(layer_names_below[top_layer_name]):
                bot_net2regions = layer2net2regions.get(bot_layer_name, None)
                if not bot_net2regions:
                    continue

                overlap_cap_spec = top_overlap_specs.get(bot_layer_name, None)
                if not overlap_cap_spec:
                    warning(f"No overlap cap specified for layer top={top_layer_name}/bottom={bot_layer_name}")
                    continue

                rdb_cat_bot_layer = report.create_category(rdb_cat_top_layer, f"bot_layer={bot_layer_name}")

                shielded_region = shielded_regions_between_layers[(top_layer_name, bot_layer_name)]
                rdb_output(rdb_cat_bot_layer, "shielded_region", shielded_region)

                for net_top in top_net2regions.keys():
                    shapes_top_net: kdb.Region = top_net2regions[net_top].dup()

                    for net_bot in bot_net2regions.keys():
                        shapes_bot_net: kdb.Region = bot_net2regions[net_bot]

                        overlapping_shapes = shapes_top_net.__and__(shapes_bot_net)
                        if overlapping_shapes:
                            rdb_cat_nets = report.create_category(rdb_cat_bot_layer, f"{net_top} {net_bot}")
                            rdb_output(rdb_cat_nets, "overlapping_shapes", overlapping_shapes)

                            shielded_net_shapes = overlapping_shapes.__and__(shielded_region)
                            rdb_output(rdb_cat_nets, "shielded_net_shapes", shielded_net_shapes)

                            area_um2 = overlapping_shapes.area() * dbu**2
                            shielded_area_um2 = shielded_net_shapes.area() * dbu**2
                            unshielded_area_um2 = area_um2 - shielded_area_um2
                            cap_femto = unshielded_area_um2 * overlap_cap_spec.capacitance / 1000.0
                            info(f"(Overlap) layers {top_layer_name}-{bot_layer_name}: "
                                 f"Nets {net_top} <-> {net_bot}: {unshielded_area_um2} µm^2, "
                                 f"cap: {round(cap_femto, 2)} fF")
                            ovk = OverlapKey(layer_top=top_layer_name,
                                             net_top=net_top,
                                             layer_bot=bot_layer_name,
                                             net_bot=net_bot)
                            cap = OverlapCap(key=ovk,
                                             cap_value=cap_femto,
                                             shielded_area=shielded_area_um2,
                                             unshielded_area=unshielded_area_um2,
                                             tech_spec=overlap_cap_spec)
                            extraction_results.overlap_coupling[ovk] = cap

        # (2) SIDEWALL CAPACITANCE
        #
        for layer_name in layer2net2regions.keys():
            sidewall_cap_spec = self.tech_info.sidewall_cap_by_layer_name.get(layer_name, None)
            if not sidewall_cap_spec:
                warning(f"No sidewall cap specified for layer {layer_name}")
                continue

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

                            length_um = avg_length * dbu
                            distance_um = avg_distance * dbu

                            cap_femto = (length_um * sidewall_cap_spec.capacitance) / \
                                        (distance_um + sidewall_cap_spec.offset) / 1000

                            info(f"(Sidewall) layer {layer_name}: Nets {net1} <-> {net2}: {round(cap_femto, 2)}fF")

                            swk = SidewallKey(layer=layer_name, net1=net1, net2=net2)
                            sw_cap = SidewallCap(key=swk,
                                                 cap_value=cap_femto,
                                                 distance=distance_um,
                                                 length=length_um,
                                                 tech_spec=sidewall_cap_spec)
                            extraction_results.sidewall_table[swk] = sw_cap

        #
        # (3) FRINGE / SIDE OVERLAP CAPACITANCE
        #

        class FringeEdgeNeighborhoodVisitor(kdb.EdgeNeighborhoodVisitor):
            def __init__(self,
                         inside_layer_name: str,
                         inside_net_name: str,
                         outside_layer_name: str,
                         outside_net_names: List[str],
                         tech_info: TechInfo,
                         report_category: rdb.RdbCategory):
                self.inside_layer_name = inside_layer_name
                self.inside_net_name = inside_net_name
                self.outside_layer_name = outside_layer_name
                self.outside_net_names = outside_net_names
                self.tech_info = tech_info
                self.report_category = report_category

                # NOTE: overlap_cap_by_layer_names is top/bot (dict is not symmetric)
                self.overlap_cap_spec = tech_info.overlap_cap_by_layer_names[inside_layer_name].get(outside_layer_name, None)
                if not self.overlap_cap_spec:
                    self.overlap_cap_spec = tech_info.overlap_cap_by_layer_names[outside_layer_name][inside_layer_name]

                self.substrate_cap_spec = tech_info.substrate_cap_by_layer_name[inside_layer_name]
                self.sideoverlap_cap_spec = tech_info.side_overlap_cap_by_layer_names[inside_layer_name][outside_layer_name]

            def begin_polygon(self,
                              layout: kdb.Layout,
                              cell: kdb.Cell,
                              polygon: kdb.Polygon):
                debug(f"----------------------------------------")
                debug(f"Polygon: {polygon}")

            def end_polygon(self):
                debug(f"End of polygon")

            def on_edge(self,
                        layout: kdb.Layout,
                        cell: kdb.Cell,
                        edge: kdb.Edge,
                        neighborhood: EdgeNeighborhood):
                #
                # NOTE: this complex operation will automatically rotate every edge to be on the x-axis
                #       going from 0 to edge.length
                #       so we only have to consider the y-axis to get the near and far distances
                #

                # TODO: consider z-shielding!

                debug(f"inside_layer={self.inside_layer_name}, "
                      f"inside_net={self.inside_net_name}, "
                      f"outside_layer={self.outside_layer_name}, "
                      f"edge = {edge}")

                for (x1, x2), polygons_by_net in neighborhood:
                    if not polygons_by_net:
                        continue

                    edge_interval_length = x2 - x1
                    edge_interval_length_um = edge_interval_length * dbu
                    rdb_cat_edge_interval = report.create_category(self.report_category,
                                                                   f"edge_interval={(x1, x2)}")

                    for net_index, polygons in polygons_by_net.items():
                        net_name = self.outside_net_names[net_index]
                        rdb_cat_outside_net = report.create_category(rdb_cat_edge_interval,
                                                                     f"outside_net={net_name}")


                        # TODO: re-enable this, currently there is a klayout bug when writing / reading the report DB
                        if polygons:
                            original_trans_polygons = [self.to_original_trans(edge) * p for p in polygons]
                            report.create_items(rdb_cell.rdb_id(),
                                                rdb_cat_outside_net.rdb_id(),
                                                kdb.CplxTrans(mag=dbu),
                                                original_trans_polygons)

                        for p in polygons:
                            bbox: kdb.Box = p.bbox()

                            if not p.is_box():
                                warning(f"Side overlap, outside polygon {p} is not a box. "
                                        f"Currently, only boxes are supported, will be using bounding box {bbox}")
                            distance_near = bbox.p1.y  #+ 1
                            if distance_near < 0:
                                distance_near = 0
                            distance_far = bbox.p2.y   #- 2
                            if distance_far < 0:
                                distance_far = 0
                            try:
                                assert distance_near >= 0
                                assert distance_far >= distance_near
                            except AssertionError:
                                print()
                                raise

                            if distance_far == distance_near:
                                continue

                            distance_near_um = distance_near * dbu
                            distance_far_um = distance_far * dbu

                            # NOTE: overlap scaling is 1/50  (see MAGIC ExtTech)
                            alpha_scale_factor = 0.02 * 0.01 * 0.5 * 200.0
                            alpha_c = self.overlap_cap_spec.capacitance * alpha_scale_factor

                            # see Magic ExtCouple.c L1164
                            cnear = (2.0 / math.pi) * math.atan(alpha_c * distance_near_um)
                            cfar = (2.0 / math.pi) * math.atan(alpha_c * distance_far_um)

                            # "cfrac" is the fractional portion of the fringe cap seen
                            # by tile tp along its length.  This is independent of the
                            # portion of the boundary length that tile tp occupies.
                            cfrac = cfar - cnear

                            # The fringe portion extracted from the substrate will be
                            # different than the portion added to the coupling layer.
                            sfrac: float

                            # see Magic ExtCouple.c L1198
                            alpha_s = self.substrate_cap_spec.area_capacitance / alpha_scale_factor
                            if alpha_s != alpha_c:
                                snear = (2.0 / math.pi) * math.atan(alpha_s * distance_near_um)
                                sfar = (2.0 / math.pi) * math.atan(alpha_s * distance_far_um)
                                sfrac = sfar - snear
                            else:
                                sfrac = cfrac

                            cap_femto = (cfrac * edge_interval_length_um *
                                         self.sideoverlap_cap_spec.capacitance / 1000.0)

                            sok = SideOverlapKey(layer_inside=self.inside_layer_name,
                                                 net_inside=self.inside_net_name,
                                                 layer_outside=self.outside_layer_name,
                                                 net_outside=net_name)
                            sov = extraction_results.sideoverlap_table.get(sok, None)
                            if sov:
                                sov.cap_value += cap_femto
                            else:
                                sov = SideOverlapCap(key=sok, cap_value=cap_femto)
                                extraction_results.sideoverlap_table[sok] = sov

                            # efflength = (cfrac - sov.so_coupfrac) * (double) length;
                            # cap += e->ec_cap * efflength;
                            #
                            # subfrac += sov.so_subfrac; / *Just add the shielded fraction * /
                            # efflength = (sfrac - subfrac) * (double) length;
                            #
                            # subcap = ExtCurStyle->exts_perimCap[ta][0] * efflength;

                            # TODO: shielding

                            # TODO: fringe portion extracted from substrate

        for inside_layer_name in layer2net2regions.keys():
            inside_net2regions = layer2net2regions.get(inside_layer_name, None)
            if not inside_net2regions:
                continue

            inside_fringe_specs = self.tech_info.side_overlap_cap_by_layer_names.get(inside_layer_name, None)
            if not inside_fringe_specs:
                warning(f"No fringe / side overlap cap specified for layer top={inside_layer_name}")
                continue

            shapes_inside_layer = layer_regions_by_name[inside_layer_name]
            fringe_halo_inside = shapes_inside_layer.sized(side_halo_dbu) - shapes_inside_layer

            rdb_cat_inside_layer = report.create_category(rdb_cat_fringe, f"inside_layer={inside_layer_name}")
            rdb_output(rdb_cat_inside_layer, "fringe_halo_inside", fringe_halo_inside)

            for outside_layer_name in layer2net2regions.keys():
                if inside_layer_name == outside_layer_name:
                    continue

                outside_net2regions = layer2net2regions.get(outside_layer_name, None)
                if not outside_net2regions:
                    continue

                cap_spec = inside_fringe_specs.get(outside_layer_name, None)
                if not cap_spec:
                    warning(f"No side overlap cap specified for "
                            f"layer inside={inside_layer_name}/outside={outside_layer_name}")
                    continue

                shapes_outside_layer = layer_regions_by_name[outside_layer_name]
                if not shapes_outside_layer:
                    continue

                shapes_outside_layer_within_halo = shapes_outside_layer.__and__(fringe_halo_inside)
                if not shapes_outside_layer_within_halo:
                    continue

                rdb_cat_outside_layer = report.create_category(rdb_cat_inside_layer,
                                                               f"outside_layer={outside_layer_name}")

                for net_inside in inside_net2regions.keys():
                    shapes_inside_net: kdb.Region = inside_net2regions[net_inside]
                    if not shapes_inside_net:
                        continue

                    visitor = FringeEdgeNeighborhoodVisitor(inside_layer_name=inside_layer_name,
                                                            inside_net_name=net_inside,
                                                            outside_layer_name=outside_layer_name,
                                                            outside_net_names=[net_inside] + list(outside_net2regions.keys()),
                                                            tech_info=self.tech_info,
                                                            report_category=rdb_cat_outside_layer)
                    # kdb.CompoundRegionOperationNode.new_secondary(shapes_inside_net)
                    children = [kdb.CompoundRegionOperationNode.new_foreign()] + \
                               [kdb.CompoundRegionOperationNode.new_secondary(region)
                                for region in list(outside_net2regions.values())]
                    node = kdb.CompoundRegionOperationNode.new_edge_neighborhood(
                        children,
                        visitor,
                        0, # bext
                        0, # eext,
                        0, # din
                        side_halo_dbu # dout
                    )

                    shapes_inside_net.complex_op(node)

        info(extraction_results.sideoverlap_table.values())

        #
        # (4) SUBSTRATE CAPACITANCE
        #
        for i, net1 in enumerate(net2layer2regions.keys()):
            layer2regions = net2layer2regions.get(net1, None)
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

                        # (1) SUBSTRATE CAPACITANCE
                        # area caps ... aF/µm^2
                        # perimeter / sidewall ... aF/µm
                        #
                        # shielding caused by of layers below
                        #  - hinders area
                        #  - hinders fringe / perimeter ... which "halo"?

                        area_shapes_unshielded = shapes.dup()
                        area_shapes_unshielded -= regions_below_layer[layer_name]
                        area = area_shapes_unshielded.area() * dbu ** 2  # in µm^2

                        edges_unshielded = shapes.edges() - regions_below_layer[layer_name]
                        perimeter_unshielded = edges_unshielded.length() * dbu
                        perimeter_shielded = 0

                        for j, net2 in enumerate(net2layer2regions.keys()):
                            if j == i:
                                continue
                            #if j > i:
                            #    break

                            shapes_net2: kdb.Region = net2layer2regions[net2].get(layer_name, None)
                            if not shapes_net2:
                                continue

                            markers_net2 = space_markers.interacting(shapes_net2)
                            sidewall_edge_pairs = markers_net2.interacting(shapes)
                            for edge_pair in sidewall_edge_pairs:
                                pair_edges = kdb.Edges([edge_pair.first, edge_pair.second])
                                own_edges = pair_edges.__and__(shapes.edges())
                                length = own_edges.length() * dbu
                                sep = edge_pair.distance() * dbu
                                assert sep > 0
                                assert length >= 0

                                sub_frac = (2.0 / math.pi) * math.atan(substrate_cap_spec.area_capacitance * sep)
                                shielded_frac = 1.0 - sub_frac
                                perimeter_shielded += sub_frac * length
                                info(f"net {net1} shielded edge, "
                                     f"sidewall interacts with net {net2}: "
                                     f"{edge_pair}, sep {sep}, len {length}, substrate {sub_frac}, shielded {shielded_frac}")

                        perimeter = perimeter_unshielded - perimeter_shielded

                        cap_area_femto = area * substrate_cap_spec.area_capacitance / 1000
                        cap_perimeter_femto = perimeter * substrate_cap_spec.perimeter_capacitance / 1000

                        info(f"net {net1} layer {layer_name}: "
                             f"area {area} µm^2, perimeter {perimeter}, "
                             f"cap_area {round(cap_area_femto, 2)}fF, "
                             f"cap_peri {round(cap_perimeter_femto, 2)}fF, "
                             f"sum {round(cap_area_femto + cap_perimeter_femto, 2)}fF")

        return extraction_results
