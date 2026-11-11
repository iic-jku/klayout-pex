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

"""Observable contracts of standalone grounding, including preserved circuit context."""

import json
import math
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import allure
import numpy as np
import pytest

from klayout_pex.netlist.coupling import CouplingPolicyError
from klayout_pex.netlist.netlist_cli import NetlistCLI
from klayout_pex.netlist.netlist_grounding import GroundingOptions, ground_spice_netlist
from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist
from tests.common.cli_runner import assert_netlist_cli_loads_neither_klayout_nor_protobuf, run_cli
from tests.common.rc_networks import scope_named
from tests.common.ngspice import ngspice_port_admittance, requires_ngspice
from tests.common.xyce import xyce_port_admittance, requires_xyce
from tests.common.vacask import vacask_port_admittance, requires_vacask

pytestmark = [allure.parent_suite('Unit Tests'), allure.tag('Netlist', 'Grounding')]

TWO_NETS = '.subckt dut A B G\nCext_1 A B 2f\nCext_2 A G 1f\nCext_3 B G 3f\n.ends dut\n'


def transform(tmp_path: Path, source: str, options: GroundingOptions = GroundingOptions('G')) \
        -> Tuple[Path, Path]:
    original = tmp_path / 'coupled.spice'
    grounded = tmp_path / 'grounded.spice'
    original.write_text(source, encoding='utf-8', newline='')
    result = ground_spice_netlist(str(original), str(grounded), options)
    assert result.output_path == str(grounded)
    return original, grounded


def capacitors(path: Path, scope_name: Optional[str] = 'dut') -> Dict[Tuple[str, str], float]:
    network = scope_named(SpiceRCNetlist.read(str(path)), scope_name).network
    return {tuple(sorted((network.name(a), network.name(b)))): branch.capacitance
            for a, b, branch in network.edges() if branch.capacitance}


def test_full_coupling_loads_reference_and_repeat_grounding(tmp_path: Path):
    original, grounded = transform(tmp_path, TWO_NETS)
    assert original.read_text(encoding='utf-8') == TWO_NETS
    assert capacitors(grounded) == {('A', 'G'): 3e-15, ('B', 'G'): 5e-15}
    second = tmp_path / 'twice.spice'
    ground_spice_netlist(str(grounded), str(second), GroundingOptions('g'))
    assert capacitors(second) == capacitors(grounded)


def test_floating_series_eliminates_before_grounding_and_reports_names(tmp_path: Path):
    source = '.subckt dut A G\nCext_1 A float 2f\nCext_2 float G 2f\n.ends\n'
    original, grounded = transform(tmp_path, source)
    result = ground_spice_netlist(str(original), str(grounded), GroundingOptions('G'))
    assert capacitors(grounded) == {('A', 'G'): 1e-15}
    assert result.floating_nodes == ['float']


def test_distributed_intra_net_capacitance_keeps_resistor_lines_verbatim(tmp_path: Path):
    resistor = 'Rext_wire A A1 1.234567890123456Meg $ keep exact text'
    source = f'.subckt dut A G\n{resistor}\nCext_1 A F 2f\nCext_2 F A1 2f\nCext_3 A1 G 3f\n.ends\n'
    _, grounded = transform(tmp_path, source)
    assert resistor in grounded.read_text(encoding='utf-8').splitlines()
    assert capacitors(grounded) == {('A', 'A1'): 1e-15, ('A1', 'G'): 3e-15}


def test_intentional_r_c_models_sources_and_other_scope_are_preserved(tmp_path: Path):
    preserved = ['Cintent A B 7p', 'Rintent A B 50', 'Xmodel A private G modeled m=2',
                 'Vbias private G DC 0', '.param gain=2']
    other = '.subckt other P Q\nCext_lib P Q {gain}\n.ends other'
    source = TWO_NETS.replace('.ends dut', '\n'.join(preserved) + '\n.ends dut') + other + '\n'
    _, grounded = transform(tmp_path, source, GroundingOptions('G', cell_name='DUT'))
    output = grounded.read_text(encoding='utf-8')
    assert all(line in output.splitlines() for line in preserved)
    assert other in output
    # In particular, an intentional resistor must not group A and B into one conductor.
    assert capacitors(grounded) == {('A', 'B'): 7e-12, ('A', 'G'): 3e-15, ('B', 'G'): 5e-15}


