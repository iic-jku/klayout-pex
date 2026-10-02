#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/martinjankoehler/klayout-pex).
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
import glob
import os
import pytest
from unittest import mock

from klayout_pex.tech_info import TechInfo
from rcx25_test_helpers import *

CSVPath = str
PNGPath = str
parent_suite = "kpex/2.5D Extraction Tests [PDK sky130A | mode CC]"
tags = ("PEX", "2.5D", "MAGIC")


pex_whiteboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.CC, blackbox=False)
pex_blackboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.CC, blackbox=True)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_single_plate_100um_x_100um_li1_over_substrate():
    # MAGIC GIVES (8.3 revision 485):
    #_______________________________ NOTE: with halo=8µm __________________________________
    # C0 PLATE VSUBS 0.38618p
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'single_plate_100um_x_100um_li1_over_substrate.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;PLATE;VSUBS;386.179;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_overlap_plates_100um_x_100um_li1_m1():
    # MAGIC GIVES (8.3 revision 485):
    #_______________________________ NOTE: with halo=8µm __________________________________
    # C2 LOWER VSUBS 0.38618p
    # C0 UPPER LOWER 0.294756p
    # C1 UPPER VSUBS 0.205833p
    #_______________________________ NOTE: with halo=50µm __________________________________
    # C2 LOWER VSUBS 0.38618p
    # C0 LOWER UPPER 0.294867p
    # C1 UPPER VSUBS 0.205621p
    # NOTE: magic with --magic_halo=50 (µm) gives UPPER-VSUBS of 0.205621p
    #       which is due to the handling of https://github.com/martinjankoehler/magic/issues/1
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'overlap_plates_100um_x_100um_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;LOWER;UPPER;294.867;
C2;LOWER;VSUBS;386.179;
C3;UPPER;VSUBS;205.619;"""
    )

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_overlap_plates_100um_x_100um_li1_m1_m2_m3():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    #_______________________________ NOTE: with halo=8µm __________________________________
    # C7 li1 VSUBS 0.38618p
    # C6 met1 VSUBS 0.205833p
    # C5 met2 VSUBS 52.151802f
    # C4 met3 VSUBS 0.136643p
    # C3 li1 met1 0.294756p
    # C0 met1 met2 0.680652p
    # C2 li1 met2 99.3128f
    # C1 li1 met3 5.59194f
    #_______________________________ NOTE: with halo=50µm __________________________________
    # C9 li1 VSUBS 0.38618p
    # C8 met1 VSUBS 0.205621p
    # C7 met2 VSUBS 51.5767f
    # C6 met3 VSUBS 0.136103p
    # C5 li1 met1 0.294867p
    # C4 li1 met2 99.518005f
    # C2 met1 met2 0.680769p
    # C3 li1 met3 6.01281f
    # C1 met1 met3 0.012287f
    # C0 met2 met3 0.0422f

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'overlap_plates_100um_x_100um_li1_m1_m2_m3.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;li1;met1;294.867;
C2;li1;met2;99.518;
C3;li1;met3;6.013;
C4;met1;met2;680.769;
C5;met1;met3;0.016;
C6;met2;met3;0.056;
C7;VSUBS;li1;386.179;
C8;VSUBS;met1;205.619;
C9;VSUBS;met2;51.574;
C10;VSUBS;met3;136.063;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_sidewall_100um_x_100um_distance_200nm_li1():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=8µm __________________________________
    # C0 A B 7.5f
    # C1 B VSUBS 8.231f
    # C2 A VSUBS 8.231f
    # _______________________________ NOTE: with halo=50µm __________________________________
    # (same!)

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sidewall_100um_x_100um_distance_200nm_li1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;B;3.75;
C2;A;VSUBS;8.231;
C3;B;VSUBS;8.231;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_sidewall_net_uturn_l1_redux():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=8µm __________________________________
    # C1 C1 VSUBS 12.5876f
    # C2 C0 VSUBS 38.1255f
    # C0 C0 C1 1.87386f
    # _______________________________ NOTE: with halo=50µm __________________________________
    # (same!)

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sidewall_net_uturn_l1_redux.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;C1;0.937;
C2;C0;VSUBS;38.125;
C3;C1;VSUBS;12.588;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_sidewall_cap_vpp_04p4x04p6_l1_redux():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=8µm __________________________________
    # C1 C1 VSUBS 0.086832f
    # C2 C0 VSUBS 0.300359f
    # C0 C0 C1 0.286226f
    # _______________________________ NOTE: with halo=50µm __________________________________
    # (same!)

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sidewall_cap_vpp_04p4x04p6_l1_redux.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;C1;0.143;
C2;C0;VSUBS;0.3;
C3;C1;VSUBS;0.087;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_near_body_shield_li1_m1():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    #_______________________________ NOTE: with halo=8µm __________________________________
    # C5 BOTTOM VSUBS 0.405082p
    # C1 BOTTOM TOPB 0.215823p   # DIFFERS marginally <0,1fF
    # C2 BOTTOM TOPA 0.215823p   # DIFFERS marginally <0,1fF
    # C0 TOPA TOPB 0.502857f
    # C3 TOPB VSUBS 0.737292f   # DIFFERS, but that's a MAGIC issue (see test_overlap_plates_100um_x_100um_li1_m1)
    # C4 TOPA VSUBS 0.737292f   # DIFFERS, but that's a MAGIC issue (see test_overlap_plates_100um_x_100um_li1_m1)
    #_______________________________ NOTE: with halo=50µm __________________________________
    # NOTE: with halo=50µm, C3/C4 becomes 0.29976f
    # see https://github.com/martinjankoehler/magic/issues/2

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'near_body_shield_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;BOTTOM;TOPA;215.972;
C2;BOTTOM;TOPB;215.972;
C3;BOTTOM;VSUBS;405.081;
C4;TOPA;TOPB;0.251;
C5;TOPA;VSUBS;0.299;
C6;TOPB;VSUBS;0.299;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_lateral_fringe_shield_by_same_polygon_li1():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    #_______________________________ NOTE: with halo=8µm __________________________________
    # C0 C0 VSUBS 6.41431f $ **FLOATING
    #_______________________________ NOTE: with halo=50µm __________________________________
    # C0 C0 VSUBS 6.41431f $ **FLOATING
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'lateral_fringe_shield_by_same_polygon_li1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;VSUBS;6.414;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_sideoverlap_simple_plates_li1_m1():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=8µm __________________________________
    # C2 li1 VSUBS 7.931799f
    # C1 met1 VSUBS 0.248901p
    # C0 li1 met1 0.143335f
    # _______________________________ NOTE: with halo=50µm __________________________________
    # C2 li1 VSUBS 7.931799f
    # C1 met1 VSUBS 0.248901p
    # C0 li1 met1 0.156859f

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_simple_plates_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;li1;met1;0.157;
C2;VSUBS;li1;7.931;
C3;VSUBS;met1;248.899;"""
        )

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_sideoverlap_shielding_simple_plates_li1_m1_m2():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=8µm __________________________________
    # C5 li1 VSUBS 11.7936f
    # C4 met1 VSUBS 57.990803f
    # C2 li1 met1 15.661301f
    # C0 met1 met2 0.257488p
    # C3 met2 VSUBS 5.29197f
    # C1 li1 met2 0.151641f
    # _______________________________ NOTE: with halo=50µm __________________________________
    # C5 li1 VSUBS 11.7936f
    # C4 met1 VSUBS 57.990803f
    # C2 li1 met1 15.709599f
    # C0 met1 met2 0.257488p
    # C3 met2 VSUBS 5.29197f
    # C1 li1 met2 0.151641f

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_shielding_simple_plates_li1_m1_m2.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;li1;met1;15.71;
C2;li1;met2;0.152;
C3;met1;met2;257.488;
C4;VSUBS;li1;11.793;
C5;VSUBS;met1;57.99;
C6;VSUBS;met2;5.291;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_sideoverlap_plates_li1_m1():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=50µm __________________________________
    # C15 LOWER_NoHaloOverlap_InsideTop VSUBS 51.9938f
    # C12 LOWER_OutsideHalo VSUBS 73.274605f
    # C17 LOWER_PartialSideHaloOverlap_Separated VSUBS 90.6184f
    # C13 LOWER_PartialSideHaloOverlap_BothSides_separated VSUBS 7.93086f
    # C14 LOWER_PartialSideHaloOverlap_Touching VSUBS 13.637f
    # C16 LOWER_FullHaloOverlap VSUBS 0.177602p
    # C11 UPPER VSUBS 0.214853p
    # C8 LOWER_NoHaloOverlap_InsideTop UPPER 0.146991p
    # C7 LOWER_PartialSideHaloOverlap_Touching UPPER 32.1587f
    # C10 LOWER_FullHaloOverlap UPPER 0.262817p
    # C3 LOWER_FullHaloOverlap LOWER_NoHaloOverlap_InsideTop 0.12574f
    # C2 LOWER_NoHaloOverlap_InsideTop LOWER_PartialSideHaloOverlap_Touching 0.063307f
    # C9 LOWER_NoHaloOverlap_InsideTop LOWER_OutsideHalo 0.06287f
    # C1 LOWER_FullHaloOverlap LOWER_OutsideHalo 0.100592f
    # C4 LOWER_PartialSideHaloOverlap_Separated LOWER_FullHaloOverlap 0.248054f
    # C5 LOWER_OutsideHalo UPPER 0.076223f
    # C6 LOWER_PartialSideHaloOverlap_BothSides_separated UPPER 0.261432f
    # C0 LOWER_PartialSideHaloOverlap_Separated UPPER 0.148834f
    #

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_plates_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;LOWER_FullHaloOverlap;LOWER_NoHaloOverlap_InsideTop;0.063;
C2;LOWER_FullHaloOverlap;LOWER_OutsideHalo;0.05;
C3;LOWER_FullHaloOverlap;LOWER_PartialSideHaloOverlap_BothSides_separated;0.0;
C4;LOWER_FullHaloOverlap;LOWER_PartialSideHaloOverlap_Separated;0.124;
C5;LOWER_FullHaloOverlap;UPPER;262.817;
C6;LOWER_FullHaloOverlap;VSUBS;177.601;
C7;LOWER_NoHaloOverlap_InsideTop;LOWER_OutsideHalo;0.031;
C8;LOWER_NoHaloOverlap_InsideTop;LOWER_PartialSideHaloOverlap_Touching;0.032;
C9;LOWER_NoHaloOverlap_InsideTop;UPPER;146.991;
C10;LOWER_NoHaloOverlap_InsideTop;VSUBS;51.994;
C11;LOWER_OutsideHalo;UPPER;0.076;
C12;LOWER_OutsideHalo;VSUBS;73.274;
C13;LOWER_PartialSideHaloOverlap_BothSides_separated;UPPER;0.261;
C14;LOWER_PartialSideHaloOverlap_BothSides_separated;VSUBS;7.931;
C15;LOWER_PartialSideHaloOverlap_Separated;UPPER;0.149;
C16;LOWER_PartialSideHaloOverlap_Separated;VSUBS;90.618;
C17;LOWER_PartialSideHaloOverlap_Touching;UPPER;32.159;
C18;LOWER_PartialSideHaloOverlap_Touching;VSUBS;13.637;
C19;UPPER;VSUBS;214.85;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_sideoverlap_fingered_li1_m1_patternA():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=50µm __________________________________
    #
    # C2 LOWER VSUBS 5.89976f
    # C1 UPPER VSUBS 72.328f
    # C0 LOWER UPPER 0.357768f

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_fingered_li1_m1_patternA.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;LOWER;UPPER;0.358;
C2;LOWER;VSUBS;5.9;
C3;UPPER;VSUBS;72.327;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_sideoverlap_fingered_li1_m1():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=50µm __________________________________
    #
    # C6 LOWER_PartialSideHaloOverlap_Fingered2 VSUBS 8.15974f
    # C8 LOWER_PartialSideHaloOverlap_Fingered3 VSUBS 8.16395f
    # C7 LOWER_PartialSideHaloOverlap_Fingered1 VSUBS 5.8844f
    # C5 LOWER_PartialSideHaloOverlap_Fingered4 VSUBS 5.88862f
    # C4 UPPER VSUBS 0.215283p
    # C0 LOWER_PartialSideHaloOverlap_Fingered3 UPPER 0.158769f
    # C2 LOWER_PartialSideHaloOverlap_Fingered2 UPPER 2.46581f
    # C1 LOWER_PartialSideHaloOverlap_Fingered4 UPPER 0.35839f
    # C3 LOWER_PartialSideHaloOverlap_Fingered1 UPPER 0.244356f

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_fingered_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;LOWER_PartialSideHaloOverlap_Fingered1;LOWER_PartialSideHaloOverlap_Fingered2;0.002;
C2;LOWER_PartialSideHaloOverlap_Fingered1;LOWER_PartialSideHaloOverlap_Fingered4;0.008;
C3;LOWER_PartialSideHaloOverlap_Fingered1;UPPER;0.244;
C4;LOWER_PartialSideHaloOverlap_Fingered1;VSUBS;5.884;
C5;LOWER_PartialSideHaloOverlap_Fingered2;LOWER_PartialSideHaloOverlap_Fingered3;0.001;
C6;LOWER_PartialSideHaloOverlap_Fingered2;UPPER;2.466;
C7;LOWER_PartialSideHaloOverlap_Fingered2;VSUBS;8.16;
C8;LOWER_PartialSideHaloOverlap_Fingered3;UPPER;0.159;
C9;LOWER_PartialSideHaloOverlap_Fingered3;VSUBS;8.164;
C10;LOWER_PartialSideHaloOverlap_Fingered4;UPPER;0.358;
C11;LOWER_PartialSideHaloOverlap_Fingered4;VSUBS;5.889;
C12;UPPER;VSUBS;215.281;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_sideoverlap_complex_li1_m1():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=50µm __________________________________
    #
    # C6 Complex_Shape_L VSUBS 3.19991f
    # C8 Complex_Shape_T VSUBS 3.19991f
    # C7 Complex_Shape_R VSUBS 3.19991f
    # C5 Complex_Shape_B VSUBS 3.19991f
    # C4 UPPER VSUBS 13.0192f
    # C0 Complex_Shape_B UPPER 1.34751f
    # C3 Complex_Shape_T UPPER 0.064969f
    # C2 Complex_Shape_R UPPER 0.089357f
    # C1 Complex_Shape_L UPPER 0.24889f

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_complex_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;Complex_Shape_B;UPPER;1.348;
C2;Complex_Shape_B;VSUBS;3.2;
C3;Complex_Shape_L;UPPER;0.249;
C4;Complex_Shape_L;VSUBS;3.2;
C5;Complex_Shape_R;UPPER;0.089;
C6;Complex_Shape_R;VSUBS;3.2;
C7;Complex_Shape_T;UPPER;0.065;
C8;Complex_Shape_T;VSUBS;3.2;
C9;UPPER;VSUBS;13.019;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_met1_over_drain_li1():
    # The met1 plate W (4 µm x 2 µm) is over the drain diffusion of the nfet (W = 2 µm, L = 0.15 µm),
    # 33.6 aF/µm² * 8 µm² = 268.8 aF to D, plus the fringe to the drain beyond the plate.
    # The diffusion used to be no part of the extraction, so W had 25.78 aF/µm² to the substrate instead
    # (D-W 0.002 fF, VSUBS-W 0.69 fF).
    # G is higher than with MAGIC, as the gate poly over the channel is poly here, rather than the transistor
    #
    # MAGIC GIVES (8.3 revision 681): (sorting changed to match order)
    # _______________________________ NOTE: with halo=8µm __________________________________
    # C2 G D 0.00247f
    # C1 S D 0.00581f
    # C7 D VSUBS 0.03027f
    # C4 D W 0.37655f
    # C3 G S 0.00323f
    # C9 G VSUBS 0.18508f
    # C0 G W 0.0014f
    # C8 S VSUBS 0.03027f
    # C5 S W 0.01027f
    # C6 W VSUBS 0.38766f
    # _______________________________ NOTE: with halo=50µm __________________________________
    # C4 G D 0.00247f
    # C3 S D 0.00645f
    # C7 D VSUBS 0.02884f
    # C0 D W 0.37655f
    # C5 G S 0.00323f
    # C9 G VSUBS 0.18508f
    # C2 G W 0.0014f
    # C8 S VSUBS 0.02884f
    # C1 S W 0.01027f
    # C6 W VSUBS 0.38766f

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'nfet_li1_met1_over_drain.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;D;G;0.002;
C2;D;S;0.006;
C3;D;VSUBS;0.029;
C4;D;W;0.377;
C5;G;S;0.004;
C6;G;VSUBS;0.235;
C7;G;W;0.007;
C8;S;VSUBS;0.029;
C9;S;W;0.01;
C10;VSUBS;W;0.388;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_inverter_over_nwell():
    # The capacitances of the shapes over the nwell go to its net VPB, the others to the substrate.
    # They all used to go to the substrate (e.g. VPWR-VSUBS 0.273 fF, which is 0.211 fF and VPB-VPWR 0.062 fF now).
    # A is higher than with MAGIC, as the gate poly over the channel is poly here, rather than the transistor,
    # and VPB-VNB (VSUBS) is the capacitance of the nwell itself, which MAGIC has, but the tech info doesn't
    #
    # MAGIC GIVES (8.3 revision 681): (sorting changed to match order)
    # _______________________________ NOTE: with halo=8µm and halo=50µm _____________________
    # C2 A VGND 0.03709f
    # C8 VPB A 0.04506f
    # C6 A VPWR 0.03629f
    # C13 A VNB 0.13301f
    # C4 A Y 0.03773f
    # C3 VPB VGND 0.01319f
    # C0 VPWR VGND 0.01841f
    # C10 VGND VNB 0.24421f
    # C9 Y VGND 0.05975f
    # C7 VPB VPWR 0.06649f
    # C5 VPB Y 0.01774f
    # C12 VPWR VNB 0.20582f
    # C1 VPWR Y 0.07413f
    # C11 Y VNB 0.0961f
    # C14 VPB VNB 0.33898f

    pex_whiteboxed.assert_expected_matches_obtained(
        'sky130_fd_sc_hd__inv_1', 'sky130_fd_sc_hd__inv_1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;VGND;0.04;
C2;A;VPB;0.091;
C3;A;VPWR;0.041;
C4;A;VSUBS;0.222;
C5;A;Y;0.051;
C6;VGND;VPB;0.012;
C7;VGND;VPWR;0.018;
C8;VGND;VSUBS;0.248;
C9;VGND;Y;0.06;
C10;VPB;VPWR;0.062;
C11;VPB;Y;0.018;
C12;VPWR;VSUBS;0.211;
C13;VPWR;Y;0.074;
C14;VSUBS;Y;0.096;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_met2_over_met1_over_nwell_of_its_net():
    # The nwell is VDD (by an ntap), and so is the met1 plate (8 µm x 8 µm) over it, which has no capacitance
    # to it, and shields it from the met2 plate X (4 µm x 4 µm) above.
    # The fringe of X beyond the met1 plate ends at the nwell (VDD), and beyond that, at the substrate.
    # The nwell used to be the substrate (VDD-VSUBS 3.003 fF, VDD-X 3.088 fF, VSUBS-X 0.369 fF).
    # MAGIC has the capacitance of the nwell itself too (100 µm² * 120 aF/µm² = 12 fF), which the tech info hasn't
    #
    # MAGIC GIVES (8.3 revision 681): (sorting changed to match order)
    # _______________________________ NOTE: with halo=50µm __________________________________
    # C2 VDD VSUBS 12.9206f
    # C0 VDD X 3.16499f
    # C1 X VSUBS 0.29271f

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'nwell_met1_met2_plates.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;VDD;VSUBS;0.923;
C2;VDD;X;3.165;
C3;VSUBS;X;0.293;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mom_cap__whiteboxed():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=50µm __________________________________
    # C0 C0 C1 13.4653f
    # C1 C1 SUB 0.77621f
    # C2 C0 SUB 2.83686f

    pex_whiteboxed.assert_expected_matches_obtained(
        'cap_vpp_04p4x04p6_l1m1m2_noshield', 'cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;C1;7.739;
C2;C0;VSUBS;2.827;
C3;C1;VSUBS;0.765;"""
        )

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mom_cap__blackboxed():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=50µm __________________________________
    # C0 C0 C1 13.4653f
    # C1 C1 SUB 0.77621f
    # C2 C0 SUB 2.83686f

    pex_blackboxed.assert_expected_matches_obtained(
        'cap_vpp_04p4x04p6_l1m1m2_noshield', 'cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;C1;0.141;
C2;C0;VSUBS;3.562;
C3;C1;VSUBS;0.117;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mom_cap_with_4_terminals__whiteboxed():
    # The LVS script reads VPP caps with 4 terminals as MOS4, so white-box mode kept the device,
    # whose capacitance is extracted from its fingers: counted twice
    _, csv_path, _ = pex_whiteboxed.run_rcx25d_single_cell('cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5',
                                                           'cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5.gds.gz')
    with open(csv_path[:-len('.csv')] + '.spice') as f:
        assert [line for line in f if line.startswith('X')] == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mim_cap__whiteboxed():
    # The device model gives camimc 2.0 fF/µm² * 18.9 µm * 5.1 µm = 192.78 fF (capm over met3)
    # plus cpmimc 0.19 fF/µm * 48 µm = 9.12 fF, the fringe to the bottom plate around the top plate
    # (8.36 fF from capm to met3 here), the rest is the interconnect
    pex_whiteboxed.assert_expected_matches_obtained(
        'cap_mim_m3_w18p9_l5p1', 'cap_mim_m3_w18p9_l5p1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;mimcap_bot;mimcap_top;204.88;
C2;VSUBS;mimcap_bot;4.353;
C3;VSUBS;mimcap_top;2.942;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mim_cap__whiteboxed_without_overlap_caps_is_an_error():
    # Without the overlap capacitances of the MIM plate capm, they would be missing,
    # which crashed the sidewall extraction with a KeyError
    overlap_cap_by_layer_names = TechInfo.overlap_cap_by_layer_names.func

    def without_capm(tech_info: TechInfo):
        return {top: {bottom: oc for bottom, oc in ocs.items() if bottom != 'capm'}
                for top, ocs in overlap_cap_by_layer_names(tech_info).items() if top != 'capm'}

    with mock.patch.object(TechInfo, 'overlap_cap_by_layer_names', property(without_capm)), \
         mock.patch('klayout_pex.kpex_cli.error') as error_mock, pytest.raises(SystemExit):
        pex_whiteboxed.run_rcx25d_single_cell('cap_mim_m3_w18p9_l5p1', 'cap_mim_m3_w18p9_l5p1.gds.gz')
    assert [c.args[0] for c in error_mock.call_args_list if 'overlap' in c.args[0]] == [
        "The tech info has no overlap capacitance for these layer pairs of the layout, "
        "so their capacitances would be missing (e.g. the plates of a MIM cap, "
        "which --blackbox leaves to the device model):\n"
        "  - capm over VSUBS\n"
        "  - capm over met3\n"
        "  - met4 over capm"
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mim_cap__blackboxed():
    results, _, _ = pex_blackboxed.run_rcx25d_single_cell('cap_mim_m3_w18p9_l5p1', 'cap_mim_m3_w18p9_l5p1.gds.gz')
    assert results.summarize().capacitances


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_varactors__blackboxed():
    # The varactors of the PDK's device generator (magic), W along the poly, L across it:
    # the lvt one with W < L, the hvt one with W > L. Their models depend on w and l separately,
    # so LVS extracts them like MOS gates, rather than by area and perimeter, which can't tell w from l
    assert pex_blackboxed.written_device_lines('test_patterns', 'cap_var_lvt_w1_l2_hvt_w2_l0p5.gds.gz') == [
        'X$1 LVT_C0 LVT_C1 LVT_B sky130_fd_pr__cap_var_lvt w=1 l=2',
        'X$2 HVT_C0 HVT_C1 HVT_B sky130_fd_pr__cap_var_hvt w=2 l=0.5',
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_hv_diffusion_resistors__blackboxed():
    # The HV diffusion resistors of the PDK's device generator (magic), their models are named ..._nd__hv, ..._pd__hv
    assert pex_blackboxed.written_device_lines('test_patterns', 'res_generic_nd_hv_pd_hv_w1_l4.gds.gz') == [
        'X$1 ND_R2 ND_R1 sky130_gnd sky130_fd_pr__res_generic_nd__hv w=1 l=4',
        'X$2 PD_R2 PD_R1 PD_B sky130_fd_pr__res_generic_pd__hv w=1 l=4',
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_sonos_fet__blackboxed():
    # The SONOS FET of the PDK's device generator (magic), with the core marker areaid.ce, which LVS needs for it
    assert pex_blackboxed.written_device_lines('test_patterns', 'sonosfet_star_w0p45_l0p22.gds.gz') == [
        'X$1 S G D sky130_gnd sky130_fd_bs_flash__special_sonosfet_star l=0.22 w=0.45 as=0.1305 ad=0.1305 ps=1.48 pd=1.48',
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_label_of_substrate_under_inductor_names_the_substrate():
    # A label (SUB) names the substrate under the inductor marker, like the ones of the PDK's VPP caps,
    # so the capacitances to the substrate (of the met1 plate over the marker) go to SUB,
    # like the bulk of the nfet next to it. It used to name a net of its own, that connected to nothing
    pex_whiteboxed.run_rcx25d_single_cell('inductor_substrate_pin', 'inductor_substrate_pin.gds.gz')
    output_dir_path = os.path.realpath(os.path.join(__file__, '..', '..', '..', f"output_{pex_whiteboxed.pdk.name}"))
    netlist_path, = glob.glob(os.path.join(output_dir_path, 'inductor_substrate_pin__*', '*_k25d_pex_netlist.spice'))
    with open(netlist_path) as f:
        lines = f.read().replace('\n+', ' ').splitlines()
    subckt_line, = [l for l in lines if l.startswith('.SUBCKT ')]
    nfet_line, = [l for l in lines if l.startswith('X$1 ')]
    plate_cap_line, = [l for l in lines if l.startswith('C') and 'PLATE' in l.split()[1:3]]
    assert subckt_line.split()[2:] == ['D', 'G', 'S', 'SUB']
    assert nfet_line.split()[4] == 'SUB'  # B
    assert sorted(plate_cap_line.split()[1:3]) == ['PLATE', 'SUB']
