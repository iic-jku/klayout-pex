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


CSVPath = str
PNGPath = str
parent_suite = "kpex/FasterCap Extraction Tests"
tags = ("PEX", "FasterCap", "Maxwell")


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

def _extract_single_cell(*path_components) -> Tuple[CSVPath, PNGPath]:
    gds_path = _gds(*path_components)

    preview_png_path = tempfile.mktemp(prefix=f"layout_preview_", suffix=".png")
    _save_layout_preview(gds_path, preview_png_path)
    output_dir_path = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'output_sky130A'))
    cli = KpexCLI()
    cli.main(['main',
              '--pdk', 'sky130A',
              '--gds', gds_path,
              '--out_dir', output_dir_path,
              '--fastercap',
              '--ooc', '0',
              '--diel', 'none'])
    assert cli.fastercap_extracted_csv_path is not None
    return cli.fastercap_extracted_csv_path, preview_png_path


def assert_expected_matches_obtained(*path_components,
                                     expected_csv_content: str):
    csv, preview_png = _extract_single_cell(*path_components)
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


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.fastercap
def test_single_plate_100um_x_100um_li1_over_substrate():
    #_______________________________ NOTE: with halo=8µm __________________________________
    # C0 PLATE VSUBS 0.38618p
    assert_expected_matches_obtained(
        'test_patterns', 'single_plate_100um_x_100um_li1_over_substrate.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF]
Cext_0_1;VSUBS;PLATE;396.78
Cext_1_1;PLATE;VSUBS;3.33"""
        )
