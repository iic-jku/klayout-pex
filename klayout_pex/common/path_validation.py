#! /usr/bin/env python3
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

from dataclasses import dataclass, field
from pathlib import Path
from typing import *


@dataclass
class FileValidationResult:
    @dataclass
    class Failure:
        path: Path
        reason: str

    working_files: List[Path] = field(default_factory=list)
    failures: List[Failure] = field(default_factory=list)


def validate_files(file_paths: List[str | Path],
                   read_bytes: int = 4) -> FileValidationResult:
    """
    :param file_paths: paths to validate
    :param read_bytes: how much bytes to read from the file
    :return: file validation result object

    # Example usage
    files = ["file1.txt", "file2.txt", "missing_file.txt"]
    result = validate_files(files)

    print("Working files:", result.working_files)
    print("Failed files:", result.failed_paths_and_reason)
    """
    result = FileValidationResult()

    for path_str in file_paths:
        path = Path(path_str)
        if not path.exists():
            result.failures.append(FileValidationResult.Failure(path_str, "File does not exist"))
            continue
        if not path.is_file():
            result.failures.append(FileValidationResult.Failure(path_str, "Not a regular file"))
            continue
        try:
            with open(path, "rb") as f:
                f.read(read_bytes)
            result.working_files.append(path_str)
        except Exception as e:
            result.failures.append(FileValidationResult.Failure(path_str, f"Unreadable: {e}"))

    return result


