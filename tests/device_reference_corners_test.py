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

"""Corner references use independent device laws, exported dimensions and the same observable."""

import math
import hashlib
from pathlib import Path
from typing import Tuple
from unittest.mock import Mock

import allure
import klayout.db as kdb
import pytest

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.pdk_config import PDK
from klayout_pex.rcx25.c.device_capacitance_references import (
    DeviceCapacitanceCheckError, DeviceCapacitanceReference, tech_device_capacitance_references,
)
from klayout_pex.tech_info import TechInfo
from klayout_pex_protobuf.kpex.tech.tech_catalog_pb2 import TechnologyDataset, TechnologyDatasetFile
from scripts.gen_tech_pb.corner_data import write_bundled_corner_catalog
from scripts.gen_tech_pb.device_reference_corners import load_corner_device_references
from tests.common.cli_runner import run_cli
from tests.common.lvsdb_fixtures import lvsdb_fixture_path
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.tech_catalog import add_scenario, edit_dataset, read_catalog, write_test_catalog


pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('TechInfo', 'Device Corner References')]
MODEL_DIRECTORY = Path(__file__).resolve().parents[1] / 'testdata/spice/device_corner_models'
SKY_STYLES = {'hrhc': 'res_high__cap_high', 'hrlc': 'res_high__cap_low',
              'lrhc': 'res_low__cap_high', 'lrlc': 'res_low__cap_low'}
CASES = [(PDK.SKY130A, corner, name) for corner in SKY_STYLES for name in
         ('sky130_fd_pr__model__cap_mim', 'sky130_fd_pr__model__cap_mim_m4')] + [
    (pdk, corner, name) for pdk, name in [(PDK.GF180MCUD, 'cap_mim_2f0fF'), (PDK.IHP_SG13G2, 'cap_cmim')]
    for corner in ('low', 'high')]


def corner_technology(pdk: PDK, corner: str) -> Tuple[TechInfo, TechnologyDataset]:
    tech = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    dataset = next(d for d in load_corner_device_references(tech) if d.id == corner)
    mappings = {m.lvs_device_class_name: m for m in tech.device_models.device_model_mappings}
    for mapping in mappings.values():
        del mapping.capacitance_references[:]
    for device in dataset.device_references.devices:
        mappings[device.lvs_device_class_name].capacitance_references.extend(device.capacitance_references)
    return TechInfo(tech, dielectric_filter=None), dataset


def model_reference(pdk: PDK, corner: str, name: str, width: float, length: float,
                     multiplier: float = 1.0) -> DeviceCapacitanceReference:
    tech, _ = corner_technology(pdk, corner)
    netlist = kdb.Netlist()
    circuit = kdb.Circuit()
    circuit.name = 'MIM'
    netlist.add(circuit)
    device_class = kdb.DeviceClass()
    device_class.name = name
    for terminal in tech.device_models.mapping_by_lvs_device_class_name[name].terminal_names:
        device_class.add_terminal(kdb.DeviceTerminalDefinition(terminal))
    values = dict(w=width, l=length, m=multiplier) if pdk == PDK.IHP_SG13G2 else \
        dict(A=width*length, P=2*(width+length))
    for parameter in values:
        device_class.add_parameter(kdb.DeviceParameterDefinition(parameter, parameter, 0.0))
    netlist.add(device_class)
    device = circuit.create_device(device_class, 'C1')
    for parameter, value in values.items():
        device.set_parameter(parameter, value)
    context = Mock(spec=KLayoutExtractionContext, tech=tech, top_circuit=circuit)
    references, unchecked = tech_device_capacitance_references(context)
    assert not unchecked
    reference, = references
    return reference


@pytest.mark.parametrize('pdk', list(PDK))
def test_reference_generation_preserves_nominal_and_declares_partial_coverage(pdk: PDK):
    tech = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    before = tech.SerializeToString(deterministic=True)
    datasets = load_corner_device_references(tech)
    assert tech.SerializeToString(deterministic=True) == before
    assert {d.id for d in datasets} == (set(SKY_STYLES) if pdk == PDK.SKY130A else
                                      set() if pdk == PDK.IHP_SG13CMOS5L else {'low', 'high'})
    for dataset in datasets:
        assert 'MIM-only' in dataset.description
        assert dataset.provenance.data_revision == dataset.provenance.history[-1].revision
        assert all(source.revision and source.uri.startswith('https://github.com/')
                   for source in dataset.provenance.sources)
        assert not any(d.lvs_device_class_name in ('cap_cmomf', 'cap_cmomi', 'rfcmim')
                       for d in dataset.device_references.devices)


