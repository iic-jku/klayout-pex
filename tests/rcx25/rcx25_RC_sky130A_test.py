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
from collections import defaultdict
import tempfile

import allure
import pytest

from rcx25_test_helpers import *
from klayout_pex.rcx25.extraction_results import NetCoupleKey, NetworkNodeNames


parent_suite = "kpex/2.5D Extraction Tests [PDK sky130A | mode RC]"
tags = ("PEX", "2.5D")


pex_whiteboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.RC, blackbox=False)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_wire_voltage_divider_li1():
    # NOTE: the capacitance of the wire (0.969 fF in CC mode) goes to the nodes of its resistor network,
    #       each part of it to the node nearest to it (#211 §8): the T junction A,B,C has the middle half
    #       of the wire from A to B, and the lower half of the stub to C
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'r_wire_voltage_divider_li1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;VSUBS;0.223;
C2;A,B,C;VSUBS;0.459;
C3;B;VSUBS;0.23;
C4;C;VSUBS;0.056;
R1;A;A,B,C;;426.667
R2;A,B,C;B;;413.867
R3;A,B,C;C;;72.533"""
    )


def capacitances_by_net_pair(pex_mode: PEXMode, *path_components) -> Dict[NetCoupleKey, float]:
    """
    The capacitances of the summary, by the pair of nets of their nodes
    """
    pdk = PDKTestConfig(PDKName.SKY130A)
    with tempfile.TemporaryDirectory() as out_dir:
        cli = KpexCLI()
        cli.main(['main', '--pdk', pdk.name, '--mode', pex_mode, '--gds', pdk.gds_path(*path_components),
                  '--out_dir', out_dir, '--cache-dir', pdk.lvs_cache_dir, '--2.5D'])
    results = list(cli.rcx25_extraction_results.cell_extraction_results.values())[0]

    net_by_node: Dict[str, str] = {}
    port_names_by_net = results.label_port_names()
    for network in results.r_extraction_result.networks:
        node_names = NetworkNodeNames.from_network(network, port_names_by_net.get(network.net_name, {}))
        for node_name in node_names.by_node_id.values():
            net_by_node[node_name] = network.net_name

    capacitances: Dict[NetCoupleKey, float] = defaultdict(float)
    for key, capacitance in results.summarize().capacitances.items():
        capacitances[NetCoupleKey(net_by_node.get(key.net1, key.net1),
                                  net_by_node.get(key.net2, key.net2)).normed()] += capacitance
    return capacitances


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.parametrize('path_components', [
    ('sky130_fd_sc_hd__inv_1', 'sky130_fd_sc_hd__inv_1.gds.gz'),
    ('cap_vpp_04p4x04p6_l1m1m2_noshield', 'cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz'),
])
def test_capacitances_between_each_pair_of_nets_are_the_ones_of_CC_mode(path_components: Tuple[str, str]):
    # NOTE: in RC mode, the capacitances are distributed onto the nodes of the resistor networks (#211 §8),
    #       so there are more of them, but their sum between each pair of nets is the same
    cc = capacitances_by_net_pair(PEXMode.CC, *path_components)
    rc = capacitances_by_net_pair(PEXMode.RC, *path_components)
    assert set(cc) == set(rc)
    for key, capacitance in cc.items():
        assert rc[key] == pytest.approx(capacitance, rel=1e-12), key