@pytest.mark.parametrize('boundary', ['.global F', 'X1 F G opaque_model', 'M1 F G G G model', 'Cintent F G 1p'])
def test_retained_terminal_or_global_keeps_its_conductor(tmp_path: Path, boundary: str):
    source = f'.subckt dut A G\n{boundary}\nCext_1 A F 2f\nCext_2 F G 2f\n.ends\n'
    _, grounded = transform(tmp_path, source)
    expected = 4e-15 + (1e-12 if boundary.startswith('Cintent') else 0)
    assert capacitors(grounded)[('A', 'G')] == 2e-15
    assert capacitors(grounded)[('F', 'G')] == pytest.approx(expected, rel=1e-14)


def test_keep_and_case_folding_do_not_change_node_spelling(tmp_path: Path):
    source = '.subckt dut A G\ncext_1 a Float 2f\nCEXT_2 FLOAT g 2f\n.ends\n'
    _, grounded = transform(tmp_path, source, GroundingOptions('g', keep_nodes=('FLOAT',)))
    assert capacitors(grounded) == {('Float', 'g'): 4e-15, ('a', 'g'): 2e-15}


def test_explicit_map_keeps_disconnected_nodes_on_observable_conductor(tmp_path: Path):
    source = '.subckt dut A G\nCext_1 A1 F 2f\nCext_2 F A2 2f\nCext_3 A2 G 3f\n.ends\n'
    options = GroundingOptions('G', net_by_node={'a1': 'A', 'a2': 'a'})
    _, grounded = transform(tmp_path, source, options)
    assert capacitors(grounded) == {('A1', 'A2'): 1e-15, ('A2', 'G'): 3e-15}


def test_distributed_reference_capacitance_stays_at_original_node(tmp_path: Path):
    source = TWO_NETS.replace('Cext_2 A G 1f', 'Cext_2 A G1 1f\nRext_1 G G1 10')
    _, grounded = transform(tmp_path, source)
    assert capacitors(grounded) == {('A', 'G'): 2e-15, ('A', 'G1'): 1e-15, ('B', 'G'): 5e-15}


@pytest.mark.parametrize('reference,alias', [('0', 'gnd'), ('gnd', '0'), ('GND', '0')])
def test_spice_ground_alias_keeps_distributed_reference_path(tmp_path: Path, reference: str, alias: str):
    # The alias and the requested reference are the same SPICE node. Moving this
    # capacitor to the ideal reference would bypass its series resistance.
    source = f'.subckt dut A\nRext_1 {alias} G1 1Meg\nCext_1 A G1 1f\n.ends\n'
    _, grounded = transform(tmp_path, source, GroundingOptions(reference))
    assert capacitors(grounded) == {('A', 'G1'): 1e-15}


def test_net_map_cannot_assign_distinct_conductors_to_ground_aliases(tmp_path: Path):
    source = '.subckt dut A\nCext_1 A gnd 1f\nCext_2 A 0 1f\n.ends\n'
    with pytest.raises(ValueError, match='Conflicting conductor'):
        transform(tmp_path, source, GroundingOptions('0', net_by_node={'0': 'one', 'gnd': 'two'}))


@pytest.mark.parametrize('reference_declaration', ['.global G\n', '.subckt dut A B G\n'])
def test_reference_can_be_declared_without_an_existing_capacitor(tmp_path: Path, reference_declaration: str):
    source = reference_declaration + 'Cext_1 A B 2f\n'
    is_subckt = reference_declaration.startswith('.subckt')
    if is_subckt:
        source += '.ends\n'
    options = GroundingOptions('G', keep_nodes=('A', 'B'))
    _, grounded = transform(tmp_path, source, options)
    assert capacitors(grounded, 'dut' if is_subckt else None) == {('A', 'G'): 2e-15, ('B', 'G'): 2e-15}


def test_custom_selectors_are_explicit_and_leave_unselected_devices(tmp_path: Path):
    source = '.subckt dut A B G\nCx_1 A B 2f\nCx_2 A A1 1f\nRw_1 A A1 5\nCext_kept B G 9f\n.ends\n'
    _, grounded = transform(tmp_path, source, GroundingOptions('G', ('CX_*',), ('RW_*',)))
    assert capacitors(grounded) == {('A', 'A1'): 1e-15, ('A', 'G'): 2e-15, ('B', 'G'): 11e-15}
    assert 'Cext_kept B G 9f' in grounded.read_text(encoding='utf-8')


