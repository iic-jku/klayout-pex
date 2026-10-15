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
from typing import *

import allure
import pytest

from rcx25_test_helpers import *
from klayout_pex.netlist.netlist_format import NetlistFormat
from klayout_pex.netlist.spice_reader import SpiceReader
from tests.common.vacask import assert_same_nets_and_values, read_vacask_subcircuits


parent_suite = "kpex/2.5D Extraction Tests [VACASK netlist]"
tags = ("PEX", "2.5D", "VACASK")


def vacask_and_spice_netlists(extraction: RCX25Extraction, *path_components) -> Tuple[str, str]:
    """
    :return: the paths of the VACASK and the SPICE netlist of the extraction
    """
    paths = extraction.written_netlist_paths(*path_components, netlist_format=NetlistFormat.VACASK)
    assert paths[NetlistFormat.VACASK].endswith('_k25d_pex_netlist.inc')
    return paths[NetlistFormat.VACASK], paths[NetlistFormat.SPICE]


def assert_vacask_netlist_is_the_spice_netlist(extraction: RCX25Extraction, *path_components) -> str:
    """
    :return: the VACASK netlist
    """
    vacask_path, spice_path = vacask_and_spice_netlists(extraction, *path_components)
    with open(vacask_path) as f:
        vacask_text = f.read()
    # NOTE: the SPICE netlist has the capacitances with 6 significant digits
    assert_same_nets_and_values(SpiceReader().read(spice_path), vacask_text, rel_tol=5e-6)
    return vacask_text


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_rc_netlist_of_wire_with_t_junction_sky130A():
    # NOTE: the node of the T junction of the net A,B,C, which the SPICE netlist (and so the VACASK netlist)
    #       names A|B|C, as KLayout's SPICE writer does
    extraction = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.RC, blackbox=False)
    text = assert_vacask_netlist_is_the_spice_netlist(extraction, 'test_patterns', 'r_wire_voltage_divider_li1.gds.gz')
    instances = read_vacask_subcircuits(text)['r_wire_voltage_divider_li1'].instances
    assert instances['Rext_1'].nodes == ['A', 'A|B|C']
    assert instances['Rext_1'].master == 'resistor'
    assert instances['Cext_2'].master == 'capacitor'


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_rc_netlist_of_nmos_ihp_sg13g2():
    extraction = RCX25Extraction(pdk=PDKTestConfig(PDKName.IHP_SG13G2), pex_mode=PEXMode.RC, blackbox=True)
    text = assert_vacask_netlist_is_the_spice_netlist(extraction, 'test_patterns', 'nmos_metal1_redux.gds.gz')
    mos = [i for i in read_vacask_subcircuits(text)['nmos_metal1_redux'].instances.values()
           if i.master == 'sg13_lv_nmos']
    assert len(mos) == 1


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_rc_netlist_of_rfcmim_ihp_sg13g2():
    # NOTE: the VACASK subcircuit cap_rfcmim of the IHP PDK declares m
    extraction = RCX25Extraction(pdk=PDKTestConfig(PDKName.IHP_SG13G2), pex_mode=PEXMode.RC, blackbox=True)
    text = assert_vacask_netlist_is_the_spice_netlist(extraction, 'sg13g2_pr__rfcmim', 'rfcmim.gds.gz')
    caps = [i for i in read_vacask_subcircuits(text)['rfcmim'].instances.values() if i.master == 'cap_rfcmim']
    assert len(caps) == 1
    assert caps[0].parameters['m'] == '1'
