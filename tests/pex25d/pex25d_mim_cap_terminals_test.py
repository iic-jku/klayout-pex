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

import os
from typing import *

import allure
import pytest

from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.pex25d.protobuf import pex25d_terminal_pb2
from klayout_pex.pex25d.reader import read_pex25d_text
from tests.rcx25.rcx25_test_helpers import PDKName, PDKTestConfig


parent_suite = "kpex/PEX25D Generation Tests"
tags = ("PEX", "PEX25D")


def device_terminal_layers(pdk_name: PDKName, *path_components) -> List[Tuple[str, str]]:
    """
    The device terminals of the PEX25D file of a layout, as (terminal name, layer)

    NOTE: without the names of the devices and nets, which depend on the LVS run (e.g. $1)
    """
    pdk = PDKTestConfig(pdk_name)
    output_path = os.path.join(pdk.output_dir, f"{path_components[-1].removesuffix('.gds.gz')}.pex25d")
    KpexCLI().main(['kpex', 'pex25d',
                    '--pdk', pdk.name,
                    '--gds', pdk.gds_path(*path_components),
                    '--out_dir', pdk.output_dir,
                    '--cache-dir', pdk.lvs_cache_dir,
                    '--blackbox', 'n',
                    '--output_file', output_path])
    with open(output_path, 'rb') as f:
        pex25d_file = read_pex25d_text(f.read(), output_path)
    return sorted((t.name.rsplit(':', 1)[1], t.layer) for t in pex25d_file.terminals
                  if t.kind == pex25d_terminal_pb2().TERMINAL_KIND_DEVICE_TERMINAL)


# NOTE: the bottom plates of the MIM caps are the parts of their metal under the top plates,
#       a layer of the process stack of their own, which their device terminals must be on (#280)

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mim_cap_terminals_of_sky130A():
    assert device_terminal_layers(PDKName.SKY130A, 'cap_mim_m3_w18p9_l5p1', 'cap_mim_m3_w18p9_l5p1.gds.gz') == \
           [('A', 'met3_cap'), ('B', 'capm')]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mim_cap_terminals_of_ihp_sg13g2():
    assert device_terminal_layers(PDKName.IHP_SG13G2, 'sg13g2_pr__cmim', 'cmim.gds.gz') == \
           [('mim_btm', 'metal5_cap'), ('mim_top', 'cmim_top')]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_rf_mim_cap_terminals_of_ihp_sg13g2():
    # NOTE: the substrate terminal (mim_sub) has no layer of the process stack
    assert device_terminal_layers(PDKName.IHP_SG13G2, 'sg13g2_pr__rfcmim', 'rfcmim.gds.gz') == \
           [('mim_btm', 'metal5_cap'), ('mim_top', 'cmim_top')]


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mim_cap_terminals_of_gf180mcuD():
    # NOTE: two MIM caps (FuseTop 5 µm x 5 µm and 20 µm x 10 µm), A the bottom and B the top plate
    assert device_terminal_layers(PDKName.GF180MCUD, 'test_patterns', 'cap_mim_m4m5.gds.gz') == \
           [('A', 'metal4_cap'), ('A', 'metal4_cap'), ('B', 'FuseTop'), ('B', 'FuseTop')]
