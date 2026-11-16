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

from pathlib import Path
from typing import Any, Collection, Dict, Optional, Tuple
from unittest.mock import patch

import pytest

from klayout_pex import pex25d
from klayout_pex.common.capacitance_matrix import CapacitanceMatrix
from klayout_pex.pex25d.accounting import SceneCapacitanceMap
from klayout_pex.pex25d.electrical import BodyKind
from klayout_pex.fastercap.pex25d_exporter import FasterCapSceneExporter, FasterCapModelOptions
from klayout_pex.fastercap.pex25d_model_builder import PEX25DFasterCapModelBuilder
from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder
from klayout_pex.plugin_api.v1 import ExportError, require_scene_capabilities
from tests.pex25d.pex25d_fixtures import MINIMAL


def accounting_scene() -> Any:
    text = MINIMAL.replace('PEX25D 1.0-rc1',
                           'PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING')
    text += '''
CAP_REGION window LAYER met1 OUTER -0.1 -0.1 2.6 -0.1 2.6 1.1 -0.1 1.1
CAP_REGION window LAYER met2 OUTER -0.1 -0.1 2.6 -0.1 2.6 1.1 -0.1 1.1
CAP_EXCLUDE modeled WITHIN window LAYER_PAIR met1 met2
CAP_EXCLUDE_SUBSTRATE neta
'''
    return pex25d.resolve(pex25d.read_text(text.encode('utf-8')))


def graph_matrix(names: Collection[str], couplings: Dict[Tuple[str, str], float]) -> CapacitanceMatrix:
    indexes = {name: i for i, name in enumerate(names)}
    rows = [[0.0] * len(names) for _ in names]
    for (a, b), value in couplings.items():
        i, j = indexes[a], indexes[b]
        rows[i][i] += value
        rows[j][j] += value
        rows[i][j] -= value
        rows[j][i] -= value
    return CapacitanceMatrix(list(names), rows)


def mutual(matrix: CapacitanceMatrix, first: str, second: str) -> float:
    return -matrix[matrix.conductor_names.index(first)][matrix.conductor_names.index(second)]


def test_result_policy_filters_only_selected_parts_and_layer_pairs():
    scene = accounting_scene()
    mapping = SceneCapacitanceMap(scene)
    def label(body: str, layer: Optional[str] = None, selected: bool = False, reference: bool = False) -> str:
        return next(name for name, part in mapping.parts.items()
                    if (part.body.name, part.layer, bool(part.regions), part.is_reference) ==
                       (body, layer, selected, reference))
    a1, a2 = label('neta', 'met1', True), label('neta', 'met2', True)
    bi, bo = label('netb', 'met1', True), label('netb')
    ground = label('subs', reference=True)
    matrix = graph_matrix(mapping.parts, {(a2, bi): 3, (a2, bo): 2, (a1, bi): 7,
                                          (a2, ground): 11, (bi, ground): 13})
    result = mapping.matrix_of_bodies(matrix, matrix.conductor_names)
    # Same-terminal-pair coupling outside the region and same-layer coupling
    # survive. Suppressing an entire net pair would erase both.
    assert mutual(result, 'neta', 'netb') == 9
    assert mutual(result, 'neta', 'subs') == 0
    assert mutual(result, 'netb', 'subs') == 13
    assert all(sum(row) == pytest.approx(0, abs=1e-14) for row in result.rows)


def test_empty_policy_aggregation_preserves_unfiltered_common_potential():
    scene = accounting_scene()
    scene.capacitance_accounting.ClearField('exclusions')
    scene.capacitance_accounting.ClearField('excluded_substrate_nets')
    mapping = SceneCapacitanceMap(scene)
    names = list(mapping.parts)
    couplings = {(first, second): float(i+j+1) for i, first in enumerate(names)
                 for j, second in enumerate(names) if j > i}
    matrix = graph_matrix(names, couplings)
    result = mapping.matrix_of_bodies(matrix, names)
    # Independent reference: P^T C P, grouping by electrical body.
    for i, first in enumerate(result.conductor_names):
        for j, second in enumerate(result.conductor_names):
            expected = sum(matrix[a][b] for a, na in enumerate(names) for b, nb in enumerate(names)
                           if mapping.body_names[mapping.parts[na].body] == first
                           and mapping.body_names[mapping.parts[nb].body] == second)
            assert result[i][j] == pytest.approx(expected, abs=1e-14)


