#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/iic-jku/kpex).
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

from kpex.kpex_cli import KpexCLI
from kpex.fastercap.fastercap_input_builder import FasterCapInputBuilder
from kpex.tech_info import TechInfo
from kpex.util.multiple_choice import MultipleChoicePattern
from tests.common.csv_comparison import assert_csv_matches_expected
from tests.common.layout_preview import attach_layout_preview
from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.fastercap.fastercap_input_builder_test import context_of_layout


parent_suite = "kpex/FasterCap Extraction Tests"
tags = ("PEX", "FasterCap", "Maxwell")

sky130a = PDKTestConfig(PDKName.SKY130A)


def _extract_single_cell(*path_components) -> str:
    cli = KpexCLI()
    cli.main(['main', 'extract',
              '--pdk', sky130a.name,
              '--lvsdb', lvsdb_fixture_path(sky130a.name, sky130a.gds_path(*path_components)),
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


@allure.parent_suite("Unit Tests")
@allure.tag(*tags)
def test_single_plate_scene_preserves_subnanometre_source_heights():
    context, technology = context_of_layout(
        PDKName.SKY130A, 'test_patterns', 'single_plate_100um_x_100um_li1_over_substrate.gds.gz')
    technology = TechInfo(technology.tech, MultipleChoicePattern('none'))
    scene = FasterCapInputBuilder(context, technology, context.substrate_net_name, k_void=3.9).build_scene()
    assert (scene.units.grid_numerator, scene.units.grid_denominator) == (1, 10000)
    plate = next(layer for layer in scene.layers if layer.name == 'li1')
    oxide = next(layer for layer in scene.dielectrics if layer.name == 'fox')
    # The former direct input rounded these to 0.936/1.036 and 0.326 um.
    # They are geometry assertions, independent of the solver's adaptive mesh.
    assert (plate.zlow, plate.zhigh) == (9361, 10361)
    assert (oxide.zlow, oxide.zhigh, oxide.permittivity) == (0, 3262, 4.632)
    assert (scene.ground_plane.zlow, scene.ground_plane.zhigh) == (-4300, -1000)
    assert scene.background.permittivity == 3.9


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.fastercap
def test_single_plate_100um_x_100um_li1_over_substrate():
    # NOTE: the substrate is the port sky130_gnd, as the pattern has no substrate net (no transistor)
    # Canonical input retains the 0.1 nm source grid instead of flooring heights
    # to the layout's 1 nm grid. FasterCap 6.4 corrects conductor hierarchy bounds
    # and algebraic accuracy, changing the previous 392.14/3.97 fF default result.
    # The released macOS arm64 and Ubuntu amd64 packages give the same CSV below.
    # Independent -pj -d0.1 controls at -a0.005 and -a0.0025 give 372.42 fF mutual
    # capacitance, 0.65% below the default result. This exact CSV checks default
    # extraction and netlist conversion, not 0.01 fF physical accuracy.
    # Numerical corrections: https://github.com/iic-jku/FasterCap/releases/tag/v6.4.0
    assert_expected_matches_obtained(
        'test_patterns', 'single_plate_100um_x_100um_li1_over_substrate.gds.gz',
        expected_csv_content="""Device;Net1;Net2;Capacitance [fF]
Cext_0_1;sky130_gnd;PLATE;374.82
Cext_1_1;PLATE;sky130_gnd;4.26"""
        )
