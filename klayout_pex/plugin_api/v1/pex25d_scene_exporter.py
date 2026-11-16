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
from typing import TYPE_CHECKING, Any, FrozenSet, List, Mapping, Optional, Protocol, Set

if TYPE_CHECKING:
    from klayout_pex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene


class ExportError(RuntimeError):
    """The scene could not be written out for the requested target."""


class ExporterUnavailable(ExportError):
    """The backend for a target is not loadable in this installation."""


class SceneCapability(Enum):
    """Scene contracts an exporter must implement before receiving them."""

    CAPACITANCE_ACCOUNTING = 'capacitance-accounting'
    """Typed exclusion masks, charge groups and result filtering."""

    GROUND_CUTOUTS = 'ground-cutouts'
    """Explicit polygon openings through the ground slab and its coatings."""

    ELECTRICAL_IDENTITY = 'electrical-identity'
    """Ground reference net and FLOATING identity independent of output labels."""


class PEX25DSceneExporter(Protocol):
    """Write solver inputs from a resolved ``PEX25DScene`` without running it.

    The caller owns the scene; exporters must not mutate it. Implementations
    validate their own options and reject unsupported capabilities with ExportError.
    NotImplementedError marks what an exporter does not implement yet.
    Geometry libraries and other optional dependencies should be imported only
    when needed, so metadata discovery remains usable without them.
    """

    @classmethod
    def supported_capabilities(cls) -> FrozenSet[SceneCapability]:
        """Return the scene contracts implemented by this exporter class.

        Querying support must not construct an exporter, import optional geometry
        libraries, or write output. Derived exporters may extend this immutable
        set with ``super().supported_capabilities()``. The default promises no
        additional capabilities; accepting protobuf fields alone is not support.
        """
        return frozenset()

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


def require_scene_capabilities(exporter: PEX25DSceneExporter, scene: Any, target: str):
    """Fail before writing if a consumer does not implement required scene semantics."""
    from ...pex25d.electrical import solver_body_names
    required: Set[SceneCapability] = set()
    declared_capabilities = getattr(scene, 'required_capabilities', ())
    has_policy = getattr(scene, 'capacitance_accounting', None) is not None and scene.HasField('capacitance_accounting')
    has_parts = any(getattr(region, 'accounting_part_id', '') or getattr(region, 'accounting_regions', ())
                    for conductor in scene.conductors for region in getattr(conductor, 'regions', ()))
    if declared_capabilities or has_policy or has_parts:
        from ...pex25d.capability_validation import validate_required_capabilities
        from ...pex25d.diagnostics import DiagnosticsReport
        from ...pex25d.protobuf import pex25d_capabilities_pb2
        report = DiagnosticsReport()
        if not validate_required_capabilities(scene, report):
            raise ExportError('Unsupported or missing required scene capability: ' +
                              '; '.join(d.message for d in report.diagnostics))
        accounting = pex25d_capabilities_pb2().REQUIRED_CAPABILITY_CAPACITANCE_ACCOUNTING
        if accounting in declared_capabilities:
            required.add(SceneCapability.CAPACITANCE_ACCOUNTING)
    if scene.HasField('ground_plane'):
        ground = scene.ground_plane
        if ground.cutouts:
            required.add(SceneCapability.GROUND_CUTOUTS)
        if ground.net and ground.net != ground.name:
            required.add(SceneCapability.ELECTRICAL_IDENTITY)
    if any(body.name != name for body, name in solver_body_names(scene).items()):
        required.add(SceneCapability.ELECTRICAL_IDENTITY)
    if not required:
        return
    declaration = getattr(exporter, 'supported_capabilities', None)
    # Structural implementations without the method support ordinary scenes only.
    if declaration is None:
        supported = frozenset()
    else:
        if not callable(declaration):
            raise ExportError(f"Exporter '{target}' must declare supported_capabilities() as a class method")
        supported = declaration()
        if not isinstance(supported, frozenset) or any(
                not isinstance(capability, SceneCapability) for capability in supported):
            raise ExportError(f"Exporter '{target}' supported_capabilities() must return "
                              "a frozenset of SceneCapability members")
    missing = required - supported
    if missing:
        names = ', '.join(sorted(capability.value for capability in missing))
        raise ExportError(f"Exporter '{target}' does not support required scene capabilities: "
                          f"{names}; update the exporter before using this scene")


__all__ = ['ExportError', 'ExporterUnavailable', 'PEX25DSceneExporter', 'SceneCapability', 'require_scene_capabilities']
