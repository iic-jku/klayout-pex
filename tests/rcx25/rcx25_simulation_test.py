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
The RC netlists of test patterns as SPICE simulators read them: simulated in ngspice and Xyce, their port
admittance is the one of the R and C elements they have, as SpiceRCNetlist reads them (case-insensitively),
and the netlists of all test patterns have what SPICE needs to read them alike
"""

from __future__ import annotations

import os
import re
from typing import *

import allure
import klayout.db as kdb
import numpy as np
import pytest

from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist
from klayout_pex.pdk_config import PDK
from klayout_pex.rcx25.pex_mode import PEXMode
from klayout_pex.tech_info import TechInfo
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.rc_networks import node_names, port_admittance, value_of
from tests.common.xyce import requires_xyce, xyce_port_admittance
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction

parent_suite = "kpex/2.5D RC netlists in simulators"
tags = ("PEX", "2.5D", "RC", "Simulation")

extraction = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.RC, blackbox=False)

SIMULATORS = [
    pytest.param(ngspice_port_admittance, id='ngspice', marks=requires_ngspice),
    pytest.param(xyce_port_admittance, id='Xyce', marks=requires_xyce),
]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.parametrize('simulated_port_admittance', SIMULATORS)
@pytest.mark.parametrize('gds_name, reduce_args', [
    ('r_wire_voltage_divider_li1.gds.gz', []),
    ('r_wire_voltage_divider_li1.gds.gz', ['--reduce', 'ticer']),
    ('cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz', []),
    ('cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz', ['--reduce', 'ticer']),
    # NOTE: the ports A and a$1, which would be one node if they were A and a
    ('net_names_A_and_a_m2.gds.gz', []),
    ('cap_vpp_04p4x04p6_l1m1m2_noshield_m2_wire.gds.gz', ['--reduce', 'floating']),
])
def test_rc_netlist_simulates_to_the_port_admittance_of_its_elements(
        simulated_port_admittance: Callable[..., Tuple[np.ndarray, np.ndarray]], gds_name: str,
        reduce_args: List[str], tmp_path):

    cli = extraction.run_kpex('test_patterns', gds_name, extra_args=reduce_args)
    netlist_path = cli.rcx25_reduced_netlist_path or f"{os.path.splitext(cli.rcx25_extracted_csv_path)[0]}.spice"
    scope = next(s for s in SpiceRCNetlist.read(netlist_path).scopes if s.network.nodes())
    with open(netlist_path, encoding='utf-8') as f:
        # NOTE: capacitances below 1 fF, which Xyce read as F when they were written in a (atto)
        assert any(line.startswith('C') and line.endswith('f') and ' 0.' in line for line in f.read().splitlines())

    # NOTE: ground (0) is global, the ties to it of the reduction are no port
    nodes = scope.ports + (['0'] if scope.network.find_node('0') is not None else [])
    # NOTE: from 100 MHz, below, the admittance (e.g. 0.1 µS at 1 MHz for the VPP cap) nears the rounding error
    #       of the conductances (up to 30 S there) in double precision, about 1e-13 S, of the simulators and the
    #       nodal analysis alike
    frequencies, y = simulated_port_admittance(netlist_path, scope.name, scope.ports, (8, 11), str(tmp_path))
    for f, y_f in zip(frequencies, y):
        y_expected = port_admittance(scope.network, nodes, f)[:len(scope.ports), :len(scope.ports)]
        # NOTE: to the 9 digits the simulators write
        assert np.linalg.norm(y_f - y_expected) <= 1e-7 * np.linalg.norm(y_expected), f


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_nets_whose_names_differ_in_case_only_stay_apart_in_spice():
    # NOTE: SPICE reads names case-insensitively, ngspice would join the wires A and a, and short their coupling
    cli = extraction.run_kpex('test_patterns', 'net_names_A_and_a_m2.gds.gz')
    netlist_path = f"{os.path.splitext(cli.rcx25_extracted_csv_path)[0]}.spice"
    scope = next(s for s in SpiceRCNetlist.read(netlist_path).scopes if s.network.nodes())
    assert node_names(scope.network) == ['A', 'a$1', 'sky130_gnd']
    assert scope.ports == ['A', 'a$1', 'sky130_gnd']
    assert value_of(scope.network, 'A', 'a$1')[1] > 0.0


def top_cell_pin_labels(gds_path: str, tech: TechInfo) -> Set[str]:
    """
    The labels of the top cell on a pin shape, by the pin and label layers of the tech info
    (not by the pins KPEX extracts, which this checks)
    """
    layout = kdb.Layout()
    layout.read(gds_path)
    top = layout.top_cell()
    labels: Set[str] = set()
    for info in tech.layer_info_by_gds_pair.values():
        if not info.HasField('pin_gds_pair') or not info.HasField('label_gds_pair'):
            continue
        pin_layer = layout.find_layer(info.pin_gds_pair.layer, info.pin_gds_pair.datatype)
        label_layer = layout.find_layer(info.label_gds_pair.layer, info.label_gds_pair.datatype)
        if pin_layer is None or label_layer is None:
            continue
        pins = kdb.Region(top.begin_shapes_rec(pin_layer))
        for text in kdb.Texts(top.shapes(label_layer)).each():
            if not pins.interacting(kdb.Region(kdb.Box(text.position(), text.position()).enlarged(1))).is_empty():
                labels.add(text.string)
    return labels


TEST_PATTERNS = [(pdk_name, name)
                 for pdk_name in PDKName
                 for name in sorted(os.listdir(PDKTestConfig(pdk_name).gds_path('test_patterns')))
                 if name.endswith('.gds.gz')]

# NOTE: the patterns of extraction errors, e.g. vias without a conductor below (see rcx25_R_sky130A_test)
ERROR_PATTERNS = {(PDKName.SKY130A, 'r_via1_without_met1.gds.gz')}

# NOTE: the MOM caps, which take 1.5 to 22 s in RC mode, the others 0.1 s
SLOW_PATTERNS = {(PDKName.SKY130A, 'cap_vpp_04p4x04p6_l1m1m2_noshield_m2_wire.gds.gz'),
                 (PDKName.SKY130A, 'sidewall_cap_vpp_04p4x04p6_l1_redux_all_layers.gds.gz'),
                 (PDKName.IHP_SG13G2, 'cap_cmomf_w10u_l25u_m2_m4_m5_wire.gds.gz'),
                 (PDKName.IHP_SG13G2, 'sidewall_cap_vpp_04p4x04p6_m1_redux_all_layers.gds.gz')}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk_name, gds_name', [
    pytest.param(pdk_name, name, id=f"{pdk_name}/{name}",
                 marks=pytest.mark.slow if (pdk_name, name) in SLOW_PATTERNS else ())
    for pdk_name, name in TEST_PATTERNS if (pdk_name, name) not in ERROR_PATTERNS
])
def test_rc_netlist_of_test_pattern_is_read_alike_by_spice_simulators(pdk_name: PDKName, gds_name: str):
    pdk = PDKTestConfig(pdk_name)
    tech = TechInfo.from_json(PDK.from_string(str(pdk_name)).config.tech_pb_json_path, dielectric_filter=None)
    labels = top_cell_pin_labels(pdk.gds_path('test_patterns', gds_name), tech)

    cli = RCX25Extraction(pdk=pdk, pex_mode=PEXMode.RC, blackbox=False).run_kpex('test_patterns', gds_name)
    assert cli.rcx25_netlist_problems == []
    with open(f"{os.path.splitext(cli.rcx25_extracted_csv_path)[0]}.spice", encoding='utf-8') as f:
        lines = f.read().replace('\n+', '').splitlines()
    ports = next(line for line in lines if line.startswith('.SUBCKT ')).split()[2:]

    # NOTE: a port per pin label (e.g. A$1 if the name is taken), also of a net without devices (#312)
    assert sorted(l for l in labels if not any(p == l or p.startswith(f"{l}$") for p in ports)) == []

    # NOTE: SPICE reads names case-insensitively, names that differ in case only would be one node (#314)
    rc_elements = [line.split() for line in lines if line[:1] in 'RC' and len(line.split()) == 4]
    names = set(ports) | {node for tokens in rc_elements for node in tokens[1:3]}
    assert len({n.casefold() for n in names}) == len(names)

    # NOTE: Xyce reads the scale factor a (atto) as a unit (#313)
    assert [tokens for tokens in rc_elements if re.fullmatch(r'.*[0-9.][aA]', tokens[3])] == []
