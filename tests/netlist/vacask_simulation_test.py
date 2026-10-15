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
import tempfile

import allure
import pytest

from klayout_pex.netlist.netlist_cli import NetlistCLI
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
        with open(spice_path, 'w') as f:
            f.write(LOWPASS_SPICE)
        with pytest.raises(SystemExit) as exit_info:
            NetlistCLI().main(['netlist', 'convert', '--to', 'vacask', spice_path])
        assert exit_info.value.code == 0

        deck_path = os.path.join(directory, 'tb.sim')
        with open(deck_path, 'w') as f:
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