def test_unknown_technology_is_not_mistaken_for_intentionally_absent_references():
    tech = TechInfo.parse_tech_def(PDK.IHP_SG13CMOS5L.config.tech_pb_json_path)
    tech.name = 'unknown-process'
    with pytest.raises(NotImplementedError, match='unknown-process'):
        load_corner_device_references(tech)


@pytest.mark.parametrize('pdk,corner,name,expected_ff', [
    (PDK.IHP_SG13G2, 'low', 'cap_cmim', 67.27),
    (PDK.IHP_SG13G2, 'high', 'cap_cmim', 81.97),
    (PDK.GF180MCUD, 'low', 'cap_mim_2f0fF', 93.76416),
    (PDK.GF180MCUD, 'high', 'cap_mim_2f0fF', 114.60064),
])
def test_mim_corner_values_retain_independent_area_and_edge_terms(
        pdk: PDK, corner: str, name: str, expected_ff: float):
    assert model_reference(pdk, corner, name, 7, 7).capacitance_f == pytest.approx(expected_ff*1e-15, rel=1e-13, abs=0)


@pytest.mark.parametrize('multiplier', [0.5, 1, 3])
def test_ihp_multiplier_is_applied_once(multiplier: float):
    reference = model_reference(PDK.IHP_SG13G2, 'low', 'cap_cmim', 7, 7, multiplier)
    assert reference.capacitance_f == pytest.approx(67.27e-15*multiplier, rel=1e-13, abs=0)


@pytest.mark.parametrize('multiplier', [0, -1])
def test_ihp_reference_rejects_nonpositive_multiplier(multiplier: float):
    with pytest.raises(DeviceCapacitanceCheckError, match='outside reference domain'):
        model_reference(PDK.IHP_SG13G2, 'low', 'cap_cmim', 7, 7, multiplier)


def test_sky130_same_c_corner_with_different_r_corner_has_different_reference():
    # Low/high C coefficients alone miss the style-dependent manufactured dimensions.
    values = {corner: model_reference(PDK.SKY130A, corner, 'sky130_fd_pr__model__cap_mim', 7, 7).capacitance_f
              for corner in SKY_STYLES}
    assert values['hrhc'] < values['lrhc']
    assert values['hrlc'] < values['lrlc']


@pytest.mark.parametrize('corner,limit', [('hrhc', 0.0705), ('hrlc', 0.09)])
@pytest.mark.parametrize('offset,accepted', [(-1e-6, False), (0.0, False), (1e-6, True)])
def test_sky130_positive_effective_dimension_boundary(corner: str, limit: float,
                                                       offset: float, accepted: bool):
    # Use a square so area/perimeter reconstruction does not introduce cancellation
    # at the exact zero-width model boundary. Both dimensions undergo the same bias.
    if accepted:
        assert model_reference(PDK.SKY130A, corner, 'sky130_fd_pr__model__cap_mim',
                               limit+offset, limit+offset).capacitance_f > 0
    else:
        with pytest.raises(DeviceCapacitanceCheckError, match='outside reference domain'):
            model_reference(PDK.SKY130A, corner, 'sky130_fd_pr__model__cap_mim', limit+offset, limit+offset)


@pytest.mark.parametrize('width,length', [(0.0, 0.0), (-1.0, 2.0)])
def test_mim_reference_rejects_invalid_geometry(width: float, length: float):
    with pytest.raises((DeviceCapacitanceCheckError, ValueError)):
        model_reference(PDK.IHP_SG13G2, 'low', 'cap_cmim', width, length)


