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

import glob
import os
import tempfile
from unittest import mock

import allure
import pytest

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.pdk_config import PDK
from klayout_pex.pex25d.diagnostics import ExitCode

TEST_DESIGNS_DIR = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata', 'designs'))

DESIGNS = [
    (PDK.SKY130A, 'sky130_fd_sc_hd__inv_1/sky130_fd_sc_hd__inv_1.gds.gz'),
    (PDK.SKY130A, 'inv/inv.gds.gz'),
    (PDK.SKY130A, 'test_patterns/nfet_li1_redux.gds.gz'),
    (PDK.SKY130A, 'cap_vpp_04p4x04p6_l1m1m2_noshield/cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz'),
    (PDK.GF180MCUD, 'test_patterns/nfet_m1.gds.gz'),
    (PDK.IHP_SG13G2, 'sg13g2_a21o_1/sg13g2_a21o_1.gds.gz'),
    (PDK.IHP_SG13G2, 'rfnmos/rfnmos_w1u_l0u72.gds.gz'),
    (PDK.IHP_SG13G2, 'cap_vpp_04p4x04p6_m1m2m3_substrate_pin/cap_vpp_04p4x04p6_m1m2m3_substrate_pin.gds.gz'),
    (PDK.IHP_SG13G2, 'test_patterns/nmos_metal1_redux_twice.gds.gz'),
    (PDK.IHP_SG13G2, 'test_patterns/nmos_metal1_redux_two_drain_labels.gds.gz'),
    (PDK.IHP_SG13G2, 'test_patterns/nmos_metal1_redux_two_labels_one_node.gds.gz'),
    (PDK.IHP_SG13CMOS5L, 'cap_cmomf_w5u_l5u_m1_m4/cap_cmomf_w5u_l5u_m1_m4.gds.gz'),
]


EXPECTED_FAILURES = {
    ('cap_vpp_04p4x04p6_l1m1m2_noshield/cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz', 'R'):
        "in R mode, the whiteboxed MOM cap leaves its port SUB touching nothing, as there are no capacitances",
}


@allure.parent_suite("kpex/2.5D Extraction Tests [RC netlist checks]")
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
@pytest.mark.parametrize('mode', ['R', 'RC'])
@pytest.mark.parametrize('pdk,gds', DESIGNS)
def test_rc_netlist_is_consistent(pdk: PDK, gds: str, mode: str, request: pytest.FixtureRequest):
    # NOTE: each defect of #211 §6, §10, §11 fails these checks (#215)
    reason = EXPECTED_FAILURES.get((gds, mode), None)
    if reason is not None:
        request.applymarker(pytest.mark.xfail(strict=True, reason=reason))
    with tempfile.TemporaryDirectory() as out_dir:
        cli = KpexCLI()
        cli.main(['main',
                  '--pdk', pdk,
                  '--mode', mode,
                  '--gds', os.path.join(TEST_DESIGNS_DIR, pdk, gds),
                  '--out_dir', out_dir,
                  '--2.5D',
                  '--check', 'n'])  # NOTE: the problems, rather than a failed run
    assert cli.rcx25_netlist_problems == []


INV_1_GDS = os.path.join(TEST_DESIGNS_DIR, PDK.SKY130A, 'sky130_fd_sc_hd__inv_1', 'sky130_fd_sc_hd__inv_1.gds.gz')
PROBLEMS = ['port Y touches nothing']


@allure.parent_suite("kpex/2.5D Extraction Tests [RC netlist checks]")
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_inconsistent_rc_netlist_fails_the_run_after_writing_it():
    # NOTE: --check is on by default in RC mode (#215)
    with tempfile.TemporaryDirectory() as out_dir, \
         mock.patch('klayout_pex.kpex_cli.check_rc_netlist', return_value=PROBLEMS), \
         mock.patch('klayout_pex.kpex_cli.error') as error_mock, \
         pytest.raises(SystemExit) as exit_info:
        try:
            KpexCLI().main(['main', '--pdk', PDK.SKY130A, '--mode', 'RC', '--gds', INV_1_GDS,
                            '--out_dir', out_dir, '--2.5D'])
        finally:
            netlists = glob.glob(os.path.join(out_dir, '*', '*_k25d_pex_netlist.spice'))
    assert exit_info.value.code == ExitCode.DIAGNOSTIC_ERRORS
    assert [c.args[0] for c in error_mock.call_args_list] == [
        "The extracted netlist is inconsistent with the LVS netlist (--check n to accept it):\n"
        "  - port Y touches nothing"
    ]
    assert len(netlists) == 1


@allure.parent_suite("kpex/2.5D Extraction Tests [RC netlist checks]")
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
@pytest.mark.parametrize('arguments', [['--mode', 'RC', '--check', 'n'],
                                       ['--mode', 'R']])  # NOTE: --check is off by default but in RC mode
def test_inconsistent_netlist_only_warns_without_check(arguments: list):
    with tempfile.TemporaryDirectory() as out_dir, \
         mock.patch('klayout_pex.kpex_cli.check_rc_netlist', return_value=PROBLEMS), \
         mock.patch('klayout_pex.kpex_cli.warning') as warning_mock:
        cli = KpexCLI()
        cli.main(['main', '--pdk', PDK.SKY130A, '--gds', INV_1_GDS, '--out_dir', out_dir, '--2.5D', *arguments])
    assert cli.rcx25_netlist_problems == PROBLEMS
    assert "The extracted netlist is inconsistent with the LVS netlist:\n  - port Y touches nothing" \
           in [c.args[0] for c in warning_mock.call_args_list]