def test_float_name_collision_does_not_inherit_connected_net_exclusion():
    scene = accounting_scene()
    floating = scene.conductors.add(name='neta', net='FLOATING', floating=True)
    region = floating.regions.add(layer='met1', accounting_part_id='floating-part')
    box = region.boxes.add()
    box.lower_left.x, box.lower_left.y = 40000, 0
    box.upper_right.x, box.upper_right.y = 50000, 10000
    mapping = SceneCapacitanceMap(scene)
    name, part = next((n, p) for n, p in mapping.parts.items() if p.body.kind == BodyKind.FLOATING_BODY)
    assert name != 'neta'
    assert not mapping.leaves_out_reference(part)


def test_policy_export_uses_shared_geometry_and_writes_explicit_map(tmp_path: Path):
    scene = accounting_scene()
    before = scene.SerializeToString(deterministic=True)
    with patch.object(FasterCapModelBuilder, 'generate', autospec=True, side_effect=lambda model: model):
        builder = PEX25DFasterCapModelBuilder(scene, FasterCapModelOptions()).build()
    mapping = SceneCapacitanceMap(scene)
    assert set(builder.clayers) == set(mapping.parts)
    # Charge groups retain a common physical surface for each electrical body.
    assert {builder.group_by_conductor[name] for name, part in mapping.parts.items()
            if part.body.name == 'netb'} == {'netb'}
    assert scene.SerializeToString(deterministic=True) == before
    from types import SimpleNamespace
    generator = SimpleNamespace(write_fastcap=lambda **kwargs: [str(tmp_path/'input.lst')])
    with patch('klayout_pex.fastercap.pex25d_exporter.build_fastercap_model', return_value=generator):
        paths = FasterCapSceneExporter().export(scene, output_dir_path=str(tmp_path), prefix='case')
    import json
    artifact = json.loads((tmp_path/'caseaccounting.json').read_text(encoding='utf-8'))
    assert str(tmp_path/'caseaccounting.json') in paths
    assert {row['solver_name'] for row in artifact['parts']} == set(mapping.parts)


def test_exporter_without_policy_capability_refuses_before_geometry():
    from types import SimpleNamespace
    scene = accounting_scene()
    with pytest.raises(ExportError, match='capacitance-accounting'):
        require_scene_capabilities(SimpleNamespace(), scene, 'old exporter')


@pytest.mark.parametrize('duplicate', [False, True])
def test_result_labels_cannot_silently_alias_unknown_charge_groups(duplicate: bool):
    mapping = SceneCapacitanceMap(accounting_scene())
    labels = list(mapping.parts)
    labels[-1] = labels[0] if duplicate else 'not-in-scene'
    with pytest.raises(ValueError, match='repeats|unknown'):
        mapping.matrix_of_bodies(CapacitanceMatrix(labels, [[0.] * len(labels) for _ in labels]), labels)


def test_direct_cli_persists_exact_replay_scene_and_keeps_geometry_location(tmp_path: Path):
    from types import SimpleNamespace
    from klayout_pex.kpex_cli import KpexCLI
    from klayout_pex.fastercap.fastercap_input_builder import FasterCapInputBuilder
    scene = accounting_scene()
    args = SimpleNamespace(output_dir_path=str(tmp_path), k_void=3.5, delaunay_amax=1.,
                           delaunay_b=.5, geometry_check=False)
    context = SimpleNamespace(substrate_net_name='subs')
    with patch.object(FasterCapInputBuilder, 'build_scene', return_value=scene):
        deck, accounting = KpexCLI().build_fastercap_input(args, context, None, None)
    assert Path(deck).is_file()
    directory = tmp_path/'FasterCap_Input_Files'
    replay = pex25d.read(str(directory/'FasterCap_Input.pex25d.scene.pb'))
    assert replay == scene
    assert accounting.parts == SceneCapacitanceMap(replay).parts
    assert list((tmp_path/'Geometries').glob('*.stl'))
    assert not list((tmp_path/'Geometries').glob('FasterCap_Input_*'))
    assert not list(directory.glob('*.stl'))
    assert (directory/'FasterCap_Input_accounting.json').is_file()


