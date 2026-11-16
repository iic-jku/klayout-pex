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
"""Source-specific physical interconnect recipes, independent of empirical coefficients."""

from typing import List
from pathlib import Path

from klayout_pex_protobuf.kpex.tech.process_stack_pb2 import ProcessStackInfo
from klayout_pex_protobuf.kpex.tech.tech_catalog_pb2 import TechnologyDataset, TechnologyScenario
from klayout_pex_protobuf.kpex.tech.tech_pb2 import Technology
from scripts.gen_tech_pb.provenance import nominal_provenance
from scripts.gen_tech_pb.source_physical_corners import load_restricted_physical_corners


CAPICHE_REVISION = '85905e8810982bd89966cbf8b7e9d3fd1e922d42'


def load_corner_process_stacks(technology: Technology) -> List[TechnologyDataset]:
    """Return complete supported interconnect recipes without changing nominal data."""
    if technology.name in ('sky130A', 'gf180mcuD', 'ihp-sg13g2'):
        return load_restricted_physical_corners(
            technology, Path(__file__).with_name('corners') / f'{technology.name}-physical.json')
    if technology.name != 'ihp-sg13cmos5l':
        raise NotImplementedError(f'Physical corner recipes for {technology.name!r} are not implemented')
    datasets = []
    # The source fixes these profiles in both corners. Checking the interface prevents
    # silently retaining newly added metal/device profiles without a source recipe.
    metals = {'GatPoly': (0.4, 0.16), 'Metal1': (1.04, 0.42), 'Metal2': (2.0, 0.49),
              'Metal3': (3.03, 0.49), 'Metal4': (4.06, 0.49), 'TopMetal1': (5.4, 2.0)}
    simple = {'ild0': 'nitride', 'ild1': 'ild0', 'ild2': 'ild1', 'ild3': 'ild2',
              'ild4': 'ild3', 'ildtm1': 'ild4'}
    hashes = {'low': '3885a4ea87e78f6c03d8a54421d270da3b0507a9a9690274dcdc0e4ed58d81b8',
              'high': 'ffdd791b2a897d62614de2ca5d03d0274f7ff14cba7c79c9e11a2b43d0c9b977'}
    for corner, oxide, nitride in [('low', 3.69, 5.94), ('high', 4.51, 7.26)]:
        dataset = TechnologyDataset(id='capiche-'+corner,
                                    description=f'Capiche {corner}-C interconnect physical recipe')
        dataset.process_stack.CopyFrom(technology.process_stack)
        layers = {layer.name: layer for layer in dataset.process_stack.layers}
        expected_names = {'subs', 'nwell_drw', 'nSD', 'pSD', 'ntap', 'ptap', 'fox',
                          'nitride', 'pass1', 'pass2', 'air', *metals, *simple}
        if set(layers) != expected_names:
            raise ValueError('SG13CMOS5L physical recipe does not cover the process-stack interface')
        for name, (z, thickness) in metals.items():
            layer = layers[name]
            if layer.layer_type != ProcessStackInfo.LAYER_TYPE_METAL:
                raise ValueError(f'{name} is not a conductor in the physical recipe')
            layer.metal_layer.z = z
            layer.metal_layer.thickness = thickness
        layers['fox'].field_oxide_layer.dielectric_k = 3.95
        for name, reference in simple.items():
            layer = layers[name].simple_dielectric_layer
            layer.dielectric_k = oxide
            layer.reference = reference
        for name, permittivity, over, field, side, reference in [
                ('nitride', 6.5, 0.05, 0.05, 0.05, 'GatPoly'),
                ('pass1', oxide, 1.5, 1.5, 0.3, 'TopMetal1'),
                ('pass2', nitride, 0.4, 1.9, 0.3, 'pass1')]:
            layer = layers[name].conformal_dielectric_layer
            layer.dielectric_k = permittivity
            layer.thickness_over_metal = over
            layer.thickness_where_no_metal = field
            layer.thickness_sidewall = side
            layer.reference = reference
        layers['air'].simple_dielectric_layer.dielectric_k = 3.0
        layers['air'].simple_dielectric_layer.reference = 'pass2'
        provenance = dataset.provenance
        provenance.data_revision = '1'
        _, nominal_components = nominal_provenance(technology.name)
        provenance.sources.extend(nominal_components['process_stack'].sources)
        source_path = f'ihp-sg13cmos5l_{corner}/metal_stack_ihp-sg13cmos5l_{corner}.py'
        provenance.sources.add(id='capiche-physical', description=f'Capiche {corner}-C physical recipe',
                               uri=f'https://github.com/RTimothyEdwards/capiche/blob/{CAPICHE_REVISION}/{source_path}',
                               revision=CAPICHE_REVISION, sha256=hashes[corner])
        provenance.assumptions.add(
            id='cumulative-field', description='The pass2 field extent is 1.9 um from the top-metal bottom: '
            '1.5 um oxide plus 0.4 um nitride; over-metal and side offsets remain incremental',
            reason='Capiche accumulates field thickness along the coating chain; KPEX stores the extent from the root',
            source_ids=['capiche-physical'])
        provenance.assumptions.add(
            id='source-recipe', description='Interconnect geometry and dielectric recipe from Capiche; '
            'not process calibration or a correlation with IHP ITF resistance corners',
            reason='Empirical coefficients and physical inputs are independently identified',
            source_ids=['capiche-physical'])
        provenance.assumptions.add(
            id='device-geometry', description='The source qualifies interconnect geometry and materials. Existing '
            'device/contact anchors, cut widths and layout connectivity are retained',
            reason='Capiche diffusion levels are alternative 2D ground planes, not an active-device physical corner law', source_ids=['recipe', 'capiche-physical'])
        provenance.assumptions.add(
            id='source-background', description='The source top background has relative permittivity 3; '
            'this is not vacuum and differs from the nominal KPEX background',
            reason='Do not silently replace the selected source material', source_ids=['capiche-physical'])
        provenance.history.add(revision='1', date='2026-11-13', summary='Add supported Capiche interconnect recipes',
                               reason='Enable explicit nonnominal physical inputs with corrected coating anchors',
                               source_ids=[source.id for source in provenance.sources],
                               references=['https://github.com/iic-jku/klayout-pex/issues/550'])
        datasets.append(dataset)
    return datasets


def physical_corner_scenarios(technology: Technology) -> List[TechnologyScenario]:
    """Author source physical/C pairings independently of the held nominal R law."""
    if technology.name not in ('sky130A', 'gf180mcuD', 'ihp-sg13g2', 'ihp-sg13cmos5l'):
        raise NotImplementedError(f'Physical scenarios for {technology.name!r} are not implemented')
    return [TechnologyScenario(
        id='capiche-'+corner+'-c', description='Source '+corner+'-C physical interconnect recipe with nominal R; '
        'layout-dependent MIM restrictions apply. No correlated R or device-reference claim',
        resistance='nominal', capacitance=corner, process_stack='capiche-'+corner,
        physical_stack_matches=True) for corner in ('low', 'high')]
