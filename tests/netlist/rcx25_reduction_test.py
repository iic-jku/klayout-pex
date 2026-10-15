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

"""``netlist reduce`` on the RC netlists KPEX writes (2.5D, RC mode) for small test patterns"""

from __future__ import annotations

import math
import os
from typing import *
from unittest import mock

import allure
import numpy as np
import pytest

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.netlist.netlist_cli import NetlistCLI
from klayout_pex.netlist.netlist_format import NetlistFormat
from klayout_pex.netlist.netlist_reduction import reduce_spice_netlist, reduced_netlist_path
from klayout_pex.netlist.rc_network import RCNetwork
from klayout_pex.netlist.rc_reduction import ReductionOptions
from klayout_pex.netlist.spice_rc_netlist import SpiceRCNetlist
from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.cli_runner import run_cli
from tests.common.rc_networks import (
    approx,
    capacitance_by_component_pair,
    port_admittance,
    protected_names,
    relative_admittance_error,
    resistive_components,
    schur_complement_conductances,
)
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction

parent_suite = "kpex/netlist reduce"
tags = ("Netlist", "Reduction", "PEX", "2.5D")

extraction = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.RC, blackbox=False)


def extract_and_reduce(gds_name: str, output_dir: str, options: ReductionOptions) \
        -> Tuple[str, str, RCNetwork, RCNetwork]:
    """
    :return: the paths of the KPEX netlist and the reduced one, and their (single) networks
    """
    _, csv_path = extraction.run_rcx25d_single_cell('test_patterns', gds_name)
    spice_path = f"{os.path.splitext(csv_path)[0]}.spice"
    reduced_path = os.path.join(output_dir, os.path.basename(spice_path).replace('.spice', '_reduced.spice'))
    assert reduce_spice_netlist(spice_path, reduced_path, options).output_path == reduced_path

    networks = []
    for path in (spice_path, reduced_path):
        scopes = [s for s in SpiceRCNetlist.read(path).scopes if s.network.nodes()]
        assert len(scopes) == 1
        networks.append(scopes[0].network)
    return spice_path, reduced_path, networks[0], networks[1]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_nfet_keeps_ports_and_device_terminals_dc_and_capacitances_between_nets(tmp_path):
    options = ReductionOptions()
    spice_path, reduced_path, original, reduced = extract_and_reduce('nfet_li1.gds.gz', str(tmp_path), options)

    # NOTE: the ports D, G, S, the substrate sky130_gnd, and the device terminals
    ports = protected_names(original)
    assert ports == ['D', 'D.P0.nsdm', 'G', 'G.P0.poly', 'S', 'S.P0.nsdm', 'sky130_gnd']
    assert protected_names(reduced) == ports
    assert reduced.connected_node_count() < original.connected_node_count()
    assert reduced.resistor_count() < original.resistor_count()

    with open(spice_path) as f:
        device_lines = [line for line in f.read().splitlines() if line.startswith(('X', '+'))]
    with open(reduced_path) as f:
        reduced_lines = f.read().splitlines()
    assert device_lines and all(line in reduced_lines for line in device_lines)

    # NOTE: DC is exact (resistances are written with 12 digits)
    np.testing.assert_allclose(schur_complement_conductances(reduced, ports),
                               schur_complement_conductances(original, ports), rtol=1e-9, atol=1e-15)

    # NOTE: no node is capacitor-only, so TICER alone runs, which keeps the capacitance between each pair of nets
    #       (to the 6 digits the capacitances are written with)
    nets = resistive_components(original)
    before = capacitance_by_component_pair(original, nets)
    after = capacitance_by_component_pair(reduced, nets)
    assert set(after) == set(before)
    for pair, capacitance in before.items():
        assert after[pair] == approx(capacitance, rel=1e-5), pair

    for frequency in (1e9, 1e10, 1e11):
        error = relative_admittance_error(original, reduced, ports, frequency)
        assert error <= 2 * math.pi * frequency * options.ticer_tau, frequency


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mom_capacitor_with_a_wire_beside_it(tmp_path):
    options = ReductionOptions()
    _, _, original, reduced = extract_and_reduce('cap_vpp_04p4x04p6_l1m1m2_noshield_m2_wire.gds.gz',
                                                 str(tmp_path), options)
    # NOTE: the wire X has a pin, hence a port, though no device
    ports = protected_names(original)
    assert ports == ['C0', 'C1', 'SUB', 'X']
    assert protected_names(reduced) == ports
    assert reduced.find_node('0') is None  # nothing tied
    assert reduced.connected_node_count() < original.connected_node_count() / 2

    # NOTE: the capacitances between the ports (Im Y / ω where the resistances don't matter yet) are kept,
    #       to the 6 digits the capacitances are written with
    frequency = 1e7
    capacitances = port_admittance(original, ports, frequency).imag
    reduced_capacitances = port_admittance(reduced, ports, frequency).imag
    assert np.linalg.norm(reduced_capacitances - capacitances) <= 1e-5 * np.linalg.norm(capacitances)

    for frequency in (1e9, 1e10, 1e11):
        error = relative_admittance_error(original, reduced, ports, frequency)
        assert error <= 2 * math.pi * frequency * options.ticer_tau, frequency


