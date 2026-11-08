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
from __future__ import annotations

import glob
import os
import re
import tempfile
from pathlib import Path
from typing import *
from unittest import mock

import allure
import klayout.db as kdb
import pytest

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.netlist.spice_reader import SpiceReader
from klayout_pex.pdk_config import PDK
from klayout_pex.pex25d.diagnostics import ExitCode
from klayout_pex.rcx25.netlist_checks import check_schematic_device_totals
from klayout_pex.schematic_devices import schematic_devices
from klayout_pex.tech_info import TechInfo
from tests.common.lvsdb_fixtures import lvsdb_fixture_path

TEST_DESIGNS_DIR = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata', 'designs'))

DESIGNS = [
    (PDK.SKY130A, 'sky130_fd_sc_hd__inv_1/sky130_fd_sc_hd__inv_1.gds.gz'),
    (PDK.SKY130A, 'inv/inv.gds.gz'),
    (PDK.SKY130A, 'test_patterns/nfet_li1_redux.gds.gz'),
    (PDK.SKY130A, 'test_patterns/r_single_wire_li1.gds.gz'),
    (PDK.SKY130A, 'test_patterns/r_nwell_pfet_ntap_li1.gds.gz'),
    (PDK.SKY130A, 'test_patterns/r_nwell_pfet_label_li1.gds.gz'),
    (PDK.SKY130A, 'test_patterns/cap_var_lvt_without_ptap_ring.gds.gz'),
    pytest.param(PDK.SKY130A, 'cap_vpp_04p4x04p6_l1m1m2_noshield/cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz',
                 marks=pytest.mark.slow),  # NOTE: the MOM caps take 2 s in RC mode
    (PDK.SKY130A, 'test_patterns/r_ptap_pair_li1_m1.gds.gz'),
    (PDK.SKY130A, 'test_patterns/r_ptap_li1_m1_two_wires.gds.gz'),
    (PDK.SKY130A, 'test_patterns/r_ntap_pair_nwell_li1_m1.gds.gz'),
    (PDK.SKY130A, 'test_patterns/r_ntap_pair_two_nwells_over_dnwell_li1_m1.gds.gz'),
    (PDK.GF180MCUD, 'test_patterns/nfet_m1.gds.gz'),
    (PDK.GF180MCUD, 'test_patterns/r_ptap_pair_m1_m2.gds.gz'),
    (PDK.GF180MCUD, 'test_patterns/r_ptap_pair_isolated_pwell_m1_m2.gds.gz'),
    (PDK.GF180MCUD, 'test_patterns/r_ntap_pair_dnwell_m1_m2.gds.gz'),
    (PDK.GF180MCUD, 'test_patterns/r_ntap_pair_two_nwells_over_dnwell_m1_m2.gds.gz'),
    (PDK.GF180MCUD, 'test_patterns/r_nwell_pfet_ntap_m1.gds.gz'),
    (PDK.GF180MCUD, 'test_patterns/plates_m1_over_isolated_pwell_and_dnwell.gds.gz'),
    (PDK.IHP_SG13G2, 'sg13g2_a21o_1/sg13g2_a21o_1.gds.gz'),
    (PDK.IHP_SG13G2, 'rfnmos/rfnmos_w1u_l0u72.gds.gz'),
    pytest.param(PDK.IHP_SG13G2, 'cap_vpp_04p4x04p6_m1m2m3_substrate_pin/cap_vpp_04p4x04p6_m1m2m3_substrate_pin.gds.gz',
                 marks=pytest.mark.slow),  # NOTE: the MOM caps take 2 s in RC mode
    (PDK.IHP_SG13G2, 'test_patterns/nmos_metal1_redux_twice.gds.gz'),
    (PDK.IHP_SG13G2, 'test_patterns/r_ptap_pair_m1_m2.gds.gz'),
    (PDK.IHP_SG13G2, 'test_patterns/r_ptap_pair_m1_m2_pins_A_B.gds.gz'),
    (PDK.IHP_SG13G2, 'test_patterns/r_ntap_pair_nwell_m1_m2.gds.gz'),
    (PDK.IHP_SG13G2, 'test_patterns/nmos_pair_abutting_ptaps.gds.gz'),
    pytest.param(PDK.IHP_SG13G2, 'test_patterns/esd_diodevss_2kv_pair.gds.gz',
                 marks=pytest.mark.slow),  # NOTE: the ESD diodes take up to 22 s in RC mode
    (PDK.IHP_SG13G2, 'test_patterns/nmos_metal1_redux_two_drain_labels.gds.gz'),
    (PDK.IHP_SG13G2, 'test_patterns/nmos_metal1_redux_two_labels_one_node.gds.gz'),
    (PDK.IHP_SG13G2, 'test_patterns/single_plate_6um_x_8um_m1_over_isolated_pwell.gds.gz'),
    pytest.param(PDK.IHP_SG13CMOS5L, 'cap_cmomf_w5u_l5u_m1_m4/cap_cmomf_w5u_l5u_m1_m4.gds.gz',
                 marks=pytest.mark.slow),  # NOTE: the MOM caps take 2 s in RC mode
    (PDK.IHP_SG13CMOS5L, 'inductor3_w2u_d25u85_2_turns/inductor3_w2u_d25u85_2_turns.gds.gz'),
]