def test_catalog_selects_corner_references_without_inheriting_nominal_mom(tmp_path: Path):
    tech = TechInfo.parse_tech_def(PDK.IHP_SG13G2.config.tech_pb_json_path)
    path = tmp_path / 'catalog.pb.json'
    write_test_catalog(tech, path)
    for dataset in load_corner_device_references(tech):
        def replace_references(target: TechnologyDataset):
            target.device_references.CopyFrom(dataset.device_references)
        edit_dataset(path, 'device_references', replace_references, new_id=dataset.id)
        add_scenario(path, name=dataset.id, device_references=dataset.id)
    low = TechInfo.from_catalog(str(path), None, 'low')
    high = TechInfo.from_catalog(str(path), None, 'high')
    nominal = TechInfo.from_catalog(str(path), None, 'nominal')
    assert low.tech.process_parasitics == high.tech.process_parasitics == nominal.tech.process_parasitics
    assert nominal.device_models.mapping_by_lvs_device_class_name['cap_cmomf'].capacitance_references
    assert not low.device_models.mapping_by_lvs_device_class_name['cap_cmomf'].capacitance_references
    assert low.device_models.mapping_by_lvs_device_class_name['cap_cmim'].capacitance_references != \
        high.device_models.mapping_by_lvs_device_class_name['cap_cmim'].capacitance_references


@pytest.mark.parametrize('pdk', list(PDK))
def test_bundled_device_components_are_hashed_and_explicitly_selectable(tmp_path: Path, pdk: PDK):
    tech = TechInfo.parse_tech_def(pdk.config.tech_pb_json_path)
    path = tmp_path / 'catalog.pb.json'
    written = write_bundled_corner_catalog(tech, path)
    catalog = read_catalog(path)
    records = [record for record in catalog.datasets
               if record.kind == TechnologyDatasetFile.DEVICE_REFERENCES and record.id != 'nominal']
    assert {record.id for record in records} == {dataset.id for dataset in load_corner_device_references(tech)}
    # Device components alone must not invent correlation with a physical stack or R law.
    assert all(not scenario.device_references or scenario.device_references == 'nominal'
               for scenario in catalog.scenarios)
    for record in records:
        file_path = path.parent / record.file.path
        assert file_path in written
        assert hashlib.sha256(file_path.read_bytes()).hexdigest() == record.file.sha256
        add_scenario(path, name='device-'+record.id, device_references=record.id)
        resolved = TechInfo.from_catalog(str(path), None, 'device-'+record.id)
        assert resolved.device_models.mapping_by_lvs_device_class_name
    nominal = TechInfo.from_catalog(str(path), None, 'nominal')
    assert nominal.tech.SerializeToString(deterministic=True) == tech.SerializeToString(deterministic=True)


def model_deck(pdk: PDK, corner: str, name: str, width: float, length: float,
               multiplier: float = 1.0) -> str:
    def include(filename: str) -> str:
        return f'.include "{MODEL_DIRECTORY / filename}"'
    def library(filename: str, section: str) -> str:
        return f'.lib "{MODEL_DIRECTORY / filename}" {section}'
    if pdk == PDK.SKY130A:
        model = 'sky130_fd_pr__cap_mim_m3_2' if name.endswith('_m4') else 'sky130_fd_pr__cap_mim_m3_1'
        setup = [include(SKY_STYLES[corner]+'.spice'), include(SKY_STYLES[corner]+'__lin.spice'),
                 include('sky130_mim_common.spice'), include(model+'.model.spice'),
                 '.param MC_MM_SWITCH=0', '.param tc1rm3=0 tc2rm3=0 tc1rm4=0 tc2rm4=0',
                 '.param tc1rvia3=0 tc2rvia3=0 tc1rvia4=0 tc2rvia4=0', '.temp 27']
        # R temperature coefficients cannot affect this 27 C reference, and the
        # model's drawn dimensions are in micrometres without a global scale option.
        instance = f'X1 a b {model} w={width:.12g} l={length:.12g}'
    elif pdk == PDK.GF180MCUD:
        setup = [library('gf180_mim_corners.spice', 'mimcap_ff' if corner == 'low' else 'mimcap_ss'),
                 include('gf180_cap_mim_2f0.spice'), '.temp 25']
        instance = f'X1 a b cap_mim_2f0_m4m5_noshield c_width={width:.12g}u c_length={length:.12g}u'
    elif pdk == PDK.IHP_SG13G2:
        setup = [library('ihp_cornerCAP.lib', 'cap_bcs' if corner == 'low' else 'cap_wcs'),
                 include('ihp_cap_cmim.spice'), '.temp 27']
        instance = f'X1 a b cap_cmim w={width:.12g}u l={length:.12g}u m={multiplier:.12g}'
    else:
        raise NotImplementedError(f'Corner simulation model for {pdk} is not implemented')
    return '\n'.join(['* Independent upstream compact-model reference', *setup,
                      '.subckt reference a b', instance, '.ends reference', ''])


