#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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
import pytest
import unittest

from klayout_pex.rcx25.extraction_results import *
import klayout_pex_protobuf.process_parasitics_pb2 as process_parasitics_pb2


@allure.parent_suite("Unit Tests")
class NetCoupleKeyTest(unittest.TestCase):
    def test_normed_ascending(self):
        k = NetCoupleKey('net_bottom', 'net_top')
        obtained_k = k.normed()
        expected_k = NetCoupleKey('net_bottom', 'net_top')
        self.assertEqual(expected_k, obtained_k)

    def test_normed_descending(self):
        k = NetCoupleKey('net_top', 'net_bottom')
        obtained_k = k.normed()
        expected_k = NetCoupleKey('net_bottom', 'net_top')
        self.assertEqual(expected_k, obtained_k)


@allure.parent_suite("Unit Tests")
class CellExtractionResultsTest(unittest.TestCase):
    def test_summarize_overlap(self):
        results = CellExtractionResults(cell_name='Cell')

        ovk1a = OverlapKey(layer_top='m2',
                           net_top='net_top',
                           layer_bot='m1',
                           net_bot='net_bot')

        ovk1b = OverlapKey(layer_top='m2',
                           net_top='net_top',
                           layer_bot='m1',
                           net_bot='net_bot')

        ovk2 = OverlapKey(layer_top='m3',
                           net_top='net_top',
                           layer_bot='m1',
                           net_bot='net_bot')

        ovc1a = OverlapCap(key=ovk1a,
                           cap_value=10.0,
                           shielded_area=20.0,
                           unshielded_area=30.0,
                           tech_spec=None)

        ovc1b = OverlapCap(key=ovk1b,
                           cap_value=11.0,
                           shielded_area=21.0,
                           unshielded_area=31.0,
                           tech_spec=None)

        ovc2 = OverlapCap(key=ovk2,
                          cap_value=12.0,
                          shielded_area=22.0,
                          unshielded_area=32.0,
                          tech_spec=None)

        results.add_overlap_cap(ovc1a)
        results.add_overlap_cap(ovc2)
        results.add_overlap_cap(ovc1b)

        summary = results.summarize()
        obtained_cap_value = summary.capacitances[NetCoupleKey('net_top', 'net_bot').normed()]
        expected_cap_value = ovc1a.cap_value + ovc1b.cap_value + ovc2.cap_value
        self.assertEqual(expected_cap_value, obtained_cap_value)

    def test_summarize_sidewall(self):
        results = CellExtractionResults(cell_name='Cell')

        k1a = SidewallKey(layer='m2',
                          net1='net1',
                          net2='net2')

        k1b = SidewallKey(layer='m2',
                          net1='net2',
                          net2='net1')

        k2 = SidewallKey(layer='m3',
                         net1='net1',
                         net2='net3')

        c1a = SidewallCap(key=k1a,
                          cap_value=10.0,
                          distance=20.0,
                          length=30.0,
                          tech_spec=None)

        c1b = SidewallCap(key=k1b,
                          cap_value=11.0,
                          distance=21.0,
                          length=31.0,
                          tech_spec=None)

        c2 = SidewallCap(key=k2,
                         cap_value=12.0,
                         distance=22.0,
                         length=32.0,
                         tech_spec=None)

        results.add_sidewall_cap(c1a)
        results.add_sidewall_cap(c1b)
        results.add_sidewall_cap(c2)

        summary = results.summarize()

        obtained_cap_value = summary.capacitances[NetCoupleKey('net1', 'net2').normed()]
        expected_cap_value = c1a.cap_value + c1b.cap_value
        self.assertEqual(expected_cap_value, obtained_cap_value)

        obtained_cap_value = summary.capacitances[NetCoupleKey('net1', 'net3').normed()]
        expected_cap_value = c2.cap_value
        self.assertEqual(expected_cap_value, obtained_cap_value)

    def test_summarize_sideoverlap(self):
        results = CellExtractionResults(cell_name='Cell')

        k1a = SideOverlapKey(layer_inside='m2',
                             net_inside='net2',
                             layer_outside='m1',
                             net_outside='net1')

        k1b = SideOverlapKey(layer_inside='m1',
                             net_inside='net1',
                             layer_outside='m2',
                             net_outside='net2')

        k2 = SideOverlapKey(layer_inside='m3',
                            net_inside='net3',
                            layer_outside='m1',
                            net_outside='net1')

        c1a = SideOverlapCap(key=k1a,
                             cap_value=10.0)

        c1b = SideOverlapCap(key=k1b,
                             cap_value=10.0)

        c2 = SideOverlapCap(key=k2,
                            cap_value=10.0)

        results.add_sideoverlap_cap(c1a)
        results.add_sideoverlap_cap(c1b)
        results.add_sideoverlap_cap(c2)

        summary = results.summarize()

        obtained_cap_value = summary.capacitances[NetCoupleKey('net1', 'net2').normed()]
        expected_cap_value = c1a.cap_value + c1b.cap_value
        self.assertEqual(expected_cap_value, obtained_cap_value)

        obtained_cap_value = summary.capacitances[NetCoupleKey('net1', 'net3').normed()]
        expected_cap_value = c2.cap_value
        self.assertEqual(expected_cap_value, obtained_cap_value)
