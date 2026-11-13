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

"""Reject full-ground shorts from real device and well-tap layouts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import klayout.db as kdb
import pytest

from klayout_pex import pex25d
from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.klayout.pex25d_builder import PEX25DBuilder
from klayout_pex.pdk_config import PDK
from klayout_pex.tech_info import TechInfo
from tests.common.lvsdb_fixtures import lvsdb_fixture_path


@pytest.mark.parametrize('pdk,directory,pattern', [
    (PDK.GF180MCUD, 'test_patterns', 'r_nwell_pfet_ntap_m1'),
    (PDK.GF180MCUD, 'test_patterns', 'r_ntap_pair_dnwell_m1_m2'),
    (PDK.IHP_SG13G2, 'nmos_diode2', 'nmos_diode2'),
    (PDK.IHP_SG13G2, 'test_patterns', 'r_ntap_pair_nwell_m1_m2'),
])
@pytest.mark.parametrize('blackbox_devices', [False, True])
def test_real_device_contacts_cannot_export_on_full_ground(
        pdk: PDK, directory: str, pattern: str, blackbox_devices: bool, tmp_path: Path):
    # These committed LVSDBs reproduce source/drain, well-tap and floating-body
    # failures. Blackboxing devices must not bypass physical contact checks.
    technology = TechInfo.from_json(pdk.config.tech_pb_json_path, dielectric_filter=None)
    gds = str(Path(__file__).resolve().parents[2] / 'testdata/designs' / str(pdk)
              / directory / (pattern + '.gds.gz'))
    lvsdb = kdb.LayoutVsSchematic()
    lvsdb.read(lvsdb_fixture_path(pdk.value, gds))
    context = KLayoutExtractionContext.prepare_extraction(
        lvsdb, pattern, technology, blackbox_devices=blackbox_devices)
    scene = pex25d.resolve(PEX25DBuilder(context, technology, pattern).build())
    # Reconstruct the unsafe full-plane scene; generated openings are covered
    # by the corresponding real-layout isolation regressions.
    scene.ground_plane.ClearField('cutouts')
    backend = Mock()
    report = pex25d.DiagnosticsReport()
    output = tmp_path / 'solver-input'
    with pytest.raises(pex25d.InvalidSceneError):
        pex25d.export_with_backend(backend, scene, 'test-exporter', str(output), report=report)
    assert report.num_errors > 0
    assert {d.code for d in report.diagnostics} == {'PEX25D-E0310'}
    backend.export.assert_not_called()
    assert not output.exists()
