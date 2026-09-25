#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
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
import glob
import os
import tempfile
import unittest

import allure
import google.protobuf.json_format

from klayout_pex.tech_info import TechDefError, TechInfo
import klayout_pex_protobuf.kpex.tech.tech_pb2 as tech_pb2
import klayout_pex_protobuf.kpex.tech.process_stack_pb2 as stack_pb2


def tech_pbjson_paths() -> list[str]:
    protobuf_dir = os.path.realpath(os.path.join(__file__, '..', '..',
                                                 'klayout_pex_protobuf'))
    return sorted(glob.glob(os.path.join(protobuf_dir, '*_tech.pb.json')))


def tech_with_duplicates() -> tech_pb2.Technology:
    tech = tech_pb2.Technology(name='test')

    stack = tech.process_stack
    for name in ('met1', 'met2', 'met1'):
        layer = stack.layers.add(name=name,
                                 layer_type=stack_pb2.ProcessStackInfo.LAYER_TYPE_METAL)
        layer.metal_layer.z = 1.0
        layer.metal_layer.thickness = 0.1
    # A contact shares the namespace with the layers, so this collides too.
    stack.layers[1].metal_layer.contact_above.name = 'met2'

    tech.layers.add(name='met1')
    tech.layers.add(name='met1')

    for name in ('met1_con', 'met1_con'):
        tech.lvs_computed_layers.add().layer_info.name = name

    return tech


@allure.parent_suite('Unit Tests')
@allure.tag('TechInfo', 'Technology')
class Test(unittest.TestCase):
    def test_shipped_tech_definitions_have_unique_names(self):
        paths = tech_pbjson_paths()
        self.assertNotEqual([], paths, "No generated tech definition to check, "
                                       "run the build first")
        for path in paths:
            with self.subTest(tech=os.path.basename(path)):
                self.assertEqual([], TechInfo.duplicate_names(
                    TechInfo.parse_tech_def(path)))

    def test_shipped_tech_definitions_have_no_unnamed_metal_contacts(self):
        # An unnamed contact_above still passes HasField(), and hides the via it
        # should describe: ihp-sg13cmos5l declared one over Metal4, so TopVia1
        # was missing from R extraction, PEX25D and FasterCap.
        paths = tech_pbjson_paths()
        self.assertNotEqual([], paths, "No generated tech definition to check, "
                                       "run the build first")
        for path in paths:
            tech = TechInfo.parse_tech_def(path)
            for lyr in tech.process_stack.layers:
                if lyr.WhichOneof('parameters') != 'metal_layer' \
                        or not lyr.metal_layer.HasField('contact_above'):
                    continue
                with self.subTest(tech=os.path.basename(path), layer=lyr.name):
                    self.assertNotEqual('', lyr.metal_layer.contact_above.name,
                                        "contact_above is set, but has no name")

    def test_shipped_tech_definitions_declare_each_capacitance_once(self):
        # The capacitances are looked up by layer (pair), so one declared twice
        # keeps only the last value: ihp-sg13g2 and ihp-sg13cmos5l declared
        # both the LV and the HV diffusion values for their single Activ layer.
        # A repeated value is harmless, until one of the two copies gets edited.
        paths = tech_pbjson_paths()
        self.assertNotEqual([], paths, "No generated tech definition to check, "
                                       "run the build first")
        for path in paths:
            cap = TechInfo.parse_tech_def(path).process_parasitics.capacitance
            tables = {
                'substrate': [((c.layer_name,), (c.area_capacitance, c.perimeter_capacitance))
                              for c in cap.substrates],
                'overlap': [((c.top_layer_name, c.bottom_layer_name), c.capacitance)
                            for c in cap.overlaps],
                'sidewall': [((c.layer_name,), (c.capacitance, c.offset))
                             for c in cap.sidewalls],
                'side overlap': [((c.in_layer_name, c.out_layer_name), c.capacitance)
                                 for c in cap.sideoverlaps],
            }
            for table, entries in tables.items():
                values_by_layers = defaultdict(list)
                for layers, value in entries:
                    values_by_layers[layers].append(value)
                with self.subTest(tech=os.path.basename(path), table=table):
                    self.assertEqual({}, {layers: values
                                          for layers, values in values_by_layers.items()
                                          if len(values) > 1})

    def test_duplicate_names_are_reported_per_namespace(self):
        problems = TechInfo.duplicate_names(tech_with_duplicates())
        self.assertEqual(4, len(problems), problems)
        self.assertIn("the process stack namespace declares 'met1' 2 times", problems[0])
        self.assertIn("the process stack namespace declares 'met2' 2 times", problems[1])
        self.assertIn('as contact, layer', problems[1])
        self.assertIn("the layer namespace declares 'met1' 2 times", problems[2])
        self.assertIn("the LVS computed layer namespace declares 'met1_con' 2 times",
                      problems[3])

    def test_the_reader_refuses_a_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, 'duplicates_tech.pb.json')
            with open(path, 'w') as f:
                f.write(google.protobuf.json_format.MessageToJson(tech_with_duplicates()))
            with self.assertRaises(TechDefError):
                TechInfo.parse_tech_def(path)
