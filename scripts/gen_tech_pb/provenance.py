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

"""Authored provenance of bundled nominal technology datasets.

Change data revisions and history with a reviewed source/assumption update. A build
records source hashes, but must never manufacture a revision or date from the clock.
"""

from __future__ import annotations

from typing import Dict, Tuple

from klayout_pex.tech_catalog import COMPONENT_KINDS
from klayout_pex_protobuf.kpex.tech.tech_catalog_pb2 import TechnologyProvenance, TechnologySource


OPEN_PDKS_REVISION = '5740c4a81c42f9fe4af5ef2ee258a99151053d28'
IHP_CAPACITANCE_REVISION = '14b1ab845696960a0a1881ec8614acba0f7b8eb7'
IHP_DEVICE_REVISION = '5e6d592e4002946a4616f798c357f0f3c06cf3b6'
NOMINAL_RECIPE_REVISION = '1b923ea54d8d9b1028de1043afd654c9e1838049'
# Immutable numerical-source snapshot from KPEX 0.9.0. Keep past source records
# unchanged when appending a data revision; a new input receives a new source ID.
RECIPE_SHA256 = {
    'sky130A.py': '409b021a9ee4b4ec03b9528c5be81335292cace0eba7ae1a527584d4b35d0d72',
    'gf180mcuD.py': '1cdbdd6b6350b56e5ba76a3df4c8fc1781eec4dd835f76e8dbc7aeb60fc560d2',
    'ihp_sg13.py': '481b497fc70aa0c122a5c85dd2a4ac0eea4bc2f6b0fd0b5d533cdd349e802c34',
    'tech_builder.py': 'abc23b724eedb8935244a6e15c2ca91b63ba380fabfd321dd87f93d94aac2fcc',
}

# Each row names the actual coefficient input and build selection, not a floating
# upstream branch. The corrected IHP input is PR #1328, not upstream main.
CAPACITANCE_INPUTS = {
    'sky130A': (
        'sky130A.py', 'fossi-foundation/open-pdks', OPEN_PDKS_REVISION,
        'sky130/magic/sky130-extract.tech',
        '28267a7090be9ace22f7d4876fb4fcf285eefeabab805f00e65923ebf31e90e1',
        ('METAL5', 'MIM', 'REDISTRIBUTION')),
    'gf180mcuD': (
        'gf180mcuD.py', 'fossi-foundation/open-pdks', OPEN_PDKS_REVISION,
        'gf180mcu/magic/gf180mcu-extract.tech',
        'e8ab78e8f3c61b43d00ef493d247700ff76477ad6e9b84d2aebafde62be61fb8',
        ('METALS5', 'MIM', 'THICKMET1P1', 'HRPOLY1K')),
    'ihp-sg13g2': (
        'ihp_sg13.py', 'IHP-GmbH/IHP-Open-PDK', IHP_CAPACITANCE_REVISION,
        'ihp-sg13g2/libs.tech/magic/ihp-sg13g2-extract.tech',
        '0f9116fe9e045af1ed654a4a01a6a6a53af5e1a60484a6637ca22033efe78ac9', ()),
    'ihp-sg13cmos5l': (
        'ihp_sg13.py', 'IHP-GmbH/IHP-Open-PDK', IHP_CAPACITANCE_REVISION,
        'ihp-sg13cmos5l/libs.tech/magic/ihp-sg13cmos5l-extract.tech',
        '15b771532b0701a6c45f6d0a1156e6422d15400a89125d640fbe7e57b44184eb', ()),
}


def _recipe_source(filename: str, identity: str) -> TechnologySource:
    return TechnologySource(
        id=identity, description=f'KPEX source recipe: scripts/gen_tech_pb/{filename}',
        uri=f'https://github.com/iic-jku/klayout-pex/blob/{NOMINAL_RECIPE_REVISION}/scripts/gen_tech_pb/{filename}',
        revision=NOMINAL_RECIPE_REVISION, sha256=RECIPE_SHA256[filename])


