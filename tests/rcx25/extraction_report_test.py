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
from __future__ import annotations

import os
import tempfile
from typing import *

import allure
import klayout.rdb as rdb
import pytest

from klayout_pex.kpex_cli import KpexCLI


CELL = 'sideoverlap_simple_plates_li1_m1'
GDS_PATH = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata', 'designs', 'sky130A',
                                         'test_patterns', f"{CELL}.gds.gz"))


def report_category_names(*report_caps_args: str) -> List[str]:
    with tempfile.TemporaryDirectory() as out_dir:
        KpexCLI().main(['main',
                        '--pdk', 'sky130A',
                        '--gds', GDS_PATH,
                        '--out_dir', out_dir,
                        '--2.5D',
                        '--mode', 'CC',
                        *report_caps_args])
        report = rdb.ReportDatabase('')
        report.load(os.path.join(out_dir, f"{CELL}__{CELL}", f"{CELL}_k25d_pex_report.rdb.gz"))
        return [c.name() for c in report.each_category()]


@allure.parent_suite("kpex/2.5D Extraction Tests")
@allure.tag("PEX", "2.5D", "Report")
@pytest.mark.slow
def test_report_has_the_capacitances_only_with_report_caps():
    # NOTE: a category for each capacitance contribution takes much memory and time on large layouts
    names = report_category_names()
    assert [n for n in names if n.startswith('[C]')] == []

    names = report_category_names('--report_caps', 'y')
    assert '[C] Overlap' in names
    assert '[C] Fringe / Side Overlap' in names


@allure.parent_suite("kpex/2.5D Extraction Tests")
@allure.tag("PEX", "2.5D", "Report")
def test_report_caps_rejects_an_invalid_value(capsys: pytest.CaptureFixture):
    with pytest.raises(SystemExit):
        KpexCLI().main(['main', '--pdk', 'sky130A', '--gds', GDS_PATH, '--2.5D', '--report_caps', 'maybe'])
    assert "argument --report_caps: Boolean value expected" in capsys.readouterr().err
