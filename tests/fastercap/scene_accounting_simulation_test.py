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

"""Physical controls for charge accounting through serialized PEX25D scenes."""

from pathlib import Path
from typing import Any, Dict
import shutil
import subprocess

import pytest

from klayout_pex import pex25d
from klayout_pex.fastercap.output_interpreter import FasterCapOutputInterpreter
from klayout_pex.fastercap.fastercap_runner import fastercap_parse_capacitance_matrix
from klayout_pex.fastercap.pex25d_exporter import FasterCapSceneExporter
from klayout_pex.pex25d.accounting import SceneCapacitanceMap


def scene_text(case: str, partitioned: bool) -> str:
    header = 'PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING' if partitioned else 'PEX25D 1.0-rc1'
    shapes = 'BOX CONDUCTOR A LAYER met1 LL 0 0 UR 4 2\n'
    b = 'BOX CONDUCTOR B LAYER met1 LL 5 0 UR 7 2\n'
    upper_metal = 'METAL met2 Z_OFFSETS 1.25 1.45'
    via = ''
    if case == 'disconnected':
        shapes = ('BOX CONDUCTOR A LAYER met1 LL 0 0 UR 1.5 2\n'
                  'BOX CONDUCTOR A LAYER met1 LL 2.5 0 UR 4 2\n')
    elif case == 'stacked':
        shapes = 'BOX CONDUCTOR A LAYER met1 LL 0 0 UR 4 4\n'
        b = 'BOX CONDUCTOR B LAYER met2 LL 0 0 UR 4 4\n'
    elif case == 'via_contact':
        # A via joins the base across a horizontal face. Its accounting part
        # must share the base potential without adding a face at that seam.
        upper_metal = 'METAL met2 Z_OFFSETS 1.7 1.9'
        via = 'VIA via1 CONNECTS met1 met2'
        shapes += 'BOX CONDUCTOR A LAYER via1 LL 0.5 0.5 UR 1.5 1.5\n'
    elif case != 'touching':
        raise NotImplementedError(case)
    text = f'''{header}
UNITS LENGTH um GRID 0.001
GROUND_PLANE REF Z_OFFSETS -0.2 0
METAL met1 Z_OFFSETS 1 1.2
{upper_metal}
{via}
DIELECTRIC_BACKGROUND oxide PERMITTIVITY 3.9
CONDUCTOR A A
CONDUCTOR B B
{shapes}{b}DOMAIN_BOX LL -2 -2 -0.2 UR 9 6 2
'''
    if partitioned:
        # A mask without an exclusion rule partitions charge accounting only.
        # The expected unfiltered result is the original common-potential solve.
        layer = 'via1' if case == 'via_contact' else 'met1'
        text += f'CAP_REGION left LAYER {layer} OUTER -1 -1 2 -1 2 5 -1 5\n'
    return text


def solve(scene: Any, directory: Path, mesh: float) -> Dict[str, Dict[str, float]]:
    directory.mkdir(parents=True)
    # Decode the artifact again: no hidden layout/Exclusions object may be needed.
    artifact = directory/'input.pex25d.scene.pb'
    pex25d.write(scene, str(artifact))
    loaded = pex25d.read(str(artifact))
    deck = FasterCapSceneExporter().export(loaded, output_dir_path=str(directory))[0]
    log = directory/'solver.log'
    args = [shutil.which('FasterCap'), '-b', '-v', f'-m{mesh}', '-t1e-7', '-d0.1', '-f0', '-ap', deck]
    # Automatic -a overrides GMRES tolerance and is a global matrix criterion.
    # Fixed mesh + tight GMRES separates mesh error from charge-group aggregation.
    with log.open('w', encoding='utf-8') as output:
        result = subprocess.run(args, stdout=output, stderr=subprocess.STDOUT, timeout=180)
    assert result.returncode == 0, log.read_text(encoding='utf-8', errors='replace')
    matrix = fastercap_parse_capacitance_matrix(str(log))
    interpreter = FasterCapOutputInterpreter()
    labels = [interpreter.signal_name_from_conductor_name(name) for name in matrix.conductor_names]
    mapping = SceneCapacitanceMap(loaded)
    # A silent merge of charge partitions would make the numeric comparison
    # pass while destroying the information needed for exclusions.
    assert matrix.dimension == (4 if mapping.active else 3)
    assert set(labels) == set(mapping.parts)
    # Independent directional P^T C P; do not reuse the result aggregator under test.
    rows = {name: {other: 0.0 for other in ('A', 'B', 'REF')} for name in ('A', 'B', 'REF')}
    for i, label in enumerate(labels):
        first = mapping.parts[label].body.name
        for j, other in enumerate(labels):
            second = mapping.parts[other].body.name
            rows[first][second] += matrix[i][j]
    return rows


@pytest.mark.slow
@pytest.mark.fastercap
@pytest.mark.skipif(shutil.which('FasterCap') is None, reason='FasterCap is not installed')
@pytest.mark.parametrize('case', ['touching', 'disconnected', 'stacked', 'via_contact'])
def test_accounting_parts_preserve_common_potential_and_refine(case: str, tmp_path: Path):
    scenes = {partitioned: pex25d.resolve(pex25d.read_text(scene_text(case, partitioned).encode('utf-8')))
              for partitioned in (False, True)}
    outputs = {(partitioned, mesh): solve(scene, tmp_path/f'{partitioned}-{mesh}', mesh)
               for partitioned, scene in scenes.items() for mesh in (.002, .001)}
    whole, parts = outputs[False, .001], outputs[True, .001]
    scale = max(abs(whole[name][name]) for name in whole)
    for first in whole:
        assert whole[first][first] > 0 and parts[first][first] > 0
        for second in whole:
            if first != second:
                assert whole[first][second] < 0 and parts[first][second] < 0
                assert parts[first][second] == pytest.approx(parts[second][first], rel=.01, abs=scale*1e-5)
            assert parts[first][second] == pytest.approx(whole[first][second], rel=.005, abs=scale*1e-5)
            for partitioned in (False, True):
                assert outputs[partitioned, .001][first][second] == pytest.approx(
                    outputs[partitioned, .002][first][second], rel=.01, abs=scale*1e-5)
        assert sum(parts[first].values()) == pytest.approx(sum(whole[first].values()), rel=.01, abs=scale*1e-5)
