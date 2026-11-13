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
"""Independent compact-model references for the supported nonnominal MIM laws."""

from typing import Dict, List, Tuple

from klayout_pex_protobuf.kpex.tech.device_models_pb2 import DeviceCapacitanceModel
from klayout_pex_protobuf.kpex.tech.tech_catalog_pb2 import TechnologyDataset, TechnologySource
from klayout_pex_protobuf.kpex.tech.tech_pb2 import Technology


SKY130_REVISION = '29b55153fd9f4badef05a02667184b81789d1f61'
GF180_REVISION = '5e4be8726e2ae8be099c4131f697a353d6457874'
IHP_REVISION = 'e73adb4045731ddec21634146d536380057f6a26'


def _source(identifier: str, repository: str, revision: str, path: str) -> TechnologySource:
    return TechnologySource(id=identifier, description=path, revision=revision,
                            uri=f'https://github.com/{repository}/blob/{revision}/{path}')


def _mim_reference(terminals: List[str], width: str, length: str, area: float, edge: float,
                   source: str, description: str) -> DeviceCapacitanceModel:
    # Dimensions below are micrometres; area and edge terms retain their separate laws.
    return DeviceCapacitanceModel(
        terminal_names=terminals,
        capacitance='area_density*width*length + edge_density*2*(width+length)',
        parameters={'width': width, 'length': length,
                    'area_density': f'{area:.12g}', 'edge_density': f'{edge:.12g}'},
        valid_when='width>0 && length>0', source=source, description=description)


def _dataset(technology: Technology, identifier: str, sources: List[TechnologySource],
             references: Dict[str, DeviceCapacitanceModel]) -> TechnologyDataset:
    dataset = TechnologyDataset(id=identifier, description=f'{identifier} MIM-only device references')
    mappings = {mapping.lvs_device_class_name: mapping for mapping in technology.device_models.device_model_mappings}
    for name, reference in references.items():
        if name not in mappings:
            raise ValueError(f'{technology.name}: MIM reference names missing device class {name}')
        if not set(reference.terminal_names) <= set(mappings[name].terminal_names):
            raise ValueError(f'{technology.name}: MIM reference terminals disagree for {name}')
        dataset.device_references.devices.add(lvs_device_class_name=name, capacitance_references=[reference])
    provenance = dataset.provenance
    provenance.data_revision = '1'
    provenance.sources.extend(sources)
    provenance.assumptions.add(
        id='partial-device-coverage', description='Only the listed MIM devices have corner references; '
        'unlisted MOM, RF and other capacitor models remain unchecked',
        reason='Interconnect corner coefficients do not establish those devices\' independent reference laws',
        source_ids=[source.id for source in sources])
    provenance.history.add(revision='1', date='2026-11-13', summary='Add compact-model MIM corner references',
                           reason='Check the same corner without scaling nominal MOM estimates',
                           source_ids=[source.id for source in sources],
                           references=['https://github.com/iic-jku/klayout-pex/issues/551'])
    return dataset


