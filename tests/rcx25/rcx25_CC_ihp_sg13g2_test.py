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

import allure
import csv
import pytest

from rcx25_test_helpers import *

parent_suite = "kpex/2.5D Extraction Tests [PDK ihp-sg13g2 | mode CC]"
tags = ("PEX", "2.5D")


pex_whiteboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.IHP_SG13G2), pex_mode=PEXMode.CC, blackbox=False)
pex_blackboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.IHP_SG13G2), pex_mode=PEXMode.CC, blackbox=True)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mim_cap__whiteboxed():
    # The device model gives cap_carea 1.5 fF/µm² * 6.99 µm * 6.99 µm = 73.29 fF
    # plus CJSW 40 aF/µm * 27.96 µm = 1.12 fF, the fringe to the bottom plate (Metal5) around the top plate (MIM)
    # NOTE: the plates' nets have no labels, so their names ($1, $2, ...) depend on the LVS run
    _, csv_path, _ = pex_whiteboxed.run_rcx25d_single_cell('sg13g2_pr__cmim', 'cmim.gds.gz')
    with open(csv_path) as f:
        rows = list(csv.DictReader(f, delimiter=';'))
    caps = [(('VSUBS' in (row['Net1'], row['Net2'])), float(row['Capacitance [fF]'])) for row in rows]
    assert sorted(cap for to_substrate, cap in caps if not to_substrate) == [74.784]  # between the plates
    assert sorted(cap for to_substrate, cap in caps if to_substrate) == [0.878, 1.38]  # top and bottom plate


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mom_cap__whiteboxed():
    # The device model gives 0.915 fF/µm² (fingers on Metal2 … Metal4) * 10 µm * 25 µm = 228.75 fF
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'cap_cmomf_w10u_l25u_m2_m4_m5_wire.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;MINUS;PLUS;205.148;
C2;MINUS;VSUBS;6.757;
C3;MINUS;X;1.805;
C4;PLUS;VSUBS;6.829;
C5;PLUS;X;1.911;
C6;VSUBS;X;1.292;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mom_cap__blackboxed():
    # The fingers of the MOM cap are metal of its terminal nets, so --blackbox extracted their capacitance
    # on top of the device, whose model has it: 205.148 fF more between PLUS and MINUS (#211 §9).
    # The model has no substrate terminal, so the capacitances of the fingers to the substrate
    # and to the wire X across are extracted, the same as in white-box mode
    pex_blackboxed.assert_expected_matches_obtained(
        'test_patterns', 'cap_cmomf_w10u_l25u_m2_m4_m5_wire.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;MINUS;VSUBS;6.757;
C2;MINUS;X;1.805;
C3;PLUS;VSUBS;6.829;
C4;PLUS;X;1.911;
C5;VSUBS;X;1.292;"""
    )
