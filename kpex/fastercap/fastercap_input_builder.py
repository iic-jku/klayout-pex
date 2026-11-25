#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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

"""Build direct field-solver input through the common resolved PEX25D scene."""

from __future__ import annotations

from typing import Any, Optional

from ..rcx25.exclusion import Exclusions, ConductorPart
from ..klayout.lvsdb_extractor import KLayoutExtractionContext
from ..tech_info import TechInfo
from ..util.number_range import DELAUNAY_B_DEFAULT
from .fastercap_error import FasterCapError
from .fastercap_model_generator import FasterCapModelGenerator


class FasterCapInputBuilder:
    """Layout-side preparation; geometry export is shared with standalone scenes."""

    def __init__(self, pex_context: KLayoutExtractionContext, tech_info: TechInfo,
                 substrate_net_name: str, k_void: float = 3.5,
                 delaunay_amax: float = 0.0, delaunay_b: float = DELAUNAY_B_DEFAULT,
                 exclusions: Optional[Exclusions] = None):
        self.pex_context = pex_context
        self.tech_info = tech_info
        self.substrate_net_name = substrate_net_name
        self.k_void = k_void
        self.delaunay_amax = delaunay_amax
        self.delaunay_b = delaunay_b
        self.exclusions = exclusions

    def build_scene(self) -> Any:
        from ..klayout.pex25d_builder import PEX25DBuilder, BuilderOptions, GeometryScope, BuildError
        from ..klayout.pex25d_exclusions import attach_layout_accounting
        from ..pex25d import resolve, ResolveError
        from ..klayout.physical_geometry import PhysicalGeometryError
        from ..klayout.pex25d_ground import GroundGeometryError
        from ..pex25d.accounting import SceneCapacitanceMap
        from fractions import Fraction
        from ..klayout.pex25d_accounting import AccountingGridError
        from ..klayout.pex25d_builder import DEFAULT_GRID_UM
        grid = Fraction(DEFAULT_GRID_UM)
        try:
            while True:
                builder = PEX25DBuilder(
                    self.pex_context, self.tech_info, self.pex_context.top_circuit.name,
                    BuilderOptions(grid_um=str(grid), geometry_scope=GeometryScope.ELECTROSTATIC,
                                   include_terminals=False, include_resistance=False,
                                   background_permittivity=self.k_void, domain_margin_um=8.0))
                file = builder.build()
                file.ground_plane.net = self.substrate_net_name
                if self.exclusions is not None:
                    attach_layout_accounting(file, builder, self.exclusions)
                try:
                    scene = resolve(file)
                    break
                except ResolveError as exc:
                    cause = exc.__cause__
                    if not isinstance(cause, AccountingGridError):
                        raise
                    # Rebuild from the original source grid; repeated rescaling
                    # of rounded geometry would change via ownership and corners.
                    grid /= cause.refinement_factor
        except (ValueError, BuildError, ResolveError, PhysicalGeometryError, GroundGeometryError) as exc:
            raise FasterCapError(f'Cannot build physical FasterCap scene: {exc}') from exc
        self.scene = scene
        self.accounting = SceneCapacitanceMap(scene)
        if self.exclusions is not None:
            # Preserve the existing enclosing netlist API for callers that still
            # pass Exclusions. Geometry/export itself uses only the scene map.
            for name, part in self.accounting.parts.items():
                indexes = frozenset(int(r.removeprefix('block')) for r in part.regions)
                layer = part.layer
                if layer is not None:
                    pair = self.tech_info.gds_pair(layer)
                    layer = self.tech_info.canonical_layer_name_by_gds_pair.get(pair, layer)
                original = ConductorPart(part.body.name, indexes, layer, part.is_reference)
                self.exclusions.conductor_parts[name] = original
                self.exclusions.conductor_names[original] = name
        return scene

    def build(self) -> FasterCapModelGenerator:
        from .pex25d_exporter import build_fastercap_model, FasterCapModelOptions
        from ..plugin_api.v1 import ExportError
        try:
            return build_fastercap_model(self.build_scene(),
                                        FasterCapModelOptions(delaunay_amax=self.delaunay_amax,
                                                              delaunay_b=self.delaunay_b), 'FasterCap')
        except ExportError as exc:
            raise FasterCapError(f'Cannot export physical FasterCap scene: {exc}') from exc
