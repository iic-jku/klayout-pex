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
from pathlib import Path
import tempfile

import allure
import pytest

from klayout_pex.netlist.netlist_cli import NetlistCLI
from klayout_pex.netlist.netlist_convert import convert_to_vacask
from tests.common.vacask import read_ascii_raw, requires_vacask, run_vacask


# NOTE: a low pass of 1 kΩ, 2 x 2 kΩ (a subcircuit call with m=2) and 1 pF, loaded with 2 kΩ,
#       with net names as KPEX writes them (A|B for the net A,B), which VACASK has no identifiers for
LOWPASS_SPICE = """\
.SUBCKT lowpass in out sub!
R1 in A|B 1k
Xr2 A|B out runit m=2
C1 out sub! 1p
Rload out SUB! 2k
.ENDS lowpass
.SUBCKT runit a b
R1 a b 2k
.ENDS runit
"""

TESTBENCH = """\
Low pass test

include "lowpass.inc"
model vsource vsource
v1 (in 0) vsource dc=1 mag=1
x1 (in out 0) lowpass

control
  include "lowpass.options.inc"
  options rawfile="ascii"
  save default v('x1:A|B')
  analysis op1 op
  analysis ac1 ac values=[1e6, 1e8]
endc
"""


@allure.parent_suite("Simulation Tests")
@allure.tag("Netlist", "VACASK")
@pytest.mark.slow
@requires_vacask
def test_converted_netlist_simulates_in_vacask():
    with tempfile.TemporaryDirectory() as directory:
        spice_path = os.path.join(directory, 'lowpass.spice')
        with open(spice_path, 'w', encoding='utf-8') as f:
            f.write(LOWPASS_SPICE)
        with pytest.raises(SystemExit) as exit_info:
            NetlistCLI().main(['netlist', 'convert', '--to', 'vacask', spice_path])
        assert exit_info.value.code == 0

        deck_path = os.path.join(directory, 'tb.sim')
        with open(deck_path, 'w', encoding='utf-8') as f:
            f.write(TESTBENCH)
        run_vacask(deck_path)

        # NOTE: 1 kΩ + 2 kΩ / 2 to 2 kΩ, the same as ngspice gives with m=2 of the subcircuit call
        op = read_ascii_raw(os.path.join(directory, 'op1.raw'))
        assert op['out'][0].real == pytest.approx(0.5, rel=1e-12)
        assert op['x1:A|B'][0].real == pytest.approx(0.75, rel=1e-12)

        # NOTE: the pole of 1 pF and 2 kΩ || 2 kΩ
        ac = read_ascii_raw(os.path.join(directory, 'ac1.raw'))
        for frequency, obtained in zip(ac['frequency'], ac['out']):
            expected = 0.5 / (1 + 1j * 2 * math.pi * frequency.real * 1e3 * 1e-12)
            assert cmath.isclose(expected, obtained, rel_tol=1e-9), f"{frequency.real} Hz"


@allure.parent_suite("Simulation Tests")
@allure.tag("Netlist", "VACASK")
@pytest.mark.slow
@requires_vacask
@pytest.mark.parametrize('kind', ['native', 'local-wrapper', 'external-wrapper'])
@pytest.mark.parametrize('directive', ['.option scale=1u', '.OPTIONS SCALE=1000n', '.options scale=1'])
def test_converted_geometry_scale_matches_explicit_si_geometry(tmp_path: Path, kind: str, directive: str):
    geometry = ('w=4u l=2u ad=3p as=5p pd=7u ps=11u' if directive.endswith('=1') else
                'w=4 l=2 ad=3 as=5 pd=7 ps=11')
    if kind == 'native':
        spice = f'M1 d g 0 0 nmos {geometry} m=2\n'
    elif kind == 'local-wrapper':
        spice = (f'.subckt local d g s b\nM1 d g s b nmos {geometry}\n.ends\n'
                 'X1 d g 0 0 local m=2\n')
    else:
        spice = f'X1 d g 0 0 external {geometry} m=2\n'
    source = tmp_path / 'circuit.spice'
    source.write_text(directive + '\n' + spice, encoding='utf-8')
    circuit, options = convert_to_vacask(str(source), str(tmp_path / 'circuit.inc'), ())

    # NOTE: the external wrapper is deliberately outside the converter's input. Its
    # expressions must see the same scale at the native model, without scaling X arguments.
    (tmp_path / 'models.inc').write_text("""\
load "spice/mos1.osdi"
model nmos sp_mos1 type=1 vto=0.3 kp=50e-6 ld=0.1e-6 tox=10e-9 cj=1e-4 cjsw=2e-10 cgso=1e-10 cgdo=1e-10
subckt external (d g s b)
  parameters w=4 l=2 ad=3 as=5 pd=7 ps=11
  m1 (d g s b) nmos w=w l=l ad=ad as=as pd=pd ps=ps
ends
""", encoding='utf-8')
    bench = """Geometry scale test

include "models.inc"
{circuit}
model supply vsource
vd (d 0) supply dc=1 mag=1
vg (g 0) supply dc=1

control
  {options}
  options rawfile="ascii"
  save default
  analysis op1 op
  analysis ac1 ac values=[1e6]
endc
"""
    path = tmp_path / 'tb.sim'
    path.write_text(bench.format(circuit=f'include "{Path(circuit).name}"',
                                 options=f'include "{Path(options).name}"'), encoding='utf-8')
    run_vacask(str(path))
    obtained = {a: read_ascii_raw(str(tmp_path / (a + '.raw'))) for a in ('op1', 'ac1')}

    # NOTE: scaling both W and L leaves W/L unchanged. Nonzero lateral diffusion makes
    # the DC current sensitive to absolute lengths; AC also checks area and perimeter terms.
    # This reference writes SI values independently, with no parser or writer conversion.
    si_instance = '(d g 0 0) nmos w=4e-6 l=2e-6 ad=3e-12 as=5e-12 pd=7e-6 ps=11e-6'
    # NOTE: gmin is added per instance, not multiplied by $mfactor. Keep the same device
    # count as the input: a native M with m=2, or two parallel calls of an X wrapper.
    reference = (f'm1 {si_instance} $mfactor=2' if kind == 'native' else
                 f'm1 {si_instance}\nm2 {si_instance}')
    path.write_text(bench.format(circuit=reference, options='options scale=1'), encoding='utf-8')
    run_vacask(str(path))
    for analysis in ('op1', 'ac1'):
        expected = read_ascii_raw(str(tmp_path / (analysis + '.raw')))
        for supply in ('vd:flow(br)', 'vg:flow(br)'):
            assert obtained[analysis][supply][0] == pytest.approx(expected[supply][0], rel=1e-12, abs=1e-22), (
                analysis, supply, kind, directive)
