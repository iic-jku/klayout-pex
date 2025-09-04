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

from dataclasses import dataclass
from enum import StrEnum
import io
import json
import os
import tempfile
from typing import *

import allure
import csv_diff

import klayout.db as kdb
import klayout.lay as klay

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.rcx25.extraction_results import CellExtractionResults
from klayout_pex.rcx25.pex_mode import PEXMode


class PDKName(StrEnum):
    SKY130A = 'sky130A'
    IHP_SG13G2 = 'ihp_sg13g2'


@dataclass
class PDKTestConfig:
    name: PDKName

    @property
    def kpex_pdk_dir(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'pdk', self.name, 'libs.tech', 'kpex'))

    @property
    def test_designs_dir(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'testdata', 'designs', self.name))

    @property
    def lyt_path(self) -> str:
        return os.path.abspath(os.path.join(self.kpex_pdk_dir, 'sky130A.lyt'))

    def load_kdb_technology(self) -> kdb.Technology:
        kdb.Technology.clear_technologies()
        tech = kdb.Technology.create_technology('sky130A')
        tech.load(self.lyt_path)
        return tech

    def gds_path(self, *path_components) -> str:
        return os.path.join(self.test_designs_dir, *path_components)


@dataclass
class RCX25Extraction:
    pdk: PDKTestConfig
    pex_mode: PEXMode
    blackbox: bool

    def save_layout_preview(self, gds_path: str, output_png_path: str):
        self.pdk.load_kdb_technology()
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

    def run_rcx25d_single_cell(self, *path_components) -> Tuple[CellExtractionResults, CSVPath, PNGPath]:
        gds_path = self.pdk.gds_path(*path_components)

        preview_png_path = tempfile.mktemp(prefix=f"layout_preview_", suffix=".png")
        self.save_layout_preview(gds_path, preview_png_path)
        output_dir_path = os.path.realpath(os.path.join(__file__, '..', '..', '..', f"output_{self.pdk.name}"))
        cli = KpexCLI()
        cli.main(['main',
                  '--pdk', self.pdk.name,
                  '--mode', self.pex_mode,
                  '--blackbox', 'y' if self.blackbox else 'n',
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

    def assert_expected_matches_obtained(self,
                                         *path_components,
                                         expected_csv_content: str) -> CellExtractionResults:
        result, csv, preview_png = self.run_rcx25d_single_cell(*path_components)
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
