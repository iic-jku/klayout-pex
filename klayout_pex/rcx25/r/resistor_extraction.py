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
from typing import *

import klayout.db as kdb

from klayout_pex.log import (
    debug,
    error,
    warning
)
from .conductance import Conductance
from .resistor_network import ResistorNetwork, ResistorNetworks

class ResistorExtraction:
    """
    Provides a resistor extraction

    This object translates a set of polygons and pins with labels into
    resistor networks.
    """

    def __init__(self,
                 b: float = 0.0,
                 amax: float = 0.0):
        """
        Constructor

        :param b: the "b" parameter governing the minimum angle in the Delaunay triangulation
        :param amax: the "amax" parameter governing the maxium area (in square database units) during Delaunay triangulation
        """
        self.b = b
        self.amax = amax

    def extract(self,
                polygons: kdb.Region,
                pins: kdb.Region,
                labels: kdb.Texts,
                doc_layer: kdb.Shapes = None) -> List[ResistorNetwork]:
        """
        Extracts resistor networks from the polygons on the given regions

        The conductance values are normalized to a conductivitiy of 1 Ohm/square.

        :param polygons: the resistor shape polygons
        :param pins: the pin shapes - every pin shape is considered infinitely conductive
        :param labels: the texts labelling the pins
        :param doc_layer: an option kdb.Shapes object where some documentation is provided
        """

        networks = []

        for p in polygons.merged():
            debug(f"Working on polygon {str(p)} ...")

            pin_shapes = {}

            r = kdb.Region(p)
            il = labels.interacting(r + pins.interacting(r))

            pr = kdb.Region()

            for l in il:
                pins_for_label = pins.interacting(kdb.Texts(l))
                for pp in pins_for_label:
                    if l.string not in pin_shapes:
                        pin_shapes[l.string] = []
                    pin_shapes[l.string].append(pp)
                    pr.insert(pp)

            r -= pr

            try:
                tris = r.delaunay(self.amax, self.b)
            except Exception as e:
                error(f"Failed to perform delaunay triangulation (a={self.amax}, b={self.b}) "
                      f"on polygon {r} due to exception: {e}")
                continue
            debug(f"Decomposed into {tris.count()} triangles with b={self.b} and amax={self.amax}")

            rn = ResistorNetwork()

            for t in tris.each():
                a = t.area()

                for pp in [t]:
                    if doc_layer is not None:
                        doc_layer.insert(pp)

                    pts = [pt for pt in pp.each_point_hull()]

                    for i in range(0, 3):
                        pm1 = pts[i]
                        p0 = pts[(i + 1) % 3]
                        p1 = pts[(i + 2) % 3]

                        lm1 = (p0 - pm1).sq_length()
                        l0 = (p1 - p0).sq_length()
                        l1 = (pm1 - p1).sq_length()

                        s = (l0 + l1 - lm1) / (8.0 * a)

                        nid0 = rn.node_id(p0)
                        nidm1 = rn.node_id(pm1)

                        rn.add_cond(nid0, nidm1, Conductance(s))
                        d = pm1 - p0
                        lpos = p0 + d * 0.5 + kdb.Vector(-d.y, d.x) / d.length()

                        if doc_layer is not None:
                            doc_layer.insert(kdb.Text("%.6g" % s, kdb.Trans(lpos)))

            # connects all nodes on the pin edge

            for label in sorted(pin_shapes.keys()):
                for poly in pin_shapes[label]:
                    nid0 = None
                    num = 1
                    for e in poly.each_edge():
                        for nid in rn.node_ids(e):
                            if nid0 is None:
                                nid0 = nid
                            elif nid0 != nid:
                                rn.connect_nodes(nid0, nid)
                                num += 1
                    if nid0 is not None:
                        debug(f"Using {label} for node {nid0} ({num} connected nodes)")
                        rn.name(nid0, label)
                        rn.mark_precious(nid0)

            # does a self-check
            rn.check()

            # eliminates internal nodes
            rn.eliminate_all()

            networks.append(rn)

        return networks
