#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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
"""Reviewed source tables for physical interconnect corners with explicit MIM restrictions."""

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from klayout_pex_protobuf.kpex.tech.process_stack_pb2 import ProcessStackInfo
from klayout_pex_protobuf.kpex.tech.tech_catalog_pb2 import TechnologyDataset
from klayout_pex_protobuf.kpex.tech.tech_pb2 import Technology
from scripts.gen_tech_pb.provenance import nominal_provenance


CAPICHE_REVISION = '85905e8810982bd89966cbf8b7e9d3fd1e922d42'


def _contact(layer: ProcessStackInfo.LayerInfo) -> Optional[ProcessStackInfo.Contact]:
    match layer.layer_type:
        case ProcessStackInfo.LAYER_TYPE_METAL:
            return layer.metal_layer.contact_above
        case ProcessStackInfo.LAYER_TYPE_DIFFUSION:
            return layer.diffusion_layer.contact_above
        case ProcessStackInfo.LAYER_TYPE_NWELL:
            return layer.nwell_layer.contact_above
        case (ProcessStackInfo.LAYER_TYPE_SUBSTRATE | ProcessStackInfo.LAYER_TYPE_FIELD_OXIDE |
              ProcessStackInfo.LAYER_TYPE_SIMPLE_DIELECTRIC | ProcessStackInfo.LAYER_TYPE_CONFORMAL_DIELECTRIC):
            return None
        case _:
            raise NotImplementedError(f'Physical contact mapping for layer type {layer.layer_type} is not implemented')


def _rows(rows: List[List[Any]], expected: Set[str], size: int) -> Dict[str, List[Any]]:
    result = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != size or not isinstance(row[0], str) or row[0] in result:
            raise ValueError(f'Invalid or duplicate process-stack row: {row}')
        result[row[0]] = row[1:]
    if set(result) != expected:
        raise ValueError(f'Incomplete process-stack coverage: expected {sorted(expected)}, found {sorted(result)}')
    return result


