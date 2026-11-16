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
"""Exporter capability queries and rejection before output is written."""
from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Any, FrozenSet, List

import pytest

from klayout_pex import pex25d
from klayout_pex.fastercap.pex25d_exporter import FasterCapSceneExporter, FastCap2SceneExporter
from klayout_pex.plugin_api.v1 import PEX25DSceneExporter, SceneCapability
from klayout_pex.stl.pex25d_exporter import STLSceneExporter
from tests.common.pex25d_ground import GROUND_CUTOUT_TEXT


@pytest.fixture
def ground_scene() -> Any:
    # Keep geometry valid so rejection specifically tests capability negotiation.
    return pex25d.resolve(pex25d.read_text(
        GROUND_CUTOUT_TEXT.replace('Z_OFFSETS 0 0.2', 'Z_OFFSETS 0.001 0.2').encode('utf-8')))


def test_class_query_does_not_require_construction_and_subclasses_can_extend():
    class GroundExporter(PEX25DSceneExporter):
        def __init__(self):
            pytest.fail('Metadata queries must not construct an exporter')

        @classmethod
        def supported_capabilities(cls) -> FrozenSet[SceneCapability]:
            return frozenset({SceneCapability.GROUND_CUTOUTS})

    class ExtendedExporter(GroundExporter):
        @classmethod
        def supported_capabilities(cls) -> FrozenSet[SceneCapability]:
            return super().supported_capabilities() | frozenset({SceneCapability.ELECTRICAL_IDENTITY})

    assert ExtendedExporter.supported_capabilities() == frozenset({
        SceneCapability.GROUND_CUTOUTS, SceneCapability.ELECTRICAL_IDENTITY})
    assert GroundExporter.supported_capabilities() == frozenset({SceneCapability.GROUND_CUTOUTS})
    assert PEX25DSceneExporter.supported_capabilities() == frozenset()




@pytest.mark.parametrize('supported', [
    frozenset(members) for size in range(len(SceneCapability) + 1)
    for members in combinations(SceneCapability, size)
])
def test_exact_required_subset_controls_export(
        supported: FrozenSet[SceneCapability], ground_scene: Any, tmp_path: Path):
    # All subsets exercise independent promises, partial support and extra support.
    # A capability unrelated to this scene must not compensate for a missing one.
    output = tmp_path/'output'

    class Exporter(PEX25DSceneExporter):
        @classmethod
        def supported_capabilities(cls) -> FrozenSet[SceneCapability]:
            return supported

        def export(self, scene: Any, **kwargs: Any) -> List[str]:
            output.mkdir()
            return [str(output)]

    required = frozenset({SceneCapability.GROUND_CUTOUTS, SceneCapability.ELECTRICAL_IDENTITY})
    if required <= supported:
        assert pex25d.export_with_backend(Exporter(), ground_scene, 'test', str(output)) == [str(output)]
    else:
        with pytest.raises(pex25d.ExportError, match='does not support required scene capabilities'):
            pex25d.export_with_backend(Exporter(), ground_scene, 'test', str(output))
        assert not output.exists()


@pytest.mark.parametrize('declaration', [
    {SceneCapability.GROUND_CUTOUTS, SceneCapability.ELECTRICAL_IDENTITY},
    [SceneCapability.GROUND_CUTOUTS, SceneCapability.ELECTRICAL_IDENTITY],
    'ground-cutouts,electrical-identity',
    frozenset({SceneCapability.GROUND_CUTOUTS, 'electrical-identity'}),
])
def test_malformed_method_result_does_not_authorize_export(declaration: Any, ground_scene: Any, tmp_path: Path):
    class Exporter(PEX25DSceneExporter):
        @classmethod
        def supported_capabilities(cls) -> Any:
            return declaration

        def export(self, scene: Any, **kwargs: Any) -> List[str]:
            pytest.fail('A malformed capability query must not authorize export')

    with pytest.raises(pex25d.ExportError, match='must return a frozenset of SceneCapability'):
        pex25d.export_with_backend(Exporter(), ground_scene, 'malformed', str(tmp_path/'output'))
    assert not (tmp_path/'output').exists()


def test_class_attribute_is_not_a_capability_method(ground_scene: Any, tmp_path: Path):
    class Exporter:
        supported_capabilities = frozenset(SceneCapability)

        def export(self, scene: Any, **kwargs: Any) -> List[str]:
            pytest.fail('A set attribute does not implement the method contract')

    with pytest.raises(pex25d.ExportError, match='as a class method'):
        pex25d.export_with_backend(Exporter(), ground_scene, 'attribute', str(tmp_path/'output'))
    assert not (tmp_path/'output').exists()


def test_query_failure_retains_plugin_context_and_cause(ground_scene: Any, tmp_path: Path):
    failure = RuntimeError('cannot determine capabilities')

    class Exporter:
        @classmethod
        def supported_capabilities(cls) -> FrozenSet[SceneCapability]:
            raise failure

        def export(self, scene: Any, **kwargs: Any) -> List[str]:
            pytest.fail('A failed capability query must not reach export')

    with pytest.raises(pex25d.ExporterExecutionError, match="Exporter 'broken' crashed") as raised:
        pex25d.export_with_backend(Exporter(), ground_scene, 'broken', str(tmp_path/'output'))
    assert raised.value.__cause__ is failure
    assert not (tmp_path/'output').exists()


def test_structural_exporter_without_query_still_accepts_ordinary_scene(ground_scene: Any, tmp_path: Path):
    ground_scene.ClearField('ground_plane')

    class OrdinaryExporter:
        def export(self, scene: Any, **kwargs: Any) -> List[str]:
            return ['ordinary-scene']

    assert pex25d.export_with_backend(
        OrdinaryExporter(), ground_scene, 'ordinary', str(tmp_path)) == ['ordinary-scene']
