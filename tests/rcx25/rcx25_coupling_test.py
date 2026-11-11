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

"""Written netlists and simulations of deliberate capacitance approximations."""

import math
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple
from unittest import mock

import allure
import numpy as np
import pytest

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.netlist.netlist_format import NetlistFormat
from klayout_pex.netlist.netlist_grounding import GroundingOptions, ground_spice_netlist
from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist, SpiceScope
from klayout_pex.netlist.spice_reader import SpiceReader
from klayout_pex.rcx25.pex_mode import PEXMode
from klayout_pex.rcx25.coupling import CouplingPolicy, apply_coupling_policy
from klayout_pex.rcx25.extraction_results import ExtractionSummary, NetCoupleKey
from tests.common.cli_runner import run_cli
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.common.rc_networks import build_network, spice_subcircuit, write
from tests.common.vacask import assert_same_nets_and_values, read_ascii_raw, requires_vacask, run_vacask
from tests.rcx25.rcx25_simulation_test import SIMULATORS
from tests.rcx25.rcx25_test_helpers import RCX25Extraction

pytestmark = [allure.parent_suite('kpex/2.5D Capacitance Modes'), allure.tag('PEX', '2.5D', 'Capacitance Modes')]
PDK = PDKTestConfig(PDKName.SKY130A)
PLATES = 'overlap_plates_100um_x_100um_li1_m1.gds.gz'


def extract(tmp_path: Path, mode: PEXMode, arguments: Sequence[str] = (),
             design: str = PLATES, blackbox: bool = True) -> KpexCLI:
    extraction = RCX25Extraction(PDK, mode, blackbox)
    return extraction.run_kpex('test_patterns', design,
                               extra_args=['--out-dir', str(tmp_path), *arguments])


def network_of(cli: KpexCLI) -> SpiceScope:
    return next(scope for scope in SpiceRCNetlist.read(cli.rcx25_netlist_paths[NetlistFormat.SPICE]).scopes
                if scope.name is not None)


def branches(cli: KpexCLI) -> Dict[Tuple[str, str], Tuple[float, float]]:
    network = network_of(cli).network
    return {tuple(sorted((network.name(a), network.name(b)))): (branch.conductance, branch.capacitance)
            for a, b, branch in network.edges()}


@pytest.mark.parametrize('arguments,expected', [
    ([], {('LOWER', 'sky130_gnd'): 684.225, ('UPPER', 'sky130_gnd'): 507.317}),
    (['--coupling', 'grounded'], {('LOWER', 'sky130_gnd'): 684.225, ('UPPER', 'sky130_gnd'): 507.317}),
])
def test_two_plate_written_loads_ground_coupling_with_full_value(tmp_path: Path, arguments: Sequence[str],
                                                          expected: Dict[Tuple[str, str], float]):
    mode = PEXMode.CC if arguments else PEXMode.C
    cli = extract(tmp_path, mode, arguments, blackbox=False)
    # The released two-plate fixture has 301.287 fF between LOWER and UPPER,
    # 382.938 fF from LOWER to substrate and 206.030 fF from UPPER to substrate.
    # These independent expected totals catch a discarded or half-counted pair.
    obtained = {names: value[1] * 1e15 for names, value in branches(cli).items()}
    assert obtained == pytest.approx(expected, abs=0.002, rel=0)
    # Geometry remains physically coupled for the report and diagnostic observers.
    raw = cli.rcx25_extraction_results.summarize()
    assert any({pair.net1, pair.net2} == {'LOWER', 'UPPER'} for pair in raw.capacitances)


def test_explicit_coupled_policy_preserves_default_output(tmp_path: Path):
    default = extract(tmp_path / 'default', PEXMode.CC)
    explicit = extract(tmp_path / 'explicit', PEXMode.CC, ['--coupling', 'coupled'])
    assert branches(explicit) == branches(default)
    assert Path(explicit.rcx25_extracted_csv_path).read_text(encoding='utf-8') == \
           Path(default.rcx25_extracted_csv_path).read_text(encoding='utf-8')