@pytest.mark.parametrize('source,options,message', [
    (TWO_NETS, GroundingOptions('missing'), 'Unknown reference'),
    (TWO_NETS, GroundingOptions('G', keep_nodes=('missing',)), 'Unknown reference/kept'),
    (TWO_NETS, GroundingOptions('G', net_by_node={'missing': 'A'}), 'Unknown mapped node'),
    (TWO_NETS.replace('.ends', 'Rext_1 A B 1\n.ends'),
     GroundingOptions('G', net_by_node={'A': 'left', 'B': 'right'}), 'Conflicting conductor'),
    (TWO_NETS, GroundingOptions('G', net_by_node={'A': 'B', 'B': 'C'}), 'different conductor'),
    (TWO_NETS + TWO_NETS.replace('dut', 'other'), GroundingOptions('G'), 'Expected one scope'),
    (TWO_NETS + '.subckt DUT X Y\n.ends\n', GroundingOptions('G'), 'Ambiguous repeated'),
    (TWO_NETS, GroundingOptions('G', cell_name='missing'), 'Available scopes'),
    ('* empty\n', GroundingOptions('0'), 'Expected one scope'),
])
def test_invalid_context_never_overwrites_existing_output(tmp_path: Path, source: str,
                                                          options: GroundingOptions, message: str):
    original = tmp_path / 'in.spice'
    output = tmp_path / 'out.spice'
    original.write_text(source, encoding='utf-8')
    output.write_text('existing output\n', encoding='utf-8')
    with pytest.raises(ValueError, match=message):
        ground_spice_netlist(str(original), str(output), options)
    assert output.read_text(encoding='utf-8') == 'existing output\n'


@pytest.mark.parametrize('element', ['Cext_1 A G -1f', 'Cext_1 A G nan', 'Cext_1 A G inf',
                                     'Cext_1 A G {value}', 'Cext_1 A G 1f m=2',
                                     'Rext_1 A B 0', 'Rext_1 A B -1', 'Rext_1 A B 1e-323'])
def test_invalid_or_symbolic_selected_elements_fail_closed(tmp_path: Path, element: str):
    original = tmp_path / 'in.spice'
    original.write_text('.subckt dut A B G\n' + element + '\nCext_2 A B 1f\n.ends\n', encoding='utf-8')
    with pytest.raises(CouplingPolicyError, match='selected element'):
        ground_spice_netlist(str(original), str(tmp_path / 'out.spice'), GroundingOptions('G'))
    assert not (tmp_path / 'out.spice').exists()


def test_floating_resistance_is_not_merged_or_grounded(tmp_path: Path):
    source = '.subckt dut A G\nCext_1 A F1 2f\nRext_1 F1 F2 1Meg\nCext_2 F2 G 2f\n.ends\n'
    original = tmp_path / 'in.spice'
    original.write_text(source, encoding='utf-8')
    with pytest.raises(CouplingPolicyError, match='floating resistive nets'):
        ground_spice_netlist(str(original), str(tmp_path / 'out.spice'), GroundingOptions('G'))
    assert not (tmp_path / 'out.spice').exists()


def test_zero_self_and_single_boundary_floating_capacitance_add_no_load(tmp_path: Path):
    source = '.subckt dut A G\nCext_1 A A 1f\nCext_2 A G 0\nCext_3 A F 1f\n.ends\n'
    _, grounded = transform(tmp_path, source)
    assert capacitors(grounded) == {}


def test_grounding_preserves_crlf_comments_and_continued_resistor(tmp_path: Path):
    source = '.subckt dut A G\r\n* comment\r\nRext_1 A A1\r\n+ 1k\r\nCext_1 A1 G\r\n+ 2f\r\n.ends\r\n'
    _, grounded = transform(tmp_path, source)
    raw = grounded.read_bytes()
    assert b'Rext_1 A A1\r\n+ 1k\r\n' in raw
    assert b'* comment\r\n' in raw
    assert b'\n' not in raw.replace(b'\r\n', b'')


@pytest.mark.parametrize('invalid', [dict(reference=''), dict(reference='two nodes'),
                                    dict(capacitor_patterns=('R*',)), dict(resistor_patterns=('C*',)),
                                    dict(capacitor_patterns=True), dict(keep_nodes='A'),
                                    dict(top_level='false'), dict(top_level=True, cell_name='dut'),
                                    dict(net_by_node={'A': 1}), dict(net_by_node={'A': 'x', 'a': 'x'})])
def test_invalid_options_are_rejected_without_io(invalid: Dict):
    with pytest.raises(ValueError):
        GroundingOptions(**{'reference': 'G', **invalid})


