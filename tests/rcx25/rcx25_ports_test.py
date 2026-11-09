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

"""
The ports of the netlists of test patterns: a port for each pin label of the top cell, also of a net without devices,
which KLayout's LVS netlist has no pin for, but none for a label without a pin shape there
"""

from __future__ import annotations

from typing import *

import allure
import pytest

from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction, netlist_ports

parent_suite = "kpex/2.5D netlist ports"
tags = ("PEX", "2.5D", "Ports")


def ports_of(pdk_name: PDKName, gds_name: str, mode: PEXMode,
             extra_args: Sequence[str] = ()) -> List[str]:
    """
    :return: the ports of the netlist of the test pattern, which has to pass the checks of the netlist
    """
    pdk = PDKTestConfig(pdk_name)
    cli = RCX25Extraction(pdk=pdk, pex_mode=mode, blackbox=False) \
        .run_kpex('test_patterns', gds_name,
                  extra_args=['--gds', pdk.gds_path('test_patterns', gds_name), *extra_args])
    assert cli.rcx25_netlist_problems == []
    return netlist_ports(cli)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.CC, PEXMode.R, PEXMode.RC])
@pytest.mark.parametrize('gds_name', ['internal_child_label.gds.gz', 'internal_child_labels.gds.gz'])
def test_top_pin_keeps_disconnected_child_labels_internal(gds_name: str, mode: PEXMode):
    ports = ports_of(PDKName.IHP_SG13G2, gds_name, mode)
    assert sorted(port for port in ports if port != 'sub!') == ['outer']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.CC, PEXMode.R, PEXMode.RC])
@pytest.mark.parametrize('policy, expected', [('auto', ['inner']), ('top', [])])
def test_child_only_ports_can_be_disabled(mode: PEXMode, policy: str, expected: List[str]):
    ports = ports_of(PDKName.IHP_SG13G2, 'label_only_in_child_cell.gds.gz', mode,
                     ['--port-labels', policy])
    assert sorted(port for port in ports if port != 'sub!') == expected


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('gds_name, mode, ports', [
    # NOTE: the wire of the pins A, B and C is the net A,B,C, which has a port per label in R and RC mode
    #       (#211 §11), and one node in CC mode
    ('r_wire_voltage_divider_li1.gds.gz', PEXMode.CC, ['A|B|C', 'sky130_gnd']),
    ('r_wire_voltage_divider_li1.gds.gz', PEXMode.R, ['A', 'B', 'C']),
    ('r_wire_voltage_divider_li1.gds.gz', PEXMode.RC, ['A', 'B', 'C', 'sky130_gnd']),
    # NOTE: the met2 wire D under the MIM cap has no device, the plates A and B have
    ('cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz', PEXMode.R, ['A', 'B', 'D']),
    ('cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz', PEXMode.RC, ['A', 'B', 'D', 'sky130_gnd']),
])
def test_nets_without_devices_have_the_ports_of_their_pins(gds_name: str, mode: PEXMode, ports: List[str]):
    assert ports_of(PDKName.SKY130A, gds_name, mode) == ports


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.CC, PEXMode.R, PEXMode.RC])
@pytest.mark.parametrize('policy', ['auto', 'top'])
def test_labels_without_pin_shapes_make_no_ports_of_their_own(mode: PEXMode, policy: str):
    # NOTE: the label W names its wire, which has no devices, without making it a port, like a label of the text
    #       layer of Magic, and the label Q names the wire of the pin P with it, one port P|Q, as in CC mode,
    #       while the label OUT names the net of the drain of the MOS, which has a port anyway, but no pin label (#405)
    assert ports_of(PDKName.IHP_SG13G2, 'labels_without_pin_shapes.gds.gz', mode,
                     ['--port-labels', policy]) == ['OUT', 'VDD', 'sub!', 'P|Q']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('gds_name, ports', [
    # NOTE: the wire of the pin outer of the top cell also has the pin inner of the child cell
    ('label_in_child_cell.gds.gz', ['outer']),
    # NOTE: the pins VDD and VSS of the child cell are on the wires of the pins A and B of the top cell
    ('cut_block_with_mos.gds.gz', ['A', 'B', 'R']),
    # NOTE: the wire of the top cell between the pins a and b of the child cells has no label, so KLayout leaves it
    #       unnamed, and kpex names it after both, like KLayout a net of several labels, one port at the first (#417)
    ('labels_in_child_cells.gds.gz', ['a|b']),
])
def test_labels_in_child_cells_are_no_ports_of_the_top_cell(gds_name: str, ports: List[str]):
    def without_substrate(mode: PEXMode) -> List[str]:
        # NOTE: in R mode, the substrate only is a port of a netlist with devices on it
        return sorted(port for port in ports_of(PDKName.IHP_SG13G2, gds_name, mode) if port != 'sub!')

    ports_cc = without_substrate(PEXMode.CC)
    assert ports_cc == ports
    assert without_substrate(PEXMode.RC) == ports_cc
    assert without_substrate(PEXMode.R) == ports_cc


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode', [PEXMode.CC, PEXMode.R, PEXMode.RC])
def test_net_of_labels_in_child_cells_that_the_top_cell_joins_is_a_port_of_their_name(mode: PEXMode):
    # NOTE: the VDD rails of 3 abutting standard cells, which KLayout leaves unnamed ($I1), and the labels X, A1, A2
    #       and B1 of each cell, which keep the paths of their cells ($1.X), as their names aren't unique (#417)
    ports = ports_of(PDKName.IHP_SG13G2, 'cut_abutting_std_cells.gds.gz', mode)
    assert 'VDD' in ports, ports
    assert sorted(port for port in ports if port.endswith('.X')) == [r'\$1.X', r'\$2.X', r'\$3.X']