@pytest.mark.parametrize('policy', ['grounded'])
def test_rc_policy_preserves_resistors_and_node_names(tmp_path: Path, policy: str):
    design = 'r_wire_voltage_divider_li1.gds.gz'
    coupled = extract(tmp_path / 'coupled', PEXMode.RC, design=design)
    uncoupled = extract(tmp_path / policy, PEXMode.RC, ['--coupling', policy], design=design)
    original_resistors = {names: values[0] for names, values in branches(coupled).items() if values[0]}
    written_resistors = {names: values[0] for names, values in branches(uncoupled).items() if values[0]}
    assert original_resistors
    assert written_resistors == original_resistors
    assert not uncoupled.rcx25_netlist_problems


def test_grounded_output_converts_to_vacask_with_same_nets_and_values(tmp_path: Path):
    cli = extract(tmp_path, PEXMode.C, ['--netlist-format', 'vacask'])
    paths = cli.rcx25_netlist_paths
    assert_same_nets_and_values(SpiceReader().read(paths[NetlistFormat.SPICE]),
                               Path(paths[NetlistFormat.VACASK]).read_text(encoding='utf-8'), rel_tol=5e-6)


@pytest.mark.parametrize('policy', ['grounded'])
def test_whiteboxed_capacitor_is_rejected_instead_of_destroying_its_coupling(tmp_path: Path, policy: str):
    extraction = RCX25Extraction(PDK, PEXMode.CC, blackbox=False)
    design = 'cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz'
    code, output = run_cli(KpexCLI().main, [
        'kpex', 'extract', '--pdk', PDK.name, '--2.5D', '--coupling', policy,
        '--lvsdb', extraction.lvsdb_fixture('test_patterns', design).up_to_date_lvsdb_path(),
        '--out-dir', str(tmp_path)])
    assert code == 1, output
    assert 'use --blackbox y' in ' '.join(output.split()), output
    assert not list(tmp_path.rglob('*_k25d_pex_netlist.spice'))


def test_blackboxed_capacitor_keeps_model_and_both_terminal_nets(tmp_path: Path):
    design = 'cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz'
    coupled = extract(tmp_path / 'coupled', PEXMode.CC, design=design)
    grounded = extract(tmp_path / 'grounded', PEXMode.C, design=design)
    # Model instances are retained verbatim while only PEX_CAP contributions change.
    def model_lines(cli: KpexCLI) -> List[str]:
        return [line for line in Path(cli.rcx25_netlist_paths[NetlistFormat.SPICE]).read_text(encoding='utf-8').splitlines()
                if line.startswith('X')]
    assert model_lines(coupled)
    assert model_lines(grounded) == model_lines(coupled)


@pytest.mark.slow
@pytest.mark.parametrize('simulator', SIMULATORS)
def test_simulator_sees_preserved_driving_load_but_no_mutual_coupling(tmp_path: Path, simulator: Callable):
    matrices = {}
    for mode in (PEXMode.CC, PEXMode.C):
        directory = tmp_path / mode.value
        directory.mkdir()
        cli = extract(directory, mode)
        scope = network_of(cli)
        frequencies, matrix = simulator(cli.rcx25_netlist_paths[NetlistFormat.SPICE],
                                         scope.name, scope.ports, (3, 9), str(directory))
        matrices[mode] = matrix
        a, b = scope.ports.index('LOWER'), scope.ports.index('UPPER')
    before, after = matrices[PEXMode.CC], matrices[PEXMode.C]
    # The six-significant-digit SPICE serialization limits agreement. A femtofarad
    # absolute tolerance would hide the behavior, so compare relative current.
    np.testing.assert_allclose(after[:, a, a], before[:, a, a], rtol=5e-6, atol=0)
    np.testing.assert_allclose(after[:, b, b], before[:, b, b], rtol=5e-6, atol=0)
    assert np.all(abs(before[:, a, b]) > 0)
    assert np.all(abs(after[:, a, b]) < 1e-12 * abs(after[:, a, a]))