def test_cli_defaults_metadata_and_format_only_imports(tmp_path: Path):
    original = tmp_path / 'in.spice'
    original.write_text(TWO_NETS, encoding='utf-8')
    code, output = run_cli(NetlistCLI().main, ['netlist', 'ground', str(original), '--reference', 'G'])
    assert code == 0, output
    assert (tmp_path / 'in_grounded.spice').is_file()
    assert_netlist_cli_loads_neither_klayout_nor_protobuf(['netlist', 'ground', str(original), '--reference', 'G'])
    assert_netlist_cli_loads_neither_klayout_nor_protobuf(['netlist', 'help', 'ground'])
    mapping = tmp_path / 'nodes.json'
    mapping.write_text(json.dumps({'A': 'signal', 'B': 'signal'}), encoding='utf-8')
    code, output = run_cli(NetlistCLI().main, ['netlist', 'ground', str(original), '--reference', 'G',
                                             '--net-map', str(mapping), '--cell', 'dut',
                                             '--out-netlist', str(tmp_path / 'new' / 'out.spice')])
    assert code == 0, output
    assert capacitors(tmp_path / 'new' / 'out.spice') == {('A', 'B'): 2e-15, ('A', 'G'): 1e-15, ('B', 'G'): 3e-15}


@pytest.mark.parametrize('mapping', ['[]', '{"A": "x", "A": "y"}', '{"A": "x", "a": "y"}', '{'])
def test_cli_bad_metadata_is_a_usage_error_before_netlist_read(tmp_path: Path, mapping: str):
    path = tmp_path / 'map.json'
    path.write_text(mapping, encoding='utf-8')
    code, output = run_cli(NetlistCLI().main, ['netlist', 'ground', 'missing.spice', '--reference', 'G', '--net-map', str(path)])
    assert code == 2, output
    assert 'No such file' not in output


def test_cli_unsupported_network_has_diagnostic_exit_and_no_output(tmp_path: Path):
    path = tmp_path / 'in.spice'
    path.write_text('.subckt dut A G\nCext_1 A F 1f\nRext_1 F F1 2\n.ends\n', encoding='utf-8')
    code, output = run_cli(NetlistCLI().main, ['netlist', 'ground', str(path), '--reference', 'G'])
    assert code == 1, output
    assert 'floating resistive' in output
    assert not (tmp_path / 'in_grounded.spice').exists()


def test_input_output_aliases_are_rejected(tmp_path: Path):
    original = tmp_path / 'in.spice'
    original.write_text(TWO_NETS, encoding='utf-8')
    with pytest.raises(ValueError, match='overwrite'):
        ground_spice_netlist(str(original), str(original), GroundingOptions('G'))
    assert original.read_text(encoding='utf-8') == TWO_NETS


def test_top_level_selection_preserves_subcircuits(tmp_path: Path):
    source = '* top-level deck\nCext_top A B 2f\n' + TWO_NETS
    _, grounded = transform(tmp_path, source, GroundingOptions('0', top_level=True, keep_nodes=('A', 'B')))
    assert TWO_NETS in grounded.read_text(encoding='utf-8')
    assert capacitors(grounded, None) == {('0', 'A'): 2e-15, ('0', 'B'): 2e-15}


SIMULATORS = [pytest.param(ngspice_port_admittance, marks=requires_ngspice, id='ngspice'),
              pytest.param(xyce_port_admittance, marks=requires_xyce, id='Xyce'),
              pytest.param(vacask_port_admittance, marks=requires_vacask, id='VACASK')]


@pytest.mark.slow
@pytest.mark.parametrize('simulator', SIMULATORS)
def test_spice_ground_alias_retains_series_rc_admittance(tmp_path: Path, simulator: Callable):
    # Write the common node-0 spelling for all simulators. The grounding API
    # accepts ngspice's gnd alias as the reference without changing the circuit.
    source = '.subckt dut A\nRext_1 0 G1 1Meg\nCext_1 A G1 1f\n.ends\n'
    _, grounded = transform(tmp_path, source, GroundingOptions('gnd'))
    frequencies, matrix = simulator(str(grounded), 'dut', ['A'], (3, 10), str(tmp_path))
    admittance = 1j * math.tau * frequencies * 1e-15
    expected = admittance / (1 + 1e6 * admittance)
    np.testing.assert_allclose(matrix[:, 0, 0], expected, rtol=5e-6, atol=0)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', SIMULATORS)
