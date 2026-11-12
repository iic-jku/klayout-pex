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

"""Corner selection is explicit, complete, traceable and independent of earlier loads."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Callable

import allure
import pytest

from klayout_pex.pdk_config import PDK
from klayout_pex.tech_catalog import load_technology_catalog
from klayout_pex.tech_identity import message_sha256
from klayout_pex.tech_info import TechDefError, TechInfo
from tests.common.tech_catalog import (
    add_scenario, edit_dataset, read_catalog, small_catalog, small_technology, write_message,
    write_test_catalog,
)


pytestmark = allure.parent_suite('Unit Tests')


@pytest.mark.parametrize('pdk', list(PDK), ids=str)
def test_nominal_catalog_preserves_the_complete_nominal_technology(pdk: PDK):
    nominal = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    resolved = load_technology_catalog(Path(pdk.config.tech_catalog_path), expected_technology=str(pdk))
    assert resolved.tech == nominal
    assert resolved.selection.scenario_id == 'nominal'
    assert resolved.selection.process_stack.sha256 == message_sha256(nominal.process_stack)
    assert resolved.selection.resolved_technology_sha256 == message_sha256(nominal)


def test_dataset_selection_changes_only_the_explicit_components_and_never_a_previous_load(tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'resistance', lambda dataset: setattr(dataset.resistance.layers[0], 'resistance', 250.0),
                 new_id='high-r')
    edit_dataset(path, 'capacitance', lambda dataset: setattr(dataset.capacitance.capacitance.overlaps[0],
                                                               'capacitance', 75.0), new_id='high-c')
    add_scenario(path, resistance='high-r', capacitance='high-c')
    nominal = TechInfo.from_catalog(str(path), None)
    # Prime caches before loading another corner: in-place overlays would leave these stale.
    nominal_stack = nominal.process_stack_layer_by_name
    changed = TechInfo.from_catalog(str(path), None, scenario_id='alternate')
    assert nominal.tech == small_technology()
    assert nominal.process_stack_layer_by_name is nominal_stack
    assert changed.tech.process_parasitics.resistance.layers[0].resistance == 250.0
    assert changed.tech.process_parasitics.capacitance.overlaps[0].capacitance == 75.0
    assert changed.tech.process_stack == nominal.tech.process_stack
    assert not changed.tech.device_models.device_model_mappings[0].capacitance_references
    assert changed.selection.device_references is None
    assert nominal.selection.process_stack == changed.selection.process_stack
    assert nominal.selection.capacitance.sha256 != changed.selection.capacitance.sha256
    assert load_technology_catalog(path).tech == nominal.tech
    changed.tech.process_parasitics.side_halo = 12.0
    assert load_technology_catalog(path, 'alternate').tech.process_parasitics.side_halo == 8.0


def test_explicit_default_is_used_and_not_inferred_from_a_corner_label(tmp_path: Path):
    path = small_catalog(tmp_path)
    add_scenario(path, name='cold-µm')
    catalog = read_catalog(path)
    catalog.default_scenario = 'cold-µm'
    write_message(path, catalog)
    resolved = load_technology_catalog(path)
    assert resolved.selection.scenario_id == 'cold-µm'
    assert resolved.selection.device_references is None
    assert load_technology_catalog(path, 'nominal').selection.device_references is not None


@pytest.mark.parametrize('corner', ['', 'missing', 'Nominal'])
def test_unknown_corner_lists_choices_before_reading_datasets(corner: str, tmp_path: Path):
    path = small_catalog(tmp_path)
    (tmp_path / 'shared.pb.json').unlink()
    with pytest.raises(TechDefError, match='valid corners: nominal'):
        load_technology_catalog(path, corner)


@pytest.mark.parametrize('edit, message', [
    (lambda c: setattr(c, 'schema_version', 0), 'supported: 1'),
    (lambda c: setattr(c, 'schema_version', 2), 'supported: 1'),
    (lambda c: setattr(c, 'default_scenario', 'absent'), 'Unknown default corner'),
    (lambda c: c.scenarios.add().CopyFrom(c.scenarios[0]), 'Duplicate corner ID'),
    (lambda c: setattr(c.scenarios[0], 'id', 'bad id'), 'without whitespace'),
    (lambda c: c.datasets.add().CopyFrom(c.datasets[0]), 'Duplicate resistance dataset ID'),
    (lambda c: setattr(c.scenarios[0], 'resistance', 'absent'), 'valid datasets: nominal'),
    (lambda c: setattr(c.datasets[0], 'kind', 99), 'unknown resistance dataset'),
])
def test_malformed_catalog_declarations_fail_before_dataset_loading(edit: Callable, message: str, tmp_path: Path):
    path = small_catalog(tmp_path)
    catalog = read_catalog(path)
    edit(catalog)
    write_message(path, catalog)
    with pytest.raises(TechDefError, match=message):
        load_technology_catalog(path)


@pytest.mark.parametrize('relative', ['../outside.pb.json', '/absolute.pb.json', 'a\\b.pb.json', 'C:/data.pb.json', ''])
def test_component_paths_must_be_portable_and_within_the_catalog(relative: str, tmp_path: Path):
    path = small_catalog(tmp_path)
    catalog = read_catalog(path)
    catalog.shared.path = relative
    write_message(path, catalog)
    with pytest.raises(TechDefError, match='relative and within'):
        load_technology_catalog(path)


def test_a_changed_component_is_not_silently_used_under_its_old_identity(tmp_path: Path):
    path = small_catalog(tmp_path)
    component = tmp_path / 'resistance/nominal.pb.json'
    component.write_bytes(component.read_bytes() + b' ')
    with pytest.raises(TechDefError, match='has SHA256 .* expected'):
        load_technology_catalog(path)


@pytest.mark.parametrize('data', [b'{invalid', b'\xff', b'{"unknown": 1}'])
def test_invalid_catalog_json_is_a_domain_error_with_its_source(data: bytes, tmp_path: Path):
    path = tmp_path / 'catalog.pb.json'
    path.write_bytes(data)
    with pytest.raises(TechDefError, match=re.escape(str(path))) as failure:
        load_technology_catalog(path)
    assert failure.value.__cause__ is not None


def test_missing_catalog_is_a_domain_error_with_its_source(tmp_path: Path):
    path = tmp_path / 'missing.pb.json'
    with pytest.raises(TechDefError, match=re.escape(str(path))) as failure:
        load_technology_catalog(path)
    assert isinstance(failure.value.__cause__, OSError)


def test_catalog_must_match_the_lvs_technology(tmp_path: Path):
    path = small_catalog(tmp_path)
    with pytest.raises(TechDefError, match="expected 'different'"):
        load_technology_catalog(path, expected_technology='different')


@pytest.mark.parametrize('edit, message', [
    (lambda d: setattr(d, 'id', 'wrong'), 'Expected resistance dataset'),
    (lambda d: d.provenance.sources.clear(), 'needs at least one source'),
    (lambda d: d.process_stack.SetInParent(), 'with process_stack data'),
    (lambda d: d.resistance.layers.add().CopyFrom(d.resistance.layers[0]), 'duplicate row keys'),
    (lambda d: setattr(d.resistance.layers[0], 'layer_name', 'absent'), 'unknown layers: absent'),
])
def test_dataset_identity_kind_source_and_keys_are_checked(edit: Callable, message: str, tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'resistance', edit)
    with pytest.raises(TechDefError, match=message):
        load_technology_catalog(path)


@pytest.mark.parametrize('resistance', [-math.ulp(0.0), -1.0, math.inf, -math.inf, math.nan])
def test_resistance_rejects_negative_and_nonfinite_values(resistance: float, tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'resistance', lambda d: setattr(d.resistance.layers[0], 'resistance', resistance))
    with pytest.raises(TechDefError, match='Resistance .* finite and >= 0'):
        load_technology_catalog(path)


@pytest.mark.parametrize('resistance', [0.0, math.ulp(0.0), 1e300])
def test_finite_nonnegative_resistance_boundaries(resistance: float, tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'resistance', lambda d: setattr(d.resistance.layers[0], 'resistance', resistance))
    assert load_technology_catalog(path).tech.process_parasitics.resistance.layers[0].resistance == resistance


@pytest.mark.parametrize('halo', [-math.ulp(0.0), 0.0, math.inf, math.nan])
def test_capacitance_halo_must_be_finite_and_strictly_positive(halo: float, tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'capacitance', lambda d: setattr(d.capacitance, 'side_halo', halo))
    with pytest.raises(TechDefError, match='side_halo .* finite number > 0'):
        load_technology_catalog(path)


@pytest.mark.parametrize('coefficient', [-math.ulp(0.0), math.inf, math.nan])
def test_capacitance_coefficients_are_checked_after_resolution(coefficient: float, tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'capacitance', lambda d: setattr(d.capacitance.capacitance.overlaps[0], 'capacitance', coefficient))
    with pytest.raises(TechDefError, match='Capacitances have to be finite'):
        load_technology_catalog(path)


@pytest.mark.parametrize('coefficient', [0.0, math.ulp(0.0), 1e300])
def test_explicit_zero_is_present_and_negative_fitted_offsets_are_preserved(coefficient: float, tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'capacitance', lambda d: setattr(d.capacitance.capacitance.overlaps[0], 'capacitance', coefficient),
                 new_id='low')
    add_scenario(path, capacitance='low')
    resolved = load_technology_catalog(path, 'alternate')
    assert resolved.tech.process_parasitics.capacitance.overlaps[0].capacitance == coefficient
    assert resolved.tech.process_parasitics.capacitance.sidewalls[0].offset == -0.01


@pytest.mark.parametrize('edit', [
    lambda d: d.capacitance.capacitance.ClearField('overlaps'),
    lambda d: setattr(d.capacitance.capacitance.overlaps[0], 'top_layer_name', 'met1'),
])
def test_missing_or_reoriented_rows_are_not_treated_as_complete_tables(edit: Callable, tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'capacitance', edit, new_id='partial')
    add_scenario(path, capacitance='partial')
    with pytest.raises(TechDefError, match='incomplete capacitance.overlaps coverage'):
        load_technology_catalog(path, 'alternate')


def test_stack_geometry_can_change_but_conductor_connectivity_cannot(tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'process_stack', lambda d: setattr(d.process_stack.layers[0].metal_layer, 'thickness', 0.25),
                 new_id='thick')
    add_scenario(path, name='thick', process_stack='thick', physical_stack_matches=True)
    resolved = load_technology_catalog(path, 'thick')
    assert resolved.tech.process_stack.layers[0].metal_layer.thickness == 0.25
    assert resolved.selection.process_stack.sha256 != load_technology_catalog(path).selection.process_stack.sha256
    edit_dataset(path, 'process_stack', lambda d: setattr(d.process_stack.layers[0].metal_layer.contact_above,
                                                          'metal_above', 'met1'), new_id='shorted')
    add_scenario(path, name='shorted', process_stack='shorted')
    with pytest.raises(TechDefError, match='changes conductor connectivity'):
        load_technology_catalog(path, 'shorted')


@pytest.mark.parametrize('edit, message', [
    (lambda d: setattr(d.device_references.devices[0], 'lvs_device_class_name', 'unknown'), 'unknown LVS class'),
    (lambda d: d.device_references.devices[0].capacitance_references[0].terminal_names.append('C'), 'Invalid .* terminals'),
    (lambda d: d.device_references.devices[0].capacitance_references.add().CopyFrom(
        d.device_references.devices[0].capacitance_references[0]), 'Duplicate capacitance reference'),
])
def test_device_references_match_the_shared_interfaces(edit: Callable, message: str, tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'device_references', edit)
    with pytest.raises(TechDefError, match=message):
        load_technology_catalog(path)


def test_analytical_only_scenario_cannot_claim_nominal_physical_or_device_references(tmp_path: Path):
    path = small_catalog(tmp_path)
    add_scenario(path)
    selected = load_technology_catalog(path, 'alternate').selection
    with pytest.raises(TechDefError, match='no matching physical stack'):
        selected.require_physical_stack()
    with pytest.raises(TechDefError, match='no device-capacitance reference dataset'):
        selected.require_device_references()
    nominal = load_technology_catalog(path).selection
    nominal.require_physical_stack()
    nominal.require_device_references()


def test_writer_returns_exactly_its_files_and_leaves_unrelated_data_alone(tmp_path: Path):
    leftover = tmp_path / 'old.pb.json'
    leftover.write_text('old', encoding='utf-8')
    path = tmp_path / 'catalog.pb.json'
    written = write_test_catalog(small_technology(), path)
    assert len(written) == 6
    assert path in written
    assert leftover not in written
    assert leftover.read_text(encoding='utf-8') == 'old'
    assert load_technology_catalog(path).selection.catalog_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('offset', [math.inf, -math.inf, math.nan])
def test_nonfinite_sidewall_offsets_are_rejected(offset: float, tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'capacitance', lambda d: setattr(d.capacitance.capacitance.sidewalls[0], 'offset', offset))
    with pytest.raises(TechDefError, match='Sidewall offset .* must be finite'):
        load_technology_catalog(path)


@pytest.mark.parametrize('value', [math.inf, -math.inf, math.nan])
def test_nonfinite_stack_dimensions_are_rejected(value: float, tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'process_stack', lambda d: setattr(d.process_stack.layers[0].metal_layer, 'thickness', value))
    with pytest.raises(TechDefError, match='Physical-stack thickness .* must be finite'):
        load_technology_catalog(path)


def test_device_reference_corner_is_separate_from_device_interface_and_stack(tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'device_references',
                 lambda d: setattr(d.device_references.devices[0].capacitance_references[0], 'capacitance', '2e-15'),
                 new_id='reference-2')
    add_scenario(path, device_references='reference-2')
    default = load_technology_catalog(path)
    changed = load_technology_catalog(path, 'alternate')
    reference = changed.tech.device_models.device_model_mappings[0]
    assert reference.terminal_names == ['A', 'B']
    assert reference.capacitance_references[0].capacitance == '2e-15'
    assert changed.selection.device_references.id == 'reference-2'
    assert default.selection.process_stack == changed.selection.process_stack
    assert default.selection.capacitance == changed.selection.capacitance


def test_physical_stack_identity_detects_mutation_but_allows_a_halo_override(tmp_path: Path):
    resolved = load_technology_catalog(small_catalog(tmp_path))
    resolved.tech.process_parasitics.side_halo = 12.0
    resolved.selection.require_physical_stack(resolved.tech.process_stack)
    resolved.tech.process_stack.layers[0].metal_layer.thickness = 0.25
    with pytest.raises(TechDefError, match='Physical stack changed after corner'):
        resolved.selection.require_physical_stack(resolved.tech.process_stack)


def test_stack_layer_requires_its_parameter_payload(tmp_path: Path):
    path = small_catalog(tmp_path)
    edit_dataset(path, 'process_stack', lambda d: d.process_stack.layers[0].ClearField('parameters'))
    with pytest.raises(TechDefError, match="layer 'met1'.*exactly one parameter payload"):
        load_technology_catalog(path)
