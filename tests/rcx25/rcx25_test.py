#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024 Martin Jan Köhler and Harald Pretl
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
from typing import *
import unittest

import klayout.db as kdb
import klayout.lay as klay

from kpex.kpex_cli import KpexCLI
from kpex.rcx25.extraction_results import CellExtractionResults


CSVPath = str
PNGPath = str
parent_suite = "kpex/2.5D Extraction Tests"
tags = ("PEX", "2.5D", "MAGIC")


def _sky130a_testdata_dir() -> str:
    return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                         'testdata', 'designs', 'sky130A'))


def _gds(*path_components) -> str:
    return os.path.join(_sky130a_testdata_dir(), *path_components)


def _save_layout_preview(gds_path: str,
                         output_png_path: str):
    kdb.Technology.clear_technologies()
    default_lyt_path = os.path.abspath(f"{os.environ['PDK_ROOT']}/sky130A/libs.tech/klayout/tech/sky130A.lyt")
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
    tech_json_path = os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                                   'build', 'sky130A_tech.pb.json'))
    output_dir_path = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'output_sky130A'))
    cli = KpexCLI()
    cli.main(['main',
              '--tech', tech_json_path,
              '--gds', gds_path,
              '--out_dir', output_dir_path,
              '--2.5D', 'y'])
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
def test_single_plate_100um_x_100um_li1_over_substrate():
    # MAGIC GIVES (8.3 revision 485):
    #_______________________________ NOTE: with halo=8µm __________________________________
    # C0 PLATE VSUBS 0.38618p
    assert_expected_matches_obtained(
        'test_patterns', 'single_plate_100um_x_100um_li1_over_substrate.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF]
C1;PLATE;VSUBS;386.18"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
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
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF]
C1;LOWER;VSUBS;386.18
C2;LOWER;UPPER;294.592
C3;UPPER;VSUBS;205.52"""
    )

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_overlap_plates_100um_x_100um_li1_m1_m2_m3():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    #_______________________________ NOTE: with halo=8µm __________________________________
    # C7 li1 VSUBS 0.38618p
    # C3 li1 met1 0.294756p     # DIFFERS a bit !!! TODO
    # C6 met1 VSUBS 0.205833p   # DIFFERS a bit !!! TODO
    # C0 met1 met2 0.680652p    # DIFFERS a bit !!! TODO
    # C2 li1 met2 99.3128f      # DIFFERS a bit !!! TODO
    # C5 met2 VSUBS 52.151802f
    # C4 met3 VSUBS 0.136643p
    # C1 li1 met3 5.59194f
    #_______________________________ NOTE: with halo=50µm __________________________________
    # C9 li1 VSUBS 0.38618p
    # C5 li1 met1 0.294867p     # DIFFERS a bit !!! TODO
    # C8 met1 VSUBS 0.205621p   # DIFFERS, but that's a MAGIC issue (see test_overlap_plates_100um_x_100um_li1_m1)
    # C2 met1 met2 0.680769p
    # C4 li1 met2 99.518005f    # DIFFERS a bit !!! TODO
    # C7 met2 VSUBS 51.5767f    # DIFFERS a bit !!! TODO
    # C3 li1 met3 6.01281f      # DIFFERS !!! TODO
    # C0 met2 met3 0.0422f      # we don't have that?! !!! TODO
    # C6 met3 VSUBS 0.136103p   # DIFFERS a bit !!! TODO
    # C1 met1 met3 0.012287f    # NOTE: we don't have that, due to halo=8µm

    assert_expected_matches_obtained(
        'test_patterns', 'overlap_plates_100um_x_100um_li1_m1_m2_m3.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF]
C1;VSUBS;li1;386.18
C2;li1;met1;294.592
C3;VSUBS;met1;205.52
C4;met1;met2;680.482
C5;li1;met2;99.015
C6;VSUBS;met2;51.302
C7;VSUBS;met3;135.996
C8;li1;met3;5.031"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sidewall_100um_x_100um_distance_200nm_li1():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=8µm __________________________________
    # C2 C VSUBS 8.231f
    # C4 A VSUBS 8.231f
    # C3 B VSUBS 4.54159f
    # C0 B C 7.5f
    # C1 A B 7.5f
    # _______________________________ NOTE: with halo=50µm __________________________________
    # (same!)

    assert_expected_matches_obtained(
        'test_patterns', 'sidewall_100um_x_100um_distance_200nm_li1.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF]
C1;C;VSUBS;11.92  # TODO: magic=8.231f 
C2;A;VSUBS;11.92  # TODO: magic=8.231f
C3;B;VSUBS;11.92  # TODO: magic=4.452f
C4;B;C;7.5
C5;A;B;7.5"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sidewall_net_uturn_l1_redux():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=8µm __________________________________
    # C2 C0 VSUBS 38.1255f
    # C1 C1 VSUBS 12.5876f
    # C0 C0 C1 1.87386f
    # _______________________________ NOTE: with halo=50µm __________________________________
    # (same!)

    assert_expected_matches_obtained(
        'test_patterns', 'sidewall_net_uturn_l1_redux.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF]
C1;C0;VSUBS;40.642
C2;C1;VSUBS;15.079
C3;C0;C1;0.019 TODO, MAGIC=1.87386 fF"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_sidewall_cap_vpp_04p4x04p6_l1_redux():
    # MAGIC GIVES (8.3 revision 485): (sorting changed to match order)
    # _______________________________ NOTE: with halo=8µm __________________________________
    # C2 C0 VSUBS 0.300359f
    # C1 C1 VSUBS 0.086832f
    # C0 C0 C1 0.286226f
    # _______________________________ NOTE: with halo=50µm __________________________________
    # (same!)

    assert_expected_matches_obtained(
        'test_patterns', 'sidewall_cap_vpp_04p4x04p6_l1_redux.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF]
C1;C0;VSUBS;0.447 TODO
C2;C1;VSUBS;0.223 TODO
C3;C0;C1;0.145 TODO"""
        )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
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
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF]
C1;BOTTOM;VSUBS;405.082
C2;BOTTOM;TOPA;215.898
C3;BOTTOM;TOPB;215.898
C4;TOPA;TOPB;0.503"""
    )


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
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
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF]
C1;VSUBS;li1;7.932
C2;VSUBS;met1;249.059
C3;li1;met1;0.125 TODO"""
        )
