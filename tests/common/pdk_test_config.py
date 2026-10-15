#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
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

"""
The PDKs of the tests: their test designs, KPEX's deck and technology files, and where extractions write to
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import glob
import os
from typing import *

import pytest


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

    def simulator_models_dir(self, simulator: str) -> Optional[str]:
        """
        The models of the PDK for the simulator (e.g. ngspice, vacask), $PDK_ROOT/<PDK>/libs.tech/<simulator>,
        None where they aren't installed
        """
        path = os.path.join(os.environ.get('PDK_ROOT', ''), self.name, 'libs.tech', simulator)
        return path if 'PDK_ROOT' in os.environ and os.path.isdir(path) else None

    def requires_simulator_models(self, *simulators: str) -> pytest.MarkDecorator:
        """
        Skips a test where the models of the PDK for one of the simulators aren't installed
        """
        missing = [s for s in simulators if self.simulator_models_dir(s) is None]
        return pytest.mark.skipif(bool(missing),
                                  reason=f"needs the {' and '.join(missing)} models of $PDK_ROOT/{self.name}")

    def gds_path(self, *path_components) -> str:
        return os.path.join(self.test_designs_dir, *path_components)
