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
"""IHP interconnect sheet limits remain separate from compact-device width laws."""

from __future__ import annotations

import copy
from pathlib import Path

import allure
import pytest

from klayout_pex.pdk_config import PDK
from klayout_pex.tech_catalog import load_technology_catalog
from klayout_pex.tech_info import TechInfo
from scripts.gen_tech_pb.corner_data import write_bundled_corner_catalog

pytestmark = allure.parent_suite('Unit Tests')
IHP_VARIANTS = [PDK.IHP_SG13G2, PDK.IHP_SG13CMOS5L]


@pytest.mark.parametrize('pdk', IHP_VARIANTS, ids=str)
def test_gatpoly_limits_come_from_interconnect_tables_without_changing_other_rows(pdk: PDK, tmp_path: Path):
    nominal = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    path = tmp_path / 'catalog.pb.json'
    write_bundled_corner_catalog(nominal, path)
    assert load_technology_catalog(path).tech == nominal
    for corner, expected in [('gatpoly-low-sheet', 6200.0), ('gatpoly-high-sheet', 7800.0)]:
        resolved = load_technology_catalog(path, corner)
        layers = resolved.tech.process_parasitics.resistance.layers
        poly = next(row for row in layers if row.layer_name == 'GatPoly')
        assert poly.resistance == expected  # mOhm/square from ITF RPSQ6.2/7.8 Ohm/square
        # Exact equality outside GatPoly prevents a hidden nominal fallback or unrelated
        # device/capacitance/geometry change from masquerading as this isolated sensitivity.
        poly.resistance = 7000.0
        restored = copy.deepcopy(resolved.tech)
        restored.device_models.CopyFrom(nominal.device_models)  # optional C references are unavailable here
        assert restored == nominal
        assert [(x.lvs_device_class_name, x) for x in resolved.tech.device_models.device_model_mappings
                if x.lvs_device_class_name in ('rsil', 'rppd', 'rhigh')] == [
                    (x.lvs_device_class_name, x) for x in nominal.device_models.device_model_mappings
                    if x.lvs_device_class_name in ('rsil', 'rppd', 'rhigh')]
        evidence = resolved.selection.resistance.provenance
        source_id = 'gatpoly-itf-min' if expected == 6200 else 'gatpoly-itf-max'
        source = next(x for x in evidence['sources'] if x['id'] == source_id)
        assert f'/{pdk}/libs.tech/parasitics/itf/' in source['uri']
        assert len(source['revision']) == 40 and len(source['sha256']) == 64
        assert {'fixed-layout', 'device-ownership', 'gatpoly-only'} <= {x['id'] for x in evidence['assumptions']}
        assert resolved.selection.physical_stack_matches is False
        assert resolved.selection.device_references is None


@pytest.mark.slow
def test_selected_sheet_corner_preserves_recognized_resistor_devices(tmp_path: Path):
    from klayout_pex.kpex_cli import KpexCLI
    from tests.common.cli_runner import run_cli
    from tests.common.lvsdb_fixtures import lvsdb_fixture_path
    from tests.common.pdk_test_config import PDKName, PDKTestConfig

    gds = PDKTestConfig(PDKName.IHP_SG13G2).gds_path('test_patterns', 'device_pcells.gds.gz')
    source = lvsdb_fixture_path('ihp-sg13g2', gds)
    devices = []
    for corner in ('nominal', 'gatpoly-low-sheet', 'gatpoly-high-sheet'):
        destination = tmp_path / f'{corner}.spice'
        code, output = run_cli(KpexCLI().main, ['kpex', 'extract', '--pdk', 'ihp-sg13g2', '--2.5D', '--mode', 'R',
                                               '--corner', corner, '--blackbox', 'n', '--lvsdb', source,
                                               '--out-dir', str(tmp_path / corner), '--out-netlist', str(destination)])
        assert code == 0, output
        lines = destination.read_text(encoding='utf-8').replace('\n+', '').splitlines()
        selected = [line for line in lines if line.startswith('X') and any(
            model in line.split() for model in ('rsil', 'rppd', 'rhigh'))]
        assert len(selected) == 3
        devices.append(selected)
    # Each recognized device stays one compact-model instance with identical terminals
    # and dimensions. Extracted wire corners do not rewrite the device's model law.
    assert devices[0] == devices[1] == devices[2]
