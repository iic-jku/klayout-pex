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
from typing import *
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


def write_tech_def(directory: str, tech: tech_pb2.Technology) -> str:
    """
    :return: the path of the JSON file of the tech definition, as the generator writes it
    """
    path = os.path.join(directory, f"{tech.name}_tech.pb.json")
    with open(path, 'w') as f:
        f.write(google.protobuf.json_format.MessageToJson(tech))
    return path


def tech_with_metal_on_one_gds_pair(stack_layer_names: Sequence[str],
                                    process_layer_name_by_lvs_layer_name: Dict[str, str]) -> tech_pb2.Technology:
    """
    The layers of the stack and the LVS layers of a metal on one GDS pair (67/0),
    each LVS layer with the layer of the stack it names ('' for none)
    """
    tech = tech_pb2.Technology(name='test')
    for name in stack_layer_names:
        tech.process_stack.layers.add(name=name, layer_type=stack_pb2.ProcessStackInfo.LAYER_TYPE_METAL)
    for name, process_layer_name in process_layer_name_by_lvs_layer_name.items():
        tech.lvs_computed_layers.add(layer_info=tech_pb2.LayerInfo(name=name,
                                                                   drw_gds_pair=tech_pb2.GDSPair(layer=67, datatype=0)),
                                     process_layer_name=process_layer_name)
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

    def test_shipped_tech_definitions_have_wells_of_lvs_computed_layers(self):
        # The capacitances above a well go to its net, which the extraction has on the shapes
        # of the LVS computed layers, so the substrate would cover a well of another layer
        paths = tech_pbjson_paths()
        self.assertNotEqual([], paths, "No generated tech definition to check, "
                                       "run the build first")
        for path in paths:
            tech_info = TechInfo(TechInfo.parse_tech_def(path), dielectric_filter=None)
            well_layer_names = list(tech_info.tech.substrate.well_lvs_layer_names)
            with self.subTest(tech=os.path.basename(path)):
                self.assertNotEqual([], well_layer_names)
                self.assertEqual([], [name for name in well_layer_names
                                      if name not in tech_info.computed_layer_info_by_name])

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

    def test_shipped_substrate_wells_have_the_layer_names_of_the_resistor_networks(self):
        # NOTE: the substrate's side of a capacitance goes to the nodes of its wells (#288),
        #       which are named after the canonical layers
        expected_by_tech = {'sky130A': {'nwell'}, 'ihp-sg13g2': {'NWell', 'PWell'}, 'gf180mcuD': {'Nwell', 'LVPWELL', 'DNWELL'}}
        paths_by_tech = {os.path.basename(path).removesuffix('_tech.pb.json'): path for path in tech_pbjson_paths()}
        for tech_name, expected in expected_by_tech.items():
            with self.subTest(tech=tech_name):
                tech_info = TechInfo.from_json(paths_by_tech[tech_name], dielectric_filter=None)
                self.assertEqual(expected, tech_info.substrate_well_layer_names)

    def test_shipped_tech_definitions_have_the_vacask_subcircuits_that_declare_m(self):
        # VACASK rejects m on a subcircuit that doesn't declare it. Of the models KPEX writes m for,
        # the IHP PNP, HBTs, Schottky and antenna diodes don't (libs.tech/vacask of IIC-OSIC-TOOLS 83ae1840458f),
        # sky130A and gf180mcuD have no VACASK models
        declaring = {'sg13_lv_nmos', 'sg13_hv_pmos', 'rppd', 'rsil', 'cap_cmomf', 'diodevdd_2kv', 'nmoscl_2'}
        not_declaring = {'pnpMPA', 'dantenna', 'dpantenna', 'sg13_hv_svaricap'}
        expected_by_tech = {'ihp-sg13g2': (declaring | {'cap_cmim', 'cap_rfcmim'},
                                           not_declaring | {'npn13G2', 'schottky_nbl1'}),
                            'ihp-sg13cmos5l': (declaring, not_declaring),
                            'sky130A': (set(), set()),
                            'gf180mcuD': (set(), set())}
        paths_by_tech = {os.path.basename(path).removesuffix('_tech.pb.json'): path for path in tech_pbjson_paths()}
        for tech_name, (expected_declaring, expected_not_declaring) in expected_by_tech.items():
            with self.subTest(tech=tech_name):
                device_models = TechInfo.from_json(paths_by_tech[tech_name], dielectric_filter=None).device_models
                obtained = device_models.vacask_subcircuits_with_m
                self.assertEqual(expected_declaring, expected_declaring & obtained)
                self.assertEqual(set(), expected_not_declaring & obtained)
                if not expected_declaring:
                    self.assertEqual(set(), obtained)

    def test_shipped_mim_dielectrics_give_the_area_capacitance_of_the_device_models(self):
        # ε0·k/d of the dielectric between the plates of the MIM caps, which the device models give:
        # sky130A camimc (r+c/res_typical__cap_typical__lin.spice), IHP cap_carea (cornerCAP.lib),
        # gf180mcuD c_cox of mim_2p0fF (sm141064.ngspice), all in fF/µm²
        expected_by_tech = {'sky130A': {'capild3': 2.0, 'capild4': 2.0},
                            'ihp-sg13g2': {'ismim': 1.5},
                            'gf180mcuD': {'capild': 1.99}}
        epsilon_0 = 8.854e-3  # fF/µm
        paths_by_tech = {os.path.basename(path).removesuffix('_tech.pb.json'): path for path in tech_pbjson_paths()}
        for tech_name, expected in expected_by_tech.items():
            with self.subTest(tech=tech_name):
                tech_info = TechInfo.from_json(paths_by_tech[tech_name], dielectric_filter=None)
                obtained = {}
                for lyr in tech_info.tech.process_stack.layers:
                    if lyr.name in expected:
                        dielectric = lyr.conformal_dielectric_layer
                        obtained[lyr.name] = round(epsilon_0 * dielectric.dielectric_k / dielectric.thickness_over_metal, 2)
                self.assertEqual(expected, obtained)

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

    def test_shipped_tech_definitions_have_the_capacitances_to_their_diffusion(self):
        # The capacitances are looked up by the canonical names of the extracted layers,
        # and the diffusion is extracted as its source/drain implants (e.g. nsdm and psdm),
        # while the tables of the magic techs have it as the drawn diffusion (e.g. diff)
        paths = tech_pbjson_paths()
        self.assertNotEqual([], paths, "No generated tech definition to check, "
                                       "run the build first")
        for path in paths:
            tech_info = TechInfo(TechInfo.parse_tech_def(path), dielectric_filter=None)

            def canonical_layer_name(layer_name: str) -> str:
                return tech_info.canonical_layer_name_by_gds_pair[tech_info.gds_pair(layer_name)]

            diffusion_layer_names = [canonical_layer_name(lyr.name) for lyr in tech_info.process_diffusion_layers]
            # NOTE: but the gate poly, whose capacitances to the source/drain are the transistor's
            metal_layer_names = [canonical_layer_name(lyr.name) for lyr in tech_info.process_metal_layers[1:]]
            missing = [f"{metal} over {diffusion}"
                       for metal in metal_layer_names
                       for diffusion in diffusion_layer_names
                       if diffusion not in tech_info.overlap_cap_by_layer_names.get(metal, {})
                       or diffusion not in tech_info.side_overlap_cap_by_layer_names.get(metal, {})]
            with self.subTest(tech=os.path.basename(path)):
                self.assertNotEqual([], diffusion_layer_names)
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
            with self.assertRaises(TechDefError):
                TechInfo.parse_tech_def(write_tech_def(tmp_dir, tech_with_duplicates()))

    def test_the_reader_refuses_a_layer_of_the_stack_off_the_gds_pair_of_the_lvs_layer_naming_it(self):
        # NOTE: kpex looks up the layers of the stack after reading, where it can't report a TechDefError
        tech = tech_with_metal_on_one_gds_pair(['met5_ncap', 'met5_cap'],
                                               {'met5_ncap': 'met5_ncap', 'met5_cap': 'met5_cap', 'met5_rfcap': 'met4'})
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaisesRegex(TechDefError, r"but in .*test_tech\.pb\.json\n"
                                                      r"  - the LVS computed layer met5_rfcap names the layer met4 "):
                TechInfo.parse_tech_def(write_tech_def(tmp_dir, tech))

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

    def test_an_lvs_layer_on_a_gds_pair_of_the_stack_names_its_layer(self):
        tech = tech_with_metal_on_one_gds_pair(['met5_ncap', 'met5_cap'],
                                               {'met5_ncap': 'met5_ncap', 'met5_cap': 'met5_cap', 'met5_rfcap': ''})
        with self.assertRaisesRegex(TechDefError, r"the LVS computed layer met5_rfcap names no layer of the process "
                                                  r"stack, but the layers of the stack on its GDS pair \(67, 0\) "
                                                  r"are: met5_ncap, met5_cap"):
            _ = TechInfo(tech, dielectric_filter=None).lvs_layer_names_by_process_layer_name

    def test_an_lvs_layer_names_a_layer_of_the_stack_on_its_gds_pair(self):
        tech = tech_with_metal_on_one_gds_pair(['met5_ncap', 'met5_cap'],
                                               {'met5_ncap': 'met5_ncap', 'met5_cap': 'met5_cap', 'met5_rfcap': 'met4'})
        with self.assertRaisesRegex(TechDefError, r"the LVS computed layer met5_rfcap names the layer met4 "
                                                  r"of the process stack, but the layers of the stack "
                                                  r"on its GDS pair \(67, 0\) are: met5_ncap, met5_cap"):
            _ = TechInfo(tech, dielectric_filter=None).lvs_layer_names_by_process_layer_name

    def test_an_lvs_layer_names_no_layer_of_the_stack_where_the_stack_has_none_on_its_gds_pair(self):
        tech = tech_with_metal_on_one_gds_pair(['met5_ncap'], {'met5_ncap': 'met5_ncap'})
        tech.lvs_computed_layers.add(layer_info=tech_pb2.LayerInfo(name='met5_pin',
                                                                   drw_gds_pair=tech_pb2.GDSPair(layer=67, datatype=2)),
                                     process_layer_name='met5_ncap')
        self.assertEqual(["the LVS computed layer met5_pin names the layer met5_ncap of the process stack, "
                          "but the layers of the stack on its GDS pair (67, 2) are: none"],
                         TechInfo.process_layer_problems(tech))

    def test_shipped_tech_definitions_name_layers_of_the_stack_on_the_gds_pairs(self):
        for path in tech_pbjson_paths():
            with self.subTest(tech=os.path.basename(path)):
                self.assertEqual([], TechInfo.process_layer_problems(TechInfo.parse_tech_def(path)))

    def test_shipped_rfcmim_has_its_plates_on_the_layers_of_the_stack_of_the_cmim(self):
        # NOTE: its bottom plate is on the GDS pair of Metal5 too, whose first layer of the stack is metal5_n_cap,
        #       the one without the MIM dielectric
        path = next(p for p in tech_pbjson_paths() if os.path.basename(p) == 'ihp-sg13g2_tech.pb.json')
        process_layer_name = TechInfo.from_json(path, dielectric_filter=None).process_layer_name_by_lvs_layer_name
        self.assertEqual([process_layer_name['metal5_cap'], process_layer_name['cmim_top']],
                         [process_layer_name['metal5_rfcap'], process_layer_name['rfmim_top']])

    def test_layers_of_the_stack_on_one_gds_pair_have_the_shapes_of_their_own_lvs_layers(self):
        # e.g. sky130A, whose met3 is split into the bottom plates of the MIM caps (met3_cap) and the rest (met3_ncap),
        # with the met3 of the MOM caps (met3_vpp) on the same GDS pair
        tech = tech_pb2.Technology(name='test')
        stack = tech.process_stack
        for name in ('met2', 'met3_ncap', 'met3_cap', 'capm'):
            stack.layers.add(name=name, layer_type=stack_pb2.ProcessStackInfo.LAYER_TYPE_METAL)
        stack.layers[0].metal_layer.contact_above.name = 'via2_con'
        stack.layers[1].metal_layer.contact_above.name = 'via3_ncap'
        stack.layers[3].metal_layer.contact_above.name = 'via3_cap'
        tech.layers.add(name='met2', drw_gds_pair=tech_pb2.GDSPair(layer=69, datatype=20))
        for name, gds_pair, process_layer_name in (
                ('met2_con', (69, 20), 'met2'), ('met2_vpp', (69, 20), 'met2'),
                ('via2_con', (69, 44), 'via2_con'),
                ('met3_ncap', (70, 20), 'met3_ncap'), ('met3_cap', (70, 20), 'met3_cap'),
                ('met3_vpp', (70, 20), 'met3_ncap'),
                ('via3_ncap', (70, 144), 'via3_ncap'), ('via3_vpp', (70, 144), 'via3_ncap'),
                ('via3_cap', (70, 244), 'via3_cap'),
                ('capm', (89, 44), 'capm'),
                ('met3_pin_con', (70, 16), '')):  # NOTE: no layer of the stack is on its GDS pair
            tech.lvs_computed_layers.add(
                layer_info=tech_pb2.LayerInfo(name=name,
                                              drw_gds_pair=tech_pb2.GDSPair(layer=gds_pair[0], datatype=gds_pair[1])),
                process_layer_name=process_layer_name)

        self.assertEqual({'met2': ['met2_con', 'met2_vpp'],
                          'via2_con': ['via2_con'],
                          'met3_ncap': ['met3_ncap', 'met3_vpp'],
                          'met3_cap': ['met3_cap'],
                          'via3_ncap': ['via3_ncap', 'via3_vpp'],
                          'capm': ['capm'],
                          'via3_cap': ['via3_cap']},
                         TechInfo(tech, dielectric_filter=None).lvs_layer_names_by_process_layer_name)
        self.assertEqual({'met2_con': 'met2', 'met2_vpp': 'met2',
                          'via2_con': 'via2_con',
                          'met3_ncap': 'met3_ncap', 'met3_vpp': 'met3_ncap',
                          'met3_cap': 'met3_cap',
                          'via3_ncap': 'via3_ncap', 'via3_vpp': 'via3_ncap',
                          'capm': 'capm',
                          'via3_cap': 'via3_cap'},
                         TechInfo(tech, dielectric_filter=None).process_layer_name_by_lvs_layer_name)