EXPECTED_FAILURES = {
    ('cap_vpp_04p4x04p6_l1m1m2_noshield/cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz', 'R'):
        "in R mode, the whiteboxed MOM cap leaves its port SUB touching nothing, as there are no capacitances",
}


@allure.parent_suite("kpex/2.5D Extraction Tests [RC netlist checks]")
@allure.tag("PEX", "2.5D")
@pytest.mark.parametrize('mode', ['R', 'RC'])
@pytest.mark.parametrize('pdk,gds', DESIGNS)
def test_rc_netlist_is_consistent(pdk: PDK, gds: str, mode: str, request: pytest.FixtureRequest):
    # NOTE: each defect of #211 §6, §10, §11 fails these checks (#215)
    reason = EXPECTED_FAILURES.get((gds, mode), None)
    if reason is not None:
        request.applymarker(pytest.mark.xfail(strict=True, reason=reason))
    with tempfile.TemporaryDirectory() as out_dir:
        cli = KpexCLI()
        cli.main(['main', 'extract',
                  '--pdk', pdk,
                  '--mode', mode,
                  '--lvsdb', lvsdb_fixture_path(pdk, os.path.join(TEST_DESIGNS_DIR, pdk, gds)),
                  '--out-dir', out_dir,
                  '--2.5D',
                  '--check', 'n'])  # NOTE: the problems, rather than a failed run
    assert cli.rcx25_netlist_problems == []


BLACKBOXED_DESIGNS = [
    (PDK.SKY130A, 'cap_vpp_04p4x04p6_l1m1m2_noshield/cap_vpp_04p4x04p6_l1m1m2_noshield.gds.gz'),
    (PDK.IHP_SG13G2, 'cap_vpp_04p4x04p6_m1m2m3_substrate_pin/cap_vpp_04p4x04p6_m1m2m3_substrate_pin.gds.gz'),
    (PDK.IHP_SG13CMOS5L, 'cap_cmomf_w5u_l5u_m1_m4/cap_cmomf_w5u_l5u_m1_m4.gds.gz'),
]


@allure.parent_suite("kpex/2.5D Extraction Tests [RC netlist checks]")
@allure.tag("PEX", "2.5D")
@pytest.mark.parametrize('pdk,gds', BLACKBOXED_DESIGNS)
def test_rc_netlist_with_blackboxed_devices_is_consistent(pdk: PDK, gds: str):
    # NOTE: the RC netlist keeps the MOM caps, which white-box mode removes
    with tempfile.TemporaryDirectory() as out_dir:
        cli = KpexCLI()
        cli.main(['main', 'extract',
                  '--pdk', pdk,
                  '--mode', 'RC',
                  '--blackbox', 'y',
                  '--lvsdb', lvsdb_fixture_path(pdk, os.path.join(TEST_DESIGNS_DIR, pdk, gds)),
                  '--out-dir', out_dir,
                  '--2.5D',
                  '--check', 'n'])  # NOTE: the problems, rather than a failed run
    assert cli.rcx25_netlist_problems == []


def cmomi_device_totals_problems(device_parameters: str) -> List[str]:
    cell_name = 'cmomi_w5u_l5u_m1_m5'
    lvsdb = kdb.LayoutVsSchematic()
    lvsdb.read(lvsdb_fixture_path(PDK.IHP_SG13G2, os.path.join(TEST_DESIGNS_DIR, PDK.IHP_SG13G2, cell_name,
                                                               f"{cell_name}.gds.gz")))
    device_models = TechInfo.from_json(PDK.IHP_SG13G2.config.tech_pb_json_path, dielectric_filter=None).device_models
    schematic = schematic_devices(netlist=SpiceReader().parse(f"""\
* {cell_name}
.subckt {cell_name} PLUS MINUS
XC1 PLUS MINUS cap_cmomi {device_parameters}
.ends
"""), device_models=device_models, top_cell_name=cell_name)
    return check_schematic_device_totals(lvs_netlist=lvsdb.netlist(),
                                         schematic=schematic,
                                         device_models=device_models)


