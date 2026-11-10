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

import math
from pathlib import Path
from typing import Dict

import allure
import pytest

from klayout_pex.rcx25.c.device_capacitance_references import (
    DeviceCapacitanceCheckError, DeviceCapacitanceReference, tech_device_capacitance_references,
)
from tests.common.device_capacitance import DESIGN, layout_context

from klayout_pex.pdk_config import PDK
from klayout_pex.tech_info import TechInfo
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice, write_spiceinit
from tests.common.pdk_test_config import PDKName, PDKTestConfig

pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('RCX25', 'Device Capacitance Models')]


def nominal_model_reference(pdk: PDK, model: str, **parameters: float) -> DeviceCapacitanceReference:
    # Use the real LVS parameter definitions, including the cmomi feed parameter.
    design = DESIGN if model == 'cap_cmomf' else 'cap_cmomi_w3u_l2u_m4_m5_orientations.gds.gz'
    context, _, _ = layout_context(design)
    context.tech = TechInfo.from_json(pdk.config.tech_pb_json_path, dielectric_filter=None)
    for device in context.top_circuit.each_device():
        for name, value in parameters.items():
            device.set_parameter(name, value)
    references, unchecked = tech_device_capacitance_references(context)
    assert not unchecked
    assert all(reference.capacitance_f == references[0].capacitance_f for reference in references)
    return references[0]


@pytest.mark.parametrize('pdk', [PDK.IHP_SG13G2, PDK.IHP_SG13CMOS5L])
@pytest.mark.parametrize('model,parameters,expected_ff', [
    ('cap_cmomf', dict(w=10, l=25, mmin=2, mmax=4), 228.75),
    ('cap_cmomf', dict(w=10, l=25, mmin=1, mmax=4), 321.75),
    ('cap_cmomi', dict(w=2.67, l=1.68, mmin=2, mmax=3, feed=0), 2.46708),
    ('cap_cmomi', dict(w=2.67, l=1.68, mmin=2, mmax=3, feed=1), 3.060805),
    ('cap_cmomi', dict(w=2.67, l=1.68, mmin=2, mmax=3, feed=2), 2.93676),
])
@pytest.mark.parametrize('multiplier', [0.5, 1, 3])
def test_nominal_model_values(pdk: PDK, model: str, parameters: Dict[str, float],
                              expected_ff: float, multiplier: float):
    reference = nominal_model_reference(pdk, model, **parameters, m=multiplier)
    assert reference.capacitance_f == pytest.approx(expected_ff * multiplier * 1e-15, rel=1e-13, abs=0)
    assert reference.source.endswith(f'{model}/{model}.va')
    assert 'Nominal low-frequency mutual capacitance' in reference.description


@pytest.mark.parametrize('model', ['cap_cmomf', 'cap_cmomi'])
@pytest.mark.parametrize('first,last', [(1, 2), (1, 3), (1, 4), (2, 4), (3, 4)])
def test_sibling_stacks_have_identical_model_capacitance(model: str, first: int, last: int):
    parameters = dict(w=10, l=25, mmin=first, mmax=last, m=2)
    if model == 'cap_cmomi':
        parameters['feed'] = 2
    values = [nominal_model_reference(pdk, model, **parameters).capacitance_f
              for pdk in (PDK.IHP_SG13G2, PDK.IHP_SG13CMOS5L)]
    assert values[0] == values[1]


@pytest.mark.parametrize('dimension,pitch,cells', [('w', 0.89, 3), ('l', 0.84, 2)])
@pytest.mark.parametrize('epsilon,drop_cell', [(-2e-6, True), (-0.5e-6, False), (0, False), (2e-6, False)])
def test_cmomi_grid_boundaries(dimension: str, pitch: float, cells: int, epsilon: float, drop_cell: bool):
    # Exact pitch multiples and sub-roundoff offsets retain the cell. A genuine
    # sub-pitch dimension drops it, unless the model's one-column/two-row clamp applies.
    parameters = dict(w=2.67, l=1.68, mmin=2, mmax=3, m=1, feed=0)
    parameters[dimension] = (cells + epsilon) * pitch
    rows = 3 - int(dimension == 'w' and drop_cell)
    columns = 2 - int(dimension == 'l' and drop_cell)
    reference = nominal_model_reference(PDK.IHP_SG13G2, 'cap_cmomi', **parameters)
    assert reference.capacitance_f == pytest.approx(rows * columns * 0.89 * 0.84 * 0.55e-15, rel=1e-13, abs=0)


