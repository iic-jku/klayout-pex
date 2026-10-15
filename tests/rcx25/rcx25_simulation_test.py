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
The RC netlists of test patterns, simulated in ngspice and Xyce: their port admittance is the one
of the R and C elements they have, as SpiceRCNetlist reads them
"""

from __future__ import annotations

import os
from typing import *

import allure
import numpy as np
import pytest

from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist
from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.ngspice import ngspice_executable, ngspice_port_admittance
from tests.common.rc_networks import port_admittance
from tests.common.xyce import xyce_executable, xyce_port_admittance
from tests.rcx25.rcx25_test_helpers import PDKName, PDKTestConfig, RCX25Extraction

parent_suite = "kpex/2.5D RC netlists in simulators"
tags = ("PEX", "2.5D", "RC", "Simulation")

extraction = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.RC, blackbox=False)

SIMULATORS = {
    'ngspice': (ngspice_executable, ngspice_port_admittance),
    'Xyce': (xyce_executable, xyce_port_admittance),
}


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.parametrize('simulator', SIMULATORS.keys())
@pytest.mark.parametrize('gds_name, reduce_args', [
    # NOTE: patterns with pins, else all nodes are internal (and TICER eliminates them)
    ('cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz', []),
    ('cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz', ['--reduce', 'ticer']),
    # NOTE: the floating plate has no DC path, which the AC analysis needs for its operating point
    ('cap_vpp_04p4x04p6_l1m1m2_noshield_m2_wire.gds.gz', ['--reduce', 'floating']),
])
def test_rc_netlist_simulates_to_the_port_admittance_of_its_elements(simulator: str, gds_name: str,
                                                                     reduce_args: List[str], tmp_path):
    executable, simulated_port_admittance = SIMULATORS[simulator]
    if executable() is None:
        pytest.skip(f"{simulator} is not on the PATH")

    cli = extraction.run_kpex('test_patterns', gds_name, extra_args=reduce_args)
    netlist_path = cli.rcx25_reduced_netlist_path or f"{os.path.splitext(cli.rcx25_extracted_csv_path)[0]}.spice"
    scope = next(s for s in SpiceRCNetlist.read(netlist_path).scopes if s.network.nodes())
    with open(netlist_path) as f:
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