@allure.parent_suite("kpex/2.5D Extraction Tests [RC netlist checks]")
@allure.tag("PEX", "2.5D", "Schematic")
@pytest.mark.parametrize('w, l, problems', [
    # NOTE: the pcell and the model floor them to 4.45 µm and 4.2 µm, the array, which is what the layout has
    ('5u', '5u', []),
    ('4.45u', '4.2u', []),
    ('4.4u', '4.2u', ['the schematic has Σ w·l = 14.952 of class cap_cmomi, the LVS netlist 18.69']),
])
def test_device_totals_of_a_cmomi_are_those_of_its_array(w: str, l: str, problems: List[str]):
    assert cmomi_device_totals_problems(f"w={w} l={l} mmin=1 mmax=5 feed=2") == problems


@allure.parent_suite("kpex/2.5D Extraction Tests [RC netlist checks]")
@allure.tag("PEX", "2.5D", "Schematic")
def test_device_totals_of_a_cmomi_as_xschem_writes_it():
    # NOTE: double is a .param of the model library, which the schematic doesn't include (#399)
    assert cmomi_device_totals_problems('w=5e-6 l=5e-6 mmin=1 mmax=5 feed=double subblock=0 m=1 mm_ok=1') == []


@allure.parent_suite("kpex/2.5D Extraction Tests [RC netlist checks]")
@allure.tag("PEX", "2.5D", "Schematic")
@pytest.mark.parametrize('prefix, suffix, matches_layout', [
    ('M', 'u', True),
    ('M', '', False),
    ('XM', '', True),
])
def test_schematic_mos_units(prefix: str, suffix: str, matches_layout: bool, tmp_path: Path):
    # NOTE: native `M` dimensions are in metres, while these simulation subcircuits take micrometres (#497)
    classes = ['sky130_fd_pr__nfet_01v8_lvt', 'sky130_fd_pr__pfet_01v8_lvt']
    source = '* inv\n.subckt inv\n' + '\n'.join(
        f'{prefix}{index} a b c d {name} L=0.45{suffix} W=1.5{suffix} m=6'
        for index, name in enumerate(classes, start=1)) + '\n.ends\n'
    models = TechInfo.from_json(PDK.SKY130A.config.tech_pb_json_path, dielectric_filter=None).device_models
    schematic = schematic_devices(netlist=SpiceReader().parse(source), device_models=models, top_cell_name='inv')
    lvsdb = kdb.LayoutVsSchematic()
    lvsdb.read(lvsdb_fixture_path(PDK.SKY130A, os.path.join(TEST_DESIGNS_DIR, PDK.SKY130A, 'inv/inv.gds.gz')))
    expected = [] if matches_layout else [
        f'the schematic has Σ {quantity} = {total} of class {name}, the LVS netlist {layout_total}'
        for name in classes
        for quantity, total, layout_total in [('W·L', '4.05e+12', '4.05'), ('W', '9000000', '9')]
    ]
    assert check_schematic_device_totals(lvsdb.netlist(), schematic, models) == expected

    if prefix == 'M':
        path = tmp_path / 'inv.cdl'
        path.write_text(source, encoding='utf-8')
        reference = kdb.Netlist()
        reference.read(str(path), kdb.NetlistSpiceReader())
        devices = list(reference.top_circuit().each_device())
        assert sorted(device.device_class().name.lower() for device in devices) == classes
        for device in devices:
            schematic_device = schematic.devices_by_class_name[device.device_class().name.lower()][0]
            # NOTE: `KLayout` folds `m` into the MOS width, KPEX keeps it separate for the totals
            assert schematic_device.lvs_parameters['W'] * schematic_device.m == pytest.approx(device.parameter('W'))
            assert schematic_device.lvs_parameters['L'] == pytest.approx(device.parameter('L'))


@allure.parent_suite("kpex/2.5D Extraction Tests [RC netlist checks]")
@allure.tag("PEX", "2.5D")
@pytest.mark.parametrize('mode', ['R', 'RC'])
def test_resistor_network_cut_off_from_its_net_is_reported(mode: str):
    # NOTE: only the labels A join the met1 and met2 to the net of the li1 and met1 over a p-tap, in LVS,
    #       the substrate doesn't, as they are on no tap
    gds = os.path.join(TEST_DESIGNS_DIR, PDK.SKY130A, 'test_patterns', 'r_ptap_li1_m1_and_floating_m1_m2.gds.gz')
    with tempfile.TemporaryDirectory() as out_dir:
        cli = KpexCLI()
        cli.main(['main', 'extract', '--pdk', PDK.SKY130A, '--mode', mode,
                  '--lvsdb', lvsdb_fixture_path(PDK.SKY130A, gds), '--out-dir', out_dir, '--2.5D', '--check', 'n'])
    assert cli.rcx25_netlist_problems == ['resistors of the nodes A.$11.met2, A.$5.met1 touch no net']


