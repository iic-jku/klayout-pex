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
import pytest

from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction

parent_suite = "kpex/2.5D Extraction Tests [PDK ihp-sg13g2 | mode CC]"
tags = ("PEX", "2.5D")


pex_whiteboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.IHP_SG13G2), pex_mode=PEXMode.CC, blackbox=False)
pex_blackboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.IHP_SG13G2), pex_mode=PEXMode.CC, blackbox=True)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mim_cap__whiteboxed():
    # The device model gives cap_carea 1.5 fF/µm² * 6.99 µm * 6.99 µm = 73.29 fF
    # plus CJSW 40 aF/µm * 27.96 µm = 1.12 fF, the fringe to the bottom plate (Metal5) around the top plate (MIM)
    # NOTE: the plates' nets have no labels, so their names ($1, $2, ...) depend on the LVS run
    rows = pex_whiteboxed.written_netlist_rows('sg13g2_pr__cmim', 'cmim.gds.gz')
    caps = [(('VSUBS' in (row['Net1'], row['Net2'])), float(row['Capacitance [fF]'])) for row in rows]
    assert sorted(cap for to_substrate, cap in caps if not to_substrate) == [74.784]  # between the plates
    assert sorted(cap for to_substrate, cap in caps if to_substrate) == [0.878, 1.38]  # top and bottom plate


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_rf_mim_cap__whiteboxed():
    # The top plate of the rfcmim (MIM 7 µm x 7 µm, cap_carea 1.5 fF/µm² gives 73.5 fF) is a conductor,
    # like the one of the cmim: it was left out, as the deck's cmim_top leaves out the RF areas (#280),
    # and the plates had 2.7 fF between them
    rows = pex_whiteboxed.written_netlist_rows('sg13g2_pr__rfcmim', 'rfcmim.gds.gz')
    assert [float(row['Capacitance [fF]']) for row in rows
            if not {'VSUBS', 'sub!'} & {row['Net1'], row['Net2']}] == [75.262]  # between the plates


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_rf_mim_cap_over_m4_wire__whiteboxed():
    # The rfcmim of test_rf_mim_cap__whiteboxed, with a Metal4 wire D under it,
    # which its bottom plate (MINUS) shields from its top plate (PLUS)
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'cap_rfcmim_w7u_l7u_over_m4_wire.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;D;MINUS;1.252;
C2;D;PLUS;0.077;
C3;D;sub!;0.343;
C4;D;VSUBS;1.359;
C5;MINUS;PLUS;75.262;
C6;MINUS;sub!;0.345;
C7;MINUS;VSUBS;1.499;
C8;PLUS;sub!;0.254;
C9;PLUS;VSUBS;1.134;
C10;VSUBS;sub!;4.878;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_rf_mim_cap_over_m4_wire__blackboxed():
    # The plates of the rfcmim are conductors, so the capacitances to the wire D are the white-box ones.
    # Its model has the capacitance between the plates, and the one of its Metal5 (MINUS) to the substrate
    # (Cox, 2.39 fF here), its terminal bn, so these are left out: MINUS–PLUS is the TopMetal1 over the Metal5
    # around the MIM, MINUS–VSUBS the feed outside the PWellBlock, MINUS–sub! the Metal1 of the ptap ring.
    # Without the plates, D coupled to PLUS through the hole (0.366 fF), MINUS–PLUS had 0.758 fF more
    # from the cut edges of the Metal5, and MINUS–VSUBS was 1.529 fF
    pex_blackboxed.assert_expected_matches_obtained(
        'test_patterns', 'cap_rfcmim_w7u_l7u_over_m4_wire.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;D;MINUS;1.252;
C2;D;PLUS;0.077;
C3;D;sub!;0.343;
C4;D;VSUBS;1.359;
C5;MINUS;PLUS;0.585;
C6;MINUS;sub!;0.201;
C7;MINUS;VSUBS;0.22;
C8;PLUS;sub!;0.254;
C9;PLUS;VSUBS;1.134;
C10;VSUBS;sub!;4.878;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mim_cap_over_m4_wire__whiteboxed():
    # The device model gives cap_carea 1.5 fF/µm² * 20 µm * 20 µm = 600 fF (MIM over Metal5)
    # plus CJSW 40 aF/µm * 80 µm = 3.2 fF, the fringe to the bottom plate around the top plate
    # (3.166 fF from MIM to Metal5 here). A–B has the fringe from TopMetal1 to the Metal5 around the MIM too (2.659 fF)
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'cap_cmim_20um_x_20um_over_m4_wire.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;B;605.825;
C2;A;D;5.343;
C3;A;VSUBS;6.342;
C4;B;D;0.084;
C5;B;VSUBS;2.344;
C6;D;VSUBS;3.462;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mim_cap_over_m4_wire__blackboxed():
    # The plates of the MIM cap are conductors, the bottom plate shields the wire D and the substrate below it
    # from the top plate and the TopMetal1 above. Only the capacitance of the device model is left out, the overlap
    # of MIM over Metal5 and the fringe from its edge, so A–B is the fringe from TopMetal1 to the Metal5 around the MIM,
    # and the rest is the same as in white-box mode. Without the plates, D coupled to B through the hole (1.62 fF)
    pex_blackboxed.assert_expected_matches_obtained(
        'test_patterns', 'cap_cmim_20um_x_20um_over_m4_wire.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;B;2.659;
C2;A;D;5.343;
C3;A;VSUBS;6.342;
C4;B;D;0.084;
C5;B;VSUBS;2.344;
C6;D;VSUBS;3.462;"""
    )


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
C3;MINUS;X;1.716;
C4;PLUS;VSUBS;6.829;
C5;PLUS;X;1.786;
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
C2;MINUS;X;1.716;
C3;PLUS;VSUBS;6.829;
C4;PLUS;X;1.786;
C5;VSUBS;X;1.292;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_rf_mim_cap__blackboxed():
    # The rfcmim of the PDK's cell library (sg13g2_pr), its model is cap_rfcmim, with the substrate as 3rd terminal
    assert pex_blackboxed.written_device_lines('sg13g2_pr__rfcmim', 'rfcmim.gds.gz') == [
        'X$1 \\$5 \\$4 sub! cap_rfcmim w=7e-06 l=7e-06 m=1 wfeed=3e-06',
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_single_plate_over_isolated_pwell():
    # The isolated p-well (the hole of the NWell ring $3 over nBuLay) is a net of its own, W by its p-tap:
    # the plate couples to it, only its fringe beyond the ring to the substrate (VSUBS).
    # It was the substrate: A–VSUBS 2.496 fF, A–W 0.013 fF (#337)
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'single_plate_6um_x_8um_m1_over_isolated_pwell.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;$3;A;0.274;
C2;$3;W;0.008;
C3;A;VSUBS;0.261;
C4;A;W;2.247;
C5;VSUBS;W;0.012;"""
    )
