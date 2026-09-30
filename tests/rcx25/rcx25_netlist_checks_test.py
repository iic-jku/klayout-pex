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

import os
import tempfile

import allure
import pytest

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.pdk_config import PDK

TEST_DESIGNS_DIR = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata', 'designs'))

DESIGNS = [
    (PDK.SKY130A, 'sky130_fd_sc_hd__inv_1/sky130_fd_sc_hd__inv_1.gds.gz'),
    (PDK.SKY130A, 'inv/inv.gds.gz'),
    (PDK.SKY130A, 'test_patterns/nfet_li1_redux.gds.gz'),
    pytest.param(PDK.SKY130A, 'cap_vpp_04p4x04p6_l1m1m2_noshield/cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz',
                 marks=pytest.mark.xfail(strict=True,
                                         reason="the whiteboxed MOM cap leaves its port SUB touching nothing, "
                                                "as the substrate capacitances are on VSUBS")),
    (PDK.GF180MCUD, 'test_patterns/nfet_m1.gds.gz'),
    (PDK.IHP_SG13G2, 'sg13g2_a21o_1/sg13g2_a21o_1.gds.gz'),
    (PDK.IHP_SG13G2, 'rfnmos/rfnmos_w1u_l0u72.gds.gz'),
    (PDK.IHP_SG13G2, 'test_patterns/nmos_metal1_redux_twice.gds.gz'),
    (PDK.IHP_SG13G2, 'test_patterns/nmos_metal1_redux_two_drain_labels.gds.gz'),
    (PDK.IHP_SG13G2, 'test_patterns/nmos_metal1_redux_two_labels_one_node.gds.gz'),
    (PDK.IHP_SG13CMOS5L, 'cap_cmomf_w5u_l5u_m1_m4/cap_cmomf_w5u_l5u_m1_m4.gds.gz'),
]


@allure.parent_suite("kpex/2.5D Extraction Tests [RC netlist checks]")
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
@pytest.mark.parametrize('mode', ['R', 'RC'])
@pytest.mark.parametrize('pdk,gds', DESIGNS)
def test_rc_netlist_is_consistent(pdk: PDK, gds: str, mode: str):
    # NOTE: each defect of #211 §6, §10, §11 fails these checks (#215)
    with tempfile.TemporaryDirectory() as out_dir:
        cli = KpexCLI()
        cli.main(['main',
                  '--pdk', pdk,
                  '--mode', mode,
                  '--gds', os.path.join(TEST_DESIGNS_DIR, pdk, gds),
                  '--out_dir', out_dir,
                  '--2.5D'])
    assert cli.rcx25_netlist_problems == []
