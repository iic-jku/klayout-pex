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
Generation of solver-native input files from a ``PEX25DScene``.

The specification calls these solver *adapters*; this module is named after the
operation the CLI exposes, ``pex25d export``.

Exporting is the one part of this package that is not pure format work: turning
a scene into a solver's input needs polygon booleans and meshing, so a backend
depends on a geometry library. Backends are therefore imported on use, and a
missing dependency is reported rather than surfacing as an ImportError from an
unexpected place. Reading, validating, converting and resolving stay
dependency-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import *


class SolverTarget(StrEnum):
    """Engines a PEX25D scene can be written out for."""

    FASTERCAP = 'fastercap'
    FASTCAP2 = 'fastcap2'

    DEFAULT = 'fastercap'


class ExportError(RuntimeError):
    """The scene could not be written out for the requested target."""


class ExporterUnavailable(ExportError):
    """The backend for a target is not importable in this installation."""


@dataclass
class ExporterOptions:
    """Knobs the CLI exposes for solver input generation."""

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

    write_stl: bool = False
    """Also dump the generated solids as STL, for looking at."""

    geometry_check: bool = False
    """Run the generator's own geometry validation before writing."""


def export(scene: Any,
           target: SolverTarget,
           output_dir_path: str,
           prefix: str = '',
           options: Optional[ExporterOptions] = None) -> List[str]:
    """
    Export ``scene`` as native input for ``target`` into ``output_dir_path``.

    Does not run the engine.

    :return: the paths written, most significant first — for FasterCap the
        ``.lst`` file, followed by the per-surface files it references.
    """
    match target:
        case SolverTarget.FASTERCAP | SolverTarget.FASTCAP2:
            backend = load_fastercap_backend()
        case _:
            raise ExportError(f"No exporter for '{target.value}'")

    return backend(scene=scene, target=target, output_dir_path=output_dir_path,
                   prefix=prefix, options=options or ExporterOptions())


def load_fastercap_backend() -> Callable[..., List[str]]:
    """
    The FasterCap / FastCap2 backend, which needs KLayout.

    Both engines read the same list-file format, so one backend serves them.
    """
    try:
        from ..fastercap.pex25d_exporter import export_fastercap
    except ImportError as e:
        raise ExporterUnavailable(
            f"The FasterCap exporter needs KLayout, which is not importable here. "
            f"Everything else the pex25d tool does works without it.\n"
            f"Original error: {e}"
        ) from e
    return export_fastercap
