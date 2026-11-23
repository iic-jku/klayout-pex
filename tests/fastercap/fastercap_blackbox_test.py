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

import csv
import math
from pathlib import Path
from typing import Dict, FrozenSet, Tuple

import allure
import klayout.db as kdb
import pytest

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.run_result import FileKind
from tests.common.cli_runner import run_cli
from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.pdk_test_config import PDKName, PDKTestConfig


def extract_mim(tmp_path: Path, engine: str, blackbox: str, *options: str) \
        -> Tuple[str, Dict[FrozenSet[str], float], FrozenSet[str]]:
    pdk = PDKTestConfig(PDKName.IHP_SG13G2)
    gds = pdk.gds_path('sg13g2_pr__cmim', 'cmim.gds.gz')
    database_path = lvsdb_fixture_path(pdk.name, gds)
    database = kdb.LayoutVsSchematic()
    database.read(database_path)
    capacitor, = [device for device in database.netlist().top_circuit().each_device()
                  if device.device_class().name == 'cap_cmim']
    # Anonymous net numbers can change when LVS fixtures are regenerated.
    # Identify the physical plate pair from the retained device's terminals.
    plate_pair = frozenset(capacitor.net_for_terminal(terminal.id()).expanded_name()
                           for terminal in capacitor.device_class().terminal_definitions())
    assert len(plate_pair) == 2
    cli = KpexCLI()
    code, output = run_cli(cli.main, ['kpex', 'extract', '--pdk', pdk.name,
                                     '--lvsdb', database_path,
                                     engine, '--blackbox', blackbox, '--out-dir', str(tmp_path), *options])
    assert code == 0, output
    netlist_path = next(item.path for item in cli.run_result.files
                        if item.kind == FileKind.NETLIST and not item.reduced)
    csv_path = next(item.path for item in cli.run_result.files if item.kind == FileKind.NETLIST_CSV)
    values: Dict[FrozenSet[str], float] = {}
    with open(csv_path, encoding='utf-8') as stream:
        for row in csv.DictReader(stream, delimiter=';'):
            pair = frozenset((row['Net1'], row['Net2']))
            values[pair] = values.get(pair, 0.0) + float(row['Capacitance [fF]'])
    return Path(netlist_path).read_text(encoding='utf-8'), values, plate_pair


@allure.parent_suite("Unit Tests")
@allure.tag("Blackbox", "Device Models")
def test_analytical_blackbox_keeps_the_model_and_external_coupling(tmp_path: Path):
    blackbox_netlist, blackbox, pair = extract_mim(tmp_path / 'blackbox', '--2.5D', 'y')
    whitebox_netlist, whitebox, whitebox_pair = extract_mim(tmp_path / 'whitebox', '--2.5D', 'n')
    assert whitebox_pair == pair
    assert ' cap_cmim ' in blackbox_netlist
    assert ' cap_cmim ' not in whitebox_netlist
    # This real device has some routing coupling on the same terminal pair.
    # The supported alternative keeps that contribution, rather than deleting the pair.
    assert 0.0 < blackbox[pair] < whitebox[pair]
    for nets in whitebox.keys() - {pair}:
        assert blackbox[nets] == whitebox[nets]


@allure.parent_suite("kpex/FasterCap Extraction Tests")
@allure.tag("PEX", "FasterCap", "Device Models")
@pytest.mark.slow
@pytest.mark.fastercap
def test_field_solver_whitebox_replaces_the_real_mim_model(tmp_path: Path):
    netlist, values, pair = extract_mim(tmp_path, '--fastercap', 'n', '--ooc', '0', '--threads', '1',
                                     '--delaunay-b', '0', '--delaunay-amax', '0', '--auto-precond', 'n', '--jacobi')
    # A real converged solve proves that the full-geometry alternative still writes
    # capacitance in place of the removed model. Its numerical result is not a reference.
    assert ' cap_cmim ' not in netlist
    assert values[pair] > 0.0
    assert all(math.isfinite(value) and value > 0.0 for value in values.values())
