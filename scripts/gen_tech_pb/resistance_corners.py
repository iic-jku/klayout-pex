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
"""Load complete, source-pinned resistance components for explicit extraction scenarios."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Dict, List, Tuple

from google.protobuf.json_format import ParseDict

from klayout_pex_protobuf.kpex.tech.process_parasitics_pb2 import ResistanceInfo
from klayout_pex_protobuf.kpex.tech.tech_catalog_pb2 import TechnologyDataset, TechnologyProvenance
from klayout_pex_protobuf.kpex.tech.tech_pb2 import Technology
from scripts.gen_tech_pb.tech_builder import add_layer_resistance, add_contact_resistance, add_via_resistance


def _resistance_keys(resistance: ResistanceInfo) -> Dict[str, List[Tuple[str, ...]]]:
    return {
        'layers': [(row.layer_name,) for row in resistance.layers],
        'contacts': [(row.contact_name, row.device_layer_name, row.layer_above) for row in resistance.contacts],
        'vias': [(row.via_name,) for row in resistance.vias],
    }


def load_corner_resistances(technology: Technology, table_path: Path) -> List[TechnologyDataset]:
    """Require full row coverage; a missing value never inherits nominal resistance."""
    document = json.loads(table_path.read_text(encoding='utf-8'))
    if type(document['schema_version']) is not int or document['schema_version'] != 1 \
            or document['technology_id'] != technology.name:
        raise ValueError(f'Unexpected technology resistance table in {table_path}')
    definitions = document['resistance']
    if not isinstance(definitions, dict) or not definitions:
        raise ValueError('Resistance corner table needs named complete datasets')
    nominal_keys = _resistance_keys(technology.process_parasitics.resistance)
    builders = {'layers': add_layer_resistance, 'contacts': add_contact_resistance, 'vias': add_via_resistance}
    datasets = []
    for identity, definition in definitions.items():
        if identity == 'nominal' or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', identity) is None:
            raise ValueError(f'Invalid resistance dataset ID: {identity}')
        if set(definition) != {'description', 'provenance', *builders}:
            raise ValueError(f'Resistance dataset {identity} needs complete layer, contact and via tables')
        dataset = TechnologyDataset(id=identity, description=definition['description'],
                                     provenance=ParseDict(definition['provenance'], TechnologyProvenance()))
        for table, builder in builders.items():
            names = 3 if table == 'contacts' else 1
            for row in definition[table]:
                if not isinstance(row, list) or len(row) != names + 1 \
                        or any(not isinstance(name, str) or not name for name in row[:names]):
                    raise ValueError(f'Invalid resistance {table} row: {row}')
                value = row[-1]
                # Zero is a source-defined ideal connection. Negative and nonfinite
                # values cannot represent passive sheet/contact resistance.
                if isinstance(value, bool) or not isinstance(value, (int, float)) \
                        or not math.isfinite(value) or value < 0:
                    raise ValueError(f'Invalid resistance value in {table} row: {row}')
                builder(dataset.resistance, *row)
        for table, keys in _resistance_keys(dataset.resistance).items():
            if len(keys) != len(set(keys)):
                raise ValueError(f'Duplicate resistance {table} rows in {identity}')
            if set(keys) != set(nominal_keys[table]):
                raise ValueError(f'Incomplete or unknown resistance {table} rows in {identity}')
        datasets.append(dataset)
    return datasets
