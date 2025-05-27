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
from __future__ import annotations

import io
import json
import tempfile

import allure
import csv_diff
import os
import pytest
from typing import *

import klayout.db as kdb
import klayout.lay as klay

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.rcx25.extraction_results import CellExtractionResults


CSVPath = str
PNGPath = str
parent_suite = "kpex/2.5D Extraction Tests"
tags = ("PEX", "2.5D", "MAGIC")


def _kpex_pdk_dir() -> str:
    return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                         'pdk', 'sky130A', 'libs.tech', 'kpex'))


def _sky130a_testdata_dir() -> str:
    return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                         'testdata', 'designs', 'sky130A'))


def _gds(*path_components) -> str:
    return os.path.join(_sky130a_testdata_dir(), *path_components)


def _save_layout_preview(gds_path: str,
                         output_png_path: str):
    kdb.Technology.clear_technologies()
    default_lyt_path = os.path.abspath(f"{_kpex_pdk_dir()}/sky130A.lyt")
    tech = kdb.Technology.create_technology('sky130A')
    tech.load(default_lyt_path)

    lv = klay.LayoutView()
    lv.load_layout(gds_path)
    lv.max_hier()
    lv.set_config('background-color', '#000000')
    lv.set_config('bitmap-oversampling', '1')
    lv.set_config('default-font-size', '4')
    lv.set_config('default-text-size', '0.1')
    lv.save_image_with_options(
        output_png_path,
        width=4096, height=2160
        # ,
        # linewidth=2,
        # resolution=0.25  # 4x as large fonts
    )

def _run_rcx25d_single_cell(*path_components) -> Tuple[CellExtractionResults, CSVPath, PNGPath]:
    gds_path = _gds(*path_components)

    preview_png_path = tempfile.mktemp(prefix=f"layout_preview_", suffix=".png")
    _save_layout_preview(gds_path, preview_png_path)
    output_dir_path = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'output_sky130A'))
    cli = KpexCLI()
    cli.main(['main',
              '--pdk', 'sky130A',
              '--gds', gds_path,
              '--out_dir', output_dir_path,
              '--2.5D',
              '--halo', '10000',
              '--scale', 'n'])
    assert cli.rcx25_extraction_results is not None
    assert len(cli.rcx25_extraction_results.cell_extraction_results) == 1  # assume single cell test
    results = list(cli.rcx25_extraction_results.cell_extraction_results.values())[0]
    assert results.cell_name == path_components[-1][:-len('.gds.gz')]
    return results, cli.rcx25_extracted_csv_path, preview_png_path