def test_c_mode_default_whitebox_reports_how_to_preserve_capacitor_model(tmp_path: Path):
    extraction = RCX25Extraction(PDK, PEXMode.C, blackbox=False)
    design = 'cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz'
    code, output = run_cli(KpexCLI().main, [
        'kpex', 'extract', '--pdk', PDK.name, '--2.5D', '--mode', 'C',
        '--lvsdb', extraction.lvsdb_fixture('test_patterns', design).up_to_date_lvsdb_path(),
        '--out-dir', str(tmp_path)])
    assert code == 1, output
    assert 'use --blackbox y' in ' '.join(output.split()), output
    assert not list(tmp_path.rglob('*_k25d_pex_netlist.spice'))


@pytest.mark.slow
def test_grounded_rc_reduction_checks_the_actual_approximated_network(tmp_path: Path):
    cli = extract(tmp_path, PEXMode.RC,
                   ['--coupling', 'grounded', '--reduce', 'floating',
                    '--check-frequency-range', '1k', '1G'],
                   design='r_wire_voltage_divider_li1.gds.gz')
    assert Path(cli.rcx25_reduced_netlist_path).is_file()
    assert not cli.run_result.check_problems


@pytest.mark.slow
def test_device_capacitance_check_keeps_coupled_geometry_in_c_mode(tmp_path: Path):
    from tests.common.device_capacitance import DESIGN, PDK_CONFIG
    extraction = RCX25Extraction(PDK_CONFIG, PEXMode.C, blackbox=True)
    cli = extraction.run_kpex('test_patterns', DESIGN, extra_args=[
        '--gds', PDK_CONFIG.gds_path('test_patterns', DESIGN), '--check-device-caps',
        '--out-dir', str(tmp_path)])
    record, = cli.run_result.device_capacitance_checks
    assert record['extracted_capacitance_f'] == pytest.approx(235.9900152180e-15, rel=1e-12, abs=0)
    assert record['ratio'] == pytest.approx(235.9900152180 / 228.75, rel=1e-12)


def vacask_currents(tmp_path: Path, cli: KpexCLI, driven_port: str, reference_port: str) -> Dict[str, List[complex]]:
    scope = network_of(cli)
    assert driven_port != reference_port and {driven_port, reference_port} <= set(scope.ports)
    assert len(scope.ports) <= 3, 'This bench has only one optional quiet terminal'
    circuit_path = cli.rcx25_netlist_paths[NetlistFormat.VACASK]
    nodes = ' '.join('0' if port == reference_port else 'a' if port == driven_port else 'b' for port in scope.ports)
    deck = tmp_path / 'grounded.sim'
    deck.write_text(f"""Grounded capacitance load
include "{circuit_path}"
model vsource vsource
va (a 0) vsource dc=0 mag=1
vb (b 0) vsource dc=0 mag=0
x1 ({nodes}) {scope.name}
control
  options rawfile="ascii"
  analysis op1 op
  analysis ac1 ac values=[1e3, 1e6, 1e9]
endc
""", encoding='utf-8')
    run_vacask(str(deck))
    return read_ascii_raw(str(tmp_path / 'ac1.raw'))


@pytest.mark.slow
@requires_vacask
def test_grounded_loading_in_vacask(tmp_path: Path):
    cli = extract(tmp_path, PEXMode.C, ['--netlist-format', 'vacask'])
    values = vacask_currents(tmp_path, cli, 'LOWER', 'sky130_gnd')
    for frequency, driven, quiet in zip(values['frequency'], values['va:flow(br)'], values['vb:flow(br)']):
        expected = -1j * math.tau * frequency.real * 684.225e-15
        assert driven == pytest.approx(expected, rel=5e-6, abs=0)
        assert abs(quiet) < 1e-12 * abs(driven)


