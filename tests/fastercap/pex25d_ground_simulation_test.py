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
"""Compare isolated-contact solves with independently assembled conductor solids."""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Dict, List

import klayout.db as kdb
import pytest

from klayout_pex import pex25d
from klayout_pex.common.capacitance_matrix import CapacitanceMatrix
from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder
from klayout_pex.fastercap.fastercap_runner import run_fastercap, fastercap_parse_capacitance_matrix
from klayout_pex.fastercap.pex25d_exporter import FasterCapSceneExporter
from tests.common.pex25d_ground import GROUND_CUTOUT_TEXT


def ordered_rows(matrix: CapacitanceMatrix, contact_name: str) -> List[List[float]]:
    assert matrix.dimension == 2  # Neither a shorted contact nor a phantom reference.
    indices = [next(i for i, name in enumerate(matrix.conductor_names)
                    if name.endswith('_' + target)) for target in ('VSS', contact_name)]
    assert len(set(indices)) == 2
    return [[matrix[i][j] for j in indices] for i in indices]


@pytest.mark.slow
@pytest.mark.fastercap
@pytest.mark.skipif(shutil.which('FasterCap') is None, reason='FasterCap is not installed')
@pytest.mark.parametrize('floating_collision', [False, True])
def test_isolated_contact_capacitance_matches_reference_solids(
        tmp_path: Path, floating_collision: bool):
    # A contact begins exactly at the ground top. Four independent rectangles
    # surround it with positive lateral clearance, so neither lifting the
    # contact nor silently merging a floating label into VSS can pass.
    text = GROUND_CUTOUT_TEXT
    contact_name = 'signal'
    if floating_collision:
        text = text.replace('CONDUCTOR pin signal', 'CONDUCTOR VSS FLOATING')
        text = text.replace('CONDUCTOR pin LAYER', 'CONDUCTOR VSS LAYER')
        contact_name = 'FLOATING:VSS'
    scene = pex25d.resolve(pex25d.read_text(text.encode('utf-8')))
    outputs = FasterCapSceneExporter().export(scene, output_dir_path=str(tmp_path / 'scene'))

    reference = FasterCapModelBuilder(dbu=0.001, k_void=1.0)
    ring = kdb.Region()
    for bounds in ((-3000, -3000, 3000, -1000), (-3000, 2000, 3000, 3000),
                   (-3000, -1000, -1000, 2000), (2000, -1000, 3000, 2000)):
        ring.insert(kdb.Box(*bounds))
    reference.add_conductor('VSS', ring.merged(), z=-0.1, height=0.1)
    reference.add_conductor(contact_name, kdb.Region(kdb.Box(0, 0, 1000, 1000)),
                            z=0.0, height=0.2)
    generator = reference.generate()
    reference_dir = tmp_path / 'reference'
    reference_dir.mkdir()
    reference_files = generator.write_fastcap(str(reference_dir), 'reference_')

    final: Dict[str, List[List[float]]] = {}
    for name, deck in (('scene', outputs[0]), ('reference', reference_files[0])):
        estimates = []
        for tolerance in (0.02, 0.005):
            log = str(tmp_path / f'{name}-{tolerance}.log')
            run_fastercap(shutil.which('FasterCap'), deck, log, tolerance, 0.1, 0,
                          True, False, False)
            rows = ordered_rows(fastercap_parse_capacitance_matrix(log), contact_name)
            assert rows[0][0] > 0 and rows[1][1] > 0
            assert rows[0][1] < 0 and rows[1][0] < 0
            assert rows[0][1] == pytest.approx(rows[1][0], rel=0.02, abs=0)
            estimates.append(rows)
        for before, after in zip(estimates[0], estimates[1]):
            assert after == pytest.approx(before, rel=0.02, abs=0)
        final[name] = estimates[-1]
    # Solver convergence, not a platform-specific golden capacitance.
    for actual, expected in zip(final['scene'], final['reference']):
        assert actual == pytest.approx(expected, rel=0.02, abs=0)
