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
The LVS deck of the IHP PDKs, on a netlist instead of a layout (-rd layout_netlist),
for what the extraction of KPEX doesn't get to: KLayout's reader and the device combiner of the deck
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import *

import allure
import pytest

from klayout_pex.pdk_config import PDK
from tests.common.lvsdb_fixtures import klayout_exe_path
from tests.common.pdk_test_config import PDKName, PDKTestConfig


def combined_devices(netlist: str, model: str, tmp_path: Path) -> List[Dict[str, str]]:
    """
    :param netlist: a SPICE netlist, in the form a schematic has it
    :return: the parameters of the devices of the model, after the deck combined them
    """
    exe_path = klayout_exe_path()
    if exe_path is None:
        pytest.skip("needs the KLayout executable (KPEX_KLAYOUT_EXE)")
    netlist_path = tmp_path / 'netlist.cir'
    netlist_path.write_text(netlist, encoding='utf-8')
    target_netlist_path = tmp_path / 'target.cir'
    # NOTE: the deck wants a layout, which it leaves aside for the netlist
    gds_path = PDKTestConfig(PDKName.IHP_SG13G2).gds_path('test_patterns', 'r_single_wire_m1.gds.gz')
    result = subprocess.run([exe_path, '-b', '-r', PDK.IHP_SG13G2.config.pex_lvs_script_path,
                             '-rd', f"input={gds_path}",
                             '-rd', f"layout_netlist={netlist_path}",
                             '-rd', f"target_netlist={target_netlist_path}",
                             '-rd', f"report={tmp_path / 'report.lvsdb'}",
                             '-rd', 'net_only=true',
                             '-rd', 'combine_devices=true'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    assert result.returncode == 0, result.stderr
    return [dict(token.split('=') for token in line.split() if '=' in token)
            for line in target_netlist_path.read_text(encoding='utf-8').splitlines()
            if model.upper() in line and not line.startswith('*')]


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "IHP")
def test_mom_caps_combine_only_within_their_metal_range(tmp_path: Path):
    devices = combined_devices("""\
.subckt chip a b
C1 a b cap_cmomf w=5u l=5u m=1 mmin=1 mmax=5
C2 a b cap_cmomf w=5u l=5u m=1 mmin=2 mmax=4
C3 a b cap_cmomf w=5u l=5u m=1 mmin=2 mmax=4
C4 a b cap_cmomf w=5u l=5u m=1 mmin=2 mmax=5
.ends
.end
""", 'cap_cmomf', tmp_path)
    assert sorted((d['mmin'], d['mmax'], d['m']) for d in devices) == [('1', '5', '1'), ('2', '4', '2'), ('2', '5', '1')]


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "IHP")
def test_cmomi_caps_combine_only_within_their_feed(tmp_path: Path):
    # NOTE: as a name of the model library (xschem), a number (the extracted netlist) or left to the default
    devices = combined_devices("""\
.subckt chip a b
C1 a b cap_cmomi w=5u l=5u m=1 mmin=1 mmax=5 feed=double
C2 a b cap_cmomi w=5u l=5u m=1 mmin=1 mmax=5 feed=2
C3 a b cap_cmomi w=5u l=5u m=1 mmin=1 mmax=5
C4 a b cap_cmomi w=5u l=5u m=1 mmin=1 mmax=5 feed=same
C5 a b cap_cmomi w=5u l=5u m=1 mmin=1 mmax=5 feed=none
.ends
.end
""", 'cap_cmomi', tmp_path)
    assert sorted((d['feed'], d['m']) for d in devices) == [('0', '1'), ('1', '1'), ('2', '3')]
