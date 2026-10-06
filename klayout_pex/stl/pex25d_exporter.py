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

"""
PEX25D scene → STL solids, the built-in exporter ``klayout-pex:stl``.

For now the solids are those of the FasterCap model, so STL shows what FasterCap
and FastCap2 get. :func:`build_fastercap_model` is the only part of FasterCap this
exporter uses; it is meant to become independent of it.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import TYPE_CHECKING, Any, ClassVar, List, Mapping, Optional

from ..fastercap.pex25d_exporter import FasterCapModelOptions, build_fastercap_model
from ..plugin_api.v1 import ExportError, PEX25DSceneExporter

if TYPE_CHECKING:
    from klayout_pex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene


@dataclass
class STLExporterOptions(FasterCapModelOptions):
    """STL settings; for now those of the FasterCap model the solids come from."""


class STLSceneExporter(PEX25DSceneExporter):
    """Write the solids of a resolved PEX25D scene as STL, one file per dielectric and net."""

    name: ClassVar[str] = 'stl'
    default_prefix: ClassVar[str] = ''

    def export(self,
               scene: PEX25DScene,
               *,
               output_dir_path: str,
               prefix: str = '',
               options: Optional[Mapping[str, Any]] = None) -> List[str]:
        """Build the solids and write them; there is no primary file."""
        try:
            settings = STLExporterOptions(**(options or {}))
        except TypeError as exc:
            raise ExportError(f"Invalid options for '{self.name}': {exc}") from exc

        generator = build_fastercap_model(scene, settings, self.name)

        os.makedirs(output_dir_path, exist_ok=True)
        return generator.dump_stl(output_dir_path=output_dir_path,
                                  prefix=prefix or self.default_prefix)
