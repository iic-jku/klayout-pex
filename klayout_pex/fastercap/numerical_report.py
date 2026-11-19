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

"""Read FasterCap's external numerical-report contract without repairing its evidence.

The upstream format is documented at
https://github.com/iic-jku/FasterCap/blob/v6.3.0/doc/numerical-report.md.
KPEX generates geometry in micrometres; 3D results are consequently scaled by
1e-6 to obtain farads, just as for the existing console-output reader.
"""

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from packaging.version import Version

from ..common.capacitance_matrix import CapacitanceMatrix
from .fastercap_error import FasterCapError


def _object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate report field '{key}'")
        result[key] = value
    return result


def _invalid_constant(value: str):
    raise ValueError(f'non-JSON number {value}')


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return value


def _numbers(rows: Any, count: int, name: str) -> List[List[float]]:
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError(f'{name} row count differs from conductor count')
    converted = []
    for row in rows:
        if not isinstance(row, list) or len(row) != count:
            raise ValueError(f'{name} column count differs from conductor count')
        values = []
        for value in row:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'{name} contains a nonfinite or nonnumeric value')
            values.append(float(value))
        converted.append(values)
    return converted


def read_numerical_report(path: Path, *, expected_input: Optional[str] = None,
                          expected_version: Optional[str] = None) -> CapacitanceMatrix:
    """Read the final successful real 3D matrix, preserving native excitation-row order.

    A present but invalid report is an error, never a reason to use rounded console
    values. Failed/partial reports remain useful artifacts, but are not valid
    capacitance results. Complex and 2D matrices need different result contracts.
    """
    try:
        data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_object,
                          parse_constant=_invalid_constant)
        if _integer(data['schema_version'], 'schema_version') != 1:
            raise ValueError('unsupported numerical report schema version')
        if not isinstance(data['input_file'], str) or not data['input_file']:
            raise ValueError('missing input identity')
        if expected_input is not None and data['input_file'] != expected_input:
            raise ValueError('report identifies a different solver input')
        from ..tool_version_constraints import Tool
        version = Tool.FASTERCAP.parse_version(data['build']['version'])
        if version is None or (expected_version is not None and version != Version(expected_version)):
            raise ValueError('report build version differs from the recorded solver')
        if (_integer(data['status']['exit_code'], 'exit_code') != 0
                or data['status']['name'] != 'FC_NORMAL_END'):
            raise ValueError(f"report records failed execution: {data['status']}")
        iterations = data['iterations']
        if not isinstance(iterations, list) or not iterations:
            raise ValueError('report has no completed matrix')
        if _integer(data['last_completed_iteration'], 'last_completed_iteration') != len(iterations) - 1:
            raise ValueError('last completed iteration does not identify the final record')
        for index, item in enumerate(iterations):
            if _integer(item['iteration'], 'iteration') != index:
                raise ValueError('iteration records are not consecutive')
        last = iterations[-1]
        if (_integer(last['solve_status']['exit_code'], 'solve_status.exit_code') != 0
                or last['solve_status']['name'] != 'FC_NORMAL_END' or last['finite'] is not True):
            raise ValueError('final matrix is nonfinite or its solve did not succeed')
        matrix = last['matrix']
        if matrix['units'] != 'F' or matrix['reference_column'] is not None:
            raise ValueError('only real 3D capacitance reports in F are supported')
        names = matrix['row_conductors']
        if (not isinstance(names, list) or not names
                or any(not isinstance(name, str) or not name for name in names)
                or len(set(names)) != len(names) or matrix['column_conductors'] != names):
            raise ValueError('matrix conductor identities or row/column ordering are invalid')
        real = _numbers(matrix['real'], len(names), 'real matrix')
        imaginary = _numbers(matrix['imaginary'], len(names), 'imaginary matrix')
        if any(value != 0 for row in imaginary for value in row):
            raise ValueError('complex capacitance cannot be represented by the real KPEX result')
        rows = []
        for row in real:
            scaled = [value / 1e6 for value in row]
            if any(value != 0 and result == 0 for value, result in zip(row, scaled)):
                raise ValueError('matrix unit conversion underflows')
            rows.append(scaled)
        return CapacitanceMatrix(conductor_names=names, rows=rows)
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError) as exc:
        raise FasterCapError(f"Could not read FasterCap numerical report '{path}': {exc}") from exc