def _number(value: Any, positive: bool = False, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or (positive and value <= 0) or (nonnegative and value < 0):
        raise ValueError(f'Invalid process-stack parameter: {value}')
    return value


def load_restricted_physical_corners(technology: Technology, table_path: Path) -> List[TechnologyDataset]:
    document = json.loads(table_path.read_text(encoding='utf-8'))
    if type(document['schema_version']) is not int or document['schema_version'] != 1 \
            or document['technology_id'] != technology.name:
        raise ValueError('Unexpected process-stack table')
    if set(document['physical']) != {'capiche-low', 'capiche-high'}:
        raise ValueError('Process-stack table needs explicit low/high components')
    datasets = []
    for identity, table in document['physical'].items():
        dataset = TechnologyDataset(id=identity, description=f'{identity} interconnect process stack; MIM geometry unavailable')
        dataset.process_stack.CopyFrom(technology.process_stack)
        layers = {layer.name: layer for layer in dataset.process_stack.layers}
        def names_by_type(kind: int) -> Set[str]:
            return {name for name, layer in layers.items() if layer.layer_type == kind}
        for name, (z, clearance) in _rows(
                table['substrate'], names_by_type(ProcessStackInfo.LAYER_TYPE_SUBSTRATE), 3).items():
            # The source ground is an ideal 2D boundary. A declared 3D clearance
            # preserves the existing isolation of device contacts above it.
            layers[name].substrate_layer.height = -_number(z) + _number(clearance, nonnegative=True)
        for name, (z, thickness, bias, unavailable) in _rows(
                table['metals'], names_by_type(ProcessStackInfo.LAYER_TYPE_METAL), 5).items():
            if type(unavailable) is not bool:
                raise ValueError(f'Physical availability flag for {name} must be a boolean')
            metal = layers[name].metal_layer
            metal.z, metal.thickness = _number(z), _number(thickness, positive=True)
            metal.line_width_bias, metal.physical_geometry_unavailable = _number(bias), unavailable
        for name, (permittivity,) in _rows(table['field_oxide'], names_by_type(ProcessStackInfo.LAYER_TYPE_FIELD_OXIDE), 2).items():
            layers[name].field_oxide_layer.dielectric_k = _number(permittivity, positive=True)
        for name, (permittivity, reference) in _rows(
                table['simple'], names_by_type(ProcessStackInfo.LAYER_TYPE_SIMPLE_DIELECTRIC), 3).items():
            layer = layers[name].simple_dielectric_layer
            layer.dielectric_k = _number(permittivity, positive=True)
            if reference not in layers:
                raise ValueError(f'Unknown physical dielectric reference {reference}')
            layer.reference = reference
        removed = set(table['removed_conformal'])
        conformal_names = names_by_type(ProcessStackInfo.LAYER_TYPE_CONFORMAL_DIELECTRIC)
        if len(removed) != len(table['removed_conformal']) or not removed <= conformal_names:
            raise ValueError('Only declared conformal dielectric profiles may be omitted by the source process stack')
        for name, (permittivity, over, field, side, reference) in _rows(
                table['conformal'], conformal_names-removed, 6).items():
            layer = layers[name].conformal_dielectric_layer
            layer.dielectric_k = _number(permittivity, positive=True)
            layer.thickness_over_metal = _number(over, nonnegative=True)
            layer.thickness_where_no_metal = _number(field, nonnegative=True)
            layer.thickness_sidewall = _number(side, nonnegative=True)
            if reference not in layers or reference in removed:
                raise ValueError(f'Unknown physical coating reference {reference}')
            layer.reference = reference
        contacts = {contact.name: contact for layer in layers.values()
                    if (contact := _contact(layer)) is not None and contact.name}
        for name, (thickness,) in _rows(table['contacts'], set(contacts), 2).items():
            contacts[name].thickness = _number(thickness, positive=True)
        for index in reversed(range(len(dataset.process_stack.layers))):
            if dataset.process_stack.layers[index].name in removed:
                del dataset.process_stack.layers[index]
        provenance = dataset.provenance
        provenance.data_revision = '1'
        _, nominal_components = nominal_provenance(technology.name)
        provenance.sources.extend(nominal_components['process_stack'].sources)
        provenance.sources.add(id='capiche-physical', description='Pinned Capiche interconnect process stack',
                               uri=f'https://github.com/RTimothyEdwards/capiche/blob/{CAPICHE_REVISION}/'+table['source_path'],
                               revision=CAPICHE_REVISION, sha256=table['source_sha256'])
        restricted = [name for name, layer in layers.items()
                      if layer.layer_type == ProcessStackInfo.LAYER_TYPE_METAL and layer.metal_layer.physical_geometry_unavailable]
        provenance.assumptions.add(
            id='unavailable-mim', description='No source MIM process-stack parameters for nonnominal profiles '+', '.join(restricted),
            reason='Their retained values serve ordering only. Physical export rejects their extracted shapes or contacts '
            'and omits the profiles and dependent coatings otherwise', source_ids=['recipe', 'capiche-physical'])
        provenance.assumptions.add(
            id='source-ground-plane', description='Source ground height and retained 3D clearance (um): '+
            json.dumps(table['substrate'])+'. The finite conducting thickness retains the nominal KPEX '
            'numerical truncation',
            reason='Capiche specifies an ideal 2D ground surface. SKY130 retains 0.1 um separation from device '
            'anchors so the full PEX25D ground plane cannot short their contacts; this is a documented 3D '
            'adaptation, not numerical identity with the 2D source',
            source_ids=['recipe', 'capiche-physical'])
        provenance.assumptions.add(
            id='contact-geometry', description='Cut widths and device-contact anchors retain the nominal KPEX contract; '
            'vertical interconnect contacts follow the selected conductor faces',
            reason='The source specifies interconnect geometry/materials, not new via-cut masks or an active-device '
            'process-stack specification',
            source_ids=['recipe', 'capiche-physical'])
        provenance.assumptions.add(
            id='field-convention', description='Coating top/side offsets are incremental; field extents are cumulative '
            'from the root metal bottom. Boundary dielectrics retain their source absolute height',
            reason='This maps the Capiche coating chain and planar boundaries into KPEX physical geometry',
            source_ids=['capiche-physical'])
        provenance.assumptions.add(
            id='independent-process-stack', description='Interconnect process stack only; not a correlated resistance '
            'corner, device capacitance model or validation against silicon measurements',
            reason='Empirical tables and physical inputs have separate identities and validation',
            source_ids=['capiche-physical'])
        if table['empirical_adjustments']:
            provenance.assumptions.add(
                id='empirical-sidewall-adjustments', description='Source empirical sidewall overrides: '+
                json.dumps(table['empirical_adjustments'], sort_keys=True),
                reason='These are coefficient-fit adjustments, not physical geometry or material changes',
                source_ids=['capiche-physical'])
        provenance.history.add(revision='1', date='2026-11-13', summary='Import reviewed process-stack corner data',
                               reason='Support source-backed interconnect geometry while rejecting missing MIM process-stack parameters',
                               source_ids=[source.id for source in provenance.sources],
                               references=['https://github.com/iic-jku/klayout-pex/issues/550',
                                           'https://github.com/iic-jku/klayout-pex/issues/559'])
        datasets.append(dataset)
    return datasets