def test_cmomi_minimum_array_has_one_column_and_two_rows():
    reference = nominal_model_reference(PDK.IHP_SG13G2, 'cap_cmomi',
                                        w=0.1, l=0.1, mmin=1, mmax=2, m=1, feed=0)
    assert reference.capacitance_f == pytest.approx(2 * 0.89 * 0.84 * 0.55e-15, rel=1e-13, abs=0)


@pytest.mark.parametrize('parameters', [dict(w=0), dict(w=-1), dict(l=0), dict(m=0), dict(m=-1),
                                        dict(mmin=0), dict(mmin=1.5), dict(mmin=4, mmax=3), dict(mmax=6)])
def test_nominal_model_rejects_invalid_dimensions_and_metal_ranges(parameters: Dict[str, float]):
    values = dict(w=10, l=25, mmin=2, mmax=4, m=1)
    values.update(parameters)
    with pytest.raises(DeviceCapacitanceCheckError, match='outside reference domain'):
        nominal_model_reference(PDK.IHP_SG13G2, 'cap_cmomf', **values)


@pytest.mark.parametrize('feed', [-1, 0.5, 3])
def test_cmomi_rejects_unknown_feed_styles(feed: float):
    with pytest.raises(DeviceCapacitanceCheckError, match='outside reference domain'):
        nominal_model_reference(PDK.IHP_SG13G2, 'cap_cmomi', w=10, l=25, mmin=2, mmax=4, m=1, feed=feed)


@pytest.mark.parametrize('model', ['cap_cmomf', 'cap_cmomi'])
def test_reference_metal_limit_depends_on_stack(model: str):
    values = dict(w=10, l=25, mmin=2, mmax=5, m=1)
    if model == 'cap_cmomi':
        values['feed'] = 0
    assert nominal_model_reference(PDK.IHP_SG13G2, model, **values)
    with pytest.raises(DeviceCapacitanceCheckError, match='outside reference domain'):
        nominal_model_reference(PDK.IHP_SG13CMOS5L, model, **values)


@pytest.mark.slow
@requires_ngspice
@pytest.mark.parametrize('model', ['cap_cmomf', 'cap_cmomi'])
@pytest.mark.parametrize('pdk,parameters', [(pdk, parameters)
    for pdk in (PDK.IHP_SG13G2, PDK.IHP_SG13CMOS5L) for parameters in [
    dict(w=10, l=25, mmin=2, mmax=4, m=1, feed=0),
    dict(w=2.67, l=1.68, mmin=1, mmax=2, m=3, feed=1),
    dict(w=3, l=2, mmin=1, mmax=4, m=0.5, feed=2),
    dict(w=0.1, l=0.1, mmin=2, mmax=3, m=1, feed=0),
    dict(w=(3-2e-6)*0.89, l=(2-2e-6)*0.84, mmin=1, mmax=3, m=1, feed=2),
    dict(w=10, l=25, mmin=1, mmax=5 if pdk == PDK.IHP_SG13G2 else 4, m=1, feed=1),
]])
def test_tech_reference_matches_model_mutual_ac_admittance(
        tmp_path: Path, pdk: PDK, model: str, parameters: Dict[str, float]):
    config = PDKTestConfig(PDKName(pdk.value))
    models = config.simulator_models_dir('ngspice')
    if models is None or not (Path(models) / f'osdi/{model}.osdi').is_file():
        pytest.skip(f'needs the compiled {model}.osdi model in the installed ngspice PDK')
    values = dict(parameters)
    if model == 'cap_cmomf':
        del values['feed']
    reference = nominal_model_reference(pdk, model, **values)
    write_spiceinit(str(tmp_path), models)
    with (tmp_path / '.spiceinit').open('a', encoding='utf-8') as stream:
        stream.write('\nset numdgt=15\n')
    arguments = ' '.join(f'{key}={value:.12g}' + ('u' if key in ('w', 'l') else '')
                         for key, value in values.items())
    path = tmp_path / 'reference.spice'
    path.write_text(f"""* Nominal mutual capacitance
.include "{models}/models/{model}.lib"
.subckt reference plus minus
Xcap plus minus {model} {arguments}
.ends reference
""", encoding='utf-8')
    # Off-diagonal Y excludes substrate shunts. At 100 Hz and 1 kHz, series R/L
    # corrections are negligible; a diagonal or RF comparison measures a different quantity.
    decades = (6, 7) if model == 'cap_cmomf' else (2, 3)
    frequencies, admittance = ngspice_port_admittance(str(path), 'reference', ['plus', 'minus'], decades, str(tmp_path))
    for frequency, matrix in zip(frequencies, admittance):
        capacitance = -matrix[0, 1].imag / (math.tau * frequency)
        assert capacitance == pytest.approx(reference.capacitance_f, rel=1e-11, abs=0)
