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

"""Version 1 PEX25D scene exporter protocol and its errors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Mapping, Optional, Protocol

if TYPE_CHECKING:
    from klayout_pex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene


class ExportError(RuntimeError):
    """The scene could not be written out for the requested target."""


class ExporterUnavailable(ExportError):
    """The backend for a target is not loadable in this installation."""


class PEX25DSceneExporter(Protocol):
    """Write solver inputs from a resolved ``PEX25DScene`` without running it.

    The caller owns the scene; exporters must not mutate it. Implementations
    validate their own options and reject unsupported features with ExportError.
    NotImplementedError marks what an exporter does not implement yet.
    Geometry libraries and other optional dependencies should be imported only
    when needed, so metadata discovery remains usable without them.
    """

    def export(self,
               scene: PEX25DScene,
               *,
               output_dir_path: str,
               prefix: str = '',
               options: Optional[Mapping[str, Any]] = None) -> List[str]:
        """Return generated paths, primary input first, as in ``pex25d.export``.

        ``scene`` is a resolved PEX25DScene protobuf message. ``options`` contains
        backend-specific settings and must not be mutated. An empty ``prefix``
        asks for the backend's default. Files are written under output_dir_path;
        returned paths must be usable by the caller without changing directory.
        """
        ...


__all__ = ['ExportError', 'ExporterUnavailable', 'PEX25DSceneExporter']
