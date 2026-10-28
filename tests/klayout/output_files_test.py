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
Files written with a writer of KLayout, a .gz one compressed by Python (#361)
"""

import os
from typing import *

import allure
import klayout.db as kdb

from klayout_pex.klayout.output_files import write_output_file


def recording_layout_writer(written_paths: List[str]) -> Callable[[str], object]:
    """
    Writes a layout of a cell with a box, after appending the path to the list
    """
    layout = kdb.Layout()
    cell = layout.create_cell('TOP')
    cell.shapes(layout.layer(1, 0)).insert(kdb.Box(0, 0, 1000, 2000))

    def write(path: str) -> object:
        written_paths.append(path)
        return layout.write(path)
    return write


@allure.parent_suite("Unit Tests")
@allure.tag("KLayout")
def test_gz_file_is_written_plain_by_klayout_and_compressed_by_python(tmp_path):
    written_paths: List[str] = []
    path = str(tmp_path / 'cell.gds.gz')
    write_output_file(recording_layout_writer(written_paths), path)

    # NOTE: the format by the suffix before .gz, the plain file gone
    assert [os.path.basename(p) for p in written_paths] == ['cell.gds']
    assert os.listdir(tmp_path) == ['cell.gds.gz']
    with open(path, 'rb') as f:
        assert f.read(2) == b'\x1f\x8b'
    layout = kdb.Layout()
    layout.read(path)
    assert layout.top_cell().name == 'TOP'
    assert [s.box for s in layout.top_cell().shapes(layout.layer(1, 0)).each()] == [kdb.Box(0, 0, 1000, 2000)]


@allure.parent_suite("Unit Tests")
@allure.tag("KLayout")
def test_other_files_are_written_by_the_writer(tmp_path):
    written_paths: List[str] = []
    path = str(tmp_path / 'cell.oas')
    write_output_file(recording_layout_writer(written_paths), path)
    assert written_paths == [path]
    assert os.listdir(tmp_path) == ['cell.oas']
