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

"""Protocol implementations for PEX25D FasterCap and FastCap2 exports.

Both solvers use the same input format. Exporter instances hold no per-scene
state; each export builds its own model. Geometry dependencies load on export.
The STL exporter builds its solids with :func:`build_fastercap_model` for now.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import os
from typing import TYPE_CHECKING, Any, ClassVar, List, Mapping, Optional

from ..plugin_api.v1 import ExportError, ExporterUnavailable, PEX25DSceneExporter

if TYPE_CHECKING:
    from klayout_pex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene

    from .fastercap_model_generator import FasterCapModelGenerator


@dataclass
class FasterCapModelOptions:
    """Geometry and meshing settings of the FasterCap model."""

    delaunay_amax: float = 0.0
    """Maximum triangle area; 0 leaves it to the mesher."""

    delaunay_b: float = 1.0
    """Minimum mesh angle as b = 2·sin(angle); 1.0 is 30 degrees."""

    field_margin_um: float = 8.0
    """
    How far the laterally unbounded materials — the simple bands, the films that
    cover the field, the background, the ground plane — are drawn beyond the
    geometry. Ignored when the scene carries a DOMAIN_BOX, which says it
    outright.
    """

    geometry_check: bool = False
    """Run the generator's own geometry validation before writing."""

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if field.type == 'bool' and not isinstance(value, bool):
                raise TypeError(f"'{field.name}' must be a bool")
            if field.type == 'float' and (isinstance(value, bool)
                                          or not isinstance(value, (int, float))):
                raise TypeError(f"'{field.name}' must be an int or float (not bool)")


@dataclass
class FasterCapExporterOptions(FasterCapModelOptions):
    """FasterCap and FastCap2 settings: the model's, and STL alongside the solver input."""

    write_stl: bool = False
    """Also dump the generated solids as STL, for looking at."""


def build_fastercap_model(scene: PEX25DScene,
                          settings: FasterCapModelOptions,
                          exporter_name: str) -> FasterCapModelGenerator:
    """Build the FasterCap model of ``scene``; KLayout loads here."""
    try:
        from .pex25d_model_builder import PEX25DFasterCapModelBuilder
    except ImportError as exc:
        raise ExporterUnavailable(
            f"The {exporter_name} exporter needs KLayout and its geometry dependencies. "
            f"Original error: {exc}") from exc

    generator = PEX25DFasterCapModelBuilder(scene, settings).build()
    if settings.geometry_check:
        generator.check()
    return generator


class FasterCapSceneExporter(PEX25DSceneExporter):
    """Write a FasterCap solver deck from a resolved PEX25D scene."""

    name: ClassVar[str] = 'fastercap'
    default_prefix: ClassVar[str] = 'FasterCap_Input_'

    def export(self,
               scene: PEX25DScene,
               *,
               output_dir_path: str,
               prefix: str = '',
               options: Optional[Mapping[str, Any]] = None) -> List[str]:
        """Build and write solver inputs, returning the primary list file first."""
        try:
            settings = FasterCapExporterOptions(**(options or {}))
        except TypeError as exc:
            raise ExportError(f"Invalid options for '{self.name}': {exc}") from exc

        generator = build_fastercap_model(scene, settings, self.name)

        os.makedirs(output_dir_path, exist_ok=True)
        effective_prefix = prefix or self.default_prefix
        written = generator.write_fastcap(output_dir_path=output_dir_path,
                                           prefix=effective_prefix)
        if settings.write_stl:
            written.extend(generator.dump_stl(output_dir_path=output_dir_path,
                                              prefix=effective_prefix))
        return written


class FastCap2SceneExporter(FasterCapSceneExporter):
    """Write the shared solver input format with FastCap2 defaults."""

    name: ClassVar[str] = 'fastcap2'
    default_prefix: ClassVar[str] = 'FastCap_Input_'