def load_corner_device_references(technology: Technology) -> List[TechnologyDataset]:
    """Return supported nonnominal references without changing nominal mappings or claiming full coverage."""
    datasets = []
    if technology.name == 'sky130A':
        repository = 'fossi-foundation/skywater-pdk-libs-sky130_fd_pr'
        models = [('sky130_fd_pr__model__cap_mim', 'sky130_fd_pr__cap_mim_m3_1'),
                  ('sky130_fd_pr__model__cap_mim_m4', 'sky130_fd_pr__cap_mim_m3_2')]
        # Both dimensions use m3_dw/m4_dw = -0.025 um plus the style's tol_m3/tol_m4.
        # R/C styles cannot share one low-C or high-C reference: their dimensions differ.
        styles: List[Tuple[str, str, float, float, float]] = [
            ('hrhc', 'res_high__cap_high', -0.0705, 2.231e-15, 0.350e-15),
            ('hrlc', 'res_high__cap_low', -0.0900, 1.778e-15, 0.030e-15),
            ('lrhc', 'res_low__cap_high', 0.0400, 2.231e-15, 0.350e-15),
            ('lrlc', 'res_low__cap_low', 0.0205, 1.778e-15, 0.030e-15),
        ]
        for identifier, style, bias, area, edge in styles:
            sources = [_source('common-parameters', repository, SKY130_REVISION,
                               'models/sky130_fd_pr__model__r+c.model.spice'),
                       _source('corner-dimensions', repository, SKY130_REVISION, f'models/r+c/{style}.spice'),
                       _source('corner-capacitance', repository, SKY130_REVISION, f'models/r+c/{style}__lin.spice')]
            references = {}
            for index, (name, model) in enumerate(models, 1):
                source = _source(f'mim-model-{index}', repository, SKY130_REVISION,
                                 f'cells/cap_mim_m3/{model}.model.spice')
                sources.append(source)
                references[name] = _mim_reference(
                    ['B', 'A'], f'w+({bias:.12g})', f'l+({bias:.12g})', area, edge, source.uri,
                    f'{style} low-frequency mutual capacitance at zero bias, 27 C and zero mismatch. '
                    'Includes both model dimension shifts; excludes series plate/contact resistance. '
                    'Geometry is the exported compact-model rectangle in micrometres.')
            datasets.append(_dataset(technology, identifier, sources, references))
    elif technology.name == 'gf180mcuD':
        repository = 'fossi-foundation/globalfoundries-pdk-libs-gf180mcu_fd_pr'
        sources = [_source('corner-parameters', repository, GF180_REVISION, 'models/ngspice/sm141064.spice'),
                   _source('mim-model', repository, GF180_REVISION, 'models/ngspice/sm141064_mim.spice')]
        for identifier, style, factor in [('low', 'mimcap_ff', 0.9), ('high', 'mimcap_ss', 1.1)]:
            reference = _mim_reference(
                ['B', 'A'], 'c_width*1e6', 'c_length*1e6', 1.99e-15*factor, 0.2383e-15*factor,
                sources[1].uri, f'{style} 2 fF/um2 MIM mutual capacitance at zero bias, 25 C and zero mismatch. '
                'Area and perimeter follow mim_corner_2p0ff. Excludes leakage conductance. '
                'Other MIM options and MOS capacitors are not covered.')
            datasets.append(_dataset(technology, identifier, sources, {'cap_mim_2f0fF': reference}))
    elif technology.name == 'ihp-sg13g2':
        repository = 'IHP-GmbH/IHP-Open-PDK'
        base = 'ihp-sg13g2/libs.tech/ngspice/models/'
        sources = [_source('corner-parameters', repository, IHP_REVISION, base+'cornerCAP.lib'),
                   _source('mim-model', repository, IHP_REVISION, base+'capacitors_mod.lib')]
        for identifier, style, area in [('low', 'cap_bcs', 1.35e-15), ('high', 'cap_wcs', 1.65e-15)]:
            reference = _mim_reference(
                ['mim_top', 'mim_btm'], 'w*1e6', 'l*1e6', area, 40e-18, sources[1].uri,
                f'{style} cap_cmim low-frequency mutual capacitance at zero bias, 27 C and zero mismatch. '
                'Only CJ varies with cap_carea; CJSW remains 40 aF/um. '
                'Excludes series resistance, substrate shunts and RF models. MOM references remain unavailable.')
            reference.capacitance = '('+reference.capacitance+')*m'
            reference.valid_when += ' && m>0'
            datasets.append(_dataset(technology, identifier, sources, {'cap_cmim': reference}))
    elif technology.name == 'ihp-sg13cmos5l':
        # This supported process variant has no MIM option in its mapped devices.
        return []
    else:
        raise NotImplementedError(f'Device corner references for {technology.name!r} are not implemented')
    return datasets
