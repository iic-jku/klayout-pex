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
"""Build complete corner components from reviewed, source-pinned coefficient tables."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

from google.protobuf.json_format import MessageToJson, Parse, ParseDict

from klayout_pex.tech_catalog import write_nominal_catalog
from klayout_pex_protobuf.kpex.tech.tech_catalog_pb2 import (
    TechnologyCatalog, TechnologyDataset, TechnologyDatasetFile, TechnologyProvenance,
    TechnologyRevision, TechnologyScenario, TechnologySource,
)
from scripts.gen_tech_pb.provenance import nominal_provenance
from scripts.gen_tech_pb.device_reference_corners import load_corner_device_references
from scripts.gen_tech_pb.resistance_corners import load_corner_resistances
from scripts.gen_tech_pb.tech_builder import (
    CapacitanceInfo, Technology, add_mim_cap, add_overlap_cap, add_sidewall_cap,
    add_sidewall_overlap_cap, add_substrate_cap, split_layer_capacitances,
)


TABLE_DIRECTORY = Path(__file__).with_name('corners')


def _capacitance_index(capacitance: CapacitanceInfo) -> Dict[str, Dict[Tuple[str, ...], Tuple[float, ...]]]:
    specifications = (
        ('substrates', ('layer_name',), ('area_capacitance', 'perimeter_capacitance')),
        ('overlaps', ('top_layer_name', 'bottom_layer_name'), ('capacitance',)),
        ('sidewalls', ('layer_name',), ('capacitance', 'offset')),
        ('sideoverlaps', ('in_layer_name', 'out_layer_name'), ('capacitance',)),
    )
    result = {}
    for table_name, key_fields, value_fields in specifications:
        table = {}
        for row in getattr(capacitance, table_name):
            key = tuple(getattr(row, field) for field in key_fields)
            if key in table:
                raise ValueError(f'Duplicate {table_name} corner row {key}')
            values = tuple(getattr(row, field) for field in value_fields)
            for field, value in zip(value_fields, values):
                if not math.isfinite(value) or (field != 'offset' and value < 0):
                    raise ValueError(f'Invalid {table_name} {field} for corner row {key}: {value}')
            table[key] = values
        result[table_name] = table
    return result


def _validate_row(row: List[Any], names: int, values: int):
    if not isinstance(row, list) or len(row) != names + values or any(not isinstance(name, str) or not name for name in row[:names]):
        raise ValueError(f'Invalid corner coefficient row: {row}')
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in row[names:]):
        raise ValueError(f'Corner coefficients must be numbers, not booleans or strings: {row}')


def _build_capacitance(tables: Dict[str, Any]) -> CapacitanceInfo:
    capacitance = CapacitanceInfo()
    builders = {
        'substrates': add_substrate_cap,
        'overlaps': add_overlap_cap,
        'sidewalls': add_sidewall_cap,
        'sideoverlaps': add_sidewall_overlap_cap,
    }
    if set(tables['base']) != set(builders):
        raise ValueError('Corner capacitance needs complete substrate, overlap, sidewall and fringe tables')
    for table_name, builder in builders.items():
        for row in tables['base'][table_name]:
            names = 2 if table_name in ('overlaps', 'sideoverlaps') else 1
            _validate_row(row, names, 3 - names)
            builder(capacitance, *row)
    _capacitance_index(capacitance)
    split_layer_capacitances(capacitance, *tables['diffusion_projection'])
    for row in tables['mim']:
        _validate_row(row, 2, 2)
        add_mim_cap(capacitance, *row)
    _capacitance_index(capacitance)
    return capacitance


def load_corner_capacitances(technology: Technology, table_path: Path) -> List[TechnologyDataset]:
    """Reject incomplete imports and changes to the established nominal coefficient interpretation."""
    document = json.loads(table_path.read_text(encoding='utf-8'))
    if type(document['schema_version']) is not int or document['schema_version'] != 1 \
            or document['technology_id'] != technology.name:
        raise ValueError(f'Unexpected technology corner table in {table_path}')
    if set(document['capacitance']) != {'nominal', 'low', 'high'}:
        raise ValueError('Corner capacitance table needs nominal, low and high data')
    nominal = _capacitance_index(technology.process_parasitics.capacitance)
    imported_nominal = _capacitance_index(_build_capacitance(document['capacitance']['nominal']))
    if imported_nominal != nominal:
        raise ValueError(f'Imported nominal capacitance differs from existing technology {technology.name}')
    if document['side_halo'] != technology.process_parasitics.side_halo:
        raise ValueError(f'Imported side halo differs from existing technology {technology.name}')
    datasets = []
    for corner in ('low', 'high'):
        capacitance = _build_capacitance(document['capacitance'][corner])
        index = _capacitance_index(capacitance)
        for table in nominal:
            if set(index[table]) != set(nominal[table]):
                raise ValueError(f'Incomplete {corner} capacitance.{table} rows for {technology.name}')
        provenance = ParseDict(document['provenance'], TechnologyProvenance())
        extraction_source = next(source for source in provenance.sources if source.id == 'extraction-table')
        extraction_source.options['variants'] = ','.join(document['source_variants'][corner])
        dataset = TechnologyDataset(
            id=corner, description=f'{corner.capitalize()} empirical capacitance coefficients',
            provenance=provenance)
        dataset.capacitance.side_halo = document['side_halo']
        dataset.capacitance.capacitance.CopyFrom(capacitance)
        datasets.append(dataset)
    return datasets


def write_bundled_corner_catalog(technology: Technology, catalog_path: Path) -> List[Path]:
    """Write source-backed components and only the explicitly authored scenarios."""
    table_path = TABLE_DIRECTORY / f'{technology.name}.json'
    datasets = load_corner_capacitances(technology, table_path)
    resistance_path = TABLE_DIRECTORY / f'{technology.name}-resistance.json'
    resistance_datasets = load_corner_resistances(technology, resistance_path) if resistance_path.is_file() else []
    resistance_document = json.loads(resistance_path.read_text(encoding='utf-8')) if resistance_datasets else None
    device_datasets = load_corner_device_references(technology)
    catalog_provenance, components = nominal_provenance(technology.name)
    for source in datasets[0].provenance.sources:
        copied = catalog_provenance.sources.add()
        copied.CopyFrom(source)
        if copied.id == 'extraction-table':
            copied.options['variants'] = ','.join(
                next(item.options['variants'] for item in dataset.provenance.sources
                     if item.id == 'extraction-table') for dataset in datasets)
    catalog_provenance.data_revision = '2'
    catalog_provenance.history.add(
        revision='2', date='2026-11-13', summary='Add low/high capacitance components',
        reason='Expose reviewed empirical C tables while retaining nominal as the only bundled scenario',
        source_ids=[source.id for source in catalog_provenance.sources],
        references=['https://github.com/iic-jku/klayout-pex/issues/518'])
    if resistance_document:
        for source in resistance_document['sources']:
            catalog_provenance.sources.add().CopyFrom(ParseDict(source, TechnologySource()))
        for record in resistance_document['catalog_revisions']:
            revision = ParseDict(record, TechnologyRevision())
            catalog_provenance.history.add().CopyFrom(revision)
            catalog_provenance.data_revision = revision.revision
    if device_datasets:
        catalog_provenance.history.add(
            revision='device-mim-1', date='2026-11-13', summary='Add independent MIM corner references',
            reason='Keep compact-model device laws distinct from empirical interconnect coefficients',
            references=['https://github.com/iic-jku/klayout-pex/issues/551'])
        catalog_provenance.data_revision = 'device-mim-1'
    written = write_nominal_catalog(
        technology, catalog_path, catalog_provenance,
        f'Explicit extraction scenarios and capacitance components for {technology.name}', components)
    catalog = Parse(catalog_path.read_text(encoding='utf-8'), TechnologyCatalog())
    components_to_write = [(TechnologyDatasetFile.CAPACITANCE, 'capacitance', dataset) for dataset in datasets]
    components_to_write.extend((TechnologyDatasetFile.RESISTANCE, 'resistance', dataset) for dataset in resistance_datasets)
    components_to_write.extend((TechnologyDatasetFile.DEVICE_REFERENCES, 'device_references', dataset)
                               for dataset in device_datasets)
    for kind, directory, dataset in components_to_write:
        relative = f'{directory}/{dataset.id}.pb.json'
        path = catalog_path.parent / relative
        data = (MessageToJson(dataset, preserving_proto_field_name=True, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written.append(path)
        record = catalog.datasets.add(id=dataset.id, kind=kind)
        record.file.path = relative
        record.file.sha256 = hashlib.sha256(data).hexdigest()
    if resistance_document:
        for scenario in resistance_document['scenarios']:
            catalog.scenarios.add().CopyFrom(ParseDict(scenario, TechnologyScenario()))
    catalog_path.write_text(MessageToJson(catalog, preserving_proto_field_name=True, ensure_ascii=False, sort_keys=True) + '\n',
                            encoding='utf-8')
    return written
