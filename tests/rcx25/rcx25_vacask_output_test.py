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
import os
from typing import *

import allure
import pytest

from rcx25_test_helpers import *
from klayout_pex.netlist.netlist_format import NetlistFormat
from klayout_pex.netlist.spice_reader import SpiceReader
from tests.common.ngspice import ngspice_executable, read_wrdata, run_ngspice
from tests.common.vacask import (
    VACASK_EXE,
    assert_same_nets_and_values,
    read_ascii_raw,
    read_vacask_subcircuits,
    run_vacask,
)


parent_suite = "kpex/2.5D Extraction Tests [VACASK netlist]"
tags = ("PEX", "2.5D", "VACASK")


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
    with open(vacask_path) as f:
        vacask_text = f.read()
    # NOTE: the SPICE netlist has the capacitances with 6 significant digits
    assert_same_nets_and_values(SpiceReader().read(spice_path), vacask_text, rel_tol=5e-6)
    return vacask_text


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
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
@pytest.mark.slow
def test_rc_netlist_of_nmos_ihp_sg13g2():
    extraction = RCX25Extraction(pdk=PDKTestConfig(PDKName.IHP_SG13G2), pex_mode=PEXMode.RC, blackbox=True)
    text = assert_vacask_netlist_is_the_spice_netlist(extraction, 'test_patterns', 'nmos_metal1_redux.gds.gz')
    mos = [i for i in read_vacask_subcircuits(text)['nmos_metal1_redux'].instances.values()
           if i.master == 'sg13_lv_nmos']
    assert len(mos) == 1


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_rc_netlist_of_rfcmim_ihp_sg13g2():
    # NOTE: the VACASK subcircuit cap_rfcmim of the IHP PDK declares m
    extraction = RCX25Extraction(pdk=PDKTestConfig(PDKName.IHP_SG13G2), pex_mode=PEXMode.RC, blackbox=True)
    text = assert_vacask_netlist_is_the_spice_netlist(extraction, 'sg13g2_pr__rfcmim', 'rfcmim.gds.gz')
    caps = [i for i in read_vacask_subcircuits(text)['rfcmim'].instances.values() if i.master == 'cap_rfcmim']
    assert len(caps) == 1
    assert caps[0].parameters['m'] == '1'


IHP_SG13G2_DIR = os.path.join(os.environ.get('PDK_ROOT', ''), 'ihp-sg13g2')

requires_ihp_simulators = pytest.mark.skipif(
    VACASK_EXE is None or ngspice_executable() is None
    or not os.path.isdir(os.path.join(IHP_SG13G2_DIR, 'libs.tech', 'vacask'))
    or not os.path.isfile(os.path.join(IHP_SG13G2_DIR, 'libs.tech', 'ngspice', '.spiceinit')),
    reason='needs vacask and ngspice on PATH, and the VACASK and ngspice models of $PDK_ROOT/ihp-sg13g2'
)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
@requires_ihp_simulators
def test_vacask_simulates_the_rc_netlist_of_an_nmos_as_ngspice_ihp_sg13g2():
    # NOTE: the diode-connected NMOS between VDD and VSS, with the parasitic resistances and capacitances,
    #       in VACASK (with the VACASK models of the PDK) and in ngspice (with its ngspice models)
    extraction = RCX25Extraction(pdk=PDKTestConfig(PDKName.IHP_SG13G2), pex_mode=PEXMode.RC, blackbox=True)
    vacask_path, spice_path = vacask_and_spice_netlists(extraction, 'nmos_diode2', 'nmos_diode2.gds.gz')
    run_dir = os.path.join(os.path.dirname(vacask_path), 'simulation')
    os.makedirs(run_dir, exist_ok=True)
    vacask_models = os.path.join(IHP_SG13G2_DIR, 'libs.tech', 'vacask')
    ngspice_models = os.path.join(IHP_SG13G2_DIR, 'libs.tech', 'ngspice')

    # NOTE: the VACASK models of the PDK load their devices (OSDI) by name, from the module path
    with open(os.path.join(run_dir, '.vacaskrc.toml'), 'w') as f:
        f.write(f'[Paths]\nmodule_path_prefix = [ "{vacask_models}/osdi" ]\n')
    with open(os.path.join(run_dir, 'tb.sim'), 'w') as f:
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

    # NOTE: the ngspice models of the PDK need their devices (OSDI), which its .spiceinit loads
    with open(os.path.join(ngspice_models, '.spiceinit')) as f:
        spiceinit = f.read().replace('$PDK_ROOT/$PDK', IHP_SG13G2_DIR)
    with open(os.path.join(run_dir, '.spiceinit'), 'w') as f:
        f.write(spiceinit)
    with open(os.path.join(run_dir, 'tb.cir'), 'w') as f:
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
