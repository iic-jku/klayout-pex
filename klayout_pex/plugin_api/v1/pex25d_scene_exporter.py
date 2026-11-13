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

from enum import Enum
from typing import TYPE_CHECKING, Any, FrozenSet, List, Mapping, Optional, Protocol

if TYPE_CHECKING:
    from klayout_pex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene


class ExportError(RuntimeError):
    """The scene could not be written out for the requested target."""


class ExporterUnavailable(ExportError):
    """The backend for a target is not loadable in this installation."""


class SceneFeature(Enum):
    """Scene contracts an exporter must implement before receiving them."""

    GROUND_CUTOUTS = 'ground-cutouts'
    """Explicit polygon openings through the ground slab and its coatings."""

    ELECTRICAL_IDENTITY = 'electrical-identity'
    """Ground reference net and FLOATING identity independent of output labels."""


class PEX25DSceneExporter(Protocol):
    """Write solver inputs from a resolved ``PEX25DScene`` without running it.

    The caller owns the scene; exporters must not mutate it. Implementations
    validate their own options and reject unsupported features with ExportError.
    NotImplementedError marks what an exporter does not implement yet.
    Geometry libraries and other optional dependencies should be imported only
    when needed, so metadata discovery remains usable without them.
    """

    scene_features: FrozenSet[SceneFeature] = frozenset()
    """Required feature contracts understood by this exporter.

    An exporter without this declaration supports only scenes requiring none
    of these additions. A declaration promises actual geometry and ownership
    support; accepting an unfamiliar protobuf field is insufficient.
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


def require_scene_features(exporter: PEX25DSceneExporter, scene: Any, target: str):
    """Fail before writing if a consumer does not implement required scene semantics."""
    from ...pex25d.electrical import solver_body_names
    required = set()
    if scene.HasField('ground_plane'):
        ground = scene.ground_plane
        if ground.cutouts:
            required.add(SceneFeature.GROUND_CUTOUTS)
        if ground.net and ground.net != ground.name:
            required.add(SceneFeature.ELECTRICAL_IDENTITY)
    if any(body.name != name for body, name in solver_body_names(scene).items()):
        required.add(SceneFeature.ELECTRICAL_IDENTITY)
    if not required:
        return
    declared = getattr(exporter, 'scene_features', frozenset())
    # Older Protocol subclasses can inherit placeholders. A stub, None,
    # Ellipsis, or a similarly spelled string never promises implementation.
    features = declared if isinstance(declared, (set, frozenset)) else frozenset()
    missing = required - features
    if missing:
        names = ', '.join(sorted(feature.value for feature in missing))
        raise ExportError(f"Exporter '{target}' does not support required scene features: "
                          f"{names}; update the exporter before using this scene")


__all__ = ['ExportError', 'ExporterUnavailable', 'PEX25DSceneExporter', 'SceneFeature', 'require_scene_features']
