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
import glob
import os
from typing import *

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.rcx25.extraction_results import CellExtractionResults
from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.csv_comparison import assert_csv_matches_expected
from tests.common.layout_preview import attach_layout_preview


CSVPath = str


def lvs_cache_dir(pdk_name: str) -> str:
    """
    The LVS cache of a PDK, shared by all tests and workers (and kept between CI runs, see integration-tests.yml)
    """
    return os.path.realpath(os.path.join(__file__, '..', '..', '..', f"output_{pdk_name}", '.kpex_cache'))


class PDKName(StrEnum):
    SKY130A = 'sky130A'
    IHP_SG13G2 = 'ihp-sg13g2'
    GF180MCUD = 'gf180mcuD'


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
    def output_dir(self) -> str:
        """
        Where the extractions write to: one directory per pytest-xdist worker (e.g. output_sky130A_worker0),
        so that parallel tests never write into each other's outputs
        """
        worker = os.environ.get('PYTEST_XDIST_WORKER', None)  # e.g. gw0
        suffix = f"_worker{worker.removeprefix('gw')}" if worker else ''
        return os.path.realpath(os.path.join(__file__, '..', '..', '..', f"output_{self.name}{suffix}"))

    @property
    def lvs_cache_dir(self) -> str:
        return lvs_cache_dir(self.name)

    @property
    def lyt_path(self) -> str:
        lyt_paths = glob.glob(os.path.join(self.kpex_pdk_dir, '*.lyt'))
        assert len(lyt_paths) == 1, f"Expected one KLayout technology file in {self.kpex_pdk_dir}"
        return os.path.abspath(lyt_paths[0])

    def gds_path(self, *path_components) -> str:
        return os.path.join(self.test_designs_dir, *path_components)


@dataclass
class RCX25Extraction:
    pdk: PDKTestConfig
    pex_mode: PEXMode
    blackbox: bool

    def run_rcx25d_single_cell(self, *path_components) -> Tuple[CellExtractionResults, CSVPath]:
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
                  '--scale', 'n'])
        assert cli.rcx25_extraction_results is not None
        assert len(cli.rcx25_extraction_results.cell_extraction_results) == 1  # assume single cell test
        results = list(cli.rcx25_extraction_results.cell_extraction_results.values())[0]
        assert results.cell_name == path_components[-1][:-len('.gds.gz')]
        return results, cli.rcx25_extracted_csv_path

    def written_device_lines(self, *path_components, prefixes: str = 'XDMQ') -> List[str]:
        """
        Extracts the single cell and returns the lines of the written SPICE netlist with these prefixes
        (by default not the capacitors and resistors KPEX adds), with their continuation lines joined
        """
        _, csv_path = self.run_rcx25d_single_cell(*path_components)
        with open(f"{os.path.splitext(csv_path)[0]}.spice") as f:
            lines = f.read().replace('\n+', '').splitlines()
        return [l for l in lines if l and l[0] in prefixes]

    def assert_expected_matches_obtained(self,
                                         *path_components,
                                         expected_csv_content: str) -> CellExtractionResults:
        result, csv_path = self.run_rcx25d_single_cell(*path_components)
        attach_layout_preview(self.pdk.lyt_path, self.pdk.gds_path(*path_components))
        assert_csv_matches_expected(csv_path, expected_csv_content)
        return result
