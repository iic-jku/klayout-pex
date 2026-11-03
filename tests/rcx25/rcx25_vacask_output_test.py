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
import cmath
import math
import os
from typing import *

import allure
import pytest

from klayout_pex.netlist.netlist_format import NetlistFormat
from klayout_pex.netlist.spice_reader import SpiceReader
from klayout_pex.rcx25.pex_mode import PEXMode
from tests.common.ngspice import read_wrdata, requires_ngspice, run_ngspice, write_spiceinit
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.common.vacask import (
    assert_same_nets_and_values,
    read_ascii_raw,
    read_vacask_subcircuits,
    requires_vacask,
    run_vacask,
    write_vacaskrc,
)
from tests.rcx25.rcx25_test_helpers import RCX25Extraction


parent_suite = "kpex/2.5D Extraction Tests [VACASK netlist]"
tags = ("PEX", "2.5D", "VACASK")

IHP_SG13G2 = PDKTestConfig(PDKName.IHP_SG13G2)
IHP_SG13CMOS5L = PDKTestConfig(PDKName.IHP_SG13CMOS5L)


def vacask_and_spice_netlists(extraction: RCX25Extraction, *path_components) -> Tuple[str, str]:
    """
    :return: the paths of the VACASK and the SPICE netlist of the extraction
    """
    paths = extraction.written_netlist_paths(*path_components, netlist_format=NetlistFormat.VACASK)
    assert paths[NetlistFormat.VACASK].endswith('_k25d_pex_netlist.inc')
    return paths[NetlistFormat.VACASK], paths[NetlistFormat.SPICE]


