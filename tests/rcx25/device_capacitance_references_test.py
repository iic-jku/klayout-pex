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

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict

import allure
import klayout.db as kdb
import pytest

from klayout_pex.rcx25.c.device_capacitance_references import (
    DeviceCapacitanceCheckError, read_device_capacitance_references, tech_device_capacitance_references,
)
from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from tests.common.device_capacitance import REFERENCE, layout_context, reference_document, write_references

pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('RCX25', 'Device Capacitance References')]


@pytest.mark.parametrize('value', ['1f', '1F', '0.001p', 1e-15])
def test_reference_capacitance_uses_si_and_spice_suffixes(value: Any, tmp_path: Path):
    references = read_device_capacitance_references(write_references(
        tmp_path / 'reference.json', reference_document(capacitance=value)))
    assert references == [REFERENCE]


@pytest.mark.parametrize('changes', [
    dict(capacitance=0), dict(capacitance=-1), dict(capacitance=True), dict(capacitance='unknown'),
    dict(capacitance=float('inf')), dict(capacitance=float('nan')),
    dict(min_ratio=-0.1), dict(max_ratio=-0.1), dict(min_ratio=2, max_ratio=1),
    dict(min_ratio=True), dict(max_ratio=float('inf')), dict(max_ratio=float('nan')), dict(max_ratio=None),
    dict(capacitance='1e-1000f'),
    dict(device=''), dict(device_class=None), dict(terminals=['A', 'A']),
    dict(terminals=['A']), dict(terminals=['A', 'B', 'C']), dict(terminals=[False, 'B']),
    dict(max_rato=2),
])
def test_reference_rejects_invalid_values(changes: Dict[str, Any], tmp_path: Path):
    with pytest.raises(DeviceCapacitanceCheckError, match='Invalid device-capacitance reference file'):
        read_device_capacitance_references(write_references(tmp_path / 'bad.json', reference_document(**changes)))


@pytest.mark.parametrize('text', [
    '{', '{"format_version":1,"format_version":1,"references":[]}',
    '{"format_version":true,"references":[]}', '{"format_version":2,"references":[]}',
    '{"format_version":1,"references":[]}', '{"format_version":1,"references":{}}',
])
def test_reference_rejects_malformed_or_empty_documents(text: str, tmp_path: Path):
    path = tmp_path / 'bad.json'
    path.write_text(text, encoding='utf-8')
    with pytest.raises(DeviceCapacitanceCheckError):
        read_device_capacitance_references(str(path))


def test_reversed_terminal_order_does_not_hide_a_duplicate(tmp_path: Path):
    document = reference_document()
    document['references'].append(dict(document['references'][0], terminals=['B', 'A']))
    with pytest.raises(DeviceCapacitanceCheckError, match='duplicate device and terminal pair'):
        read_device_capacitance_references(write_references(tmp_path / 'duplicate.json', document))


@pytest.mark.parametrize('changes', [
    dict(capacitance_f=0), dict(capacitance_f=-1), dict(capacitance_f=True),
    dict(capacitance_f=float('nan')), dict(capacitance_f=float('inf')),
    dict(min_ratio=-1), dict(max_ratio=True), dict(max_ratio=float('nan')),
    dict(min_ratio=2, max_ratio=1),
])
def test_programmatic_references_enforce_numeric_invariants(changes: Dict[str, Any]):
    with pytest.raises(ValueError):
        replace(REFERENCE, **changes)


def tech_reference_context() -> KLayoutExtractionContext:
    context, _, _ = layout_context()
    mapping = context.tech.device_models.mapping_by_lvs_device_class_name['cap_cmomf']
    del mapping.capacitance_references[:]
    mapping.capacitance_references.add(
        terminal_names=['mim_top', 'mim_btm'], capacitance='W*l*m*density',
        parameters={'density': '1m'}, valid_when='w>0 && l>0 && m>0',
        source='test model', description='Nominal mutual low-frequency capacitance')
    return context