@pytest.mark.parametrize('distributed', [False, True])
def test_written_grounding_retains_floating_series_loading_and_intra_net_pole(
        tmp_path: Path, simulator: Callable, distributed: bool):
    # This independently derived admittance changes if floating metal is grounded
    # first or if its induced intra-net C is moved away from the wire resistor.
    if distributed:
        source = '.subckt dut A G\nRext_1 A A1 1Meg\nCext_1 A F 2f\nCext_2 F A1 2f\nCext_3 A1 G 3f\n.ends\n'
    else:
        source = '.subckt dut A G\nCext_1 A F 2f\nCext_2 F G 2f\n.ends\n'
    _, grounded = transform(tmp_path, source)
    frequencies, after = simulator(str(grounded), 'dut', ['A', 'G'], (3, 10), str(tmp_path))
    omega = math.tau * frequencies
    if distributed:
        between = 1e-6 + 1j * omega * 1e-15
        shunt = 1j * omega * 3e-15
        expected = between * shunt / (between + shunt)
    else:
        expected = 1j * omega * 1e-15
    # The ideal floating input has no unique DC operating point. The exact
    # two-terminal admittance is an independent reference for all simulators.
    matrix = expected[:, None, None] * np.array([[1, -1], [-1, 1]])
    np.testing.assert_allclose(after, matrix, rtol=5e-6, atol=0)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', SIMULATORS)
def test_grounded_coupling_preserves_nodal_loads_and_removes_transfer(tmp_path: Path, simulator: Callable):
    original, grounded = transform(tmp_path, TWO_NETS)
    frequencies, before = simulator(str(original), 'dut', ['A', 'B', 'G'], (3, 10), str(tmp_path))
    _, after = simulator(str(grounded), 'dut', ['A', 'B', 'G'], (3, 10), str(tmp_path))
    omega = math.tau * frequencies
    np.testing.assert_allclose(after[:, 0, 0], 1j * omega * 3e-15, rtol=5e-6, atol=0)
    np.testing.assert_allclose(after[:, 1, 1], 1j * omega * 5e-15, rtol=5e-6, atol=0)
    np.testing.assert_allclose(after[:, :2, :2].diagonal(axis1=1, axis2=2),
                               before[:, :2, :2].diagonal(axis1=1, axis2=2), rtol=5e-6, atol=0)
    assert np.all(np.abs(after[:, 0, 1]) < 1e-12 * np.abs(after[:, 0, 0]))
    assert np.all(np.abs(before[:, 0, 1]) > 0)


@pytest.mark.parametrize('capacitance', [1e-100, 1e-30, 1e-15, 1e100, 1e308])
def test_written_positive_capacitance_has_no_threshold(tmp_path: Path, capacitance: float):
    source = f'.subckt dut A B G\nCext_1 A B {capacitance}\n.ends\n'
    _, grounded = transform(tmp_path, source)
    assert capacitors(grounded) == {('A', 'G'): capacitance, ('B', 'G'): capacitance}


def test_accumulated_overflow_does_not_write_output(tmp_path: Path):
    original = tmp_path / 'in.spice'
    original.write_text('.subckt dut A B C G\nCext_1 A B 1e308\nCext_2 A C 1e308\n.ends\n', encoding='utf-8')
    with pytest.raises(CouplingPolicyError, match='finite numeric range'):
        ground_spice_netlist(str(original), str(tmp_path / 'out.spice'), GroundingOptions('G'))
    assert not (tmp_path / 'out.spice').exists()


@pytest.mark.parametrize('degree', [63, 64, 65])
def test_written_floating_degree_limit_fails_explicitly_above_boundary(tmp_path: Path, degree: int):
    # A degree beyond the bounded exact elimination must not silently ground F.
    ports = ' '.join(f'A{i}' for i in range(degree))
    lines = [f'.subckt dut {ports} G']
    lines += [f'Cext_{i} A{i} F 1f' for i in range(degree)]
    original = tmp_path / 'in.spice'
    original.write_text('\n'.join([*lines, '.ends', '']), encoding='utf-8')
    output = tmp_path / 'out.spice'
    if degree == 65:
        with pytest.raises(CouplingPolicyError, match='64-neighbor limit'):
            ground_spice_netlist(str(original), str(output), GroundingOptions('G'))
        assert not output.exists()
    else:
        result = ground_spice_netlist(str(original), str(output), GroundingOptions('G'))
        assert result.floating_nodes == ['F']
        assert len(capacitors(output)) == degree
        assert all(value == pytest.approx((degree - 1) / degree * 1e-15, rel=5e-6, abs=0)
                   for value in capacitors(output).values())
