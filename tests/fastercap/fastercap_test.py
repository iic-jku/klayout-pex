#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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

import io
import json

import allure
import csv_diff
import os
import pytest
from typing import *

from klayout_pex.kpex_cli import KpexCLI
from tests.common.layout_preview import attach_layout_preview
from tests.rcx25.rcx25_test_helpers import PDKName, PDKTestConfig


CSVPath = str
parent_suite = "kpex/FasterCap Extraction Tests"
tags = ("PEX", "FasterCap", "Maxwell")


def _sky130a_testdata_dir() -> str:
    return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                         'testdata', 'designs', 'sky130A'))


def _gds(*path_components) -> str:
    return os.path.join(_sky130a_testdata_dir(), *path_components)


def _extract_single_cell(*path_components) -> CSVPath:
    gds_path = _gds(*path_components)

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
    return cli.fastercap_extracted_csv_path


def assert_expected_matches_obtained(*path_components,
                                     expected_csv_content: str):
    csv = _extract_single_cell(*path_components)
    allure.attach.file(csv, name='pex_obtained.csv', attachment_type=allure.attachment_type.CSV)
    attach_layout_preview(PDKTestConfig(PDKName.SKY130A).lyt_path, _gds(*path_components))
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
    #
    # NOTE: the substrate is the port sky130_gnd, as the pattern has no substrate net (no transistor)
    assert_expected_matches_obtained(
        'test_patterns', 'single_plate_100um_x_100um_li1_over_substrate.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF]
Cext_0_1;sky130_gnd;PLATE;396.78
Cext_1_1;PLATE;sky130_gnd;3.33"""
        )
