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
"""Ground-isolation text and committed device/tap fixtures."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Tuple
import klayout.db as kdb
from klayout_pex import pex25d
from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.klayout.pex25d_builder import PEX25DBuilder
from klayout_pex.pdk_config import PDK
from klayout_pex.tech_info import TechInfo
from tests.common.lvsdb_fixtures import lvsdb_fixture_path

GROUND_CUTOUT_TEXT = """PEX25D 1.0-rc1
UNITS LENGTH um GRID 0.001
GROUND_PLANE subs NET VSS Z_OFFSETS -0.1 0
GROUND_CUTOUT subs OUTER -1 -1 2 -1 2 2 -1 2
METAL contact Z_OFFSETS 0 0.2
DIELECTRIC_BACKGROUND air PERMITTIVITY 1
CONDUCTOR pin signal
BOX CONDUCTOR pin LAYER contact LL 0 0 UR 1 1
DOMAIN_BOX LL -3 -3 -1 UR 3 3 1
"""

GROUND_CONTACT_CASES = [
    (PDK.GF180MCUD, 'test_patterns', 'r_nwell_pfet_ntap_m1'),
    (PDK.GF180MCUD, 'test_patterns', 'r_ntap_pair_dnwell_m1_m2'),
    (PDK.IHP_SG13G2, 'nmos_diode2', 'nmos_diode2'),
    (PDK.IHP_SG13G2, 'test_patterns', 'r_ntap_pair_nwell_m1_m2'),
]


def ground_contact_scene(pdk: PDK, directory: str, pattern: str,
                         blackbox_devices: bool) -> Tuple[Any, KLayoutExtractionContext]:
    technology = TechInfo.from_json(pdk.config.tech_pb_json_path, dielectric_filter=None)
    gds = str(Path(__file__).resolve().parents[2] / 'testdata/designs' / str(pdk)
              / directory / (pattern + '.gds.gz'))
    lvsdb = kdb.LayoutVsSchematic()
    lvsdb.read(lvsdb_fixture_path(pdk.value, gds))
    context = KLayoutExtractionContext.prepare_extraction(
        lvsdb, pattern, technology, blackbox_devices=blackbox_devices)
    scene = pex25d.resolve(PEX25DBuilder(context, technology, pattern).build())
    return scene, context
