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

import json
from pathlib import Path
from typing import Any, Dict, Tuple

import klayout.db as kdb

from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.pdk_config import PDK
from klayout_pex.rcx25.c.device_capacitance_references import DeviceCapacitanceReference
from klayout_pex.rcx25.pex_mode import PEXMode
from klayout_pex.tech_info import TechInfo
from tests.common.pdk_test_config import PDKName, PDKTestConfig
from tests.rcx25.rcx25_test_helpers import RCX25Extraction


REFERENCE = DeviceCapacitanceReference('$1', 'metal_cap', ('A', 'B'), 1e-15)
PDK_CONFIG = PDKTestConfig(PDKName.IHP_SG13G2)
DESIGN = 'cap_cmomf_w10u_l25u_m2_m4_m5_wire.gds.gz'


def reference_document(**changes: Any) -> Dict[str, Any]:
    item = dict(device='$1', device_class='metal_cap', terminals=['A', 'B'], capacitance='1f')
    item.update(changes)
    return dict(format_version=1, references=[item])



def write_references(path: Path, document: Dict[str, Any]) -> str:
    path.write_text(json.dumps(document), encoding='utf-8')
    return str(path)



def layout_context(design: str = DESIGN) -> Tuple[KLayoutExtractionContext, kdb.Layout, kdb.Cell]:
    extraction = RCX25Extraction(PDK_CONFIG, PEXMode.CC, blackbox=True)
    lvsdb = extraction.read_lvsdb('test_patterns', design)
    tech = TechInfo.from_json(PDK.IHP_SG13G2.config.tech_pb_json_path, dielectric_filter=None)
    context = KLayoutExtractionContext.prepare_extraction(
        lvsdb, lvsdb.internal_top_cell().name, tech, blackbox_devices=True)
    layout = kdb.Layout()
    layout.read(PDK_CONFIG.gds_path('test_patterns', design))
    # The cell is owned by the layout, which the test must keep alive too.
    return context, layout, layout.cell(context.annotated_top_cell.name)
