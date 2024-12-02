#!/bin/env python3

from dataclasses import dataclass
import klayout.db as kdb
import os.path

import pya
from rich.pretty import pprint
import rich.console
import sys
from typing import *

import tech_pb2
import google.protobuf.json_format

console = rich.console.Console()

def parse_tech_def(jsonpb_path: str) -> tech_pb2.Technology:
    with open(jsonpb_path, 'r') as f:
        contents = f.read()
        tech = google.protobuf.json_format.Parse(contents, tech_pb2.Technology())
        return tech

# Name to layer/datatype mapping for computed layers

# NOTE: the names are from computed layers. Specifically the tap
# original layer is split into ntap and ptap, so there is no
# meaningful layer/datatype combination from original layer space.
# Other layers are mapped to functionally equivalent layers.
name_to_lp = {
  "dnwell":    (64, 18),
  "li_con":    (67, 20),
  "licon":     (66, 44),
  "mcon":      (67, 44),
  "met1_con":  (68, 20),
  "met2_con":  (69, 20),
  "met3_ncap": (70, 20),
  "met4_ncap": (71, 20),
  "met5_con":  (72, 20),
  "nsd":       (93, 44),   # borrow from nsdm
  "ntap_conn": (65, 144),  # original tap is 65/44, but we need to separate ntap/ptap
  "nwell":     (64, 20),
  "poly_con":  (66, 20),
  "psd":       (94, 20),   # borrow from psdm
  "ptap_conn": (65, 244),  # original tap is 65/44, but we need to separate ntap/ptap
  "via1":      (68, 44),
  "via2":      (69, 44),
  "via3":      (70, 44),
  "via4":      (71, 44)
}

def build_LVS_layer_map(target_layout: kdb.Layout,
                        lvsdb: kdb.LayoutToNetlist) -> Dict[int, kdb.LayerInfo]:
    # # TODO: currently, the layer numbers are auto-assigned
    # # by the sequence they occur in the LVS script, hence not well defined!
    # # build a layer map for the layers that correspond to original ones.
    # lm = {}
    # for lname in lvsdb.layer_names():
    #     li = kdb.LayerInfo(lname)
    #     target_layer_index = target_layout.layer(li)  # Creates a new internal layer!
    #     lm[target_layer_index] = lvsdb.layer_by_name(lname)
    # pprint(lm)

    # https://www.klayout.de/doc-qt5/code/class_LayerInfo.html
    lm: Dict[int, kdb.LayerInfo] = {}

    if not hasattr(lvsdb, "layer_indexes"):
        raise Exception("Needs at least KLayout version 0.29.2")

    for layer_index in lvsdb.layer_indexes():

        lname = lvsdb.layer_name(layer_index)

        layer = datatype = None
        if lname in name_to_lp:
            layer, datatype = name_to_lp[lname]
        else:
            info = lvsdb.internal_layout().get_info(layer_index)
            if info != kdb.LayerInfo():
                layer = info.layer
                datatype = info.datatype

        if layer is not None:
            target_layer_index = target_layout.layer(layer, datatype)  # Creates a new internal layer!
            region = lvsdb.layer_by_index(layer_index)
            lm[target_layer_index] = region

    pprint(lm)
    return lm

@dataclass
class NetGeometriesInfo:
    top_cell: str
    layer_map: Dict[int, kdb.LayerInfo]
    cell_mapping: kdb.CellMapping
    target_layout: kdb.Layout

def build_net_geometries(top_cell: str,
                         lvsdb: kdb.LayoutToNetlist) -> NetGeometriesInfo:
    target_layout = kdb.Layout()
    top_cell = target_layout.create_cell(top_cell)

    # CellMapping
    #   mapping of internal layout to target layout for the circuit mapping
    #   https://www.klayout.de/doc-qt5/code/class_CellMapping.html
    # ---
    # https://www.klayout.de/doc-qt5/code/class_LayoutToNetlist.html#method18
    # Creates a cell mapping for copying shapes from the internal layout to the given target layout
    cm = lvsdb.cell_mapping_into(target_layout,  # target layout
                                 top_cell,
                                 True)  # with_device_cells

    lm = build_LVS_layer_map(target_layout=target_layout,
                             lvsdb=lvsdb)

    net_name_prop_num = 1

    # Build a full hierarchical representation of the nets
    # https://www.klayout.de/doc-qt5/code/class_LayoutToNetlist.html#method14
    # hier_mode = None

    hier_mode = kdb.LayoutToNetlist.BuildNetHierarchyMode.BNH_Flatten
    # hier_mode = kdb.LayoutToNetlist.BuildNetHierarchyMode.BNH_SubcircuitCells
    lvsdb.build_all_nets(
        cmap=cm,               # mapping of internal layout to target layout for the circuit mapping
        target=target_layout,  # target layout
        lmap=lm,               # maps: target layer index => net regions
        hier_mode=hier_mode,   # hier mode
        netname_prop=net_name_prop_num,
        circuit_cell_name_prefix="CIRCUIT_",
        device_cell_name_prefix=None # "DEVICE_"
    )  # property name to which to attach the net name

    return NetGeometriesInfo(top_cell=top_cell,
                             layer_map=lm,
                             cell_mapping=cm,
                             target_layout=target_layout)

