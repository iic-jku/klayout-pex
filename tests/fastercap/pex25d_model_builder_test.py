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

from typing import *
from unittest import mock

import allure

import klayout.db as kdb

from klayout_pex import pex25d
from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder
from klayout_pex.fastercap.pex25d_exporter import FasterCapModelOptions
from klayout_pex.fastercap.pex25d_model_builder import PEX25DFasterCapModelBuilder


def dielectric_prisms(text: str) -> Dict[str, List[Tuple[kdb.Region, int, int]]]:
    """The dielectric prisms of the FasterCap model of a PEX25D file, z in grid units"""
    scene = pex25d.resolve(pex25d.read_text(text.encode('utf-8')))
    with mock.patch.object(FasterCapModelBuilder, 'generate', autospec=True) as generate:
        PEX25DFasterCapModelBuilder(scene, FasterCapModelOptions()).build()
    return generate.call_args.args[0].dlayers


@allure.parent_suite("Unit Tests")
@allure.tag("Capacitance", "FasterCap")
def test_films_on_ground_plane_cover_the_field():
    prisms = dielectric_prisms('''PEX25D 1.0-rc1
UNITS LENGTH um GRID 0.001
GROUND_PLANE gp Z_OFFSETS -0.1 0.0
METAL M1 Z_OFFSETS 0.65 0.90
DIELECTRIC_BACKGROUND air PERMITTIVITY 1.0
DIELECTRIC_CONFORMAL ox WRAPS gp PERMITTIVITY 4.1 THICKNESS_OVER_WRAPPED 0.25 \\
    THICKNESS_BESIDE_WRAPPED 0.05 THICKNESS_ON_FIELD 0
DIELECTRIC_CONFORMAL nit WRAPS ox PERMITTIVITY 7.0 THICKNESS_OVER_WRAPPED 0.05 \\
    THICKNESS_BESIDE_WRAPPED 0 THICKNESS_ON_FIELD 0
CONDUCTOR w1 net0
BOX CONDUCTOR w1 LAYER M1 LL 0.0 0.0 UR 0.14 1.4
DOMAIN_BOX LL -1.0 -1.0 0.0 UR 1.14 2.4 1.9
''')

    # grown up from the ground plane's bottom face, but not sideways past the field
    field = kdb.Region(kdb.Box(-1000, -1000, 1140, 2400))
    for name, zhigh in (('ox', 250), ('nit', 300)):
        assert [(zlow, ztop) for _, zlow, ztop in prisms.get(name, [])] == [(-100, zhigh)], name
        (region, _, _), = prisms[name]
        assert (region ^ field).is_empty(), name