INV_1_GDS =os.path.join(TEST_DESIGNS_DIR, PDK.SKY130A, 'sky130_fd_sc_hd__inv_1', 'sky130_fd_sc_hd__inv_1.gds.gz')
PROBLEMS = ['port Y touches nothing']


@allure.parent_suite("kpex/2.5D Extraction Tests [RC netlist checks]")
@allure.tag("PEX", "2.5D")
def test_inconsistent_rc_netlist_fails_the_run_after_writing_it():
    # NOTE: --check is on by default in RC mode (#215)
    with tempfile.TemporaryDirectory() as out_dir, \
         mock.patch('klayout_pex.kpex_cli.check_rc_netlist', return_value=PROBLEMS), \
         mock.patch('klayout_pex.kpex_cli.error') as error_mock, \
         pytest.raises(SystemExit) as exit_info:
        try:
            KpexCLI().main(['main', 'extract', '--pdk', PDK.SKY130A, '--mode', 'RC',
                            '--lvsdb', lvsdb_fixture_path(PDK.SKY130A, INV_1_GDS), '--out-dir', out_dir, '--2.5D'])
        finally:
            netlists = glob.glob(os.path.join(out_dir, '*', '*_k25d_pex_netlist.spice'))
    assert exit_info.value.code == ExitCode.DIAGNOSTIC_ERRORS
    assert [c.args[0] for c in error_mock.call_args_list] == [
        "The extracted netlist is inconsistent with the LVS netlist (--check n to accept it):\n"
        "  - port Y touches nothing"
    ]
    assert len(netlists) == 1


@allure.parent_suite("kpex/2.5D Extraction Tests [RC netlist checks]")
@allure.tag("PEX", "2.5D")
@pytest.mark.parametrize('arguments', [['--mode', 'RC', '--check', 'n'],
                                       ['--mode', 'R']])  # NOTE: --check is off by default but in RC mode
def test_inconsistent_netlist_only_warns_without_check(arguments: list):
    with tempfile.TemporaryDirectory() as out_dir, \
         mock.patch('klayout_pex.kpex_cli.check_rc_netlist', return_value=PROBLEMS), \
         mock.patch('klayout_pex.kpex_cli.warning') as warning_mock:
        cli = KpexCLI()
        cli.main(['main', 'extract', '--pdk', PDK.SKY130A, '--lvsdb', lvsdb_fixture_path(PDK.SKY130A, INV_1_GDS),
                  '--out-dir', out_dir, '--2.5D', *arguments])
    assert cli.rcx25_netlist_problems == PROBLEMS
    assert "The extracted netlist is inconsistent with the LVS netlist:\n  - port Y touches nothing" \
           in [c.args[0] for c in warning_mock.call_args_list]


WIRES_NO_PIN_GDS = os.path.join(TEST_DESIGNS_DIR, PDK.IHP_SG13G2, 'test_patterns', 'wires_no_pin.gds.gz')


@allure.parent_suite("kpex/2.5D Extraction Tests [RC netlist checks]")
@allure.tag("PEX", "2.5D")
@pytest.mark.parametrize('mode, listed_nets', [
    ('CC', r"A \(\d+\.\d{3} fF\), B \(\d+\.\d{3} fF\)"),
    ('R', "A, B"),
    ('RC', r"A \(\d+\.\d{3} fF\), B \(\d+\.\d{3} fF\)"),
])
def test_nets_without_device_terminal_and_port_are_a_warning(mode: str, listed_nets: str):
    # NOTE: nothing drives the wires A and B, with labels on the text layer only (#407), nor the substrate sub!
    #       (without taps), which the warning leaves out, and --check passes (on by default in RC mode)
    with tempfile.TemporaryDirectory() as out_dir, \
         mock.patch('klayout_pex.kpex_cli.warning') as warning_mock:
        cli = KpexCLI()
        cli.main(['main', 'extract', '--pdk', PDK.IHP_SG13G2, '--mode', mode,
                  '--lvsdb', lvsdb_fixture_path(PDK.IHP_SG13G2, WIRES_NO_PIN_GDS), '--out-dir', out_dir, '--2.5D'])
    assert cli.rcx25_netlist_problems == []
    warnings = [c.args[0] for c in warning_mock.call_args_list if c.args[0].startswith('Nothing drives these nets')]
    assert len(warnings) == 1 and re.fullmatch(f"Nothing drives these nets, .*: {listed_nets}", warnings[0]), \
           warnings