@pytest.mark.slow
@requires_ngspice
@pytest.mark.parametrize('pdk,corner,name,multiplier', [(*case, 1.0) for case in CASES] + [
    (PDK.IHP_SG13G2, corner, 'cap_cmim', 3.0) for corner in ('low', 'high')])
@pytest.mark.parametrize('width,length', [(7.0, 7.0), (7.0, 40.0), (40.0, 40.0)])
def test_corner_reference_matches_upstream_model_mutual_ac_admittance(
        tmp_path: Path, pdk: PDK, corner: str, name: str, width: float, length: float, multiplier: float):
    reference = model_reference(pdk, corner, name, width, length, multiplier)
    path = tmp_path / 'reference.spice'
    path.write_text(model_deck(pdk, corner, name, width, length, multiplier), encoding='utf-8')
    (tmp_path / '.spiceinit').write_text('set numdgt=15\n', encoding='utf-8')
    frequencies, admittance = ngspice_port_admittance(str(path), 'reference', ['a', 'b'], (2, 4), str(tmp_path))
    for frequency, matrix in zip(frequencies, admittance):
        # Off-diagonal imaginary Y measures mutual C independently of leakage.
        # Low frequencies suppress series resistance corrections, retained in the fixtures.
        capacitance = -matrix[0, 1].imag / (math.tau*frequency)
        assert capacitance == pytest.approx(reference.capacitance_f, rel=1e-8, abs=0)


@pytest.mark.parametrize('corner,reference_corner,area_ff,reference_ff', [
    ('low', 'low', 540.0, 543.2), ('high', 'high', 660.0, 663.2),
    ('low', 'high', 540.0, 663.2), ('high', 'low', 660.0, 543.2)])
def test_real_ihp_mim_keeps_marker_observation_distinct_from_full_model_reference(
        tmp_path: Path, corner: str, reference_corner: str, area_ff: float, reference_ff: float):
    technology = TechInfo.parse_tech_def(PDK.IHP_SG13G2.config.tech_pb_json_path)
    catalog_path = tmp_path / 'catalog.pb.json'
    write_bundled_corner_catalog(technology, catalog_path)
    # Deliberately crossed references remain explicit author choices. They must
    # neither select a different C table nor silently become same-name references.
    add_scenario(catalog_path, name='selected-mim', capacitance=corner, device_references=reference_corner)
    pattern = 'cap_cmim_20um_x_20um_over_m4_wire'
    gds = str(Path(__file__).resolve().parents[1] / 'testdata/designs/ihp-sg13g2/test_patterns' / (pattern+'.gds.gz'))
    cli = KpexCLI()
    code, output = run_cli(cli.main, [
        'kpex', 'extract', '--pdk', 'ihp-sg13g2', '--2.5D', '--mode', 'CC', '--blackbox', 'y',
        '--gds', gds, '--lvsdb', lvsdb_fixture_path('ihp-sg13g2', gds),
        '--tech-catalog', str(catalog_path), '--corner', 'selected-mim', '--check-device-caps',
        '--out-dir', str(tmp_path / 'output')])
    assert code == 0, output
    record, = cli.run_result.device_capacitance_checks
    assert record['status'] == 'informational'
    assert record['reference_capacitance_f'] == pytest.approx(reference_ff*1e-15, rel=1e-13, abs=0)
    assert record['extracted_capacitance_f'] == pytest.approx(area_ff*1e-15, rel=1e-13, abs=0)
    # LVS intersects the bottom plate with the MIM marker. Both observed plates
    # therefore have the same 20 um square footprint. Its 2 um bottom-metal
    # overhang is outside the marker; the independent model includes the full
    # 80 um * 40 aF/um edge term. Matching corner identity does not erase this
    # observable-domain difference or silently substitute the extracted value.
    assert record['contributions']['fringe_f'] == 0.0