@pytest.mark.parametrize('mode,arguments', [
    (PEXMode.C, []), (PEXMode.CC, ['--coupling', 'grounded']),
])
def test_multi_engine_run_changes_only_analytical_capacitance(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: PEXMode, arguments: Sequence[str]):
    # Keep CLI validation, MAGIC script generation and analytical extraction real.
    # Only external solver execution and fresh LVS are replaced by the fixture.
    executable = tmp_path / 'external-tool'
    executable.touch()
    magicrc = tmp_path / 'magicrc'
    magicrc.write_text('# unused test configuration\n', encoding='utf-8')
    monkeypatch.setenv('KPEX_MAGIC_EXE', str(executable))
    monkeypatch.setenv('KPEX_KLAYOUT_EXE', str(executable))
    extraction = RCX25Extraction(PDK, mode, blackbox=True)
    lvsdb = extraction.read_lvsdb('test_patterns', PLATES)
    cli = KpexCLI()
    with mock.patch.object(cli, 'create_lvsdb', return_value=lvsdb), \
            mock.patch('klayout_pex.kpex_cli.run_magic') as run_magic, \
            mock.patch('klayout_pex.kpex_cli.parse_magic_pex_run'):
        code, output = run_cli(cli.main, [
            'kpex', 'extract', '--pdk', PDK.name, '--gds', PDK.gds_path('test_patterns', PLATES),
            '--2.5D', '--mode', mode.value, *arguments, '--blackbox', 'y', '--halo', '10000', '--scale', 'n',
            '--magic', '--magicrc', str(magicrc), '--magic-analyze', 'n',
            '--tool-version-checks', 'off', '--out-dir', str(tmp_path / 'output')])
    assert code == 0, output
    run_magic.assert_called_once()
    script = Path(run_magic.call_args.kwargs['script_path']).read_text(encoding='utf-8')
    assert 'extract do capacitance' in script
    assert 'extract do coupling' in script
    assert 'extract no resistance' in script
    assert not any(set(pair) == {'LOWER', 'UPPER'} for pair in branches(cli))
    expected_lower = 684.225
    assert branches(cli)[('LOWER', 'sky130_gnd')][1] * 1e15 == pytest.approx(expected_lower, abs=0.002)


@pytest.mark.parametrize('mode', [PEXMode.C, PEXMode.RC])
def test_unnamed_layout_float_is_eliminated_and_reported(tmp_path: Path, mode: PEXMode):
    from tests.rcx25.rcx25_exclusion_test import Extraction, ExclusionMarkerMode
    with mock.patch('klayout_pex.kpex_cli.warning') as warning:
        cli = Extraction('exclusion_floating_plate_neighbor', mode).run(
            ExclusionMarkerMode.IGNORE, '--out-dir', str(tmp_path), '--coupling', 'grounded')
    # Independent series calculation from the released coupled fixture's values:
    # N--2.12476fF--unnamed--6.7108fF--sub!, plus N--3.56073fF--sub!.
    expected = (3.56073 + 2.12476 * 6.7108 / (2.12476 + 6.7108)) * 1e-15
    assert branches(cli) == {('N', 'sub!'): (0, pytest.approx(expected, rel=5e-6, abs=0))}
    assert network_of(cli).ports == ['N', 'sub!']
    messages = [call.args[0] for call in warning.call_args_list]
    assert any('Eliminated 1 floating capacitance nets' in message and '$3' in message for message in messages)
    assert not any('simulators' in message for message in messages)
    assert not cli.rcx25_netlist_problems


@pytest.mark.parametrize('mode', [PEXMode.C, PEXMode.RC])
def test_explicitly_excluded_floating_metal_keeps_exclusion_contract(tmp_path: Path, mode: PEXMode):
    from tests.rcx25.rcx25_exclusion_test import Extraction, ExclusionMarkerMode
    cli = Extraction('exclusion_floating_plate_neighbor', mode).run(
        ExclusionMarkerMode.TIE, '--out-dir', str(tmp_path), '--coupling', 'grounded')
    assert branches(cli) == {('N', 'sub!'): (0, pytest.approx(5.68549e-15, rel=5e-6, abs=0))}
    assert not cli.rcx25_netlist_problems


