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
import os
from typing import *

import klayout.db as kdb

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.netlist.netlist_format import NetlistFormat
from klayout_pex.rcx25.extraction_results import CellExtractionResults
from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.csv_comparison import assert_csv_matches_expected
from tests.common.layout_preview import attach_layout_preview
from tests.common.pdk_test_config import PDKTestConfig


CSVPath = str


def read_lvsdb(csv_path: CSVPath, cell_name: str) -> kdb.LayoutVsSchematic:
    """
    The LVS database of the extraction that wrote the CSV, which the CLI writes next to it
    """
    lvsdb = kdb.LayoutVsSchematic()
    lvsdb.read(os.path.join(os.path.dirname(csv_path), f"{cell_name}.lvsdb.gz"))
    return lvsdb


@dataclass
class RCX25Extraction:
    pdk: PDKTestConfig
    pex_mode: PEXMode
    blackbox: bool

    def run_kpex(self, *path_components, extra_args: Sequence[str] = ()) -> KpexCLI:
        """
        Extracts the single cell with the options of the tests and the extra ones

        :return: the CLI, e.g. for the paths it wrote
        """
        gds_path = self.pdk.gds_path(*path_components)

        cli = KpexCLI()
        cli.main(['main',
                  '--pdk', self.pdk.name,
                  '--mode', self.pex_mode,
                  '--blackbox', 'y' if self.blackbox else 'n',
                  '--gds', gds_path,
                  '--out_dir', self.pdk.output_dir,
                  '--cache-dir', self.pdk.lvs_cache_dir,
                  '--2.5D',
                  '--halo', '10000',
                  '--scale', 'n',
                  *extra_args])
        return cli

    def run_rcx25d_single_cell(self, *path_components) -> Tuple[CellExtractionResults, CSVPath]:
        cli = self.run_kpex(*path_components)
        assert cli.rcx25_extraction_results is not None
        assert len(cli.rcx25_extraction_results.cell_extraction_results) == 1  # assume single cell test
        results = list(cli.rcx25_extraction_results.cell_extraction_results.values())[0]
        assert results.cell_name == path_components[-1][:-len('.gds.gz')]
        return results, cli.rcx25_extracted_csv_path

    def written_netlist_paths(self,
                              *path_components,
                              netlist_format: NetlistFormat) -> Dict[NetlistFormat, str]:
        """
        Extracts the single cell and returns the paths of the netlists written into the run directory
        """
        return self.run_kpex(*path_components, extra_args=['--netlist_format', netlist_format]).rcx25_netlist_paths

    def written_netlist_lines(self, *path_components) -> Tuple[List[str], List[str]]:
        """
        Extracts the single cell and returns the lines of the written netlists, CSV and SPICE,
        the latter with their continuation lines joined
        """
        _, csv_path = self.run_rcx25d_single_cell(*path_components)
        with open(csv_path) as f:
            csv_lines = f.read().splitlines()
        with open(f"{os.path.splitext(csv_path)[0]}.spice") as f:
            spice_lines = f.read().replace('\n+', '').splitlines()
        return csv_lines, spice_lines

    def written_device_lines(self, *path_components, prefixes: str = 'XDMQ') -> List[str]:
        """
        Extracts the single cell and returns the lines of the written SPICE netlist with these prefixes
        (by default not the capacitors and resistors KPEX adds), with their continuation lines joined
        """
        _, spice_lines = self.written_netlist_lines(*path_components)
        return [l for l in spice_lines if l and l[0] in prefixes]

    def assert_expected_matches_obtained(self,
                                         *path_components,
                                         expected_csv_content: str) -> CellExtractionResults:
        result, csv_path = self.run_rcx25d_single_cell(*path_components)
        attach_layout_preview(self.pdk.lyt_path, self.pdk.gds_path(*path_components))
        assert_csv_matches_expected(csv_path, expected_csv_content)
        return result
