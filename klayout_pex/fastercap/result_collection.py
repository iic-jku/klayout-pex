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

"""Collect FasterCap electrical data without KLayout or solver execution."""

from pathlib import Path
import re
from typing import List, Optional, Tuple

from .fastercap_error import FasterCapError
from .fastercap_runner import fastercap_parse_capacitance_matrix
from klayout_pex_protobuf.kpex.result.capacitance_matrix_pb2 import MaxwellCapacitanceMatrix as Matrix


def collect_fastercap_matrix(log: Path, signals: List[str], ground: str, *,
                             numerical_report: Optional[Path] = None,
                             expected_input: Optional[str] = None,
                             expected_version: Optional[str] = None) -> Tuple[Matrix, Matrix]:
    if not signals or len(set(signals)) != len(signals) or ground in signals or not ground:
        raise FasterCapError('Measured conductors and ground must be distinct nonempty identities')
    if numerical_report is None:
        parsed = fastercap_parse_capacitance_matrix(str(log))
    else:
        from .numerical_report import read_numerical_report
        parsed = read_numerical_report(numerical_report, expected_input=expected_input,
                                       expected_version=expected_version)
    names = []
    for label in parsed.conductor_names:
        match = re.fullmatch(r'g[0-9]+_(.+)', label)
        if match is None:
            raise FasterCapError(f"Cannot map native conductor label '{label}'")
        names.append(match.group(1))
    if len(set(names)) != len(names) or set(names) != {*signals, ground}:
        raise FasterCapError('Native matrix does not identify exactly the prepared conductors and finite ground')
    native = Matrix(unit=Matrix.FARAD, conductor_ids=names, native_labels=parsed.conductor_names,
                    reference_convention=Matrix.POTENTIAL_AT_INFINITY, source_value_scale_to_farads=1e-6,
                    index_convention=Matrix.EXCITATION_ROWS)
    for row in parsed.rows:
        native.rows.add(values=row)
    measured = Matrix(unit=Matrix.FARAD, conductor_ids=signals,
                      reference_convention=Matrix.GROUNDED_PRINCIPAL_SUBMATRIX,
                      grounded_conductor_ids=[ground], index_convention=Matrix.EXCITATION_ROWS)
    positions = [names.index(name) for name in signals]
    for i in positions:
        measured.rows.add(values=[parsed.rows[i][j] for j in positions])
    return native, measured