def test_floating_resistive_layout_reports_explicit_remedy_without_netlist(tmp_path: Path):
    extraction = RCX25Extraction(PDK, PEXMode.RC, blackbox=True)
    design = 'r_ptap_li1_m1_two_wires.gds.gz'
    code, output = run_cli(KpexCLI().main, [
        'kpex', 'extract', '--pdk', PDK.name, '--2.5D', '--mode', 'RC', '--coupling', 'grounded',
        '--blackbox', 'y', '--lvsdb', extraction.lvsdb_fixture('test_patterns', design).up_to_date_lvsdb_path(),
        '--out-dir', str(tmp_path)])
    assert code == 1, output
    message = ' '.join(output.split())
    assert 'floating resistive nets exactly at every frequency' in message, output
    assert '--coupling coupled' in message and '--mode C' in message, output
    assert not list(tmp_path.rglob('*_k25d_pex_netlist.spice'))


def test_replaced_device_block_keeps_external_ports_in_grounded_output(tmp_path: Path):
    from tests.rcx25.rcx25_exclusion_test import Extraction, ExclusionMarkerMode, devices_of
    outputs = []
    for mode in (PEXMode.CC, PEXMode.C):
        outputs.append(Extraction('cut_cell_of_devices', mode, blackbox=True).run(
            ExclusionMarkerMode.IGNORE, '--cut', 'block', '--out-dir', str(tmp_path / mode.value)))
    assert devices_of(outputs[0]) == devices_of(outputs[1]) == []
    assert network_of(outputs[0]).ports
    assert network_of(outputs[0]).ports == network_of(outputs[1]).ports
    assert not outputs[1].rcx25_netlist_problems


def write_summary_netlist(path: Path, summary: ExtractionSummary) -> str:
    branches = [(pair.net1, pair.net2, 1 / value, 0) for pair, value in summary.resistances.items()]
    branches += [(pair.net1, pair.net2, 0, value * 1e-15) for pair, value in summary.capacitances.items()]
    network = build_network(branches, protected=['A', 'G'])
    return write(str(path.parent), path.name, spice_subcircuit(network, 'floating', ['A', 'G']))


@pytest.mark.slow
@pytest.mark.parametrize('simulator', SIMULATORS)
@pytest.mark.parametrize('distributed_rc', [False, True])
def test_floating_series_loading_and_intra_net_rc_dynamics_in_simulator(
        tmp_path: Path, simulator: Callable, distributed_rc: bool):
    if distributed_rc:
        # The float bridges two points of ONE resistive net. Its equivalent 1 fF
        # must stay across the resistor; grounding it changes the high-frequency pole.
        original = ExtractionSummary({NetCoupleKey('A', 'F'): 2, NetCoupleKey('A1', 'F'): 2,
                                      NetCoupleKey('A1', 'G'): 3},
                                     {NetCoupleKey('A', 'A1'): 1e6}, net_by_node={'A1': 'A'})
    else:
        original = ExtractionSummary({NetCoupleKey('A', 'F'): 2, NetCoupleKey('F', 'G'): 2}, {})
    grounded = apply_coupling_policy(original, CouplingPolicy.GROUNDED, 'G', floating_net_names={'F'})
    matrices = []
    for label, summary in [('original', original), ('grounded', grounded)]:
        path = write_summary_netlist(tmp_path / f'{label}.spice', summary)
        frequencies, matrix = simulator(path, 'floating', ['A', 'G'], (3, 10), str(tmp_path))
        matrices.append(matrix)
    np.testing.assert_allclose(matrices[1], matrices[0], rtol=5e-6, atol=0)
    omega = math.tau * frequencies
    if distributed_rc:
        between = 1e-6 + 1j * omega * 1e-15
        to_reference = 1j * omega * 3e-15
        expected = between * to_reference / (between + to_reference)
    else:
        expected = 1j * omega * 1e-15
    np.testing.assert_allclose(matrices[1][:, 0, 0], expected, rtol=5e-6, atol=0)
    assert grounded.resistances == original.resistances


