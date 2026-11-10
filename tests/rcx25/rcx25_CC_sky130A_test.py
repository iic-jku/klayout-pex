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
import pytest
from unittest import mock

from klayout_pex.pdk_config import PDK
from klayout_pex.tech_info import TechInfo
from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction

parent_suite = "kpex/2.5D Extraction Tests [PDK sky130A | mode CC]"
tags = ("PEX", "2.5D", "MAGIC")

# Expectations use the pinned nominal OpenPDKs tables in the generator (#523).
# Overlap follows the area coefficient. Fringe uses its directional coefficient
# and the overlap-dependent spreading. Sidewall uses the full pair fit (#390)
# with the updated offset. Geometry and resistance values are unchanged.


pex_whiteboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.CC, blackbox=False)
pex_blackboxed = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.CC, blackbox=True)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_single_plate_100um_x_100um_li1_over_substrate():
    # `li1`: 10000 µm² * 36.888 aF/µm² = 368.880 fF, plus the four-edge fringe
    # of 400 µm * 35.149 aF/µm, limited by the 10000 µm halo, gives 382.938 fF
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'single_plate_100um_x_100um_li1_over_substrate.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;PLATE;VSUBS;382.938;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_overlap_plates_100um_x_100um_li1_m1():
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'overlap_plates_100um_x_100um_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;LOWER;UPPER;301.287;
C2;LOWER;VSUBS;382.938;
C3;UPPER;VSUBS;206.03;"""
    )

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_overlap_plates_100um_x_100um_li1_m1_m2_m3():

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'overlap_plates_100um_x_100um_li1_m1_m2_m3.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;li1;met1;301.287;
C2;li1;met2;107.601;
C3;li1;met3;5.425;
C4;met1;met2;748.257;
C5;met1;met3;0.015;
C6;met2;met3;0.049;
C7;VSUBS;li1;382.938;
C8;VSUBS;met1;206.03;
C9;VSUBS;met2;52.885;
C10;VSUBS;met3;143.916;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_overlap_shield_same_net_100um_x_100um_li1_m1_m2():
    # `met1` of net `A` shields its `li1` from `met2` of net `B`, so `A`–`B` is
    # `met2`–`met1` only: 147.570 aF/µm² * 100 µm * 100 µm = 1475.7 fF (#299)
    # Counting the shielded `met2`–`li1` area would add another 410.47 fF
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'overlap_shield_same_net_100um_x_100um_li1_m1_m2.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;B;1475.7;
C2;A;VSUBS;397.438;
C3;B;VSUBS;13.168;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_overlap_shield_same_net_half_100um_x_100um_li1_m1_m2():
    # `met1` of net `A` covers half its `li1`, so `A`–`B` has 737.85 fF of `met2`–`met1`
    # over the left half, 205.235 fF of `met2`–`li1` over the right half, and edge fringe
    # The `met2`–`li1` area under `met1` stays shielded (#299)
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'overlap_shield_same_net_half_100um_x_100um_li1_m1_m2.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;B;947.789;
C2;A;VSUBS;390.276;
C3;B;VSUBS;13.168;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_plate_20um_x_20um_li1_over_ntap():
    # The n-tap is diffusion, the same stack as the source/drain, so A–W is li1 over diffusion,
    # 56.321 aF/µm² * 20 µm * 20 µm = 22.5284 fF, plus fringe, rather than `li1` over `nwell`
    # at 36.888 aF/µm² (#301)
    # The nwell has no capacitance to the substrate (the PDKs model it as a diode)
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'plate_20um_x_20um_li1_over_ntap.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;VSUBS;0.201;
C2;A;W;25.532;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_plate_20um_x_20um_li1_over_ptap():
    # The p-tap is diffusion, the same stack as the source/drain, so A–VSS (the net of the tap) is li1 over diffusion,
    # 56.321 aF/µm² * 20 µm * 20 µm = 22.5284 fF, plus fringe (#301)
    # Using the field area coefficient would incorrectly substitute 36.888 aF/µm²
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'plate_20um_x_20um_li1_over_ptap.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;VSS;25.492;
C2;A;VSUBS;0.241;
C3;VSS;VSUBS;0.112;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sidewall_100um_x_100um_distance_200nm_li1():
    # The full facing-edge pair gives 18.194 aF * 100 µm / (0.2 + 0.038) µm = 7.645 fF

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sidewall_100um_x_100um_distance_200nm_li1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;B;7.645;
C2;A;VSUBS;7.601;
C3;B;VSUBS;7.601;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sidewall_net_uturn_l1_redux():

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sidewall_net_uturn_l1_redux.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;C1;1.391;
C2;C0;VSUBS;36.034;
C3;C1;VSUBS;11.815;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sidewall_cap_vpp_04p4x04p6_l1_redux():

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sidewall_cap_vpp_04p4x04p6_l1_redux.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;C1;0.3;
C2;C0;VSUBS;0.266;
C3;C1;VSUBS;0.077;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_near_body_shield_li1_m1():

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'near_body_shield_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;BOTTOM;TOPA;220.071;
C2;BOTTOM;TOPB;220.071;
C3;BOTTOM;VSUBS;401.734;
C4;TOPA;TOPB;0.519;
C5;TOPA;VSUBS;0.265;
C6;TOPB;VSUBS;0.265;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_lateral_fringe_shield_by_same_polygon_li1():
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'lateral_fringe_shield_by_same_polygon_li1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;VSUBS;5.973;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sideoverlap_simple_plates_li1_m1():

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_simple_plates_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;li1;met1;0.149;
C2;VSUBS;li1;7.344;
C3;VSUBS;met1;249.165;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sideoverlap_needs_no_substrate_capacitance_beyond_its_overlap_and_side_overlap():
    # The fringe takes the overlap and side overlap capacitances, of the substrate too (as of TechInfo),
    # but looked up the substrate capacitance of its layer as well, unused, which raised a KeyError without one
    tech_info = TechInfo.from_json(PDK.SKY130A.config.tech_pb_json_path, dielectric_filter=None)
    overlap_caps = tech_info.overlap_cap_by_layer_names
    side_overlap_caps = tech_info.side_overlap_cap_by_layer_names
    substrate_caps = {name: cap for name, cap in tech_info.substrate_cap_by_layer_name.items() if name != 'met1'}
    with mock.patch.object(TechInfo, 'substrate_cap_by_layer_name', property(lambda _: substrate_caps)), \
         mock.patch.object(TechInfo, 'overlap_cap_by_layer_names', property(lambda _: overlap_caps)), \
         mock.patch.object(TechInfo, 'side_overlap_cap_by_layer_names', property(lambda _: side_overlap_caps)):
        pex_whiteboxed.assert_expected_matches_obtained(
            'test_patterns', 'sideoverlap_simple_plates_li1_m1.gds.gz',
            expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;li1;met1;0.149;
C2;VSUBS;li1;7.344;
C3;VSUBS;met1;249.165;"""
            )

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sideoverlap_shielding_simple_plates_li1_m1_m2():

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_shielding_simple_plates_li1_m1_m2.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;li1;met1;15.797;
C2;li1;met2;0.123;
C3;met1;met2;283.093;
C4;VSUBS;li1;11.173;
C5;VSUBS;met1;57.759;
C6;VSUBS;met2;4.593;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sideoverlap_plates_li1_m1():

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_plates_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;LOWER_FullHaloOverlap;LOWER_NoHaloOverlap_InsideTop;0.091;
C2;LOWER_FullHaloOverlap;LOWER_OutsideHalo;0.073;
C3;LOWER_FullHaloOverlap;LOWER_PartialSideHaloOverlap_BothSides_separated;0.0;
C4;LOWER_FullHaloOverlap;LOWER_PartialSideHaloOverlap_Separated;0.181;
C5;LOWER_FullHaloOverlap;UPPER;268.816;
C6;LOWER_FullHaloOverlap;VSUBS;175.62;
C7;LOWER_NoHaloOverlap_InsideTop;LOWER_OutsideHalo;0.045;
C8;LOWER_NoHaloOverlap_InsideTop;LOWER_PartialSideHaloOverlap_Touching;0.045;
C9;LOWER_NoHaloOverlap_InsideTop;UPPER;150.468;
C10;LOWER_NoHaloOverlap_InsideTop;VSUBS;51.08;
C11;LOWER_OutsideHalo;UPPER;0.07;
C12;LOWER_OutsideHalo;VSUBS;72.177;
C13;LOWER_PartialSideHaloOverlap_BothSides_separated;UPPER;0.248;
C14;LOWER_PartialSideHaloOverlap_BothSides_separated;VSUBS;7.343;
C15;LOWER_PartialSideHaloOverlap_Separated;UPPER;0.133;
C16;LOWER_PartialSideHaloOverlap_Separated;VSUBS;89.38;
C17;LOWER_PartialSideHaloOverlap_Touching;UPPER;32.879;
C18;LOWER_PartialSideHaloOverlap_Touching;VSUBS;13.012;
C19;UPPER;VSUBS;214.731;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sideoverlap_fingered_li1_m1_patternA():

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_fingered_li1_m1_patternA.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;LOWER;UPPER;0.338;
C2;LOWER;VSUBS;5.395;
C3;UPPER;VSUBS;72.061;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sideoverlap_fingered_li1_m1():

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_fingered_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;LOWER_PartialSideHaloOverlap_Fingered1;LOWER_PartialSideHaloOverlap_Fingered2;0.002;
C2;LOWER_PartialSideHaloOverlap_Fingered1;LOWER_PartialSideHaloOverlap_Fingered4;0.011;
C3;LOWER_PartialSideHaloOverlap_Fingered1;UPPER;0.231;
C4;LOWER_PartialSideHaloOverlap_Fingered1;VSUBS;5.382;
C5;LOWER_PartialSideHaloOverlap_Fingered2;LOWER_PartialSideHaloOverlap_Fingered3;0.001;
C6;LOWER_PartialSideHaloOverlap_Fingered2;UPPER;2.364;
C7;LOWER_PartialSideHaloOverlap_Fingered2;VSUBS;7.498;
C8;LOWER_PartialSideHaloOverlap_Fingered3;UPPER;0.15;
C9;LOWER_PartialSideHaloOverlap_Fingered3;VSUBS;7.502;
C10;LOWER_PartialSideHaloOverlap_Fingered4;UPPER;0.338;
C11;LOWER_PartialSideHaloOverlap_Fingered4;VSUBS;5.385;
C12;UPPER;VSUBS;215.556;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sideoverlap_complex_li1_m1():

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_complex_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;Complex_Shape_B;UPPER;1.333;
C2;Complex_Shape_B;VSUBS;2.922;
C3;Complex_Shape_L;UPPER;0.237;
C4;Complex_Shape_L;VSUBS;2.922;
C5;Complex_Shape_R;UPPER;0.085;
C6;Complex_Shape_R;VSUBS;2.922;
C7;Complex_Shape_T;UPPER;0.061;
C8;Complex_Shape_T;VSUBS;2.922;
C9;UPPER;VSUBS;12.807;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_met1_over_drain_li1():
    # The met1 plate W (4 µm x 2 µm) is over the drain diffusion of the nfet (W = 2 µm, L = 0.15 µm),
    # 34.371 aF/µm² * 8 µm² = 274.968 aF to `D`, plus fringe to the drain beyond the plate
    # Omitting diffusion incorrectly assigns that area capacitance to the substrate instead
    # The gate poly has no capacitance to the substrate over its channel, nor from its edges along it,
    # as the transistor model has these, like with MAGIC (G-VSUBS 0.235 fF before, #290)

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'nfet_li1_met1_over_drain.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;D;G;0.002;
C2;D;S;0.006;
C3;D;VSUBS;0.025;
C4;D;W;0.374;
C5;G;S;0.004;
C6;G;VSUBS;0.155;
C7;G;W;0.007;
C8;S;VSUBS;0.025;
C9;S;W;0.009;
C10;VSUBS;W;0.346;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_inverter_over_nwell():
    # The capacitances of the shapes over the nwell go to its net VPB, the others to the substrate.
    # Assigning the well area to the substrate instead loses its coupling to `VPB`
    # The gate poly has no capacitance to the substrate or well over its channel, nor from its edges along it,
    # as the transistor model has these, like with MAGIC (A-VSUBS 0.222 and A-VPB 0.091 fF before, #290).
    # VPB-VNB (VSUBS) is the capacitance of the nwell itself, which MAGIC has, but the tech info doesn't

    pex_whiteboxed.assert_expected_matches_obtained(
        'sky130_fd_sc_hd__inv_1', 'sky130_fd_sc_hd__inv_1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;VGND;0.049;
C2;A;VPB;0.032;
C3;A;VPWR;0.048;
C4;A;VSUBS;0.11;
C5;A;Y;0.059;
C6;VGND;VPB;0.011;
C7;VGND;VPWR;0.032;
C8;VGND;VSUBS;0.22;
C9;VGND;Y;0.104;
C10;VPB;VPWR;0.057;
C11;VPB;Y;0.016;
C12;VPWR;VSUBS;0.185;
C13;VPWR;Y;0.133;
C14;VSUBS;Y;0.083;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_met2_over_met1_over_nwell_of_its_net():
    # The nwell is VDD (by an ntap), and so is the met1 plate (8 µm x 8 µm) over it, which has no capacitance
    # to it, and shields it from the met2 plate X (4 µm x 4 µm) above.
    # The fringe of X beyond the met1 plate ends at the nwell (VDD), and beyond that, at the substrate.
    # The nwell used to be the substrate (VDD-VSUBS 3.003 fF, VDD-X 3.088 fF, VSUBS-X 0.369 fF).
    # MAGIC has the capacitance of the nwell itself too (100 µm² * 120 aF/µm² = 12 fF), which the tech info hasn't

    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'nwell_met1_met2_plates.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;VDD;VSUBS;0.821;
C2;VDD;X;3.247;
C3;VSUBS;X;0.246;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mom_cap__whiteboxed():

    pex_whiteboxed.assert_expected_matches_obtained(
        'cap_vpp_04p4x04p6_l1m1m2_noshield', 'cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;C1;13.852;
C2;C0;VSUBS;2.516;
C3;C1;VSUBS;0.696;"""
        )

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mom_cap__blackboxed():

    # The fingers of the VPP cap (the metal within its marker) are plates, and its model has their capacitances
    # to each other and to the substrate (c0_sub 1.528 fF, c1_sub 0.44 fF), its terminal B, so these are left out.
    # What's left is the metal around the marker (0.17 µm wide), whose inner edges fringed to the substrate
    # where the fingers were left out (C0–VSUBS 3.562 fF, C1–VSUBS 0.117 fF)
    pex_blackboxed.assert_expected_matches_obtained(
        'cap_vpp_04p4x04p6_l1m1m2_noshield', 'cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;C1;0.21;
C2;C0;VSUBS;1.945;
C3;C1;VSUBS;0.08;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mom_cap_beside_m2_wire__whiteboxed():
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'cap_vpp_04p4x04p6_l1m1m2_noshield_m2_wire.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;C1;13.852;
C2;C0;VSUBS;2.392;
C3;C0;X;0.452;
C4;C1;VSUBS;0.671;
C5;C1;X;0.041;
C6;VSUBS;X;0.352;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mom_cap_beside_m2_wire__blackboxed():
    # The fingers of the VPP cap are plates, so the capacitances to the wire X beside it are the white-box ones,
    # and those of the fingers to each other and to the substrate are the model's (see test_mom_cap__blackboxed)
    pex_blackboxed.assert_expected_matches_obtained(
        'test_patterns', 'cap_vpp_04p4x04p6_l1m1m2_noshield_m2_wire.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;C1;0.21;
C2;C0;VSUBS;1.821;
C3;C0;X;0.452;
C4;C1;VSUBS;0.061;
C5;C1;X;0.041;
C6;VSUBS;X;0.352;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mom_cap_model_is_not_changed_by_routing_across__blackboxed():
    # The LVS deck told the VPP caps apart by the layers that touch their markers, so the wires across the first
    # cap made it sky130_fd_pr__cap_vpp_04p4x04p6_m1m2m3_shieldl1m5_floatm4, and the wire across the second one
    # left it without a model. The metal of a cap does count: its plates, also the ones on met5 with holes or a lead
    device_lines = pex_blackboxed.written_device_lines('test_patterns', 'cap_vpp_routing_across.gds.gz')
    assert sorted(line.split()[-1] for line in device_lines) == [
        'sky130_fd_pr__cap_vpp_04p4x04p6_l1m1m2_noshield',
        'sky130_fd_pr__cap_vpp_04p4x04p6_m1m2_noshield',
        'sky130_fd_pr__cap_vpp_04p4x04p6_m1m2_noshield',
        'sky130_fd_pr__cap_vpp_06p8x06p1_m1m2m3_shieldl1m4',
        'sky130_fd_pr__cap_vpp_11p5x11p7_l1m1m2m3m4_shieldpom5_x',
        'sky130_fd_pr__cap_vpp_11p5x11p7_m1m2m3m4_shieldm5',
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('net_name, layer_name', [('X10', 'li_vpp'), ('X11', 'poly_vpp')])
def test_mom_cap_li1_and_poly_wires_across_are_one_net(net_name: str, layer_name: str):
    # The LVS deck connected the wires only outside the marker of the cap, so their pieces were 3 nets,
    # and the extraction stopped with a ZeroDivisionError on the poly wire, as shapes of different nets touched
    lvsdb = pex_whiteboxed.read_lvsdb('test_patterns', 'cap_vpp_routing_across.gds.gz')
    net = lvsdb.netlist().circuit_by_name('cap_vpp_routing_across').net_by_name(net_name)
    assert not lvsdb.shapes_of_net(net, lvsdb.layer_by_name(layer_name), True).is_empty()


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mom_cap_with_4_terminals__whiteboxed():
    # The LVS script reads VPP caps with 4 terminals as MOS4, so white-box mode kept the device,
    # whose capacitance is extracted from its fingers: counted twice
    _, csv_path = pex_whiteboxed.run_rcx25d_single_cell('cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5',
                                                           'cap_vpp_11p5x11p7_l1m1m2m3m4_shieldm5.gds.gz')
    with open(csv_path[:-len('.csv')] + '.spice', encoding='utf-8') as f:
        assert [line for line in f if line.startswith('X')] == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mim_cap__whiteboxed():
    # The device model gives camimc 2.0 fF/µm² * 18.9 µm * 5.1 µm = 192.78 fF (capm over met3)
    # plus cpmimc 0.19 fF/µm * 48 µm = 9.12 fF, the fringe to the bottom plate around the top plate
    # (8.36 fF from capm to met3 here), the rest is the interconnect
    pex_whiteboxed.assert_expected_matches_obtained(
        'cap_mim_m3_w18p9_l5p1', 'cap_mim_m3_w18p9_l5p1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;mimcap_bot;mimcap_top;207.336;
C2;VSUBS;mimcap_bot;4.184;
C3;VSUBS;mimcap_top;2.694;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
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
def test_sideoverlap_without_side_overlap_cap_is_an_error():
    # Without the side overlap capacitance of li1 to met1 (and of met1 to the substrate),
    # the fringe crashed the extraction with a KeyError
    side_overlap_cap_by_layer_names = TechInfo.side_overlap_cap_by_layer_names.func

    def without_li1_to_met1(tech_info: TechInfo):
        caps = side_overlap_cap_by_layer_names(tech_info)
        return {inside: {outside: soc for outside, soc in socs.items()
                         if (inside, outside) not in (('li1', 'met1'), ('met1', 'VSUBS'))}
                for inside, socs in caps.items()}

    with mock.patch.object(TechInfo, 'side_overlap_cap_by_layer_names', property(without_li1_to_met1)), \
         mock.patch('klayout_pex.kpex_cli.error') as error_mock, pytest.raises(SystemExit):
        pex_whiteboxed.run_rcx25d_single_cell('test_patterns', 'sideoverlap_simple_plates_li1_m1.gds.gz')
    assert [c.args[0] for c in error_mock.call_args_list if 'side overlap' in c.args[0]] == [
        "The tech info has no side overlap capacitance for these layer pairs of the layout, "
        "so the fringe from the edges of the first to the second can't be extracted:\n"
        "  - li1 to met1\n"
        "  - met1 to VSUBS"
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mim_cap__blackboxed():
    results, _ = pex_blackboxed.run_rcx25d_single_cell('cap_mim_m3_w18p9_l5p1', 'cap_mim_m3_w18p9_l5p1.gds.gz')
    assert results.summarize().capacitances


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mim_cap_over_m2_wire__whiteboxed():
    # The device model gives camimc 2.0 fF/µm² * 20 µm * 20 µm = 800 fF (capm over met3)
    # plus cpmimc 0.19 fF/µm * 80 µm = 15.2 fF, the fringe to the bottom plate around the top plate
    # (15.079 fF from capm to met3 here). A–B has the fringe from met4 to the met3 around the capm too (4.142 fF)
    pex_whiteboxed.assert_expected_matches_obtained(
        'test_patterns', 'cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;B;819.221;
C2;A;D;6.343;
C3;A;VSUBS;10.406;
C4;B;D;0.07;
C5;B;VSUBS;1.959;
C6;D;VSUBS;4.651;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_mim_cap_over_m2_wire__blackboxed():
    # The plates of the MIM cap are conductors, the bottom plate shields the wire D and the substrate below it
    # from the top plate and the met4 above. Only the capacitance of the device model is left out, the overlap
    # of capm over met3 and the fringe from its edge, so A–B is the fringe from met4 to the met3 around the capm,
    # and the rest is the same as in white-box mode. Without the plates, D coupled to B through the hole (1.636 fF).
    pex_blackboxed.assert_expected_matches_obtained(
        'test_patterns', 'cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;B;4.142;
C2;A;D;6.343;
C3;A;VSUBS;10.406;
C4;B;D;0.07;
C5;B;VSUBS;1.959;
C6;D;VSUBS;4.651;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
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
def test_hv_diffusion_resistors__blackboxed():
    # The HV diffusion resistors of the PDK's device generator (magic), their models are named ..._nd__hv, ..._pd__hv
    assert pex_blackboxed.written_device_lines('test_patterns', 'res_generic_nd_hv_pd_hv_w1_l4.gds.gz') == [
        'X$1 ND_R2 ND_R1 sky130_gnd sky130_fd_pr__res_generic_nd__hv w=1 l=4',
        'X$2 PD_R2 PD_R1 PD_B sky130_fd_pr__res_generic_pd__hv w=1 l=4',
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sonos_fet__blackboxed():
    # The SONOS FET of the PDK's device generator (magic), with the core marker areaid.ce, which LVS needs for it
    assert pex_blackboxed.written_device_lines('test_patterns', 'sonosfet_star_w0p45_l0p22.gds.gz') == [
        'X$1 S G D sky130_gnd sky130_fd_bs_flash__special_sonosfet_star l=0.22 w=0.45 as=0.1305 ad=0.1305 ps=1.48 pd=1.48',
    ]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_label_of_substrate_under_inductor_names_the_substrate():
    # A label (SUB) names the substrate under the inductor marker, like the ones of the PDK's VPP caps,
    # so the capacitances to the substrate (of the met1 plate over the marker) go to SUB,
    # like the bulk of the nfet next to it. It used to name a net of its own, that connected to nothing
    _, lines = pex_whiteboxed.written_netlist_lines('inductor_substrate_pin', 'inductor_substrate_pin.gds.gz')
    subckt_line, = [l for l in lines if l.startswith('.SUBCKT ')]
    nfet_line, = [l for l in lines if l.startswith('X$1 ')]
    plate_cap_line, = [l for l in lines if l.startswith('C') and 'PLATE' in l.split()[1:3]]
    # NOTE: the met1 plate has a pin of its own (PLATE)
    assert subckt_line.split()[2:] == ['D', 'G', 'PLATE', 'S', 'SUB']
    assert nfet_line.split()[4] == 'SUB'  # B
    assert sorted(plate_cap_line.split()[1:3]) == ['PLATE', 'SUB']
