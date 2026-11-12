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

"""Small complete technology catalogs and explicit dataset edits used across tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, List

from google.protobuf.json_format import MessageToJson, Parse
from google.protobuf.message import Message

from klayout_pex.tech_catalog import COMPONENT_KINDS, write_nominal_catalog
from klayout_pex_protobuf.kpex.tech.device_models_pb2 import DeviceModelMapping
from klayout_pex_protobuf.kpex.tech.tech_catalog_pb2 import TechnologyCatalog, TechnologyDataset, TechnologyFile, TechnologyProvenance
from klayout_pex_protobuf.kpex.tech.tech_pb2 import Technology
from tests.common.technology import tech_with_two_metals


def small_technology() -> Technology:
    tech = tech_with_two_metals()
    tech.name = 'test-µm'
    parasitics = tech.process_parasitics
    parasitics.side_halo = 8.0
    for name in ('met1', 'met2'):
        parasitics.resistance.layers.add(layer_name=name, resistance=100.0)
        parasitics.capacitance.substrates.add(layer_name=name, area_capacitance=10.0, perimeter_capacitance=20.0)
        parasitics.capacitance.sidewalls.add(layer_name=name, capacitance=30.0, offset=-0.01)
    parasitics.resistance.vias.add(via_name='via1', resistance=40.0)
    parasitics.capacitance.overlaps.add(top_layer_name='met2', bottom_layer_name='met1', capacitance=50.0)
    parasitics.capacitance.sideoverlaps.add(in_layer_name='met1', out_layer_name='met2', capacitance=60.0)
    device = tech.device_models.device_model_mappings.add(lvs_device_class_name='plate_cap',
                                                          kind=DeviceModelMapping.KIND_METAL_CAPACITOR,
                                                          terminal_names=['A', 'B'])
    device.capacitance_references.add(terminal_names=['A', 'B'], capacitance='1e-15', source='synthetic test model',
                                      description='zero-bias nominal reference')
    return tech


def sample_provenance() -> TechnologyProvenance:
    evidence = TechnologyProvenance(data_revision='test-1')
    evidence.sources.add(id='recipe', description='Synthetic two-metal test technology',
                         uri='urn:kpex:test:two-metals', revision='test-1')
    evidence.assumptions.add(id='synthetic', description='Coefficients are synthetic, not PDK corner data',
                             reason='Independent known values make selection effects measurable', source_ids=['recipe'])
    evidence.history.add(revision='test-1', date='2026-11-12', summary='Define synthetic nominal data',
                         reason='Exercise explicit scenario selection', source_ids=['recipe'])
    return evidence


def write_test_catalog(tech: Technology, path: Path) -> List[Path]:
    evidence = sample_provenance()
    return write_nominal_catalog(tech, path, evidence, 'Synthetic two-metal test technology',
                                 {kind: evidence for kind in COMPONENT_KINDS})


def small_catalog(directory: Path) -> Path:
    path = directory / 'catalog.pb.json'
    write_test_catalog(small_technology(), path)
    return path


def read_catalog(path: Path) -> TechnologyCatalog:
    return Parse(path.read_text(encoding='utf-8'), TechnologyCatalog())


def write_message(path: Path, message: Message) -> TechnologyFile:
    data = (MessageToJson(message, preserving_proto_field_name=True, ensure_ascii=False) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return TechnologyFile(path=path.name, sha256=hashlib.sha256(data).hexdigest())


def edit_dataset(catalog_path: Path, component: str, edit: Callable[[TechnologyDataset], None],
                 new_id: str = 'nominal'):
    catalog = read_catalog(catalog_path)
    reference = next(dataset for dataset in catalog.datasets
                     if dataset.kind == COMPONENT_KINDS[component] and dataset.id == 'nominal')
    dataset = Parse((catalog_path.parent / reference.file.path).read_text(encoding='utf-8'), TechnologyDataset())
    dataset.id = new_id
    edit(dataset)
    filename = f'{component}/{new_id}.pb.json'
    written = write_message(catalog_path.parent / filename, dataset)
    written.path = filename
    if new_id == 'nominal':
        reference.file.CopyFrom(written)
    else:
        catalog.datasets.add(id=new_id, kind=reference.kind, file=written)
    write_message(catalog_path, catalog)


def add_scenario(path: Path, name: str = 'alternate', physical_stack_matches: bool = False,
                 resistance: str = 'nominal', capacitance: str = 'nominal', process_stack: str = 'nominal',
                 device_references: str = ''):
    catalog = read_catalog(path)
    catalog.scenarios.add(id=name, description='Synthetic scenario, not PDK process data',
                          resistance=resistance, capacitance=capacitance, process_stack=process_stack,
                          device_references=device_references, physical_stack_matches=physical_stack_matches)
    write_message(path, catalog)