@pytest.mark.slow
@pytest.mark.parametrize('simulator', SIMULATORS)
def test_unnamed_floating_layout_has_same_driving_response_after_elimination(tmp_path: Path, simulator: Callable):
    from tests.rcx25.rcx25_exclusion_test import Extraction, ExclusionMarkerMode
    matrices = []
    for mode in (PEXMode.CC, PEXMode.C):
        directory = tmp_path / mode.value
        cli = Extraction('exclusion_floating_plate_neighbor', mode).run(
            ExclusionMarkerMode.IGNORE, '--out-dir', str(directory))
        scope = network_of(cli)
        _, matrix = simulator(cli.rcx25_netlist_paths[NetlistFormat.SPICE], scope.name, scope.ports,
                               (3, 9), str(directory))
        matrices.append(matrix)
    np.testing.assert_allclose(matrices[1], matrices[0], rtol=5e-6, atol=0)


@pytest.mark.slow
@requires_vacask
def test_unnamed_floating_layout_loading_in_vacask(tmp_path: Path):
    from tests.rcx25.rcx25_exclusion_test import Extraction, ExclusionMarkerMode
    cli = Extraction('exclusion_floating_plate_neighbor', PEXMode.C).run(
        ExclusionMarkerMode.IGNORE, '--netlist-format', 'vacask', '--out-dir', str(tmp_path))
    values = vacask_currents(tmp_path, cli, 'N', 'sub!')
    capacitance = (3.56073 + 2.12476 * 6.7108 / (2.12476 + 6.7108)) * 1e-15
    for frequency, driven in zip(values['frequency'], values['va:flow(br)']):
        expected = -1j * math.tau * frequency.real * capacitance
        assert driven == pytest.approx(expected, rel=5e-6, abs=0)


@pytest.mark.parametrize('mode,design', [
    (PEXMode.CC, PLATES),
    (PEXMode.RC, 'r_wire_voltage_divider_li1.gds.gz'),
    (PEXMode.CC, 'cap_mim_m3_20um_x_20um_over_m2_wire.gds.gz'),
])
def test_standalone_grounding_matches_direct_extraction(tmp_path: Path, mode: PEXMode, design: str):
    coupled = extract(tmp_path / 'coupled', mode, design=design)
    direct = extract(tmp_path / 'direct', mode, ['--coupling', 'grounded'], design=design)
    path = tmp_path / 'postprocessed.spice'
    ground_spice_netlist(coupled.rcx25_netlist_paths[NetlistFormat.SPICE], str(path),
                        GroundingOptions('sky130_gnd'))
    network = next(scope.network for scope in SpiceRCNetlist.read(str(path)).scopes if scope.name is not None)
    obtained = {tuple(sorted((network.name(a), network.name(b)))): (branch.conductance, branch.capacitance)
                for a, b, branch in network.edges()}
    expected = branches(direct)
    assert obtained.keys() == expected.keys()
    for names, values in obtained.items():
        # Standalone input was already serialized to six significant digits.
        assert values == pytest.approx(expected[names], rel=1e-5, abs=0)
    original = Path(coupled.rcx25_netlist_paths[NetlistFormat.SPICE]).read_text(encoding='utf-8')
    rewritten = path.read_text(encoding='utf-8')
    for line in original.splitlines():
        if line.startswith(('X', 'R')):
            assert line in rewritten.splitlines()


def test_standalone_grounding_eliminates_real_layout_float(tmp_path: Path):
    from tests.rcx25.rcx25_exclusion_test import Extraction, ExclusionMarkerMode
    coupled = Extraction('exclusion_floating_plate_neighbor', PEXMode.CC).run(
        ExclusionMarkerMode.IGNORE, '--out-dir', str(tmp_path / 'coupled'))
    path = tmp_path / 'postprocessed.spice'
    result = ground_spice_netlist(coupled.rcx25_netlist_paths[NetlistFormat.SPICE], str(path),
                                  GroundingOptions('sub!'))
    assert len(result.floating_nodes) == 1
    network = next(scope.network for scope in SpiceRCNetlist.read(str(path)).scopes if scope.name is not None)
    values = [branch.capacitance for _, _, branch in network.edges()]
    expected = (3.56073 + 2.12476 * 6.7108 / (2.12476 + 6.7108)) * 1e-15
    assert values == [pytest.approx(expected, rel=5e-6, abs=0)]
