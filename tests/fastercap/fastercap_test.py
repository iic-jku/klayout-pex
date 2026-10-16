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

import allure
import pytest
from typing import *

from klayout_pex.kpex_cli import KpexCLI
from tests.common.csv_comparison import assert_csv_matches_expected
from tests.common.layout_preview import attach_layout_preview
from tests.common.pdk_test_config import PDKName, PDKTestConfig


parent_suite = "kpex/FasterCap Extraction Tests"
tags = ("PEX", "FasterCap", "Maxwell")

sky130a = PDKTestConfig(PDKName.SKY130A)


def _extract_single_cell(*path_components) -> str:
    cli = KpexCLI()
    cli.main(['main',
              '--pdk', sky130a.name,
              '--gds', sky130a.gds_path(*path_components),
              '--out-dir', sky130a.output_dir,
              '--fastercap',
              '--ooc', '0',
              '--diel', 'none'])
    assert cli.fastercap_extracted_csv_path is not None
    return cli.fastercap_extracted_csv_path


def assert_expected_matches_obtained(*path_components,
                                     expected_csv_content: str):
    csv_path = _extract_single_cell(*path_components)
    attach_layout_preview(sky130a.lyt_path, sky130a.gds_path(*path_components))
    assert_csv_matches_expected(csv_path, expected_csv_content)


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
