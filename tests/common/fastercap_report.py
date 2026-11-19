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

"""Fixtures for FasterCap's externally defined numerical report."""

from typing import Any, Dict, List


def numerical_report(names: List[str], rows: List[List[float]], input_file: str = 'geometry.lst') -> Dict[str, Any]:
    # Deliberately independent of KPEX protobuf serialization: this is the solver's contract.
    return {
        'schema_version': 1, 'input_file': input_file,
        'build': {'version': 'FasterCap version 6.3.0'},
        'status': {'exit_code': 0, 'name': 'FC_NORMAL_END'},
        'last_completed_iteration': 0,
        'iterations': [{
            'iteration': 0, 'solve_status': {'exit_code': 0, 'name': 'FC_NORMAL_END'}, 'finite': True,
            'panels': 24, 'links': 576,
            'matrix': {'units': 'F', 'reference_column': None,
                       'row_conductors': names, 'column_conductors': names,
                       'real': rows, 'imaginary': [[0.0] * len(names) for _ in names]},
        }],
    }
