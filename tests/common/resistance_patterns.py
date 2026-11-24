#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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
"""Module-only conductor and contact layouts for independent resistance checks."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import klayout.db as kdb
import klayout.pex as klp

from klayout_pex.netlist.rc_network import RCNetwork
from klayout_pex.tech_info import TechInfo
from klayout_pex_protobuf.kpex.tech.tech_pb2 import LayerInfo
from tests.common.rc_networks import build_network


def write_strip_lvsdb(path: Path, layer: LayerInfo, lvs_names: Tuple[str, str, str],
                       length_dbu: int, width_dbu: int, dbu: float = 0.001) -> Path:
    """Place A/B ports on opposite ends of a rectangular conductor with no contacts."""
    assert length_dbu > 0 and width_dbu > 0
    layout = kdb.Layout()
    layout.dbu = dbu
    top = layout.create_cell('strip')
    drawing, pins, labels = [layout.layer(pair.layer, pair.datatype)
                             for pair in (layer.drw_gds_pair, layer.pin_gds_pair, layer.label_gds_pair)]
    top.shapes(drawing).insert(kdb.Box(0, 0, length_dbu, width_dbu))
    for x, name in ((0, 'A'), (length_dbu, 'B')):
        top.shapes(pins).insert(kdb.Box(x, 0, x + 1, width_dbu))
        top.shapes(labels).insert(kdb.Text(name, kdb.Trans(x, width_dbu // 2)))
    lvsdb = kdb.LayoutVsSchematic(kdb.RecursiveShapeIterator(layout, top, []))
    conductor = lvsdb.make_layer(drawing, lvs_names[0])
    pin_shapes = conductor if pins == drawing else lvsdb.make_layer(pins, lvs_names[1])
    texts = lvsdb.make_text_layer(labels, lvs_names[2])
    lvsdb.connect(conductor)
    lvsdb.connect(conductor, pin_shapes)
    lvsdb.connect(conductor, texts)
    lvsdb.extract_netlist()
    lvsdb.netlist().make_top_level_pins()
    lvsdb.write(str(path))
    return path


def write_contact_array_lvsdb(path: Path,
                              bottom_layer: LayerInfo, bottom_lvs: Tuple[str, str, str],
                              top_layer: LayerInfo, top_lvs: Tuple[str, str, str],
                              cut_layer: LayerInfo, cut_lvs_name: str,
                              size: int, cut_count: int) -> Path:
    """Place coincident A/B access ports at each cut so only Rcut/N is observed.

    Ports on each side are ideal terminals shared by every cut. Metal spreading
    resistance is therefore outside this test; it is exercised by the strip cases.
    """
    assert size > 0 and cut_count > 0
    layout = kdb.Layout()
    layout.dbu = .001
    top = layout.create_cell('contact_array')
    names = []
    for layer, port, lvs_names in ((bottom_layer, 'A', bottom_lvs), (top_layer, 'B', top_lvs)):
        drawing, pins, labels = [layout.layer(pair.layer, pair.datatype)
                                 for pair in (layer.drw_gds_pair, layer.pin_gds_pair, layer.label_gds_pair)]
        area = kdb.Box(0, 0, 1000 + 2 * size * cut_count, 2000)
        top.shapes(drawing).insert(area)
        top.shapes(pins).insert(area)
        for index in range(cut_count):
            x = 500 + index * 2 * size + size // 2
            top.shapes(labels).insert(kdb.Text(port, kdb.Trans(x, 500 + size // 2)))
        names.append((drawing, pins, labels, lvs_names))
    cuts = layout.layer(cut_layer.drw_gds_pair.layer, cut_layer.drw_gds_pair.datatype)
    for index in range(cut_count):
        x = 500 + index * 2 * size
        top.shapes(cuts).insert(kdb.Box(x, 500, x + size, 500 + size))
    lvsdb = kdb.LayoutVsSchematic(kdb.RecursiveShapeIterator(layout, top, []))
    conductors = []
    for drawing, pins, labels, lvs_names in names:
        conductor = lvsdb.make_layer(drawing, lvs_names[0])
        pin_shapes = conductor if pins == drawing else lvsdb.make_layer(pins, lvs_names[1])
        texts = lvsdb.make_text_layer(labels, lvs_names[2])
        lvsdb.connect(conductor)
        lvsdb.connect(conductor, pin_shapes)
        lvsdb.connect(conductor, texts)
        conductors.append(conductor)
    cut_shapes = lvsdb.make_layer(cuts, cut_lvs_name)
    lvsdb.connect(conductors[0], cut_shapes)
    lvsdb.connect(conductors[1], cut_shapes)
    lvsdb.extract_netlist()
    lvsdb.netlist().make_top_level_pins()
    lvsdb.write(str(path))
    return path


def extracted_strip(tech: TechInfo, layer: str, width: int, length: int) -> RCNetwork:
    rex = klp.RExtractorTech()
    conductor = klp.RExtractorTechConductor()
    conductor.layer = 0
    conductor.algorithm = klp.Algorithm.SquareCounting
    conductor.resistance = tech.milliohm_to_ohm(tech.layer_resistance_by_layer_name[layer].resistance)
    rex.add_conductor(conductor)
    network = klp.RNetExtractor(0.001).extract(
        rex, {0: kdb.Region(kdb.Box(0, 0, length, width))},
        {0: [kdb.Point(0, width // 2), kdb.Point(length, width // 2)]}, {})
    names = {node.object_id(): ('A' if node.port_index() == 0 else 'B') for node in network.each_node()}
    return build_network([(names[edge.a().object_id()], names[edge.b().object_id()],
                           1.0 / edge.resistance(), 0.0) for edge in network.each_element()], ['A', 'B'])