def assert_expected_matches_obtained(*path_components,
                                     expected_csv_content: str) -> CellExtractionResults:
    result, csv, preview_png = _run_rcx25d_single_cell(*path_components)
    allure.attach.file(csv, name='pex_obtained.csv', attachment_type=allure.attachment_type.CSV)
    allure.attach.file(preview_png, name='📸 layout_preview.png', attachment_type=allure.attachment_type.PNG)
    expected_csv = csv_diff.load_csv(io.StringIO(expected_csv_content), key='Device')
    with open(csv, 'r') as f:
        obtained_csv = csv_diff.load_csv(f, key='Device')
        diff = csv_diff.compare(expected_csv, obtained_csv, show_unchanged=False)
        human_diff = csv_diff.human_text(
            diff, current=obtained_csv, extras=(('Net1','{Net1}'),('Net2','{Net2}'))
        )
        allure.attach(expected_csv_content, name='pex_expected.csv', attachment_type=allure.attachment_type.CSV)
        allure.attach(json.dumps(diff, sort_keys=True, indent='    ').encode("utf8"),
                      name='pex_diff.json', attachment_type=allure.attachment_type.JSON)
        allure.attach(human_diff.encode("utf8"), name='‼️ pex_diff.txt', attachment_type=allure.attachment_type.TEXT)
        # assert diff['added'] == []
        # assert diff['removed'] == []
        # assert diff['changed'] == []
        # assert diff['columns_added'] == []
        # assert diff['columns_removed'] == []
        assert human_diff == '', 'Diff detected'
    return result

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_single_plate_100um_x_100um_li1_over_substrate():
    # MAGIC GIVES (8.3 revision 485):
    #_______________________________ NOTE: with halo=8µm __________________________________
    # C0 PLATE VSUBS 0.38618p
    assert_expected_matches_obtained(
        'test_patterns', 'single_plate_100um_x_100um_li1_over_substrate.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;PLATE;VSUBS;386.179;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.wip
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
    assert_expected_matches_obtained(
        'test_patterns', 'overlap_plates_100um_x_100um_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;LOWER;UPPER;294.867;
C2;LOWER;VSUBS;386.179;
C3;UPPER;VSUBS;205.619;"""
    )

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.wip
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

    assert_expected_matches_obtained(
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
@pytest.mark.wip
def test_sidewall_100um_x_100um_distance_200nm_li1():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=8µm __________________________________
    # C0 A B 7.5f
    # C1 B VSUBS 8.231f
    # C2 A VSUBS 8.231f
    # _______________________________ NOTE: with halo=50µm __________________________________
    # (same!)

    assert_expected_matches_obtained(
        'test_patterns', 'sidewall_100um_x_100um_distance_200nm_li1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;A;B;7.5;
C2;A;VSUBS;8.231;
C3;B;VSUBS;8.231;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.wip
def test_sidewall_net_uturn_l1_redux():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=8µm __________________________________
    # C1 C1 VSUBS 12.5876f
    # C2 C0 VSUBS 38.1255f
    # C0 C0 C1 1.87386f
    # _______________________________ NOTE: with halo=50µm __________________________________
    # (same!)

    assert_expected_matches_obtained(
        'test_patterns', 'sidewall_net_uturn_l1_redux.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;C1;1.874;
C2;C0;VSUBS;38.125;
C3;C1;VSUBS;12.588;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.wip
def test_sidewall_cap_vpp_04p4x04p6_l1_redux():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=8µm __________________________________
    # C1 C1 VSUBS 0.086832f
    # C2 C0 VSUBS 0.300359f
    # C0 C0 C1 0.286226f
    # _______________________________ NOTE: with halo=50µm __________________________________
    # (same!)

    assert_expected_matches_obtained(
        'test_patterns', 'sidewall_cap_vpp_04p4x04p6_l1_redux.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;C1;0.286;
C2;C0;VSUBS;0.3;
C3;C1;VSUBS;0.087;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.wip
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

    assert_expected_matches_obtained(
        'test_patterns', 'near_body_shield_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;BOTTOM;TOPA;215.972;
C2;BOTTOM;TOPB;215.972;
C3;BOTTOM;VSUBS;405.081;
C4;TOPA;TOPB;0.503;
C5;TOPA;VSUBS;0.299;
C6;TOPB;VSUBS;0.299;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.wip
def test_lateral_fringe_shield_by_same_polygon_li1():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    #_______________________________ NOTE: with halo=8µm __________________________________
    # C0 C0 VSUBS 6.41431f $ **FLOATING
    #_______________________________ NOTE: with halo=50µm __________________________________
    # C0 C0 VSUBS 6.41431f $ **FLOATING
    assert_expected_matches_obtained(
        'test_patterns', 'lateral_fringe_shield_by_same_polygon_li1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;C0;VSUBS;6.414;"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.wip
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

    assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_simple_plates_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;li1;met1;0.157;
C2;VSUBS;li1;7.931;
C3;VSUBS;met1;248.899;"""
        )

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.wip
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

    assert_expected_matches_obtained(
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
@pytest.mark.wip
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

    assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_plates_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;LOWER_FullHaloOverlap;LOWER_NoHaloOverlap_InsideTop;0.126;
C2;LOWER_FullHaloOverlap;LOWER_OutsideHalo;0.101;
C3;LOWER_FullHaloOverlap;LOWER_PartialSideHaloOverlap_BothSides_separated;0.001;
C4;LOWER_FullHaloOverlap;LOWER_PartialSideHaloOverlap_Separated;0.248;
C5;LOWER_FullHaloOverlap;UPPER;262.817;
C6;LOWER_FullHaloOverlap;VSUBS;177.601;
C7;LOWER_NoHaloOverlap_InsideTop;LOWER_OutsideHalo;0.063;
C8;LOWER_NoHaloOverlap_InsideTop;LOWER_PartialSideHaloOverlap_Touching;0.063;
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
@pytest.mark.wip
def test_sideoverlap_fingered_li1_m1_patternA():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=50µm __________________________________
    #
    # C2 LOWER VSUBS 5.89976f
    # C1 UPPER VSUBS 72.328f
    # C0 LOWER UPPER 0.357768f

    assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_fingered_li1_m1_patternA.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;LOWER;UPPER;0.358;
C2;LOWER;VSUBS;5.9;
C3;UPPER;VSUBS;72.327;"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.wip
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

    assert_expected_matches_obtained(
        'test_patterns', 'sideoverlap_fingered_li1_m1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
C1;LOWER_PartialSideHaloOverlap_Fingered1;LOWER_PartialSideHaloOverlap_Fingered2;0.003;
C2;LOWER_PartialSideHaloOverlap_Fingered1;LOWER_PartialSideHaloOverlap_Fingered4;0.016;
C3;LOWER_PartialSideHaloOverlap_Fingered1;UPPER;0.244;
C4;LOWER_PartialSideHaloOverlap_Fingered1;VSUBS;5.884;
C5;LOWER_PartialSideHaloOverlap_Fingered2;LOWER_PartialSideHaloOverlap_Fingered3;0.002;
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
@pytest.mark.wip
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

    assert_expected_matches_obtained(
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
