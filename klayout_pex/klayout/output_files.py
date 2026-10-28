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

import gzip
import os
import shutil
import tempfile
from typing import *


def write_output_file(write: Callable[[str], object], path: str):
    """
    Writes a file with a writer of KLayout (e.g. Layout.write, ReportDatabase.save), a .gz one compressed by Python:
    on Windows, KLayout leaks a C runtime stream with each gzip file it writes (_wfopen without fclose),
    of which a process has 512 (#361)

    :param write: the writer, called with the path to write to
    :param path: e.g. cell.gds.gz, or cell.oas, which the writer writes itself
    """
    if not path.lower().endswith('.gz'):
        write(path)
        return
    with tempfile.TemporaryDirectory() as tmp_dir:
        # NOTE: without .gz, but with the suffix that selects the format (e.g. .gds)
        plain_path = os.path.join(tmp_dir, os.path.basename(path)[:-len('.gz')])
        write(plain_path)
        with open(plain_path, 'rb') as plain, gzip.open(path, 'wb') as compressed:
            shutil.copyfileobj(plain, compressed)
