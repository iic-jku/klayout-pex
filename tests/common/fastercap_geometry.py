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

from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest import mock

import klayout.db as kdb

from klayout_pex.fastercap.fastercap_input_builder import FasterCapInputBuilder
from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder
from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.rcx25.exclusion import Exclusions
from klayout_pex.tech_info import TechInfo
from klayout_pex.types import GDSPair


def context_from_shapes(shapes_by_gds: Dict[GDSPair, Optional[kdb.Region]], bbox: kdb.Box,
                        dbu: float = 0.001) -> KLayoutExtractionContext:
    """One-net extraction input with explicit regions, including absent and empty layers."""
    netlist = kdb.Netlist()
    circuit = kdb.Circuit()
    circuit.name = 'plate'
    netlist.add(circuit)
    circuit.create_net('wire')

    def shapes(gds_pair: GDSPair, **kwargs: Any) -> Optional[kdb.Region]:
        return shapes_by_gds.get(gds_pair)

    context = mock.Mock(spec=KLayoutExtractionContext)
    context.dbu = dbu
    context.substrate_net_name = 'sub'
    context.annotated_top_cell = SimpleNamespace(name='plate')
    context.lvsdb = mock.Mock(spec=kdb.LayoutVsSchematic)
    context.lvsdb.netlist.return_value = netlist
    context.top_cell_bbox.return_value = bbox
    context.shapes_of_layer.side_effect = shapes
    context.shapes_of_net.side_effect = shapes
    return context


def fastercap_input(pex_context: KLayoutExtractionContext, tech_info: TechInfo,
                    exclusions: Optional[Exclusions] = None) -> FasterCapModelBuilder:
    """The raw conductor/dielectric prisms before surface generation."""
    with mock.patch.object(FasterCapModelBuilder, 'generate', autospec=True, side_effect=lambda builder: builder):
        return FasterCapInputBuilder(pex_context=pex_context,
                                     tech_info=tech_info,
                                     substrate_net_name=pex_context.substrate_net_name,
                                     exclusions=exclusions).build()