def test_tech_reference_uses_mapped_units_and_multiplier_once():
    context = tech_reference_context()
    device = next(context.top_circuit.each_device())
    device.set_parameter('m', 3)
    references, unchecked = tech_device_capacitance_references(context)
    reference, = references
    assert reference.capacitance_f == pytest.approx(750e-15, rel=1e-14, abs=0)
    assert reference.min_ratio is reference.max_ratio is None
    assert reference.source == 'test model'
    assert not unchecked


@pytest.mark.parametrize('changes,problem', [
    ({'capacitance': '0'}, 'greater than zero'),
    ({'capacitance': '-1f'}, 'greater than zero'),
    ({'capacitance': '1e308*1e308'}, 'finite'),
    ({'capacitance': '1e-300*1e-300'}, 'greater than zero'),
    ({'capacitance': 'unknown'}, 'not defined'),
    ({'capacitance': '1/'}, 'ends early'),
    ({'valid_when': 'w<0'}, 'outside reference domain'),
    ({'source': ''}, 'source'),
    ({'description': ''}, 'assumptions'),
    ({'terminal_names': ['mim_top', 'missing']}, 'valid terminals'),
    ({'terminal_names': ['mim_top', 'mim_top']}, 'distinct'),
    ({'parameters': {'w': '1u'}}, 'shadow'),
    ({'parameters': {'density': '1m', 'DENSITY': '1m'}}, 'unique'),
    ({'parameters': {'density': 'other', 'other': 'density'}}, 'depends on itself'),
])
def test_invalid_tech_reference_is_a_named_domain_error(changes: Dict[str, Any], problem: str):
    context = tech_reference_context()
    spec = context.tech.device_models.mapping_by_lvs_device_class_name['cap_cmomf'].capacitance_references[0]
    for name, value in changes.items():
        if name == 'parameters':
            spec.parameters.clear()
            spec.parameters.update(value)
        elif name == 'terminal_names':
            del spec.terminal_names[:]
            spec.terminal_names.extend(value)
        else:
            setattr(spec, name, value)
    with pytest.raises(DeviceCapacitanceCheckError, match=problem) as error:
        tech_device_capacitance_references(context)
    assert 'cap_cmomf' in str(error.value)
    assert error.value.__cause__ is not None


def test_tech_reference_rejects_duplicate_terminal_pairs_in_either_order():
    context = tech_reference_context()
    mapping = context.tech.device_models.mapping_by_lvs_device_class_name['cap_cmomf']
    mapping.capacitance_references.add().CopyFrom(mapping.capacitance_references[0])
    mapping.capacitance_references[1].terminal_names.reverse()
    with pytest.raises(DeviceCapacitanceCheckError, match='duplicate reference terminal pair'):
        tech_device_capacitance_references(context)


def test_tech_reference_names_missing_coverage_and_rejects_empty_selection():
    context = tech_reference_context()
    models = context.tech.device_models
    mapping = models.mapping_by_lvs_device_class_name['cap_cmomf']
    other_class = kdb.DeviceClassCapacitor()
    other_class.name = 'unsupported_metal_cap'
    context.top_circuit.netlist().add(other_class)
    context.top_circuit.create_device(other_class, 'unchecked')
    models.mapping_by_lvs_device_class_name[other_class.name] = type(mapping)(
        lvs_device_class_name=other_class.name, kind=mapping.kind)
    models.metal_capacitor_class_names.add(other_class.name)
    references, unchecked = tech_device_capacitance_references(context)
    assert len(references) == 1
    assert unchecked == ['unchecked (unsupported_metal_cap)']
    del mapping.capacitance_references[:]
    with pytest.raises(DeviceCapacitanceCheckError, match='No tech-info capacitance references') as error:
        tech_device_capacitance_references(context)
    assert '$1 (cap_cmomf)' in str(error.value)
    assert 'unchecked (unsupported_metal_cap)' in str(error.value)
