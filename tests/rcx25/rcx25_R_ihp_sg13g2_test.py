#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/martinjankoehler/klayout-pex).
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
import tempfile

import allure
import klayout.db as kdb
import pytest

from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.pdk_config import PDK
from klayout_pex.tech_info import TechInfo

parent_suite = "kpex/2.5D Extraction Tests [PDK ihp-sg13g2 | mode R]"
tags = ("PEX", "2.5D", "RF MOS")

TEST_DESIGNS_DIR = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata', 'designs', 'ihp_sg13g2'))


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_rf_mos_keeps_its_layout_geometry():
    # The IHP LVS script replaced each extracted RF MOS by a newly created device
    # of the base class (sg13_lv_nmos with rfmode=1), which has no layout geometry,
    # so the resistance extraction could not connect it (#211)
    cell_name = 'rfnmos_w1u_l0u72'
    gds_path = os.path.join(TEST_DESIGNS_DIR, 'rfnmos', f"{cell_name}.gds.gz")

    with tempfile.TemporaryDirectory() as out_dir:
        cli = KpexCLI()
        cli.main(['main',
                  '--pdk', PDK.IHP_SG13G2,
                  '--mode', 'R',
                  '--gds', gds_path,
                  '--out_dir', out_dir,
                  '--2.5D'])
        assert cli.rcx25_extraction_results is not None

        lvsdb = kdb.LayoutVsSchematic()
        lvsdb.read(os.path.join(out_dir, f"{cell_name}__{cell_name}", f"{cell_name}.lvsdb.gz"))

    assert [c.name for c in lvsdb.internal_layout().top_cells()] == [cell_name]

    tech = TechInfo.from_json(PDK.IHP_SG13G2.config.tech_pb_json_path, dielectric_filter=None)
    pex_context = KLayoutExtractionContext.prepare_extraction(lvsdb=lvsdb,
                                                              top_cell=cell_name,
                                                              tech=tech,
                                                              blackbox_devices=False)
    devices = list(pex_context.devices_by_name.values())
    assert [(d.device_class_name, d.device_abstract_name) for d in devices] == [('rfnmos', 'D$rfnmos')]
    assert {t.name: [r.layer.canonical_layer_name for r in t.region_by_layer] for t in devices[0].terminals} \
           == {'S': ['nSD'], 'G': ['GatPoly'], 'D': ['nSD'], 'B': ['PWell']}
