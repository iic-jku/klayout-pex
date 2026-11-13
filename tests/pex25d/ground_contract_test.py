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
"""Ground format and typed exporter ownership contracts."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, List

import pytest

from klayout_pex import pex25d
from tests.common.pex25d_ground import GROUND_CUTOUT_TEXT as BASE


# Capability negotiation is independent of physical contact checking.
CLEAR_GROUND_TEXT = BASE.replace('Z_OFFSETS 0 0.2', 'Z_OFFSETS 0.001 0.2')


def test_explicit_ground_round_trip_and_electrical_namespace():
    file = pex25d.read_text(BASE.encode('utf-8'), with_source_refs=True)
    assert file.ground_plane.name == 'subs'
    assert file.ground_plane.net == 'VSS'
    assert file.ground_plane.cutouts[0].source.line == 4
    text = pex25d.write_text(file)
    reparsed = pex25d.read_text(text)
    scene = pex25d.resolve(reparsed)
    assert scene.ground_plane.name == 'subs'
    assert scene.ground_plane.net == 'VSS'
    assert (scene.ground_plane.zlow, scene.ground_plane.zhigh) == (-100, 0)
    assert scene.ground_plane.cutouts == reparsed.ground_plane.cutouts
    assert scene.conductors[0].net == 'signal'
    assert scene.layers[0].zlow == 0



def test_cutout_record_order_does_not_change_geometry():
    lines = BASE.splitlines()
    lines[2], lines[3] = lines[3], lines[2]
    first = pex25d.resolve(pex25d.read_text(BASE.encode('utf-8')))
    second = pex25d.resolve(pex25d.read_text(('\n'.join(lines)).encode('utf-8')))
    assert first == second



@pytest.mark.parametrize('change', [
    lambda text: text.replace('NET VSS ', ''),
    lambda text: text.replace('GROUND_CUTOUT subs', 'GROUND_CUTOUT unknown'),
])
def test_cutouts_need_explicit_ground_ownership(change: Callable[[str], str]):
    with pytest.raises(pex25d.ReadError):
        pex25d.read_text(change(BASE).encode('utf-8'))



@pytest.mark.parametrize('net', ['FLOATING', ''])
def test_binary_cutout_scene_cannot_omit_ground_reference(net: str):
    scene = pex25d.resolve(pex25d.read_text(BASE.encode('utf-8')))
    scene.ground_plane.net = net
    report = pex25d.validate(scene)
    assert 'PEX25D-E0212' in {d.code for d in report.diagnostics}



def test_text_writer_does_not_invent_missing_ground_ownership():
    file = pex25d.read_text(BASE.encode('utf-8'))
    file.ground_plane.net = ''
    with pytest.raises(pex25d.WriteError, match='explicit reference NET'):
        pex25d.write_text(file)



def test_exporter_without_feature_support_receives_no_cutout_scene(tmp_path: Path):
    class OlderExporter:
        def export(self, scene: Any, **kwargs: Any) -> List[str]:
            pytest.fail('Old exporter must not receive unknown ground semantics')
    scene = pex25d.resolve(pex25d.read_text(CLEAR_GROUND_TEXT.encode('utf-8')))
    with pytest.raises(pex25d.ExportError, match='does not support required scene features'):
        pex25d.export_with_backend(OlderExporter(), scene, 'older-exporter', str(tmp_path / 'output'))
    assert not (tmp_path / 'output').exists()



def test_typed_ground_feature_reaches_updated_exporter(tmp_path: Path):
    from klayout_pex.plugin_api.v1 import SceneFeature
    class UpdatedExporter:
        scene_features = frozenset({SceneFeature.GROUND_CUTOUTS, SceneFeature.ELECTRICAL_IDENTITY})
        def export(self, scene: Any, **kwargs: Any) -> List[str]:
            return ['supported']
    scene = pex25d.resolve(pex25d.read_text(CLEAR_GROUND_TEXT.encode('utf-8')))
    assert pex25d.export_with_backend(UpdatedExporter(), scene, 'updated', str(tmp_path)) == ['supported']



def test_disambiguation_cannot_collide_with_other_connected_net():
    from klayout_pex.plugin_api.v1 import conductor_body, solver_body_names
    text = BASE.replace('CONDUCTOR pin signal', 'CONDUCTOR VSS FLOATING').replace('CONDUCTOR pin LAYER', 'CONDUCTOR VSS LAYER')
    scene = pex25d.resolve(pex25d.read_text(text.encode('utf-8')))
    scene.conductors.add(name='another-net', net='FLOATING:VSS')
    names = solver_body_names(scene)
    assert names[conductor_body(scene.conductors[0])] == 'FLOATING:VSS:2'
    assert len(set(names.values())) == 3



def test_unchanged_labels_write_no_mapping_file(tmp_path: Path):
    from klayout_pex.plugin_api.v1 import write_solver_body_map
    scene = pex25d.resolve(pex25d.read_text(BASE.encode('utf-8')))
    path = tmp_path / 'body_names.json'
    assert write_solver_body_map(scene, path) is None
    assert not path.exists()



@pytest.mark.parametrize('capability', [None, Ellipsis, frozenset({'ground-isolation'})])
def test_unimplemented_protocol_capability_is_not_support(capability: Any, tmp_path: Path):
    from klayout_pex.plugin_api.v1 import PEX25DSceneExporter
    class OldSubclass(PEX25DSceneExporter):
        scene_features = capability
        def export(self, scene: Any, **kwargs: Any) -> List[str]:
            pytest.fail('Inherited placeholders cannot authorize export')
    scene = pex25d.resolve(pex25d.read_text(CLEAR_GROUND_TEXT.encode('utf-8')))
    with pytest.raises(pex25d.ExportError, match='does not support required scene features'):
        pex25d.export_with_backend(OldSubclass(), scene, 'old-subclass', str(tmp_path))



@pytest.mark.parametrize('feature', ['cutout', 'net'])
def test_each_ground_contract_independently_requires_consumer_support(feature: str, tmp_path: Path):
    from klayout_pex.plugin_api.v1 import PEX25DSceneExporter
    class OldSubclass(PEX25DSceneExporter):
        def export(self, scene: Any, **kwargs: Any) -> List[str]:
            pytest.fail('An old Protocol subclass must refuse new geometry or ownership')
    text = CLEAR_GROUND_TEXT
    if feature == 'cutout':
        text = text.replace('NET VSS', 'NET subs')
    else:
        text = text.replace('GROUND_CUTOUT subs OUTER -1 -1 2 -1 2 2 -1 2\n', '')
        text = text.replace('Z_OFFSETS 0 0.2', 'Z_OFFSETS 0.001 0.2')
    scene = pex25d.resolve(pex25d.read_text(text.encode('utf-8')))
    with pytest.raises(pex25d.ExportError, match='does not support required scene features'):
        pex25d.export_with_backend(OldSubclass(), scene, 'old-subclass', str(tmp_path))



def test_floating_collision_alone_requires_electrical_identity_support(tmp_path: Path):
    from klayout_pex.plugin_api.v1 import PEX25DSceneExporter
    class OlderExporter(PEX25DSceneExporter):
        def export(self, scene: Any, **kwargs: Any) -> List[str]:
            pytest.fail('A collision-only scene still needs typed electrical identity')
    text = BASE.replace('NET VSS', 'NET subs')
    text = text.replace('GROUND_CUTOUT subs OUTER -1 -1 2 -1 2 2 -1 2\n', '')
    text = text.replace('Z_OFFSETS 0 0.2', 'Z_OFFSETS 0.001 0.2')
    text = text.replace('CONDUCTOR pin signal', 'CONDUCTOR subs FLOATING').replace('CONDUCTOR pin LAYER', 'CONDUCTOR subs LAYER')
    scene = pex25d.resolve(pex25d.read_text(text.encode('utf-8')))
    with pytest.raises(pex25d.ExportError, match='electrical-identity'):
        pex25d.export_with_backend(OlderExporter(), scene, 'older', str(tmp_path))


def test_strict_cutout_validation_without_native_geometry_reports_diagnostic():
    import subprocess
    import sys
    script = f"""
import importlib.abc
import sys
class BlockNativeGeometry(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'klayout':
            raise ImportError('native geometry deliberately unavailable')
sys.meta_path.insert(0, BlockNativeGeometry())
from klayout_pex import pex25d
file = pex25d.read_text({BASE.encode('utf-8')!r})
assert not pex25d.validate(file).num_errors
report = pex25d.validate(file, strict=True)
assert {{d.code for d in report.diagnostics}} == {{'PEX25D-E0311'}}, report
assert 'requires KLayout' in report.diagnostics[0].message
"""
    result = subprocess.run([sys.executable, '-c', script], capture_output=True,
                            text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + '\n' + result.stderr
