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

"""Reject foreign conductor contact with full ground before physical export."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from klayout_pex import pex25d
from klayout_pex.pex25d.exporters import validate_export_scene


def contact_scene(zlow: int = 0, zhigh: int = 10, net: str = 'signal') -> Any:
    return pex25d.resolve(pex25d.read_text(f"""PEX25D 1.0-rc1
UNITS LENGTH um GRID 0.001
GROUND_PLANE subs Z_OFFSETS -0.100 0.000
METAL contact Z_OFFSETS {zlow / 1000:.3f} {zhigh / 1000:.3f}
DIELECTRIC_BACKGROUND air PERMITTIVITY 1.0
CONDUCTOR terminal {net}
BOX CONDUCTOR terminal LAYER contact LL 0 0 UR 1 1
""".encode('utf-8')))


@pytest.mark.parametrize('zlow,zhigh,accepted', [
    (1, 10, True), (0, 10, False), (-1, 10, False),
    (-102, -101, True), (-101, -100, False), (-100, -99, False),
])
def test_closed_ground_boundaries(zlow: int, zhigh: int, accepted: bool):
    # One grid of clearance, exact face contact, and penetration on both faces.
    # Testing only positive-volume overlap would miss the original failure.
    scene = contact_scene(zlow, zhigh)
    report = pex25d.DiagnosticsReport()
    before = scene.SerializeToString(deterministic=True)
    if accepted:
        validate_export_scene(scene, report=report)
        assert not report.num_errors
    else:
        with pytest.raises(pex25d.InvalidSceneError):
            validate_export_scene(scene, report=report)
        assert [d.code for d in report.diagnostics] == ['PEX25D-E0310']
        assert "'terminal'" in report.diagnostics[0].message
        assert "'contact'" in report.diagnostics[0].message
        assert "'subs'" in report.diagnostics[0].message
    assert scene.SerializeToString(deterministic=True) == before


def test_ground_anchor_without_geometry_remains_valid():
    scene = contact_scene(1, 10)
    anchor = scene.layers.add(name='device-anchor', zlow=-1, zhigh=0)
    anchor.kind = anchor.RESOLVED_LAYER_KIND_METAL
    scene.conductors[0].regions.add(layer='device-anchor')
    validate_export_scene(scene)


def test_explicit_same_ground_body_retains_existing_behavior():
    validate_export_scene(contact_scene(net='subs'))


@pytest.mark.parametrize('name', ['floating-contact', 'subs'])
def test_floating_bodies_do_not_inherit_ground_ownership(name: str):
    scene = contact_scene(net='FLOATING')
    scene.conductors[0].name = name
    assert scene.conductors[0].floating
    with pytest.raises(pex25d.InvalidSceneError):
        validate_export_scene(scene)


def test_shared_export_preflight_writes_nothing_and_never_calls_backend(tmp_path: Path):
    scene = contact_scene()
    backend = Mock()
    output = tmp_path / 'solver-input'
    report = pex25d.DiagnosticsReport()
    with pytest.raises(pex25d.InvalidSceneError):
        pex25d.export_with_backend(backend, scene, 'test-exporter', str(output), report=report)
    backend.export.assert_not_called()
    assert not output.exists()
    assert [d.code for d in report.diagnostics] == ['PEX25D-E0310']


def test_interconnect_only_scene_still_reaches_backend(tmp_path: Path):
    backend = Mock()
    backend.export.return_value = ['input.lst']
    scene = contact_scene(1, 10)
    assert pex25d.export_with_backend(backend, scene, 'test-exporter', str(tmp_path)) == ['input.lst']
    backend.export.assert_called_once()


@pytest.mark.parametrize('target', ['fastercap', 'fastcap2', 'stl'])
def test_direct_builtin_export_calls_cannot_bypass_safeguard(target: str, tmp_path: Path):
    # Calling the implementation directly must be as safe as registry dispatch.
    backend = pex25d.exporter_registry().load(target)
    output = tmp_path / 'solver-input'
    with pytest.raises(pex25d.InvalidSceneError):
        backend.export(contact_scene(), output_dir_path=str(output))
    assert not output.exists()


def test_direct_model_build_rejects_before_meshing():
    from klayout_pex.fastercap.pex25d_exporter import FasterCapModelOptions
    from klayout_pex.fastercap.pex25d_model_builder import PEX25DFasterCapModelBuilder
    from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder
    with patch.object(FasterCapModelBuilder, 'generate') as generate:
        with pytest.raises(pex25d.InvalidSceneError):
            PEX25DFasterCapModelBuilder(contact_scene(), FasterCapModelOptions()).build()
    generate.assert_not_called()


def test_cli_reports_ground_contact_without_solver_output(tmp_path: Path):
    import json
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI
    scene_path = tmp_path / 'contact.pex25d.scene.pb'
    pex25d.write(contact_scene(), str(scene_path))
    output = tmp_path / 'solver-input'
    diagnostics = tmp_path / 'diagnostics.json'
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', 'export', str(scene_path), '--to', 'fastercap',
                         '--out-dir', str(output), '--diagnostics', 'json',
                         '--out-diagnostics', str(diagnostics)])
    assert completion.value.code == pex25d.ExitCode.DIAGNOSTIC_ERRORS
    report = json.loads(diagnostics.read_text(encoding='utf-8'))
    assert [d['code'] for d in report['diagnostics']] == ['PEX25D-E0310']
    assert not output.exists()