def assert_vacask_netlist_is_the_spice_netlist(extraction: RCX25Extraction, *path_components) -> str:
    """
    :return: the VACASK netlist
    """
    vacask_path, spice_path = vacask_and_spice_netlists(extraction, *path_components)
    with open(vacask_path, encoding='utf-8') as f:
        vacask_text = f.read()
    # NOTE: the SPICE netlist has the capacitances with 6 significant digits
    assert_same_nets_and_values(SpiceReader().read(spice_path), vacask_text, rel_tol=5e-6)
    return vacask_text


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_rc_netlist_of_wire_with_t_junction_sky130A():
    # NOTE: the node of the T junction of the net A,B,C, which the SPICE netlist (and so the VACASK netlist)
    #       names A|B|C, as KLayout's SPICE writer does
    extraction = RCX25Extraction(pdk=PDKTestConfig(PDKName.SKY130A), pex_mode=PEXMode.RC, blackbox=False)
    text = assert_vacask_netlist_is_the_spice_netlist(extraction, 'test_patterns', 'r_wire_voltage_divider_li1.gds.gz')
    instances = read_vacask_subcircuits(text)['r_wire_voltage_divider_li1'].instances
    assert instances['Rext_1'].nodes == ['A', 'A|B|C']
    assert instances['Rext_1'].master == 'resistor'
    assert instances['Cext_2'].master == 'capacitor'


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_rc_netlist_of_nmos_ihp_sg13g2():
    extraction = RCX25Extraction(pdk=IHP_SG13G2, pex_mode=PEXMode.RC, blackbox=True)
    text = assert_vacask_netlist_is_the_spice_netlist(extraction, 'test_patterns', 'nmos_metal1_redux.gds.gz')
    mos = [i for i in read_vacask_subcircuits(text)['nmos_metal1_redux'].instances.values()
           if i.master == 'sg13_lv_nmos']
    assert len(mos) == 1


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_rc_netlist_of_rfcmim_ihp_sg13g2():
    # NOTE: the VACASK subcircuit cap_rfcmim of the IHP PDK declares m
    extraction = RCX25Extraction(pdk=IHP_SG13G2, pex_mode=PEXMode.RC, blackbox=True)
    text = assert_vacask_netlist_is_the_spice_netlist(extraction, 'sg13g2_pr__rfcmim', 'rfcmim.gds.gz')
    caps = [i for i in read_vacask_subcircuits(text)['rfcmim'].instances.values() if i.master == 'cap_rfcmim']
    assert len(caps) == 1
    assert caps[0].parameters['m'] == '1'


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@requires_vacask
@requires_ngspice
@IHP_SG13G2.requires_simulator_models('vacask', 'ngspice')
def test_vacask_simulates_the_rc_netlist_of_an_nmos_as_ngspice_ihp_sg13g2():
    # NOTE: the diode-connected NMOS between VDD and VSS, with the parasitic resistances and capacitances,
    #       in VACASK (with the VACASK models of the PDK) and in ngspice (with its ngspice models)
    extraction = RCX25Extraction(pdk=IHP_SG13G2, pex_mode=PEXMode.RC, blackbox=True)
    vacask_path, spice_path = vacask_and_spice_netlists(extraction, 'nmos_diode2', 'nmos_diode2.gds.gz')
    run_dir = os.path.join(os.path.dirname(vacask_path), 'simulation')
    os.makedirs(run_dir, exist_ok=True)
    vacask_models = IHP_SG13G2.simulator_models_dir('vacask')
    ngspice_models = IHP_SG13G2.simulator_models_dir('ngspice')

    write_vacaskrc(run_dir, vacask_models)
    with open(os.path.join(run_dir, 'tb.sim'), 'w', encoding='utf-8') as f:
        f.write(f"""nmos_diode2 in VACASK

include "{vacask_models}/models/sg13g2_vacask_common.lib"
include "{vacask_models}/models/cornerMOSlv.lib" section=mos_tt
include "{vacask_path}"

model vsource vsource
vdd (vdd 0) vsource dc=1.2 mag=1
x1 (vdd 0 0) nmos_diode2

control
  options rawfile="ascii"
  analysis op1 op
  analysis ac1 ac from=1e3 to=1e10 mode="dec" points=1
endc
""")
    run_vacask(os.path.join(run_dir, 'tb.sim'))

    write_spiceinit(run_dir, ngspice_models)
    with open(os.path.join(run_dir, 'tb.cir'), 'w', encoding='utf-8') as f:
        f.write(f"""nmos_diode2 in ngspice
.lib {ngspice_models}/models/cornerMOSlv.lib mos_tt
.include {spice_path}
Vdd vdd 0 dc 1.2 ac 1
X1 vdd 0 0 nmos_diode2
.control
set wr_singlescale
set wr_vecnames
op
wrdata op_ngspice.txt i(vdd)
ac dec 1 1e3 1e10
wrdata ac_ngspice.txt i(vdd)
.endc
.end
""")
    run_ngspice(os.path.join(run_dir, 'tb.cir'))

    # NOTE: within the tolerance of the simulators (reltol 1e-3)
    vacask_op = read_ascii_raw(os.path.join(run_dir, 'op1.raw'))['vdd:flow(br)'][0].real
    ngspice_op = read_wrdata(os.path.join(run_dir, 'op_ngspice.txt'))[0][1]
    assert vacask_op == pytest.approx(ngspice_op, rel=1e-3)

    vacask_ac = read_ascii_raw(os.path.join(run_dir, 'ac1.raw'))
    ngspice_ac = read_wrdata(os.path.join(run_dir, 'ac_ngspice.txt'))
    assert len(vacask_ac['frequency']) == len(ngspice_ac) == 8
    for frequency, vacask_current, (_, real, imag) in zip(vacask_ac['frequency'], vacask_ac['vdd:flow(br)'],
                                                          ngspice_ac):
        assert cmath.isclose(vacask_current, complex(real, imag), rel_tol=1e-3), f"{frequency.real:g} Hz"


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@requires_vacask
@requires_ngspice
@pytest.mark.parametrize('pdk, common_lib, gds_name, capacitance_femto', [
    # NOTE: the models give 0.915 fF/µm² of Metal2 … Metal4, 398 fF by their default of Metal1 … Metal5
    pytest.param(IHP_SG13G2, 'sg13g2_vacask_common.lib', 'cap_cmomf_w10u_l25u_m2_m4_m5_wire.gds.gz', 228.75,
                 marks=IHP_SG13G2.requires_simulator_models('vacask', 'ngspice'), id='ihp-sg13g2'),
    # NOTE: the models give 0.61 fF/µm² of Metal2 and Metal3, 32.175 fF by their default of Metal1 … Metal4
    pytest.param(IHP_SG13CMOS5L, 'sg13cmos5l_vacask_common.lib', 'cap_cmomf_w5u_l5u_m2_m3_m4_wire.gds.gz', 15.25,
                 marks=IHP_SG13CMOS5L.requires_simulator_models('vacask', 'ngspice'), id='ihp-sg13cmos5l'),
])
def test_mom_cap_simulates_to_the_capacitance_of_its_metal_range(pdk: PDKTestConfig,
                                                                 common_lib: str,
                                                                 gds_name: str,
                                                                 capacitance_femto: float):
    # NOTE: mode R, so the netlist has no other capacitance than the one of the model, between PLUS and MINUS
    extraction = RCX25Extraction(pdk=pdk, pex_mode=PEXMode.R, blackbox=True)
    vacask_path, spice_path = vacask_and_spice_netlists(extraction, 'test_patterns', gds_name)
    cell_name = gds_name.removesuffix('.gds.gz')
    with open(spice_path, encoding='utf-8') as f:
        ports = next(line for line in f.read().splitlines() if line.startswith('.SUBCKT ')).split()[2:]
    nodes = ' '.join('plus' if port == 'PLUS' else '0' for port in ports)
    run_dir = os.path.join(os.path.dirname(vacask_path), 'simulation')
    os.makedirs(run_dir, exist_ok=True)
    vacask_models = pdk.simulator_models_dir('vacask')
    ngspice_models = pdk.simulator_models_dir('ngspice')

    write_vacaskrc(run_dir, vacask_models)
    with open(os.path.join(run_dir, 'tb.sim'), 'w', encoding='utf-8') as f:
        f.write(f"""{cell_name} in VACASK

include "{vacask_models}/models/{common_lib}"
include "{vacask_models}/models/cornerCAP.lib" section=cap_typ
include "{vacask_path}"

model vsource vsource
vplus (plus 0) vsource dc=0 mag=1
x1 ({nodes}) {cell_name}

control
  options rawfile="ascii"
  analysis ac1 ac from=1e6 to=1e6 mode="lin" points=1
endc
""")
    run_vacask(os.path.join(run_dir, 'tb.sim'))

    write_spiceinit(run_dir, ngspice_models)
    with open(os.path.join(run_dir, 'tb.cir'), 'w', encoding='utf-8') as f:
        f.write(f"""{cell_name} in ngspice
.lib {ngspice_models}/models/cornerCAP.lib cap_typ
.include {spice_path}
Vplus plus 0 dc 0 ac 1
X1 {nodes} {cell_name}
.control
set wr_singlescale
set wr_vecnames
ac lin 1 1e6 1e6
wrdata ac_ngspice.txt i(vplus)
.endc
.end
""")
    run_ngspice(os.path.join(run_dir, 'tb.cir'))

    def capacitance_femto_of(current: complex) -> float:
        return abs(current.imag) / (2 * math.pi * 1e6) * 1e15

    vacask_current = read_ascii_raw(os.path.join(run_dir, 'ac1.raw'))['vplus:flow(br)'][0]
    (_, real, imag), = read_wrdata(os.path.join(run_dir, 'ac_ngspice.txt'))
    assert capacitance_femto_of(vacask_current) == pytest.approx(capacitance_femto, rel=1e-3)
    assert capacitance_femto_of(complex(real, imag)) == pytest.approx(capacitance_femto, rel=1e-3)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_rc_netlist_of_ports_that_only_the_substrate_joins_ihp_sg13g2():
    extraction = RCX25Extraction(pdk=IHP_SG13G2, pex_mode=PEXMode.RC, blackbox=False)
    text = assert_vacask_netlist_is_the_spice_netlist(extraction, 'test_patterns', 'r_ptap_pair_m1_m2_pins_A_B.gds.gz')
    assert read_vacask_subcircuits(text)['r_ptap_pair_m1_m2_pins_A_B'].ports == ['A', 'B']


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@requires_vacask
@requires_ngspice
@IHP_SG13G2.requires_simulator_models('vacask', 'ngspice')
def test_vacask_simulates_ports_that_only_the_substrate_joins_as_ngspice_ihp_sg13g2():
    cell_name = 'r_ptap_pair_m1_m2_pins_A_B'
    extraction = RCX25Extraction(pdk=IHP_SG13G2, pex_mode=PEXMode.RC, blackbox=False)
    vacask_path, spice_path = vacask_and_spice_netlists(extraction, 'test_patterns', f"{cell_name}.gds.gz")
    run_dir = os.path.join(os.path.dirname(vacask_path), 'simulation')
    os.makedirs(run_dir, exist_ok=True)
    vacask_models = IHP_SG13G2.simulator_models_dir('vacask')

    write_vacaskrc(run_dir, vacask_models)
    with open(os.path.join(run_dir, 'tb.sim'), 'w', encoding='utf-8') as f:
        f.write(f"""{cell_name} in VACASK

include "{vacask_models}/models/sg13g2_vacask_common.lib"
include "{vacask_path}"

model vsource vsource
va (a 0) vsource dc=0 mag=1
x1 (a 0) {cell_name}

control
  options rawfile="ascii"
  analysis ac1 ac from=1e9 to=1e9 mode="lin" points=1
endc
""")
    run_vacask(os.path.join(run_dir, 'tb.sim'))

    with open(os.path.join(run_dir, 'tb.cir'), 'w', encoding='utf-8') as f:
        f.write(f"""{cell_name} in ngspice
.include {spice_path}
Va a 0 dc 0 ac 1
X1 a 0 {cell_name}
.control
set wr_singlescale
set wr_vecnames
ac lin 1 1e9 1e9
wrdata ac_ngspice.txt i(va)
.endc
.end
""")
    run_ngspice(os.path.join(run_dir, 'tb.cir'))

    vacask_current = read_ascii_raw(os.path.join(run_dir, 'ac1.raw'))['va:flow(br)'][0]
    (_, real, imag), = read_wrdata(os.path.join(run_dir, 'ac_ngspice.txt'))
    # NOTE: within the tolerance of the simulators (reltol 1e-3)
    assert cmath.isclose(vacask_current, complex(real, imag), rel_tol=1e-3)