def test_direct_cli_reports_export_failure_as_field_solver_error(tmp_path: Path):
    from types import SimpleNamespace
    from klayout_pex.kpex_cli import KpexCLI
    from klayout_pex.fastercap.fastercap_input_builder import FasterCapInputBuilder
    from klayout_pex.fastercap.fastercap_error import FasterCapError
    args = SimpleNamespace(output_dir_path=str(tmp_path), k_void=3.5, delaunay_amax=1.,
                           delaunay_b=.5, geometry_check=False)
    failure = ExportError('invalid physical scene')
    with patch.object(FasterCapInputBuilder, 'build_scene', return_value=accounting_scene()), \
         patch.object(FasterCapSceneExporter, 'export', side_effect=failure):
        with pytest.raises(FasterCapError, match='invalid physical scene') as caught:
            KpexCLI().build_fastercap_input(args, SimpleNamespace(substrate_net_name='subs'), None, None)
    assert caught.value.__cause__ is failure


def test_substrate_exclusion_keeps_coupling_to_routing_on_reference_net():
    scene = accounting_scene()
    scene.ground_plane.net = 'netb'
    mapping = SceneCapacitanceMap(scene)
    a = next(name for name, part in mapping.parts.items()
             if part.body.name == 'neta' and part.layer == 'met2')
    routing = next(name for name, part in mapping.parts.items()
                   if part.body.name == 'netb' and not part.is_reference and not part.regions)
    reference = mapping.reference_name
    # The reference slab and routing are at the same potential, but only the
    # slab contribution is excluded. A net-pair filter would wrongly drop both.
    matrix = graph_matrix(mapping.parts, {(a, routing): 5., (a, reference): 11.})
    result = mapping.matrix_of_bodies(matrix, matrix.conductor_names)
    assert mutual(result, 'neta', 'netb') == 5.
    assert all(sum(row) == pytest.approx(0, abs=1e-14) for row in result.rows)



def test_result_aggregation_accepts_fully_buried_accounting_part_without_panels():
    scene = pex25d.resolve(pex25d.read_text(b"""PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING
UNITS LENGTH um GRID 0.001
GROUND_PLANE REF Z_OFFSETS -0.2 0
METAL bottom Z_OFFSETS 1 1.2
METAL middle Z_OFFSETS 1.2 1.4
METAL top Z_OFFSETS 1.4 1.6
DIELECTRIC_BACKGROUND oxide PERMITTIVITY 3.9
CONDUCTOR A A
BOX CONDUCTOR A LAYER bottom LL 0 0 UR 4 2
BOX CONDUCTOR A LAYER middle LL 0 0 UR 4 2
BOX CONDUCTOR A LAYER top LL 0 0 UR 4 2
DOMAIN_BOX LL -2 -2 -0.2 UR 6 4 2
CAP_REGION interior LAYER middle OUTER 1 0.5 3 0.5 3 1.5 1 1.5
CAP_REGION exterior LAYER top OUTER 0 0 2 0 2 2 0 2
"""))
    mapping = SceneCapacitanceMap(scene)
    generator = PEX25DFasterCapModelBuilder(scene, FasterCapModelOptions()).build()
    exported = sorted({key.net_name for key, triangles in generator.cond_data.items() if triangles})
    buried = next(name for name, part in mapping.parts.items() if part.regions == {'interior'})
    exterior = next(name for name, part in mapping.parts.items() if part.regions == {'exterior'})
    # The middle patch is surrounded by A on all six faces. Its charge group
    # legitimately has no external panels and therefore no solver matrix axis.
    assert set(exported) == set(mapping.parts) - {buried}
    reference = mapping.reference_name
    matrix = graph_matrix(exported, {('A', exterior): 3., ('A', reference): 5.,
                                     (exterior, reference): 7.})
    for name, infinity in (('A', 1.5), (exterior, .5), (reference, 2.5)):
        index = exported.index(name)
        matrix[index][index] += infinity
    result = mapping.matrix_of_bodies(matrix, exported)
    assert result.conductor_names == ['A', 'REF']
    assert mutual(result, 'A', 'REF') == 12.
    assert [sum(row) for row in result.rows] == pytest.approx([2., 2.5], abs=1e-14)
