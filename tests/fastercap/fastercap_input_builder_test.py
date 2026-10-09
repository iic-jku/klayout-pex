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

from collections import defaultdict
from typing import *
from unittest import mock

import allure
import pytest

import klayout.db as kdb

from klayout_pex.fastercap.fastercap_input_builder import FasterCapInputBuilder
from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder
from klayout_pex.kpex_cli import KpexCLI
from tests.rcx25.rcx25_test_helpers import PDKName, PDKTestConfig


parent_suite = "kpex/FasterCap Input Tests"
tags = ("PEX", "FasterCap")


def dielectric_areas_um2(pdk_name: PDKName, *path_components) -> Dict[str, float]:
    """
    The areas of the FasterCap input dielectrics of a layout (in µm², with the white-box devices),
    built from the LVS database of a run (whose engine is left out)
    """
    pdk = PDKTestConfig(pdk_name)
    with mock.patch.object(KpexCLI, 'run_kpex_2_5d_engine', autospec=True) as run_kpex_2_5d_engine:
        KpexCLI().main(['main',
                        '--pdk', pdk.name,
                        '--gds', pdk.gds_path(*path_components),
                        '--out_dir', pdk.output_dir,
                        '--cache-dir', pdk.lvs_cache_dir,
                        '--2.5D',
                        '--blackbox', 'n'])
    pex_context = run_kpex_2_5d_engine.call_args.kwargs['pex_context']
    tech_info = run_kpex_2_5d_engine.call_args.kwargs['tech_info']

    regions_by_material: Dict[str, kdb.Region] = defaultdict(kdb.Region)
    add_dielectric = FasterCapModelBuilder.add_dielectric

    def add_and_collect_dielectric(self, material_name: str, layer: kdb.Region, z: float, height: float):
        regions_by_material[material_name] += layer
        add_dielectric(self, material_name=material_name, layer=layer, z=z, height=height)

    with mock.patch.object(FasterCapModelBuilder, 'add_dielectric', add_and_collect_dielectric):
        FasterCapInputBuilder(pex_context=pex_context,
                              tech_info=tech_info,
                              substrate_net_name=pex_context.substrate_net_name).build()

    return {material: round(region.merged().area() * pex_context.dbu ** 2, 4)
            for material, region in regions_by_material.items()}


# NOTE: the process stacks have a metal that's split into the bottom plates of the MIM caps and the rest,
#       two layers of the stack on the same GDS pair, which have different dielectrics above them,
#       so each one has the shapes of its own LVS layer: the MIM dielectric is on the bottom plates only,
#       not on all of the metal (nor are both layers all of the metal)

@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mim_dielectric_of_ihp_sg13g2():
    # MIM 6.99 µm x 6.99 µm, over Metal5 8.19 µm x 8.19 µm (67.0761 µm²)
    areas = dielectric_areas_um2(PDKName.IHP_SG13G2, 'sg13g2_pr__cmim', 'cmim.gds.gz')
    assert areas['ismim'] == 48.8601


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mim_dielectric_of_sky130A():
    # capm 18.9 µm x 5.1 µm, over met3 of 147.36 µm² (with the interconnect), no capm2 over met4
    areas = dielectric_areas_um2(PDKName.SKY130A, 'cap_mim_m3_w18p9_l5p1', 'cap_mim_m3_w18p9_l5p1.gds.gz')
    assert areas['capild3'] == 96.39
    assert 'capild4' not in areas


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_mim_dielectric_of_gf180mcuD():
    # FuseTop 5 µm x 5 µm and 20 µm x 10 µm, over Metal4 of 275.88 µm²
    areas = dielectric_areas_um2(PDKName.GF180MCUD, 'test_patterns', 'cap_mim_m4m5.gds.gz')
    assert areas['capild'] == 225.0
