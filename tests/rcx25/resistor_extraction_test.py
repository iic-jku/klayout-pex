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

import allure
import unittest
import klayout_pex.rcx25.r.resistor_extraction as rex
import klayout.db as kdb


@allure.parent_suite("Unit Tests")
class REXTest(unittest.TestCase):
    def test_conductance(self):
        c1 = rex.Conductance(1.0)
        c2 = rex.Conductance(0.25)
        self.assertEqual(str(c1.parallel(c2)), "1.25")
        self.assertEqual(str(c1.serial(c2)), "0.2")

    def test_rex_basic(self):
        ex = rex.ResistorNetwork()
        self.assertEqual(ex.check(), 0)
        self.assertEqual("\n" + str(ex) + "\n", """
Nodes:
Conductors:
""")

        nid = ex.node_id(kdb.Point(100, 200))
        nid2 = ex.node_id(kdb.Point(100, 200))
        self.assertEqual(nid, nid2)
        self.assertEqual(str(ex.location(nid)), "100,200")
        self.assertEqual(ex.check(), 0)
        self.assertEqual("\n" + str(ex) + "\n", """
Nodes:
  0: 100,200
Conductors:
""")

        nid2 = ex.node_id(kdb.Point(200, 100))
        self.assertNotEqual(nid, nid2)
        self.assertEqual(ex.check(), 0)
        self.assertEqual("\n" + str(ex) + "\n", """
Nodes:
  0: 100,200
  1: 200,100
Conductors:
""")
        ex.add_cond(nid, nid2, rex.Conductance(0.25))
        self.assertEqual(ex.check(), 0)
        self.assertEqual("\n" + str(ex) + "\n", """
Nodes:
  0: 100,200
  1: 200,100
Conductors:
  0,1: 0.25
""")
        ex.add_cond(nid, nid2, rex.Conductance(0.75))
        self.assertEqual(ex.check(), 0)
        self.assertEqual("\n" + str(ex) + "\n", """
Nodes:
  0: 100,200
  1: 200,100
Conductors:
  0,1: 1
""")

        nid3 = ex.node_id(kdb.Point(0, 0))
        ex.add_cond(nid, nid3, rex.Conductance(0.5))
        ex.add_cond(nid2, nid3, rex.Conductance(1.0))
        self.assertEqual(ex.check(), 0)
        self.assertEqual("\n" + str(ex) + "\n", """
Nodes:
  0: 100,200
  1: 200,100
  2: 0,0
Conductors:
  0,1: 1
  0,2: 0.5
  1,2: 1
""")

        ex.connect_nodes(nid, nid3)
        self.assertEqual(ex.check(), 0)
        self.assertEqual("\n" + str(ex) + "\n", """
Nodes:
  0: 100,200
  1: 200,100
Conductors:
  0,1: 2
""")

    def test_rn_eliminate(self):
        ex = rex.ResistorNetwork()

        nid1 = ex.node_id(kdb.Point(100, 200))
        nid2 = ex.node_id(kdb.Point(200, 100))
        nid3 = ex.node_id(kdb.Point(0, -200))
        nid4 = ex.node_id(kdb.Point(0, 0))
        ex.add_cond(nid1, nid2, rex.Conductance(1.0))
        ex.add_cond(nid1, nid3, rex.Conductance(0.5))
        ex.add_cond(nid2, nid3, rex.Conductance(2.0))
        ex.add_cond(nid1, nid4, rex.Conductance(1.0))
        ex.add_cond(nid2, nid4, rex.Conductance(2.0))
        ex.add_cond(nid3, nid4, rex.Conductance(0.5))
        self.assertEqual(ex.check(), 0)
        self.assertEqual("\n" + str(ex) + "\n", """
Nodes:
  0: 100,200
  1: 200,100
  2: 0,-200
  3: 0,0
Conductors:
  0,1: 1
  0,2: 0.5
  0,3: 1
  1,2: 2
  1,3: 2
  2,3: 0.5
""")

        ex.eliminate_node(nid4)
        self.assertEqual(ex.check(), 0)
        self.assertEqual("\n" + str(ex) + "\n", """
Nodes:
  0: 100,200
  1: 200,100
  2: 0,-200
Conductors:
  0,1: 1.57143
  0,2: 0.642857
  1,2: 2.28571
""")

    def test_rn_eliminate2(self):
        ex = rex.ResistorNetwork()

        nid1 = ex.node_id(kdb.Point(100, 200))
        nid2 = ex.node_id(kdb.Point(200, 100))
        nid3 = ex.node_id(kdb.Point(0, -200))
        nid4 = ex.node_id(kdb.Point(0, 0))

        ex.add_cond(nid1, nid2, rex.Conductance(1.0))
        ex.add_cond(nid1, nid3, rex.Conductance(0.5))
        ex.add_cond(nid2, nid3, rex.Conductance(2.0))
        ex.add_cond(nid1, nid4, rex.Conductance(1.0))
        ex.add_cond(nid2, nid4, rex.Conductance(2.0))
        ex.add_cond(nid3, nid4, rex.Conductance(0.5))
        self.assertEqual(ex.check(), 0)

        ex.mark_precious(nid1)
        ex.mark_precious(nid4)

        ex.eliminate_all()
        self.assertEqual(ex.check(), 0)

        self.assertEqual("\n" + str(ex) + "\n", """
Nodes:
  0: 100,200
  3: 0,0
Conductors:
  0,3: 1.93182
""")

    def test_expand_skinny_tris(self):
        # non-skinny
        p = kdb.Polygon([(0, 0), (2000, -10000), (5000, 0)])
        pp = rex.ResistorNetwork.expand_skinny_tris(p)
        self.assertEqual("\n" + "\n".join([str(p) for p in pp]) + "\n", """
(2000,-10000;0,0;5000,0)
""")

        # non-skinny (exactly 90 degree)
        p = kdb.Polygon([(0, 0), (2000, -2000), (4000, 0)])
        pp = rex.ResistorNetwork.expand_skinny_tris(p)
        self.assertEqual("\n" + "\n".join([str(p) for p in pp]) + "\n", """
(2000,-2000;0,0;4000,0)
""")

        # skinny (angle >90 degree)
        p = kdb.Polygon([(0, 0), (2000, -1000), (5000, 0)])
        pp = rex.ResistorNetwork.expand_skinny_tris(p)
        self.assertEqual("\n" + "\n".join([str(p) for p in pp]) + "\n", """
(2000,-1000;2000,0;5000,0)
(2000,-1000;0,0;2000,0)
""")

    def test_extraction(self):
        rx = rex.ResistorExtraction(b=1.0)

        polygons = kdb.Region(kdb.Box(0, 0, 10000, 1000))

        pins = kdb.Region()
        pins.insert(kdb.Box(0, 0, 1000, 1000))
        pins.insert(kdb.Box(9000, 0, 10000, 1000))

        labels = kdb.Texts()
        labels.insert(kdb.Text("A", kdb.Trans(500, 500)))
        labels.insert(kdb.Text("B", kdb.Trans(9500, 500)))

        rn = rx.extract(polygons, pins, labels)
        self.assertEqual("\n" + "\n".join([n.to_string(True) for n in rn]) + "\n", """
Nodes:
  A: 1000,1000
  B: 9000,0
Resistors:
  A,B: 8
""")
