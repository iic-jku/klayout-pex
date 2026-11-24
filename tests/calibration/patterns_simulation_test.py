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

"""Compare prepared substrate/fringe scenes with independent conductor solids."""

from pathlib import Path
import shutil
from typing import Dict, List, Tuple

from google.protobuf.json_format import MessageToJson
import klayout.db as kdb
import pytest

from kpex import pex25d
from kpex.calibration.patterns import read_patterns
from kpex.calibration.prepare import prepare_calibration
from kpex.fastercap.fastercap_model_generator import FasterCapModelBuilder
from kpex.fastercap.output_interpreter import FasterCapOutputInterpreter
from kpex.fastercap.pex25d_exporter import FasterCapSceneExporter
from kpex.tech_info import TechInfo
from kpex_protobuf.kpex.calibration.patterns_pb2 import PatternSetSpecification
from kpex_protobuf.kpex.tech.process_stack_pb2 import ProcessStackInfo as Stack
from kpex_protobuf.kpex.tech.tech_pb2 import Technology
from tests.common.fastercap_simulation import solve_fastercap


def uniform_technology(source: TechInfo) -> TechInfo:
    # Uniform dielectric permits a genuinely independent solid reference: no
    # production stack builder, resolver or calibration geometry is reused.
    tech = Technology()
    tech.CopyFrom(source.tech)
    for layer in list(tech.process_stack.layers):
        if layer.layer_type == Stack.LAYER_TYPE_CONFORMAL_DIELECTRIC:
            tech.process_stack.layers.remove(layer)
        elif layer.layer_type == Stack.LAYER_TYPE_FIELD_OXIDE:
            layer.field_oxide_layer.dielectric_k = 1.0
        elif layer.layer_type == Stack.LAYER_TYPE_SIMPLE_DIELECTRIC:
            layer.simple_dielectric_layer.dielectric_k = 1.0
    for number in (1, 2):
        canonical, profile = f'routing{number}', f'M{number}'
        drawn = tech.layers.add(name=canonical)
        drawn.drw_gds_pair.layer = number
        computed = tech.lvs_computed_layers.add(original_layer_name=canonical, process_layer_name=profile)
        computed.layer_info.name = profile
        computed.layer_info.drw_gds_pair.layer = number
    capacitance = tech.process_parasitics.capacitance
    capacitance.substrates.add(layer_name='routing1', area_capacitance=1.0, perimeter_capacitance=2.0)
    for edge, receiver in (('routing1', 'routing2'), ('routing2', 'routing1')):
        capacitance.sideoverlaps.add(in_layer_name=edge, out_layer_name=receiver, capacitance=3.0)
    return TechInfo(tech, dielectric_filter=None)


def pattern_specification(case: str) -> PatternSetSpecification:
    spec = PatternSetSpecification(schema_version=1, grid_um='0.001', domain_margin_um='2',
                          fringe_scale_mode='HALO_NORMALIZED')
    pattern = spec.patterns.add(id=case, width_um='2', length_um='4', role='TRAINING', target_ids=['coefficient'])
    target = spec.targets.add(id='coefficient')
    if case == 'substrate':
        pattern.substrate.layer = 'M1'
        target.substrate.layer.canonical_layer = 'routing1'
        target.substrate.layer.process_profile = 'M1'
        target.substrate.parameters.extend(['AREA', 'PERIMETER'])
    else:
        edge, receiver = (1, 2) if case == 'fringe_up' else (2, 1)
        pattern.directional_fringe.edge_layer = f'M{edge}'
        pattern.directional_fringe.receiver_layer = f'M{receiver}'
        pattern.directional_fringe.receiver_width_um = '4'
        # A=[0,2], B=[-1,3]. The wider receiver overhangs both long edges.
        pattern.directional_fringe.lateral_offset_um = '-3'
        target.sideoverlap.edge.canonical_layer = f'routing{edge}'
        target.sideoverlap.edge.process_profile = f'M{edge}'
        target.sideoverlap.receiver.canonical_layer = f'routing{receiver}'
        target.sideoverlap.receiver.process_profile = f'M{receiver}'
    return spec