def nonempty_extracted_layers(lvsdb: kdb.LayoutToNetlist) -> List[Tuple[str, kdb.Region]]:
    # https://www.klayout.de/doc-qt5/code/class_LayoutToNetlist.html#method18
    nonempty_layers: List[Tuple[str, kdb.Region]] = []
    for ln in lvsdb.layer_names():
        layer = lvsdb.layer_by_name(ln)
        if layer.count() >= 1:
            nonempty_layers.append((ln, layer))
    return nonempty_layers

def build_fastercap_input(lvsdb: kdb.LayoutToNetlist,
                          net_geometries_info: NetGeometriesInfo,
                          tech: tech_pb2.Technology) -> str:
    lst = ""
    netlist = lvsdb.netlist()

    nonempty_layers = nonempty_extracted_layers(lvsdb=lvsdb)

    def format_terminal(t: kdb.NetTerminalRef) -> str:
        td = t.terminal_def()
        d = t.device()
        return f"{d.expanded_name()}/{td.name}/{td.description}"

    metal_stack_layer_by_name = {lyr.name: lyr for lyr in tech.metal_stack.layer}
    layer_info_by_name = {lyr.name: lyr for lyr in tech.layers}
    layer_info_by_gds_pair = {(lyr.gds_layer, lyr.gds_datatype): lyr for lyr in tech.layers}

    for circuit in netlist.each_circuit():
        # https://www.klayout.de/doc-qt5/code/class_Circuit.html
        for net in circuit.each_net():
            # https://www.klayout.de/doc-qt5/code/class_Net.html
            print(f"Net name={net.name}, expanded_name={net.expanded_name()}, pin_count={net.pin_count()}, "
                  f"is_floating={net.is_floating()}, is_passive={net.is_passive()}, "
                  f"terminals={list(map(lambda t: format_terminal(t), net.each_terminal()))}")

            print(f"Shapes of net {net.expanded_name()}: ")
            for lvs_layer_name, region in nonempty_layers:
                # TODO: how can I find the
                #
                #
                if lvs_layer_name not in name_to_lp:
                    print(
                        f"ERROR: Unable to find info about LVS layer '{lvs_layer_name}')")
                    continue

                gds_pair = name_to_lp[lvs_layer_name]
                if gds_pair not in layer_info_by_gds_pair:
                    print(
                        f"ERROR: Unable to find layer info for GDS pair '{gds_pair}'")
                    continue

                layer_info = layer_info_by_gds_pair[gds_pair]
                if layer_info.name not in metal_stack_layer_by_name:
                     print(f"ERROR: Unable to find layer '{layer_info.name}' in metal stack definition")
                     continue

                console.print(f"Layer [green]{layer_info.name}[/green]:")

                shapes = lvsdb.shapes_of_net(net, region)
                for shape in shapes:
                    console.print(f"Type: {type(shape)}: {shape}")

    return lst


jsonpb_path = os.path.realpath(
    os.path.join(os.path.dirname(os.path.realpath(__file__)),
                 "..",
                 "build",
                 "sky130A_tech.pb.json")
)
tech = parse_tech_def(jsonpb_path)


# cell = "inv"
# cell = "inverter2"
cell = "nmos_diode2"
# cell = "nmos_diode2"

# NOTE: can be L2N database for pure extracted information (current
lvsdb = kdb.LayoutVsSchematic()
lvsdb.read(f"{cell}.lvsdb.gz")

# dump_list_of_circuits(lvsdb=lvsdb)
gds_path = f"{cell}_l2ndb.gds.gz"
net_geometries_info = build_net_geometries(top_cell=cell,
                                           lvsdb=lvsdb)
net_geometries_info.target_layout.write(gds_path)

lst = build_fastercap_input(lvsdb=lvsdb,
                            net_geometries_info=net_geometries_info,
                            tech=tech)
print(lst)
