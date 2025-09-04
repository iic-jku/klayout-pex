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
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import *


@dataclass
class CapacitanceMatrix:
    conductor_names: List[str]  # NOTE FasterCap generates [g_1, g_2, ...]
    rows: List[List[float]]     # NOTE: in µm

    def __getitem__(self, key):
        return self.rows.__getitem__(key)

    def __setitem__(self, key, value):
        self.rows.__setitem__(key, value)

    @property
    def dimension(self):
        return len(self.conductor_names)

    @classmethod
    def parse_csv(cls, path: str, separator: str = ';'):
        with open(path, 'r') as f:
            lines = f.readlines()
            if len(lines) < 2:
                raise Exception(f"Capacitance Matrix CSV must at least have 2 lines: "
                                f"{path}")
            conductor_names = [cell.strip() for cell in lines[0].split(sep=separator)]
            rows = []
            for line in lines[1:]:
                row = [float(cell.strip()) for cell in line.split(sep=separator)]
                rows.append(row)
            return CapacitanceMatrix(conductor_names=conductor_names,
                                     rows=rows)

    def write_csv(self, output_path: str, separator: str = ';'):
        with open(output_path, 'w', encoding='utf-8') as f:
            header_line = separator.join(self.conductor_names)
            f.write(header_line)
            f.write('\n')

            for row in self.rows:
                cells = ['%.12g' % cell for cell in row]
                row_line = separator.join(cells)
                f.write(row_line)
                f.write('\n')

    def averaged_off_diagonals(self) -> CapacitanceMatrix:
        c = copy.deepcopy(self)
        for i in range(len(self.rows)):
            for j in range(len(self.conductor_names)):
                if j <= i:
                    continue
                v1 = self[i][j]
                v2 = self[j][i]
                avg = (v1 + v2) / 2
                # print(f"i={i} j={j}, avg({v1}, {v2}) == {avg}")
                c[i][j] = avg
                c[j][i] = avg
        return c
