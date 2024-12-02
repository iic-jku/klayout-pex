from __future__ import annotations

import tempfile
from typing import *
from dataclasses import dataclass
from rich.pretty import pprint

import klayout.db as kdb

from ..log import (
    console,
    debug,
    info,
    warning,
    error
)


# Name to layer/datatype mapping for computed layers

# NOTE: the names are from computed layers. Specifically the tap
# original layer is split into ntap and ptap, so there is no
# meaningful layer/datatype combination from original layer space.
# Other layers are mapped to functionally equivalent layers.
name_to_lp: Dict[str, Tuple[int, int]] = {
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
    "via4":      (71, 44),
    'poly_vpp':  (66, 20),
    'li_vpp':    (67, 20),  # borrow from li1.drawing
    'met1_vpp':  (68, 20),
    'met2_vpp':  (69, 20),
    'met3_vpp':  (70, 20),
    'met4_vpp':  (71, 20),
    'met5_vpp':  (72, 20),
    'licon_vpp': (66, 44),
    'mcon_vpp':  (67, 44),
    'via1_vpp':  (68, 44),
    'via2_vpp':  (69, 44),
    'via3_vpp':  (70, 44),
    'via4_vpp':  (71, 44),
}


GDSPair = Tuple[int, int]


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
    region: kdb.Region


@dataclass
class KLayoutExtractionContext:
    lvsdb: kdb.LayoutToNetlist
    dbu: float
    top_cell: kdb.Cell
    layer_map: Dict[int, kdb.LayerInfo]
    cell_mapping: kdb.CellMapping
    target_layout: kdb.Layout
    extracted_layers: Dict[GDSPair, KLayoutMergedExtractedLayerInfo]
    unnamed_layers: List[KLayoutExtractedLayerInfo]

    @classmethod
    def prepare_extraction(cls,
                           lvsdb: kdb.LayoutToNetlist,
                           top_cell: str) -> KLayoutExtractionContext:
        dbu = lvsdb.internal_layout().dbu
        target_layout = kdb.Layout()
        target_layout.dbu = dbu
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

        lm = cls.build_LVS_layer_map(target_layout=target_layout, lvsdb=lvsdb)

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
            device_cell_name_prefix=None  # "DEVICE_"
        )  # property name to which to attach the net name

        extracted_layers, unnamed_layers = cls.nonempty_extracted_layers(lvsdb=lvsdb)

        return KLayoutExtractionContext(
            lvsdb=lvsdb,
            dbu=dbu,
            top_cell=top_cell,
            layer_map=lm,
            cell_mapping=cm,
            target_layout=target_layout,
            extracted_layers=extracted_layers,
            unnamed_layers=unnamed_layers
        )

    @staticmethod
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

        return lm

    @staticmethod
    def nonempty_extracted_layers(lvsdb: kdb.LayoutToNetlist) -> Tuple[Dict[GDSPair, KLayoutMergedExtractedLayerInfo], List[KLayoutExtractedLayerInfo]]:
        # https://www.klayout.de/doc-qt5/code/class_LayoutToNetlist.html#method18
        nonempty_layers: Dict[GDSPair, KLayoutMergedExtractedLayerInfo] = {}

        unnamed_layers: List[KLayoutExtractedLayerInfo] = []

        for idx, ln in enumerate(lvsdb.layer_names()):
            layer = lvsdb.layer_by_name(ln)
            if layer.count() >= 1:
                if ln not in name_to_lp:
                    warning(
                        f"Unable to find info about extracted LVS layer '{ln}'")
                    gds_pair = (1000 + idx, 20)
                    linfo = KLayoutExtractedLayerInfo(
                        index=idx,
                        lvs_layer_name=ln,
                        gds_pair=gds_pair,
                        region=layer
                    )
                    unnamed_layers.append(linfo)
                    continue

                gds_pair = name_to_lp[ln]
                linfo = KLayoutExtractedLayerInfo(
                    index=idx,
                    lvs_layer_name=ln,
                    gds_pair=gds_pair,
                    region=layer
                )

                entry = nonempty_layers.get(gds_pair, None)
                if entry:
                    entry.source_layers.append(linfo)
                    merged_region = kdb.Region()
                    merged_region += entry.region
                    merged_region += layer
                    entry.region = merged_region
                else:
                    nonempty_layers[gds_pair] = KLayoutMergedExtractedLayerInfo(
                        source_layers=[linfo],
                        gds_pair=gds_pair,
                        region=layer,
                    )

        return nonempty_layers, unnamed_layers
