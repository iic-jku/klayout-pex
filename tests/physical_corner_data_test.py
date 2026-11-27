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
"""Process-stack corners preserve source profiles and independently select their capability."""

import hashlib
import shutil
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

import allure
import pytest

from kpex.klayout.pex25d_builder import PEX25DBuilder
from kpex.pdk_config import PDK
from kpex.pex25d.protobuf import pex25d_file_pb2
from kpex.pex25d.resolver import resolve
from kpex.tech_info import TechDefError, TechInfo
from kpex_protobuf.kpex.tech.tech_catalog_pb2 import TechnologyDatasetFile
from scripts.gen_tech_pb.corner_data import write_bundled_corner_catalog
from scripts.gen_tech_pb.physical_corners import load_corner_process_stacks
from tests.common.tech_catalog import add_scenario, read_catalog


pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('Process-Stack Corners')]


def selected_stack(corner: str, pdk: PDK = PDK.IHP_SG13CMOS5L) -> TechInfo:
    technology = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    dataset = next(dataset for dataset in load_corner_process_stacks(technology) if dataset.id == 'capiche-'+corner)
    technology.process_stack.CopyFrom(dataset.process_stack)
    return TechInfo(technology, None)


def physical_file(corner: str, pdk: PDK = PDK.IHP_SG13CMOS5L):
    builder = PEX25DBuilder(SimpleNamespace(dbu=0.001, substrate_net_name='stack-reference'),
                            selected_stack(corner, pdk), 'physical-corner')
    file = pex25d_file_pb2().PEX25DFile()
    for step in (builder.build_units, builder.build_ground_plane, builder.build_layers, builder.build_dielectrics):
        step(file)
    return file


@pytest.mark.parametrize('pdk', list(PDK))
def test_process_stack_generation_preserves_nominal_and_has_explicit_coverage(pdk: PDK):
    technology = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    before = technology.SerializeToString(deterministic=True)
    datasets = load_corner_process_stacks(technology)
    assert technology.SerializeToString(deterministic=True) == before
    assert {dataset.id for dataset in datasets} == {'capiche-low', 'capiche-high'}
    for dataset in datasets:
        assert any(source.id == 'capiche-physical' and len(source.sha256) == 64
                   for source in dataset.provenance.sources)
        assert dataset.provenance.data_revision == dataset.provenance.history[-1].revision


def test_unknown_physical_process_is_not_treated_as_an_audited_gap():
    technology = TechInfo.parse_tech_def(PDK.IHP_SG13CMOS5L.config.tech_pb_json_path)
    technology.name = 'unknown'
    with pytest.raises(NotImplementedError, match='unknown'):
        load_corner_process_stacks(technology)


@pytest.mark.parametrize('corner,oxide,nitride', [('low', 3.69, 5.94), ('high', 4.51, 7.26)])
def test_resolved_process_stack_keeps_corrected_coatings_and_source_materials(corner: str, oxide: float, nitride: float):
    scene = resolve(physical_file(corner))
    metals = {layer.name: layer for layer in scene.layers}
    for name, bounds in {'GatPoly': (4000, 5600), 'Metal1': (10400, 14600), 'Metal2': (20000, 24900),
                         'Metal3': (30300, 35200), 'Metal4': (40600, 45500),
                         'TopMetal1': (54000, 74000)}.items():
        assert (metals[name].zlow, metals[name].zhigh) == bounds
    films = {film.name: film for film in scene.dielectrics}
    assert all(film.zlow < film.zhigh for film in scene.dielectrics)
    assert (films['nitride'].wraps, films['nitride'].root) == ('GatPoly', 'GatPoly')
    assert (films['pass1'].wraps, films['pass1'].root) == ('TopMetal1', 'TopMetal1')
    assert (films['pass2'].wraps, films['pass2'].root) == ('pass1', 'TopMetal1')
    assert (films['pass1'].thickness_over_wrapped, films['pass1'].thickness_beside_wrapped,
            films['pass1'].thickness_on_field) == (15000, 3000, 15000)
    assert (films['pass2'].thickness_over_wrapped, films['pass2'].thickness_beside_wrapped,
            films['pass2'].thickness_on_field) == (4000, 3000, 19000)
    assert films['pass1'].permittivity == oxide
    assert films['pass2'].permittivity == nitride
    assert films['nitride'].permittivity == 6.5
    assert all(films[f'ild{i}'].permittivity == oxide for i in range(5))
    assert (scene.background.name, scene.background.permittivity) == ('air', 3.0)


