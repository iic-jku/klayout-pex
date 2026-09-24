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
"""
Smoke test: `kpex extract --pdk <PDK>` works for each bundled PDK (e.g. all rule decks are packaged).

Requires the KLayout executable (see KPEX_KLAYOUT_EXE), see conftest.py for running the smoke tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import *

import allure
import pytest

from klayout_pex.pdk_config import PDK

if TYPE_CHECKING:
    from .conftest import InstalledWheel  # NOTE: the `installed_wheel` fixture


TESTDATA_DESIGNS_DIR = Path(__file__).resolve().parents[2] / 'testdata' / 'designs'

# NOTE: one small layout per bundled PDK, each PDK needs one
SMOKE_TEST_DESIGNS: Dict[PDK, Path] = {
    PDK.GF180MCUD: TESTDATA_DESIGNS_DIR / 'gf180mcuD' / 'test_patterns' / 'nfet_m1.gds.gz',
    PDK.IHP_SG13G2: TESTDATA_DESIGNS_DIR / 'ihp_sg13g2' / 'sg13g2_a21o_1' / 'sg13g2_a21o_1.gds.gz',
    PDK.IHP_SG13CMOS5L: TESTDATA_DESIGNS_DIR / 'ihp-sg13cmos5l' / 'cap_cmomf_w5u_l5u_m1_m4'
                        / 'cap_cmomf_w5u_l5u_m1_m4.gds.gz',
    PDK.SKY130A: TESTDATA_DESIGNS_DIR / 'sky130A' / 'inv' / 'inv.gds.gz',
}

parent_suite = "Smoke Tests (installed wheel)"
suite = "Bundled PDKs"
tags = ("Smoke", "Wheel", "Packaging", "PDK")


def _tail(text: str, lines: int = 40) -> str:
    return '\n'.join(text.splitlines()[-lines:])


@allure.parent_suite(parent_suite)
@allure.suite(suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk', list(PDK), ids=str)
def test_kpex_extract(pdk: PDK, installed_wheel: InstalledWheel, tmp_path: Path):
    assert pdk in SMOKE_TEST_DESIGNS, f"No smoke test design for PDK {pdk}, please add one to SMOKE_TEST_DESIGNS"
    gds_path = SMOKE_TEST_DESIGNS[pdk]
    assert gds_path.is_file(), f"Smoke test design is missing: {gds_path}"

    out_dir = tmp_path / 'out'
    proc = installed_wheel.run('kpex', 'extract',
                               '--pdk', pdk,
                               '--gds', gds_path,
                               '--2.5D',
                               '--out_dir', out_dir,
                               cwd=tmp_path)
    allure.attach(proc.stdout + proc.stderr, name='kpex output', attachment_type=allure.attachment_type.TEXT)

    # NOTE: output files are within <out_dir>/<gds stem>__<cell>/
    lvs_logs = sorted(out_dir.glob('*/*_lvs.log'))
    lvsdbs = sorted(out_dir.glob('*/*.lvsdb.gz'))
    netlists = sorted(out_dir.glob('*/*_k25d_pex_netlist.spice'))

    diagnostics = f"--- kpex output (tail):\n{_tail(proc.stdout + proc.stderr)}"
    for lvs_log in lvs_logs:
        lvs_log_text = lvs_log.read_text(errors='replace')
        allure.attach(lvs_log_text, name=lvs_log.name, attachment_type=allure.attachment_type.TEXT)
        errors = [line for line in lvs_log_text.splitlines() if 'ERROR' in line]
        diagnostics += f"\n--- ERROR lines of {lvs_log}:\n" + '\n'.join(errors[:20])

    returncode = proc.returncode
    assert returncode == 0, f"kpex failed with status {returncode}\n{diagnostics}"
    assert len(lvsdbs) == 1, f"Expected 1 LVSDB, got {lvsdbs}\n{diagnostics}"
    assert len(netlists) == 1 and netlists[0].stat().st_size > 0, \
        f"Expected 1 non-empty extracted netlist, got {netlists}\n{diagnostics}"