def independent_solids(case: str, directory: Path) -> str:
    builder = FasterCapModelBuilder(dbu=0.001, k_void=1.0)
    # The ground plane is finite in this export. Derive its expected footprint
    # independently from the known conductors and the requested 2 um margin.
    xmin, xmax = (-3000, 5000) if case != 'substrate' else (-2000, 4000)
    builder.add_conductor('substrate', kdb.Region(kdb.Box(xmin, -2000, xmax, 6000)), z=-0.3, height=0.2)
    z_a, h_a = (2.0, 0.3) if case == 'fringe_down' else (1.0, 0.2)
    builder.add_conductor('A', kdb.Region(kdb.Box(0, 0, 2000, 4000)), z=z_a, height=h_a)
    if case != 'substrate':
        z_b, h_b = (1.0, 0.2) if case == 'fringe_down' else (2.0, 0.3)
        builder.add_conductor('B', kdb.Region(kdb.Box(-1000, 0, 3000, 4000)), z=z_b, height=h_b)
    directory.mkdir()
    return builder.generate().write_fastcap(str(directory), 'independent_')[0]


def solve(deck: str, log: Path, mesh: float, labels: Tuple[str, ...]) -> List[List[float]]:
    matrix = solve_fastercap(deck, log, mesh)
    interpreter = FasterCapOutputInterpreter()
    names = [interpreter.signal_name_from_conductor_name(name) for name in matrix.conductor_names]
    assert len(names) == len(labels) and set(names) == set(labels), names
    indices = [names.index(label) for label in labels]
    rows = [[matrix[i][j] for j in indices] for i in indices]
    for i, row in enumerate(rows):
        assert row[i] > 0
        for j, value in enumerate(row):
            if i != j:
                assert value < 0
                assert value == pytest.approx(rows[j][i], rel=0.02, abs=0)
    return rows


@pytest.mark.slow
@pytest.mark.fastercap
@pytest.mark.skipif(shutil.which('FasterCap') is None, reason='FasterCap is not installed')
@pytest.mark.parametrize('case', ['substrate', 'fringe_up', 'fringe_down'])
def test_prepared_patterns_match_independent_solids_and_refine(
        tmp_path: Path, tech_info: TechInfo, case: str):
    specification = tmp_path / 'patterns.json'
    specification.write_text(MessageToJson(pattern_specification(case)), encoding='utf-8')
    output = tmp_path / 'prepared'
    prepare_calibration(uniform_technology(tech_info), read_patterns(specification), output)
    # Exercise the serialized scene and normal exporter, rather than an in-memory
    # shortcut. Missing reference bodies or reversed layer assignments must fail.
    scene = pex25d.read(str(output / f'case_{case}.pex25d.scene.pb'))
    actual = FasterCapSceneExporter().export(scene, output_dir_path=str(tmp_path / 'actual'))[0]
    expected = independent_solids(case, tmp_path / 'independent')
    labels = ('A', 'substrate') if case == 'substrate' else ('A', 'B', 'substrate')
    final: Dict[str, List[List[float]]] = {}
    for kind, deck in (('actual', actual), ('independent', expected)):
        estimates = [solve(deck, tmp_path / f'{kind}-{mesh}.log', mesh, labels)
                     for mesh in (0.002, 0.001)]
        # A 2% per-entry refinement bound follows the existing finite-ground solver
        # regression. This checks numerical consistency, not a golden PDK fit.
        for coarse, fine in zip(*estimates):
            assert fine == pytest.approx(coarse, rel=0.02, abs=0)
        final[kind] = estimates[-1]
    for actual_row, expected_row in zip(final['actual'], final['independent']):
        assert actual_row == pytest.approx(expected_row, rel=0.02, abs=0)