@pytest.mark.parametrize('corner', ['low', 'high'])
def test_nitride_field_slab_survives_above_oxide_when_top_metal_is_absent(corner: str):
    import klayout.db as kdb
    from kpex.fastercap.fastercap_model_generator import FasterCapModelBuilder
    from kpex.fastercap.pex25d_exporter import FasterCapModelOptions, build_fastercap_model
    file = physical_file(corner)
    file.conductors.add(name='plate', net='plate')
    shape = file.shapes.add(conductor='plate', layer='Metal1',
                            kind=pex25d_file_pb2().ShapeRecord.SHAPE_KIND_BOX)
    shape.box.upper_right.x = shape.box.upper_right.y = 100000
    with patch.object(FasterCapModelBuilder, 'generate', autospec=True, side_effect=lambda model: model):
        model = build_fastercap_model(resolve(file), FasterCapModelOptions(), 'fastercap')
    # At 7.1 um the 1.5 um field oxide (5.4..6.9) is over, and the nitride
    # occupies 6.9..7.3 um. Storing only its incremental 0.4 um loses it.
    point = kdb.Point(-10000, -10000)
    materials = {name for name, slabs in model.dlayers.items()
                 for region, low, high in slabs if low < 71000 < high
                 and any(polygon.inside(point) for polygon in region.each_merged())}
    assert 'pass2' in materials
    assert 'pass1' not in materials


def test_uncovered_process_profile_is_rejected_instead_of_inherited():
    technology = TechInfo.parse_tech_def(PDK.IHP_SG13CMOS5L.config.tech_pb_json_path)
    technology.process_stack.layers.add(name='new-mim')
    with pytest.raises(ValueError, match='does not cover'):
        load_corner_process_stacks(technology)


def test_physical_component_selection_requires_explicit_scenario_capability(tmp_path: Path):
    technology = TechInfo.parse_tech_def(PDK.IHP_SG13CMOS5L.config.tech_pb_json_path)
    path = tmp_path / 'catalog.pb.json'
    written = write_bundled_corner_catalog(technology, path)
    catalog = read_catalog(path)
    records = [record for record in catalog.datasets
               if record.kind == TechnologyDatasetFile.PROCESS_STACK and record.id != 'nominal']
    assert {record.id for record in records} == {'capiche-low', 'capiche-high'}
    for record in records:
        component = path.parent / record.file.path
        assert component in written
        assert hashlib.sha256(component.read_bytes()).hexdigest() == record.file.sha256
    add_scenario(path, name='ordering-only', capacitance='low', process_stack='capiche-low')
    with pytest.raises(TechDefError, match='no matching physical stack'):
        TechInfo.from_catalog(str(path), None, 'ordering-only').selection.require_physical_stack()
    add_scenario(path, name='physical-low', capacitance='low', process_stack='capiche-low', physical_stack_matches=True)
    selected = TechInfo.from_catalog(str(path), None, 'physical-low')
    selected.selection.require_physical_stack()
    assert selected.selection.device_references is None
    assert selected.tech.process_stack == selected_stack('low').tech.process_stack
    assert TechInfo.from_catalog(str(path), None, 'nominal').tech == technology