def read_text(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.parametrize('mode, reduce_args, options', [
    (PEXMode.RC, ['--reduce', 'ticer'], ReductionOptions()),
    (PEXMode.RC, ['--reduce', 'ticer', '--reduce_tau', '1f'], ReductionOptions(ticer_tau=1e-15)),
    (PEXMode.RC, ['--reduce', 'floating'], ReductionOptions(ticer=False)),
    (PEXMode.R, ['--reduce', 'ticer'], ReductionOptions()),
])
def test_kpex_reduce_writes_the_reduced_netlist_beside_the_netlist_and_to_out_netlist(
        mode: PEXMode, reduce_args: List[str], options: ReductionOptions, tmp_path):
    out_netlist = os.path.join(str(tmp_path), 'out.spice')
    cli = RCX25Extraction(pdk=extraction.pdk, pex_mode=mode, blackbox=False) \
        .run_kpex('test_patterns', 'nfet_li1.gds.gz', extra_args=[*reduce_args, '--out_netlist', out_netlist])

    spice_path = f"{os.path.splitext(cli.rcx25_extracted_csv_path)[0]}.spice"
    assert cli.rcx25_reduced_netlist_path == reduced_netlist_path(spice_path)

    # NOTE: the same reduction as 'netlist reduce' of the full netlist, which stays as it is
    expected_path = os.path.join(str(tmp_path), 'expected.spice')
    reduce_spice_netlist(spice_path, expected_path, options)
    assert read_text(cli.rcx25_reduced_netlist_path) == read_text(expected_path)
    assert read_text(out_netlist) == read_text(expected_path)
    assert read_text(spice_path) != read_text(expected_path)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_kpex_reduce_converts_the_reduced_netlist_to_vacask(tmp_path):
    out_netlist = os.path.join(str(tmp_path), 'out.inc')
    cli = extraction.run_kpex('test_patterns', 'nfet_li1.gds.gz',
                              extra_args=['--reduce', 'ticer', '--netlist_format', 'vacask',
                                          '--out_netlist', out_netlist])

    # NOTE: the same conversion as 'netlist convert' of the reduced netlist
    reduced_path = cli.rcx25_reduced_netlist_path
    vacask_path = cli.rcx25_netlist_paths[NetlistFormat.VACASK]
    assert vacask_path == os.path.splitext(reduced_path)[0] + '.inc'
    expected_path = os.path.join(str(tmp_path), os.path.basename(vacask_path))
    code, output = run_cli(NetlistCLI().main, ['netlist', 'convert', '--to', 'vacask', '--pdk', extraction.pdk.name,
                                               reduced_path, '-o', expected_path])
    assert code == 0, output
    assert read_text(vacask_path) == read_text(expected_path)
    assert read_text(out_netlist) == read_text(expected_path)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@pytest.mark.parametrize('out_option', ['--out_netlist', '--out_spice'])  # NOTE: --out_spice is deprecated
def test_kpex_without_reduce_writes_the_full_netlist_to_out_netlist(out_option: str, tmp_path):
    out_netlist = os.path.join(str(tmp_path), 'out.spice')
    cli = extraction.run_kpex('test_patterns', 'nfet_li1.gds.gz', extra_args=[out_option, out_netlist])

    assert cli.rcx25_reduced_netlist_path is None
    assert read_text(out_netlist) == read_text(f"{os.path.splitext(cli.rcx25_extracted_csv_path)[0]}.spice")


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('mode, reduce_args, message', [
    (PEXMode.CC, ['--reduce', 'ticer'],
     "--reduce ticer needs --mode R or RC, a CC netlist has no nodes to reduce"),
    (PEXMode.RC, ['--reduce', 'floating', '--reduce_tau', '1f'],
     "--reduce_tau applies to --reduce ticer only, not to --reduce floating"),
    (PEXMode.RC, ['--reduce_tau', '1f'],
     "--reduce_tau applies to --reduce ticer only, not to --reduce none"),
])
def test_kpex_reduce_option_errors(mode: PEXMode, reduce_args: List[str], message: str):
    # NOTE: found by the argument validation, before LVS
    invalid = RCX25Extraction(pdk=extraction.pdk, pex_mode=mode, blackbox=False)
    with mock.patch('klayout_pex.kpex_cli.error') as error_mock, pytest.raises(SystemExit):
        invalid.run_kpex('test_patterns', 'nfet_li1.gds.gz', extra_args=reduce_args)
    # NOTE: among others, e.g. a missing KLayout executable (as in CI, which has the Python module only)
    assert [c.args[0] for c in error_mock.call_args_list if '--reduce' in c.args[0]] == [message]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_kpex_reduce_needs_the_2_5d_engine():
    pdk = extraction.pdk
    with mock.patch('klayout_pex.kpex_cli.error') as error_mock, pytest.raises(SystemExit):
        KpexCLI().main(['main', '--pdk', pdk.name, '--gds', pdk.gds_path('test_patterns', 'nfet_li1.gds.gz'),
                        '--out_dir', pdk.output_dir, '--reduce', 'floating'])
    assert "--reduce floating reduces the netlist of the 2.5D engine, it needs --2.5D" in \
           [c.args[0] for c in error_mock.call_args_list]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('reduce_args, messages', [
    # NOTE: newer Pythons quote the choices in the message, older ones don't
    (['--reduce', 'all'], ["argument --reduce: invalid choice: 'all' (choose from", 'none', 'floating', 'ticer']),
    (['--reduce', 'ticer', '--reduce_tau', '0'], ["argument --reduce_tau: must be > 0 s, got '0'"]),
])
def test_kpex_reduce_invalid_values_are_usage_errors(reduce_args: List[str], messages: List[str],
                                                     capsys: pytest.CaptureFixture):
    with pytest.raises(SystemExit) as exit_info:
        extraction.run_kpex('test_patterns', 'nfet_li1.gds.gz', extra_args=reduce_args)
    assert exit_info.value.code == 2
    stderr = capsys.readouterr().err
    assert all(message in stderr for message in messages), stderr
