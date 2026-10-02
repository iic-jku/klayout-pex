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
import re
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

    for name in ('nmos', 'nmos'):
        tech.device_models.device_model_mappings.add(lvs_device_class_name=name)

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

    def test_shipped_tech_definitions_have_no_unnamed_contacts(self):
        # An unnamed contact_above still passes HasField(), and hides the via it
        # should describe: ihp-sg13cmos5l declared one over Metal4, so TopVia1
        # was missing from R extraction, PEX25D and FasterCap.
        paths = tech_pbjson_paths()
        self.assertNotEqual([], paths, "No generated tech definition to check, "
                                       "run the build first")
        for path in paths:
            tech = TechInfo.parse_tech_def(path)
            for lyr in tech.process_stack.layers:
                parameters = lyr.WhichOneof('parameters')
                layer = getattr(lyr, parameters) if parameters else None
                # NOTE: nwell, diffusion and metal layers can carry a contact
                if not hasattr(layer, 'contact_above') or not layer.HasField('contact_above'):
                    continue
                with self.subTest(tech=os.path.basename(path), layer=lyr.name):
                    self.assertNotEqual('', layer.contact_above.name,
                                        "contact_above is set, but has no name")

    def test_shipped_tech_definitions_name_the_substrate(self):
        paths = tech_pbjson_paths()
        self.assertNotEqual([], paths, "No generated tech definition to check, "
                                       "run the build first")
        for path in paths:
            substrate = TechInfo.parse_tech_def(path).substrate
            with self.subTest(tech=os.path.basename(path)):
                self.assertNotEqual([], list(substrate.net_names))
                self.assertNotEqual([], list(substrate.lvs_layer_names))

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

    def test_shipped_tech_definitions_have_the_resistances_of_their_conductors_and_vias(self):
        # The resistance extraction looks them up by their canonical layer name,
        # and stops at a layer without one (e.g. at the top plates of the MIM caps)
        paths = tech_pbjson_paths()
        self.assertNotEqual([], paths, "No generated tech definition to check, "
                                       "run the build first")
        LP = tech_pb2.LayerInfo
        LK = tech_pb2.ComputedLayerInfo
        for path in paths:
            tech_info = TechInfo(TechInfo.parse_tech_def(path), dielectric_filter=None)
            missing = []
            for lyr in tech_info.tech.lvs_computed_layers:
                if lyr.kind in (LK.KIND_PIN, LK.KIND_LABEL):
                    continue
                gds_pair = (lyr.layer_info.drw_gds_pair.layer, lyr.layer_info.drw_gds_pair.datatype)
                canonical_layer_name = tech_info.canonical_layer_name_by_gds_pair[gds_pair]
                match lyr.layer_info.purpose:
                    case LP.PURPOSE_METAL | LP.PURPOSE_MIM_CAP:
                        resistances = tech_info.layer_resistance_by_layer_name
                    case LP.PURPOSE_VIA:
                        resistances = tech_info.via_resistance_by_layer_name
                    case _:
                        continue
                if canonical_layer_name not in resistances:
                    missing.append(f"{canonical_layer_name} (LVS {lyr.layer_info.name})")
            with self.subTest(tech=os.path.basename(path)):
                self.assertEqual([], missing)

    def test_shipped_tech_definitions_whitebox_the_metal_capacitors_only(self):
        # White-box mode removes the devices whose capacitance the extraction has from their geometry:
        # the MIM and MOM caps (whatever their LVS device class, e.g. sky130A VPP caps with 4 terminals are MOS4),
        # but not the MOS caps and varactors, whose capacitance (of the gate oxide) the extraction doesn't have
        paths = tech_pbjson_paths()
        self.assertNotEqual([], paths, "No generated tech definition to check, "
                                       "run the build first")
        for path in paths:
            tech_info = TechInfo.from_json(path, dielectric_filter=None)
            mim_and_mom_caps = {name for name in tech_info.device_models.mapping_by_lvs_device_class_name
                                if re.search(r'cap_(mim|cmim|cmom|vpp)|rfcmim', name)}
            with self.subTest(tech=os.path.basename(path)):
                self.assertNotEqual(set(), mim_and_mom_caps)
                self.assertEqual(mim_and_mom_caps, tech_info.device_models.metal_capacitor_class_names)

    def test_shipped_tech_definitions_have_the_resistances_of_the_wells_their_contacts_land_on(self):
        # The contacts over the taps land on the well below (e.g. sky130A licon_ntap_con on the nwell),
        # which the resistance extraction leaves out without a sheet resistance,
        # so that they'd join nothing there
        paths = tech_pbjson_paths()
        self.assertNotEqual([], paths, "No generated tech definition to check, "
                                       "run the build first")
        LP = tech_pb2.LayerInfo
        for path in paths:
            tech_info = TechInfo(TechInfo.parse_tech_def(path), dielectric_filter=None)
            missing = []
            for contact in tech_info.contact_by_contact_lvs_layer_name.values():
                gds_pair = tech_info.gds_pair_for_computed_layer_name.get(contact.layer_below, None) or \
                           tech_info.gds_pair_for_layer_name.get(contact.layer_below, None)
                computed_layer_info = tech_info.computed_layer_info_by_gds_pair.get(gds_pair, None)
                if computed_layer_info is None or \
                        computed_layer_info.layer_info.purpose not in (LP.PURPOSE_NWELL, LP.PURPOSE_PWELL):
                    continue
                canonical_layer_name = tech_info.canonical_layer_name_by_gds_pair[gds_pair]
                if canonical_layer_name not in tech_info.layer_resistance_by_layer_name:
                    missing.append(f"{canonical_layer_name}: sheet resistance, below {contact.name}")
                if contact.layer_below not in tech_info.contact_resistance_by_device_layer_name:
                    missing.append(f"{contact.name}: contact resistance")
            with self.subTest(tech=os.path.basename(path)):
                self.assertEqual([], missing)

    def test_duplicate_names_are_reported_per_namespace(self):
        problems = TechInfo.duplicate_names(tech_with_duplicates())
        self.assertEqual(5, len(problems), problems)
        self.assertIn("the process stack namespace declares 'met1' 2 times", problems[0])
        self.assertIn("the process stack namespace declares 'met2' 2 times", problems[1])
        self.assertIn('as contact, layer', problems[1])
        self.assertIn("the layer namespace declares 'met1' 2 times", problems[2])
        self.assertIn("the LVS computed layer namespace declares 'met1_con' 2 times",
                      problems[3])
        self.assertIn("the device model mapping namespace declares 'nmos' 2 times", problems[4])

    def test_the_reader_refuses_a_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, 'duplicates_tech.pb.json')
            with open(path, 'w') as f:
                f.write(google.protobuf.json_format.MessageToJson(tech_with_duplicates()))
            with self.assertRaises(TechDefError):
                TechInfo.parse_tech_def(path)

    def test_process_conductor_gds_pairs_are_from_the_bottom_up(self):
        tech = tech_pb2.Technology(name='test')
        stack = tech.process_stack
        for name, layer_type in (('subs', stack_pb2.ProcessStackInfo.LAYER_TYPE_SUBSTRATE),
                                 ('nsd', stack_pb2.ProcessStackInfo.LAYER_TYPE_DIFFUSION),
                                 ('fox', stack_pb2.ProcessStackInfo.LAYER_TYPE_FIELD_OXIDE),
                                 ('poly', stack_pb2.ProcessStackInfo.LAYER_TYPE_METAL),
                                 ('met1', stack_pb2.ProcessStackInfo.LAYER_TYPE_METAL),
                                 ('met1_cap', stack_pb2.ProcessStackInfo.LAYER_TYPE_METAL)):
            stack.layers.add(name=name, layer_type=layer_type)
        for name, gds_pair in (('nsd', (7, 0)), ('poly', (5, 0)), ('met1', (8, 0))):
            tech.layers.add(name=name, drw_gds_pair=tech_pb2.GDSPair(layer=gds_pair[0], datatype=gds_pair[1]))
        # NOTE: a layer of the stack can be a computed layer, and share the GDS pair of another one
        tech.lvs_computed_layers.add(layer_info=tech_pb2.LayerInfo(name='met1_cap',
                                                                   drw_gds_pair=tech_pb2.GDSPair(layer=8, datatype=0)))
        self.assertEqual([(7, 0), (5, 0), (8, 0)], TechInfo(tech, dielectric_filter=None).process_conductor_gds_pairs)
