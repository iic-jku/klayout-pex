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

"""
What the field solver leaves to a model of what is marked, on the test patterns of the 2.5D engine (see
tests/rcx25/rcx25_exclusion_test.py), with the values of the solver as trends only (it's no reference):
the conductors within a block stay in its model, so the values around them stay
"""

import csv
from collections import defaultdict
from typing import *
from unittest import mock

import allure
import pytest

from klayout_pex.kpex_cli import KpexCLI
from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import pair

parent_suite = "kpex/FasterCap Exclusions"
tags = ("PEX", "FasterCap", "Exclusion")

# NOTE: of values that differ by the panels at the end of a part only, as the solver has tolerances (0.01 by default)
TOLERANCE = 0.05

pdk = PDKTestConfig(PDKName.IHP_SG13G2)


def capacitances(cell_name: str, *arguments: str) -> Dict[FrozenSet[str], float]:
    """
    :return: the capacitances of FasterCap in fF, by their nets, also to infinity, which go to the substrate
    """
    gds_path = pdk.gds_path('test_patterns', f"{cell_name}.gds.gz")
    cli = KpexCLI()
    cli.main(['main', 'extract',
              '--pdk', pdk.name,
              '--gds', gds_path,
              '--lvsdb', lvsdb_fixture_path(pdk.name, gds_path),
              '--out-dir', pdk.output_dir,
              '--fastercap',
              *arguments])
    values: Dict[FrozenSet[str], float] = defaultdict(float)
    with open(cli.fastercap_extracted_csv_path, encoding='utf-8') as f:
        for row in csv.DictReader(f, delimiter=';'):
            values[frozenset((row['Net1'], row['Net2']))] += float(row['Capacitance [fF]'])
    return dict(values)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.fastercap
def test_what_is_outside_a_marker_keeps_its_values():
    ignored = capacitances('exclusion_plate_neighbor')
    honored = capacitances('exclusion_plate_neighbor', '--exclusion-markers', 'tie')

    assert ignored[pair('P', 'sub!')] > 0.0
    assert pair('P', 'sub!') not in honored
    assert honored[pair('N', 'P')] == pytest.approx(ignored[pair('N', 'P')], rel=TOLERANCE)
    assert honored[pair('N', 'sub!')] == pytest.approx(ignored[pair('N', 'sub!')], rel=TOLERANCE)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.fastercap
def test_wire_across_a_marker_has_the_capacitance_of_its_part_outside():
    # NOTE: half of this wire is within the marker
    ignored = capacitances('exclusion_wire_end')
    honored = capacitances('exclusion_wire_end', '--exclusion-markers', 'tie')
    assert honored[pair('W', 'sub!')] == pytest.approx(ignored[pair('W', 'sub!')] / 2.0, rel=TOLERANCE)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.fastercap
def test_excluded_net_keeps_the_capacitances_of_other_nets():
    ignored = capacitances('exclusion_plate_neighbor')
    excluded = capacitances('exclusion_plate_neighbor', '--exclude-net', 'P')
    assert pair('P', 'sub!') not in excluded
    assert excluded[pair('N', 'P')] == pytest.approx(ignored[pair('N', 'P')], rel=TOLERANCE)
    assert excluded[pair('N', 'sub!')] == pytest.approx(ignored[pair('N', 'sub!')], rel=TOLERANCE)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.fastercap
def test_parts_of_a_net_add_up_to_the_net_for_the_wires_around_a_cut_cell():
    # NOTE: the coil and its leads are two conductors that touch, the wire VC is under them, the guard ring VDD around,
    #       and the capacitances of these to the net are the sums over the two conductors
    coil = 'OSCN,OSCP,VCT'
    ignored = capacitances('cut_coil')
    cut = capacitances('cut_coil', '--cut', 'coil=xind', '--cut-keep-net', 'VDD')

    for key in (pair('VC', coil), pair('VDD', coil), pair('VC', 'VDD'), pair('VC', 'sub!'), pair('VDD', 'sub!')):
        assert cut[key] == pytest.approx(ignored[key], rel=TOLERANCE), key
    assert cut[pair(coil, 'sub!')] < ignored[pair(coil, 'sub!')] / 2.0


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.fastercap
def test_warns_of_ports_that_its_netlist_cannot_have():
    with mock.patch('klayout_pex.rcx25.extractor.warning') as warning_mock:
        capacitances('exclusion_wire_end', '--exclusion-markers', 'ports')
    assert any('The netlist of a field solver has one node per net' in c.args[0] for c in warning_mock.call_args_list)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.fastercap
def test_order_of_overlapping_marker_layers_does_not_matter():
    regular = ('--exclusion-marker-layer', 'NoRCX.drawing')
    capacitance_pair = ('--exclusion-marker-layer', 'NoRCX.m2m3')
    arguments = ('--exclusion-markers', 'tie')
    first = capacitances('exclusion_overlapping_markers', *arguments, *regular, *capacitance_pair)
    second = capacitances('exclusion_overlapping_markers', *arguments, *capacitance_pair, *regular)
    assert first.keys() == second.keys()
    for nets, value in first.items():
        assert second[nets] == pytest.approx(value, rel=TOLERANCE)
