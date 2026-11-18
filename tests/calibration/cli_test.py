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

"""The preparation subcommand runs without layout input and refuses unsupported work."""

import json
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import allure
from google.protobuf.json_format import MessageToDict, Parse
import pytest

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.pdk_config import PDK
from klayout_pex.tech_identity import message_sha256
from klayout_pex.tech_info import TechInfo
from klayout_pex_protobuf.kpex.calibration.preparation_pb2 import CalibrationManifest
from tests.common.cli_runner import run_cli

pytestmark = allure.parent_suite('Unit Tests')


def test_help_explains_preparation_scope():
    code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'prepare', '--help'])
    assert code == 0, output
    assert '--patterns' in output and '--out-dir' in output
    assert 'not a qualified reference solution' in ' '.join(output.split())


def test_calibration_prepare_needs_no_layout_or_solver(tmp_path: Path, pattern_data: Dict[str, Any], tech_info: TechInfo):
    spec = tmp_path / 'patterns.json'
    spec.write_text(json.dumps(pattern_data), encoding='utf-8')
    output_dir = tmp_path / 'prepared'
    with mock.patch.object(TechInfo, 'from_catalog', return_value=tech_info):
        code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'prepare', '--pdk', 'sky130A',
                                              '--patterns', str(spec), '--out-dir', str(output_dir)])
    assert code == 0, output
    assert 'Reference solving and coefficient fitting have not run' in output
    assert (output_dir / 'manifest.json').is_file()


def test_invalid_dimensions_fail_before_loading_selected_technology(tmp_path: Path, pattern_data: Dict[str, Any]):
    spec = tmp_path / 'patterns.json'
    pattern_data['patterns'][0]['width_um'] = '0'
    spec.write_text(json.dumps(pattern_data), encoding='utf-8')
    with mock.patch.object(TechInfo, 'from_catalog') as load:
        code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'prepare', '--pdk', 'sky130A',
                                              '--patterns', str(spec), '--out-dir', str(tmp_path / 'output')])
    assert code == 2, output
    assert 'positive finite decimal' in output
    load.assert_not_called()
    assert not (tmp_path / 'output').exists()


def test_unknown_pdk_lists_valid_values():
    code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'prepare', '--pdk', 'missing',
                                          '--patterns', 'missing.json', '--out-dir', 'missing'])
    assert code == 2, output
    assert 'sky130A' in output


@pytest.mark.parametrize('pdk', list(PDK))
def test_nominal_cli_preserves_catalog_provenance_and_component_identities(
        tmp_path: Path, pattern_data: Dict[str, Any], pdk: PDK):
    selected = TechInfo.from_catalog(pdk.config.tech_catalog_path, None, scenario_id='nominal')
    pattern_data['grid_um'] = '0.0001'
    pattern_data['patterns'][0]['parallel_plates'].update(
        lower_layer=selected.process_metal_layers[0].name, upper_layer=selected.process_metal_layers[-1].name)
    pattern_data['patterns'][1]['parallel_wires']['layer'] = selected.process_metal_layers[-1].name
    specification = tmp_path / 'patterns.json'
    specification.write_text(json.dumps(pattern_data), encoding='utf-8')
    destination = tmp_path / 'prepared'
    code, output = run_cli(KpexCLI().main, ['kpex', 'calibrate', 'prepare', '--pdk', str(pdk),
                                          '--patterns', str(specification), '--out-dir', str(destination)])
    assert code == 0, output
    manifest = Parse((destination / 'manifest.json').read_text(encoding='utf-8'), CalibrationManifest())
    technology = manifest.technology
    assert technology.selection == selected.selection.to_proto()
    assert technology.selection.scenario_id == 'nominal'
    assert technology.selection.catalog_sha256 == selected.selection.catalog_sha256
    assert technology.selection.catalog_description == selected.selection.catalog_description
    assert MessageToDict(technology.selection.catalog_provenance,
                         preserving_proto_field_name=True) == selected.selection.catalog_provenance
    # Compare to the resolved source identities independently of to_proto(), so
    # the producer and this expectation cannot silently drop the same evidence.
    for name in ('resistance', 'capacitance', 'process_stack', 'device_references'):
        expected = getattr(selected.selection, name)
        if expected is None:
            assert not technology.selection.datasets.HasField(name)
        else:
            identity = getattr(technology.selection.datasets, name)
            assert (identity.id, identity.sha256) == (expected.id, expected.sha256)
            assert MessageToDict(identity.provenance, preserving_proto_field_name=True) == expected.provenance
    assert technology.resolved_technology_sha256 == selected.selection.resolved_technology_sha256
    assert technology.physical_stack_sha256 == message_sha256(selected.tech.process_stack)
    evidence = technology.selection.datasets.process_stack.provenance
    assert evidence.sources and evidence.assumptions and evidence.history
    assert manifest.stage == CalibrationManifest.PREPARED