def _source(evidence: TechnologyProvenance, identity: str, description: str,
            repository: str, revision: str, path: str):
    evidence.sources.add(id=identity, description=description,
                         uri=f'https://github.com/{repository}/blob/{revision}/{path}', revision=revision)


def _assumption(evidence: TechnologyProvenance, identity: str, description: str, reason: str,
                *sources: str):
    evidence.assumptions.add(id=identity, description=description, reason=reason,
                             source_ids=sources or ['recipe'])


def nominal_provenance(technology_id: str) -> Tuple[TechnologyProvenance, Dict[str, TechnologyProvenance]]:
    filename, repository, revision, source_path, digest, defines = CAPACITANCE_INPUTS[technology_id]
    catalog = TechnologyProvenance(data_revision='1')
    for name, identity in ((filename, 'recipe'), ('tech_builder.py', 'builder')):
        catalog.sources.add().CopyFrom(_recipe_source(name, identity))
    catalog.history.add(
        revision='1', date='2026-11-12', summary='Describe the nominal technology scenario and its component sources',
        reason='Make source choices reproducible without changing the existing nominal numerical data',
        source_ids=['recipe', 'builder'],
        references=['https://github.com/iic-jku/klayout-pex/pull/534'])
    components = {}
    for kind in COMPONENT_KINDS:
        evidence = TechnologyProvenance()
        evidence.CopyFrom(catalog)
        evidence.history[0].summary = f'Record nominal {kind.replace("_", " ")} sources and assumptions'
        components[kind] = evidence

    capacitance = components['capacitance']
    _source(capacitance, 'extraction-table', 'Nominal MAGIC extraction coefficients',
            repository, revision, source_path)
    capacitance.sources[-1].sha256 = digest
    capacitance.sources[-1].options.update({name: '1' for name in defines})
    capacitance.sources[-1].options['variants'] = '()'
    _assumption(capacitance, 'diffusion-projection',
                'Diffusion coefficients are projected onto the extracted implant and tap layers',
                'The LVS layer split differs from the source table layer grouping', 'recipe', 'extraction-table')
    if technology_id != 'ihp-sg13cmos5l':
        _assumption(capacitance, 'mim-projection',
                    'MIM plate-to-plate coupling uses device-model values; coupling to other layers uses the thin-plate approximation',
                    'The MIM top plate needs complete coupling rows as well as its independent plate-to-plate model')
    if technology_id.startswith('ihp-'):
        capacitance.history[0].references.append('https://github.com/IHP-GmbH/IHP-Open-PDK/pull/1328')
        _assumption(capacitance, 'lv-diffusion', 'Use LV diffusion coefficients for the extracted diffusion rows',
                    'The current layer mapping does not distinguish HV diffusion coefficients', 'recipe', 'extraction-table')

    resistance = components['resistance']
    if technology_id.startswith('ihp-'):
        _assumption(resistance, 'poly-sheet', 'Use 7 Ohm/square for GatPoly',
                    'This is the existing nominal recipe value; it does not define an interconnect corner law')
        if technology_id == 'ihp-sg13g2':
            _assumption(resistance, 'mim-sheet', 'Use 13.36 Ohm/square for the MIM plate and TopVia1 resistance for its contact',
                        'The nominal recipe derives the plate estimate from 0.5 MS/m and 0.1497 um and aliases the contact material')
    elif technology_id == 'gf180mcuD':
        _assumption(resistance, 'mim-sheet', 'Use 500 mOhm/square for FuseTop',
                    'Retain the nominal estimate from the 1/1.5 fF MIM option; a range for the 2 fF option is not established')
    else:
        _assumption(resistance, 'model-overrides',
                    'Keep the independent nominal nwell, MIM plate and MIM via values from the KPEX recipe',
                    'Replacing them with all MAGIC rows would lose the device-model and cut-geometry distinctions')

    stack = components['process_stack']
    _assumption(stack, 'nominal-geometry', 'The physical stack is the declared nominal KPEX geometry recipe',
                'A matching nominal scenario does not establish foundry qualification or numerical agreement with every analytical fit')
    if technology_id == 'sky130A':
        _assumption(stack, 'substrate-dielectric', 'The dielectric constant below local interconnect includes the existing nominal adjustment',
                    'The recipe matches the single-plate substrate-capacitance reference')
    elif technology_id == 'gf180mcuD':
        _source(stack, 'cross-section', 'Detailed five-metal cross-section', 'fossi-foundation/gf180mcu-pdk',
                '25ed9c64b64b8e1b93cc4d2d5cade4cd82383a9a', 'docs/analog/layout/inter_specs/images/2_cross_section_43.png')
        _assumption(stack, 'top-oxide', 'Use 2.3925 um from the detailed cross-section for the 11KA oxide',
                    'Keep the oxide and metal thicknesses consistent with the same drawing rather than mix it with the general table',
                    'recipe', 'cross-section')

    if technology_id.startswith('ihp-'):
        # Preserve the historical recipe record; this correction has its own
        # source identities and component revision. Other numerical inputs stay
        # unchanged, including the nominal background dielectric constant.
        passivation_revision = '85905e8810982bd89966cbf8b7e9d3fd1e922d42'
        passivation_hashes = {
            'ihp-sg13g2': 'f7a5ba53bf51b61602d7baf40fb20dffbeed13613482d8c6ab8cc9994345daf6',
            'ihp-sg13cmos5l': '291c5731174298c993adca376d391bc508800b0bfd709be0cb6e5ff48dcb61dd',
        }
        _source(stack, 'passivation-recipe', 'Nominal oxide and nitride coating dimensions',
                'RTimothyEdwards/capiche', passivation_revision,
                f'{technology_id}/metal_stack_{technology_id}.py')
        stack.sources[-1].sha256 = passivation_hashes[technology_id]
        _source(stack, 'conformal-mapping', 'Cumulative field extent of chained conformal coatings',
                'RTimothyEdwards/capiche', passivation_revision, 'src/capiche/ordered_stack.py')
        stack.sources[-1].sha256 = 'ef91dec393e1ac97bc1f491a8c605d1842533bc5a2deff5b53879f9fc8199ea7'
        _assumption(stack, 'cumulative-field-extent',
                    'pass2 has 1.9 um cumulative field extent: 1.5 um oxide plus 0.4 um nitride',
                    'The field extent is measured from the root metal bottom; the incremental top and side coatings remain 0.4 and 0.3 um',
                    'passivation-recipe', 'conformal-mapping')
        stack.data_revision = 'passivation-field-1'
        stack.history.add(
            revision='passivation-field-1', date='2026-11-13',
            summary='Restore nominal nitride above the passivation oxide over the field',
            reason='The former 0.4 um field extent placed the nitride inside the 1.5 um oxide instead of above it',
            source_ids=['passivation-recipe', 'conformal-mapping'],
            references=['https://github.com/iic-jku/klayout-pex/issues/556'])

    devices = components['device_references']
    if technology_id.startswith('ihp-'):
        for model in ('cap_cmomf', 'cap_cmomi'):
            _source(devices, model, f'Independent nominal {model} reference', 'IHP-GmbH/IHP-Open-PDK',
                    IHP_DEVICE_REVISION, f'{technology_id}/libs.tech/verilog-a/{model}/{model}.va')
        _assumption(devices, 'nominal-model', 'MOM references are low-frequency engineering estimates without corner or mismatch variation',
                    'They provide independent nominal checks rather than silicon-qualified corner limits',
                    'cap_cmomf', 'cap_cmomi')
    else:
        _assumption(devices, 'no-references', 'No automatic device-capacitance references are defined',
                    'An empty reference dataset must not imply that device capacitances have been checked')
    for evidence in components.values():
        evidence.history[0].source_ids[:] = [source.id for source in evidence.sources
                                              if source.id not in ('passivation-recipe', 'conformal-mapping')]
    return catalog, components
