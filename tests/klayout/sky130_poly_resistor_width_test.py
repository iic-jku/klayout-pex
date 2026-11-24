#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
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

"""A fixed-width poly resistor has one class, independent of length and rotation.

Regenerate the layout and its committed LVS database with the KLayout executable:
    poetry run python -m tests.klayout.sky130_poly_resistor_width_test
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import *

import klayout.db as kdb
import pytest

from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.pdk_test_config import PDKName, PDKTestConfig


@dataclass(frozen=True)
class PolyResistorCase:
    family: str
    width_nm: int
    length_nm: int
    rotation: int
    expected_suffix: Optional[str]

    @property
    def name(self) -> str:
        return f'{self.family}_w{self.width_nm}_l{self.length_nm}_r{self.rotation}'


def resistor_cases() -> List[PolyResistorCase]:
    # The model names specify transverse width, even when length is shorter.
    # Keep the existing half-open width windows; test each boundary on a 1 nm grid.
    widths = [('0p35', 350, 340, 360), ('0p69', 690, 680, 700),
              ('1p41', 1410, 1400, 1420), ('2p85', 2850, 2840, 2860),
              ('5p73', 5730, 5720, 5740)]
    cases: Dict[str, PolyResistorCase] = {}

    def add(case: PolyResistorCase):
        cases[case.name] = case

    for family in ('high', 'xhigh'):
        for suffix, width, lower, upper in widths:
            # Longitudinal edges deliberately match the other nominal widths.
            # 1.40 um is the lower boundary that duplicated the 0.69 um dummies.
            for length in (350, 690, 1400, 1410, 2000, 2850, 5730):
                for rotation in (0, 90):
                    add(PolyResistorCase(family, width, length, rotation, suffix))
            for drawn_width, expected in ((lower - 1, None), (lower, suffix),
                                          (upper - 1, suffix), (upper, None),
                                          (upper + 1, None)):
                add(PolyResistorCase(family, drawn_width, 2000, 90, expected))
        for length in (1399, 1419, 1420):
            for rotation in (0, 90):
                add(PolyResistorCase(family, 690, length, rotation, '0p69'))
        for rotation in (180, 270):
            add(PolyResistorCase(family, 690, 1400, rotation, '0p69'))
            add(PolyResistorCase(family, 1410, 690, rotation, '1p41'))
    return list(cases.values())


CASES = resistor_cases()
GDS_PATH = PDKTestConfig(PDKName.SKY130A).gds_path('test_patterns', 'fixed_width_poly_resistors.gds.gz')


@pytest.fixture(scope='module')
def devices_by_case() -> Dict[int, List[Tuple[str, float, float]]]:
    database = kdb.LayoutVsSchematic()
    database.read(lvsdb_fixture_path('sky130A', GDS_PATH))
    devices: Dict[int, List[Tuple[str, float, float]]] = defaultdict(list)
    for device in database.netlist().top_circuit().each_device():
        # The contacts are symmetric about the body, whose center stays in its
        # own 20 um grid square under every tested rotation.
        point = device.trans.disp
        index = int(point.y // 20) * 16 + int(point.x // 20)
        assert 0 <= index < len(CASES), (device.expanded_name(), point)
        devices[index].append((device.device_class().name,
                               device.parameter('W'), device.parameter('L')))
    return devices


@pytest.mark.parametrize('index,case', list(enumerate(CASES)), ids=[case.name for case in CASES])
def test_fixed_width_poly_resistor_has_only_its_transverse_width_class(
        index: int, case: PolyResistorCase,
        devices_by_case: Dict[int, List[Tuple[str, float, float]]]):
    actual = devices_by_case.get(index, [])
    if case.expected_suffix is None:
        assert actual == [], (case.name, actual)
        return
    assert len(actual) == 1, (case.name, actual)
    model, width, length = actual[0]
    assert model == f'sky130_fd_pr__res_{case.family}_po_{case.expected_suffix}'
    assert width == pytest.approx(case.width_nm * 0.001, rel=0, abs=1e-9)
    assert length == pytest.approx(case.length_nm * 0.001, rel=0, abs=1e-9)


def generate_layout():
    layout = kdb.Layout()
    layout.dbu = 0.001
    top = layout.create_cell('fixed_width_poly_resistors')
    for index, case in enumerate(CASES):
        cell = layout.create_cell(case.name)
        width, length = case.width_nm, case.length_nm
        shapes = [((66, 20), kdb.Box(0, -500, width, length + 500)),
                  ((66, 13), kdb.Box(-100, 0, width + 100, length)),
                  ((94, 20), kdb.Box(-200, -700, width + 200, length + 700)),
                  ((86 if case.family == 'high' else 79, 20),
                   kdb.Box(-300, -200, width + 300, length + 200))]
        for layer, box in shapes:
            cell.shapes(layout.layer(*layer)).insert(box)
        transform = kdb.Trans(case.rotation // 90, False,
                              10000 + (index % 16) * 20000,
                              10000 + (index // 16) * 20000)
        top.insert(kdb.CellInstArray(cell.cell_index(), transform))
    layout.write(GDS_PATH)
    lvsdb_fixture_path('sky130A', GDS_PATH)


if __name__ == '__main__':
    generate_layout()