@pytest.mark.slow
@pytest.mark.fastercap
@pytest.mark.skipif(shutil.which('FasterCap') is None, reason='FasterCap is not installed')
@pytest.mark.parametrize('pdk', list(PDK))
def test_physical_corner_parallel_plates_converge_and_preserve_expected_order(tmp_path: Path, pdk: PDK):
    from kpex.fastercap.calibration_backend import read_native_statistics
    from kpex.fastercap.fastercap_runner import run_fastercap, fastercap_parse_capacitance_matrix
    from kpex.fastercap.pex25d_exporter import FasterCapSceneExporter

    results = {}
    for corner in ('low', 'high'):
        file = physical_file(corner, pdk)
        layers = ('met1', 'met2') if pdk == PDK.SKY130A else ('Metal1', 'Metal2')
        for net, layer in zip(('bottom', 'top'), layers):
            file.conductors.add(name=net, net=net)
            shape = file.shapes.add(conductor=net, layer=layer,
                                    kind=pex25d_file_pb2().ShapeRecord.SHAPE_KIND_BOX)
            shape.box.upper_right.x = shape.box.upper_right.y = 100000  # 10 um square
        from fractions import Fraction
        from kpex.klayout.physical_geometry import apply_width_bias, width_bias_offsets
        apply_width_bias(file, width_bias_offsets(selected_stack(corner, pdk), Fraction('0.0001')))
        scene = resolve(file)
        directory = tmp_path / corner
        outputs = FasterCapSceneExporter().export(scene, output_dir_path=str(directory),
                                                  options={'field_margin_um': 8.0})
        # NOTE: explicit mesh refinement levels, as the automatic refinement can stop on its panel-count
        #       criterion without refining (sky130A gave the same matrix at -a0.02 and -a0.005). The finer
        #       level must refine, so that the comparison is evidence of convergence. The GMRES tolerance
        #       keeps the solver error below the change between the levels.
        estimates = []
        panels = []
        for mesh_refinement in (0.005, 0.0025):
            log = str(directory / f'solve-{mesh_refinement}.log')
            run_fastercap(shutil.which('FasterCap'), outputs[0], log, None, 0.1, 0, True, False, False,
                          mesh_refinement=mesh_refinement, gmres_tolerance=1e-6)
            panels.append(read_native_statistics(Path(log))['refined_panels'])
            matrix = fastercap_parse_capacitance_matrix(log)
            first = next(i for i, name in enumerate(matrix.conductor_names) if name.endswith('_bottom'))
            second = next(i for i, name in enumerate(matrix.conductor_names) if name.endswith('_top'))
            forward, backward = -matrix[first][second], -matrix[second][first]
            assert forward > 0 and backward > 0
            assert forward == pytest.approx(backward, rel=0.02, abs=0)
            estimates.append((forward+backward)/2)
        assert None not in panels and panels[0] < panels[1], panels
        assert estimates[-1] == pytest.approx(estimates[-2], rel=0.02, abs=0)
        results[corner] = estimates[-1]
        # Independent infinite-plate area estimates from the pinned source gap,
        # permittivity and manufactured full width. The finite 10 um plates add
        # fringe; this comparison exposes unit/gap errors without treating a
        # field solver as a calibrated reference for the empirical C table.
        area_inputs = {
            PDK.GF180MCUD: {'low': (4.0, .719, 10.0), 'high': (4.0, .481, 10.0)},
            PDK.IHP_SG13G2: {'low': (3.69, .54, 10.0), 'high': (4.51, .54, 10.0)},
            PDK.IHP_SG13CMOS5L: {'low': (3.69, .54, 10.0), 'high': (4.51, .54, 10.0)},
            PDK.SKY130A: {'low': (4.5, .43, 9.9794), 'high': (4.3, .11, 10.0206)},
        }
        permittivity, gap_um, width_um = area_inputs[pdk][corner]
        area_only = 8.8541878128e-18 * permittivity * width_um**2 / gap_um
        assert area_only < estimates[-1] < 1.3*area_only
        print(pdk, corner, 'area-only [F]', area_only, 'finite-plate excess', estimates[-1]/area_only-1)
    # These source high-C process stacks increase permittivity and/or tighten the
    # interconnect geometry. This checks the selected process stack, not agreement with silicon measurements.
    assert results['high'] > results['low']
    print('Converged physical corner mutual capacitances [F]:', results)
