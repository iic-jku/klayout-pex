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

"""Resolve complete, independently sourced technology datasets before constructing TechInfo."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import hashlib
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit

from google.protobuf.json_format import MessageToDict, MessageToJson, Parse, ParseError
from google.protobuf.message import Message

from .tech_identity import message_sha256
from .tech_info import TechDefError, TechInfo
from klayout_pex_protobuf.kpex.tech.tech_pb2 import Technology
from klayout_pex_protobuf.kpex.tech.process_stack_pb2 import ProcessStackInfo
from klayout_pex_protobuf.kpex.tech.tech_catalog_pb2 import (
    TechnologyCatalog, TechnologyDataset, TechnologyDatasetFile, TechnologyFile, TechnologyScenario,
    TechnologyProvenance,
)


# Field names are shared by the scenario and the dataset oneof, never inferred from IDs.
COMPONENT_KINDS = {
    'resistance': TechnologyDatasetFile.RESISTANCE,
    'capacitance': TechnologyDatasetFile.CAPACITANCE,
    'process_stack': TechnologyDatasetFile.PROCESS_STACK,
    'device_references': TechnologyDatasetFile.DEVICE_REFERENCES,
}


@dataclass(frozen=True)
class DatasetIdentity:
    id: str
    sha256: str
    provenance: Dict[str, Any]

    def to_json(self) -> Dict[str, Any]:
        return {'id': self.id, 'sha256': self.sha256, 'provenance': deepcopy(self.provenance)}


@dataclass(frozen=True)
class TechnologySelection:
    technology_id: str
    scenario_id: str
    catalog_path: str
    catalog_sha256: str
    resolved_technology_sha256: str
    resistance: DatasetIdentity
    capacitance: DatasetIdentity
    process_stack: DatasetIdentity
    device_references: Optional[DatasetIdentity]
    physical_stack_matches: bool
    catalog_description: str
    catalog_provenance: Dict[str, Any]

    def to_json(self) -> Dict[str, Any]:
        return {
            'technology_id': self.technology_id,
            'scenario_id': self.scenario_id,
            'catalog_path': self.catalog_path,
            'catalog_sha256': self.catalog_sha256,
            'catalog_description': self.catalog_description,
            'catalog_provenance': deepcopy(self.catalog_provenance),
            'resolved_technology_sha256': self.resolved_technology_sha256,
            'datasets': {name: value.to_json() if value is not None else None
                         for name in COMPONENT_KINDS for value in (getattr(self, name),)},
            'physical_stack_matches': self.physical_stack_matches,
        }

    def require_physical_stack(self, process_stack: Optional[ProcessStackInfo] = None):
        if not self.physical_stack_matches:
            raise TechDefError(f"Corner '{self.scenario_id}' has analytical tables but no matching physical stack; "
                               "field-solver extraction and PEX25D geometry export are unavailable")
        if process_stack is not None and message_sha256(process_stack) != self.process_stack.sha256:
            raise TechDefError(f"Physical stack changed after corner '{self.scenario_id}' was selected; "
                               "resolve a matching technology dataset before geometry generation")

    def require_device_references(self):
        if self.device_references is None:
            raise TechDefError(f"Corner '{self.scenario_id}' has no device-capacitance reference dataset; "
                               "supply --check-device-caps JSON explicitly or omit the check")


@dataclass(frozen=True)
class ResolvedTechnology:
    tech: Technology
    selection: TechnologySelection


def _parse(data: bytes, message: Message, source: Path) -> Message:
    try:
        return Parse(data.decode('utf-8'), message)
    except (UnicodeError, ParseError) as exc:
        raise TechDefError(f"Invalid technology data in {source}: {exc}") from exc


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise TechDefError(f"Cannot read technology data at {path}: {exc}") from exc


def _id(value: str, what: str):
    if not value or value.strip() != value or any(character.isspace() for character in value):
        raise TechDefError(f"{what} must be a nonempty identifier without whitespace, got {value!r}")


def _referenced_message(directory: Path, reference: TechnologyFile, message: Message) -> Message:
    relative = PurePosixPath(reference.path)
    if not reference.path or relative.is_absolute() or '..' in relative.parts or '\\' in reference.path \
            or ':' in reference.path:
        raise TechDefError(f"Technology file path must be relative and within its catalog: {reference.path!r}")
    path = directory.joinpath(*relative.parts).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise TechDefError(f"Technology file is outside its catalog directory: {reference.path!r}")
    if not re.fullmatch(r'[0-9a-f]{64}', reference.sha256):
        raise TechDefError(f"Technology file {reference.path!r} needs a lowercase SHA256 digest")
    data = _read(path)
    actual = hashlib.sha256(data).hexdigest()
    if actual != reference.sha256:
        raise TechDefError(f"Technology file {path} has SHA256 {actual}, expected {reference.sha256}")
    return _parse(data, message, path)


def _unique(values: List[str], what: str):
    for value in values:
        _id(value, what)
    repeated = sorted(value for value, count in Counter(values).items() if count > 1)
    if repeated:
        raise TechDefError(f"Duplicate {what}: {', '.join(repeated)}")


def _text(value: str, what: str):
    if not value.strip():
        raise TechDefError(f"{what} must not be empty")


def _uri(value: str, what: str):
    try:
        parsed = urlsplit(value)
        valid = bool(parsed.scheme and value.split(':', 1)[1]) and not any(c.isspace() for c in value)
        if parsed.scheme in ('http', 'https'):
            valid = valid and bool(parsed.hostname)
    except ValueError:
        valid = False
    if not valid:
        raise TechDefError(f"{what} must be an absolute URI, got {value!r}")


def _provenance(provenance: TechnologyProvenance, what: str):
    """Check authored evidence without fetching sources or inferring physical qualification."""
    _id(provenance.data_revision, f'{what} data revision')
    if not provenance.sources:
        raise TechDefError(f'{what} needs at least one source')
    _unique([source.id for source in provenance.sources], f'{what} source ID')
    source_ids = {source.id for source in provenance.sources}
    for source in provenance.sources:
        label = f"{what} source '{source.id}'"
        _text(source.description, f'{label} description')
        _uri(source.uri, f'{label} URI')
        if not source.revision.strip() and not source.sha256:
            raise TechDefError(f'{label} needs a revision or SHA256')
        if source.sha256 and not re.fullmatch(r'[0-9a-f]{64}', source.sha256):
            raise TechDefError(f'{label} SHA256 must be 64 lowercase hexadecimal characters')
        for key in source.options:
            _id(key, f'{label} option name')

    def references(ids: List[str], label: str):
        _unique(list(ids), f'{label} source reference')
        unknown = sorted(set(ids) - source_ids)
        if unknown:
            raise TechDefError(f'{label} references unknown sources: {", ".join(unknown)}')

    _unique([assumption.id for assumption in provenance.assumptions], f'{what} assumption ID')
    for assumption in provenance.assumptions:
        label = f"{what} assumption '{assumption.id}'"
        _text(assumption.description, f'{label} description')
        _text(assumption.reason, f'{label} reason')
        references(assumption.source_ids, label)
    if not provenance.history:
        raise TechDefError(f'{what} needs data-revision history')
    _unique([entry.revision for entry in provenance.history], f'{what} history revision')
    previous = None
    for entry in provenance.history:
        label = f"{what} revision '{entry.revision}'"
        try:
            if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', entry.date):
                raise ValueError('not YYYY-MM-DD')
            day = date.fromisoformat(entry.date)
        except ValueError as exc:
            raise TechDefError(f'{label} date must be a valid YYYY-MM-DD calendar date') from exc
        if previous is not None and day < previous:
            raise TechDefError(f'{what} history dates must be oldest first')
        previous = day
        _text(entry.summary, f'{label} summary')
        _text(entry.reason, f'{label} reason')
        references(entry.source_ids, label)
        for reference in entry.references:
            _uri(reference, f'{label} reference')
    if provenance.history[-1].revision != provenance.data_revision:
        raise TechDefError(f'{what} data revision must match its last history entry')


def _scenario_catalog(catalog: TechnologyCatalog, scenario_id: Optional[str],
                      expected_technology: Optional[str]) -> TechnologyScenario:
    if catalog.schema_version != 1:
        raise TechDefError(f"Unsupported technology catalog schema version {catalog.schema_version}; supported: 1")
    _id(catalog.technology_id, 'technology ID')
    _text(catalog.description, 'Technology catalog description')
    _provenance(catalog.provenance, 'Technology catalog')
    if expected_technology is not None and catalog.technology_id != expected_technology:
        raise TechDefError(f"Technology catalog is for '{catalog.technology_id}', expected '{expected_technology}'")
    _unique([scenario.id for scenario in catalog.scenarios], 'corner ID')
    scenarios = {scenario.id: scenario for scenario in catalog.scenarios}
    valid = ', '.join(sorted(scenarios)) or 'none'
    if catalog.default_scenario not in scenarios:
        raise TechDefError(f"Unknown default corner '{catalog.default_scenario}'; valid corners: {valid}")
    selected_id = catalog.default_scenario if scenario_id is None else scenario_id
    if selected_id not in scenarios:
        raise TechDefError(f"Unknown corner '{selected_id}' for '{catalog.technology_id}'; valid corners: {valid}")
    # Validate names before opening any dataset. A typo must not start layout loading.
    for name, kind in COMPONENT_KINDS.items():
        datasets = [dataset for dataset in catalog.datasets if dataset.kind == kind]
        _unique([dataset.id for dataset in datasets], f'{name} dataset ID')
        ids = {dataset.id for dataset in datasets}
        for scenario in catalog.scenarios:
            reference = getattr(scenario, name)
            if name == 'device_references' and not reference:
                continue
            if reference not in ids:
                raise TechDefError(f"Corner '{scenario.id}' selects unknown {name} dataset '{reference}'; "
                                   f"valid datasets: {', '.join(sorted(ids)) or 'none'}")
    for dataset in catalog.datasets:
        if dataset.kind not in COMPONENT_KINDS.values():
            raise TechDefError(f"Dataset '{dataset.id}' has unknown kind {dataset.kind}")
    return scenarios[selected_id]


def _table_keys(tech: Technology) -> Dict[str, Set[Tuple[str, ...]]]:
    resistance = tech.process_parasitics.resistance
    capacitance = tech.process_parasitics.capacitance
    rows = {
        'resistance.layers': [(row.layer_name,) for row in resistance.layers],
        'resistance.contacts': [(row.contact_name, row.device_layer_name, row.layer_above)
                                for row in resistance.contacts],
        'resistance.vias': [(row.via_name,) for row in resistance.vias],
        'capacitance.substrates': [(row.layer_name,) for row in capacitance.substrates],
        'capacitance.overlaps': [(row.top_layer_name, row.bottom_layer_name) for row in capacitance.overlaps],
        'capacitance.sidewalls': [(row.layer_name,) for row in capacitance.sidewalls],
        'capacitance.sideoverlaps': [(row.in_layer_name, row.out_layer_name) for row in capacitance.sideoverlaps],
    }
    for name, keys in rows.items():
        if any(not all(key) for key in keys):
            raise TechDefError(f"The {name} table has an empty row key")
        duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
        if duplicates:
            raise TechDefError(f"The {name} table has duplicate row keys: {duplicates}")
    return {name: set(keys) for name, keys in rows.items()}


def _validate_values(tech: Technology, source: str):
    TechInfo.validate_tech_def(tech, source)
    known = {layer.name for layer in tech.layers} | {layer.name for layer in tech.process_stack.layers} \
        | {layer.layer_info.name for layer in tech.lvs_computed_layers} \
        | {layer.original_layer_name for layer in tech.lvs_computed_layers} | {'VSUBS'}
    resistance = tech.process_parasitics.resistance
    capacitance = tech.process_parasitics.capacitance
    layer_names = {row.layer_name for row in resistance.layers} \
        | {row.device_layer_name for row in resistance.contacts} \
        | {row.layer_above for row in resistance.contacts} \
        | {row.layer_name for row in capacitance.substrates} | {row.layer_name for row in capacitance.sidewalls} \
        | {row.top_layer_name for row in capacitance.overlaps} | {row.bottom_layer_name for row in capacitance.overlaps} \
        | {row.in_layer_name for row in capacitance.sideoverlaps} | {row.out_layer_name for row in capacitance.sideoverlaps}
    unknown = sorted(layer_names - known)
    if unknown:
        raise TechDefError(f"Parasitic tables in {source} name unknown layers: {', '.join(unknown)}")
    for name in ('layers', 'contacts', 'vias'):
        for row in getattr(resistance, name):
            if not math.isfinite(row.resistance) or row.resistance < 0:
                raise TechDefError(f"Resistance in {source} must be finite and >= 0, got {row.resistance:g}")
    for row in capacitance.sidewalls:
        # A fitted lateral offset can be negative; rejecting it would change existing nominal tables.
        if not math.isfinite(row.offset):
            raise TechDefError(f"Sidewall offset of '{row.layer_name}' in {source} must be finite")
    _finite_stack(tech.process_stack, source)
    _table_keys(tech)


def _finite_stack(message: Message, source: str):
    for field, value in message.ListFields():
        values = value if field.is_repeated else [value]
        if field.message_type is not None:
            for item in values:
                _finite_stack(item, source)
        elif field.type in (field.TYPE_DOUBLE, field.TYPE_FLOAT):
            if any(not math.isfinite(item) for item in values):
                raise TechDefError(f"Physical-stack {field.name} in {source} must be finite")


def _device_references(tech: Technology, dataset: TechnologyDataset):
    mappings = {mapping.lvs_device_class_name: mapping for mapping in tech.device_models.device_model_mappings}
    devices = dataset.device_references.devices
    _unique([device.lvs_device_class_name for device in devices], 'device-reference class')
    for device in devices:
        if device.lvs_device_class_name not in mappings:
            raise TechDefError(f"Device references name unknown LVS class '{device.lvs_device_class_name}'; "
                               f"valid classes: {', '.join(sorted(mappings)) or 'none'}")
        mapping = mappings[device.lvs_device_class_name]
        if mapping.kind != mapping.KIND_METAL_CAPACITOR:
            raise TechDefError(f"Device references for '{device.lvs_device_class_name}' require a metal capacitor")
        pairs: Set[Tuple[str, ...]] = set()
        for reference in device.capacitance_references:
            pair = tuple(sorted(reference.terminal_names))
            if len(pair) != 2 or pair[0] == pair[1] or not set(pair) <= set(mapping.terminal_names):
                raise TechDefError(f"Invalid capacitance reference terminals {list(reference.terminal_names)} "
                                   f"for '{device.lvs_device_class_name}'; valid terminals: "
                                   f"{', '.join(mapping.terminal_names)}")
            if pair in pairs:
                raise TechDefError(f"Duplicate capacitance reference {pair} for '{device.lvs_device_class_name}'")
            if not reference.capacitance or not reference.source or not reference.description:
                raise TechDefError(f"Capacitance reference {pair} for '{device.lvs_device_class_name}' "
                                   "needs a capacitance expression, source and description")
            pairs.add(pair)
        mapping.capacitance_references.extend(device.capacitance_references)


def _conductor_keys(tech: Technology) -> Set[Tuple[str, ...]]:
    keys: Set[Tuple[str, ...]] = set()
    for layer in tech.process_stack.layers:
        kind = layer.WhichOneof('parameters')
        if kind in ('substrate_layer', 'nwell_layer', 'diffusion_layer', 'metal_layer'):
            contact = getattr(getattr(layer, kind), 'contact_above', None)
            keys.add((layer.name, kind))
            if contact is not None and contact.name:
                keys.add((contact.name, 'contact', contact.layer_below, contact.metal_above))
    return keys


def load_technology_catalog(catalog_path: Path, scenario_id: Optional[str] = None,
                            expected_technology: Optional[str] = None) -> ResolvedTechnology:
    """Resolve a fresh Technology; no overlays, inferred combinations or mutation of a cached selection."""
    catalog_path = catalog_path.resolve()
    catalog_bytes = _read(catalog_path)
    catalog = _parse(catalog_bytes, TechnologyCatalog(), catalog_path)
    selected = _scenario_catalog(catalog, scenario_id, expected_technology)
    shared = _referenced_message(catalog_path.parent, catalog.shared, Technology())
    if shared.name != catalog.technology_id:
        raise TechDefError(f"Shared technology is '{shared.name}', catalog is '{catalog.technology_id}'")
    if shared.HasField('process_stack') or shared.HasField('process_parasitics') \
            or any(mapping.capacitance_references for mapping in shared.device_models.device_model_mappings):
        raise TechDefError(f"Shared technology in {catalog_path} contains scenario-dependent data")
    references = {(dataset.kind, dataset.id): dataset.file for dataset in catalog.datasets}
    datasets: Dict[Tuple[str, str], TechnologyDataset] = {}

    def resolve(scenario: TechnologyScenario) -> Tuple[Technology, Dict[str, Optional[DatasetIdentity]]]:
        tech = Technology()
        tech.CopyFrom(shared)
        identities: Dict[str, Optional[DatasetIdentity]] = {}
        for name, kind in COMPONENT_KINDS.items():
            dataset_id = getattr(scenario, name)
            if name == 'device_references' and not dataset_id:
                identities[name] = None
                continue
            key = (name, dataset_id)
            if key not in datasets:
                dataset = _referenced_message(catalog_path.parent, references[kind, dataset_id], TechnologyDataset())
                if dataset.id != dataset_id or dataset.WhichOneof('data') != name:
                    raise TechDefError(f"Expected {name} dataset '{dataset_id}', got "
                                       f"'{dataset.id}' with {dataset.WhichOneof('data')} data")
                _text(dataset.description, f"{name} dataset '{dataset_id}' description")
                _provenance(dataset.provenance, f"{name} dataset '{dataset_id}'")
                datasets[key] = dataset
            dataset = datasets[key]
            payload = getattr(dataset, name)
            identities[name] = DatasetIdentity(dataset_id, message_sha256(payload),
                                               MessageToDict(dataset.provenance, preserving_proto_field_name=True))
            if name == 'resistance':
                tech.process_parasitics.resistance.CopyFrom(payload)
            elif name == 'capacitance':
                tech.process_parasitics.capacitance.CopyFrom(payload.capacitance)
                tech.process_parasitics.side_halo = payload.side_halo
            elif name == 'process_stack':
                tech.process_stack.CopyFrom(payload)
            else:
                _device_references(tech, dataset)
        _validate_values(tech, f"{catalog_path} (corner '{scenario.id}')")
        return tech, identities

    default = next(scenario for scenario in catalog.scenarios if scenario.id == catalog.default_scenario)
    baseline, default_identities = resolve(default)
    if selected.id == default.id:
        tech, identities = baseline, default_identities
    else:
        tech, identities = resolve(selected)
        # Complete tables have exactly the default's row keys. A missing row is not an explicit zero.
        if _conductor_keys(tech) != _conductor_keys(baseline):
            raise TechDefError(f"Corner '{selected.id}' changes conductor connectivity or layer identities; "
                               "a different layer stack needs a separate technology catalog")
        actual_keys = _table_keys(tech)
        for name, expected in _table_keys(baseline).items():
            actual = actual_keys[name]
            if actual != expected:
                raise TechDefError(f"Corner '{selected.id}' has incomplete {name} coverage; "
                                   f"missing: {sorted(expected - actual)}, unexpected: {sorted(actual - expected)}")
    selection = TechnologySelection(
        technology_id=catalog.technology_id, scenario_id=selected.id, catalog_path=str(catalog_path),
        catalog_sha256=hashlib.sha256(catalog_bytes).hexdigest(), resolved_technology_sha256=message_sha256(tech),
        physical_stack_matches=selected.physical_stack_matches,
        catalog_description=catalog.description,
        catalog_provenance=MessageToDict(catalog.provenance, preserving_proto_field_name=True), **identities)
    return ResolvedTechnology(tech, selection)


def write_nominal_catalog(tech: Technology, catalog_path: Path, provenance: TechnologyProvenance,
                          description: str,
                          dataset_provenance: Dict[str, TechnologyProvenance]) -> List[Path]:
    """Package existing nominal data losslessly. Return exactly the files written, including the catalog."""
    _text(description, 'Technology catalog description')
    _provenance(provenance, 'Technology catalog')
    if set(dataset_provenance) != set(COMPONENT_KINDS):
        raise TechDefError(f'Nominal dataset provenance must cover exactly {", ".join(COMPONENT_KINDS)}')
    for kind, evidence in dataset_provenance.items():
        _provenance(evidence, f'{kind} dataset')
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []

    def write(relative: str, message: Message) -> TechnologyFile:
        path = catalog_path.parent / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (MessageToJson(message, preserving_proto_field_name=True, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
        path.write_bytes(data)
        written.append(path)
        return TechnologyFile(path=relative, sha256=hashlib.sha256(data).hexdigest())

    shared = Technology()
    shared.CopyFrom(tech)
    shared.ClearField('process_stack')
    shared.ClearField('process_parasitics')
    reference_dataset = TechnologyDataset(id='nominal', description='Nominal device capacitance references',
                                          provenance=dataset_provenance['device_references'])
    reference_dataset.device_references.SetInParent()
    for mapping in shared.device_models.device_model_mappings:
        if mapping.capacitance_references:
            reference_dataset.device_references.devices.add(
                lvs_device_class_name=mapping.lvs_device_class_name,
                capacitance_references=mapping.capacitance_references)
            mapping.ClearField('capacitance_references')
    catalog = TechnologyCatalog(schema_version=1, technology_id=tech.name, description=description,
                                provenance=provenance, default_scenario='nominal',
                                shared=write('shared.pb.json', shared))
    for name, kind in COMPONENT_KINDS.items():
        dataset = reference_dataset if name == 'device_references' else TechnologyDataset(
            id='nominal', description=f'Nominal {name.replace("_", " ")} data', provenance=dataset_provenance[name])
        if name == 'resistance':
            dataset.resistance.CopyFrom(tech.process_parasitics.resistance)
        elif name == 'capacitance':
            dataset.capacitance.side_halo = tech.process_parasitics.side_halo
            dataset.capacitance.capacitance.CopyFrom(tech.process_parasitics.capacitance)
        elif name == 'process_stack':
            dataset.process_stack.CopyFrom(tech.process_stack)
        catalog.datasets.add(id='nominal', kind=kind, file=write(f'{name}/nominal.pb.json', dataset))
    catalog.scenarios.add(id='nominal', description='Existing nominal technology data', resistance='nominal',
                          capacitance='nominal', process_stack='nominal', device_references='nominal',
                          physical_stack_matches=True)
    write(catalog_path.name, catalog)
    return written
