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

The CLI exposes this operation as ``pex25d export``.

Exporting is the one part of this package that is not pure format work: turning
a scene into a solver's input needs polygon booleans and meshing, so a backend
depends on a geometry library. Backends are therefore imported on use, and a
missing dependency is reported rather than surfacing as an ImportError from an
unexpected place. Reading, validating, converting and resolving stay
dependency-free.
"""

from __future__ import annotations

from typing import *

from ..plugin_api.v1 import ExportError, ExporterUnavailable, PEX25DSceneExporter

if TYPE_CHECKING:
    from ..plugin.exporter_registry import ExporterRegistry
    from klayout_pex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene


class ExporterExecutionError(ExportError):
    """An exporter crashed; the original exception is preserved as the cause."""


def export(scene: PEX25DScene,
           target: str,
           output_dir_path: str,
           prefix: str = '',
           options: Optional[Mapping[str, Any]] = None,
           *,
           registry: Optional[ExporterRegistry] = None) -> List[str]:
    """
    Export ``scene`` as native input for ``target`` into ``output_dir_path``.

    Does not run the engine. ``target`` is an exporter entry-point name or
    a qualified ``distribution:name``. Options are passed to the selected
    exporter, which owns their schema and validation.

    Pass a registry to reuse its metadata snapshot across multiple exports.
    Without one, installed exporters are discovered for this call.

    :return: only paths written by this call, primary input first — for FasterCap
        the ``.lst``, its referenced surface files, and any requested STL files.
    """
    registry = registry if registry is not None else exporter_registry()
    backend = registry.load(target)
    return export_with_backend(backend, scene, target, output_dir_path,
                                prefix, options, registry=registry)


def export_with_backend(backend: PEX25DSceneExporter,
                        scene: PEX25DScene,
                        target: str,
                        output_dir_path: str,
                        prefix: str = '',
                        options: Optional[Mapping[str, Any]] = None,
                        *,
                        registry: Optional[ExporterRegistry] = None) -> List[str]:
    """Export with an already loaded backend, which need not be registered.

    ``target`` identifies the backend in error messages. Only an unexpected
    exception triggers provider lookup; a supplied registry reuses its metadata
    snapshot for that lookup. If lookup fails, the message uses ``target``.
    The backend is reused without another factory call. ExportError, NotImplementedError
    and OSError pass through unchanged; unexpected exceptions become ExporterExecutionError
    with their original cause. Return paths follow the contract of ``export``.
    """
    try:
        return backend.export(scene, output_dir_path=output_dir_path, prefix=prefix, options=options)
    except (ExportError, NotImplementedError, OSError):
        raise
    except Exception as exc:
        provider = target
        try:
            registry = registry if registry is not None else exporter_registry()
            provider = registry.get_info(target).qualified_name
        except Exception:
            pass  # Metadata failures must not hide the exporter's original crash.
        raise ExporterExecutionError(
            f"Exporter '{provider}' crashed: {type(exc).__name__}: {exc}") from exc


def exporter_registry() -> ExporterRegistry:
    """Discover installed exporters alongside the two built-in implementations."""
    from ..plugin.exporter_registry import ExporterRegistry
    return ExporterRegistry({
        'fastercap': create_fastercap_exporter,
        'fastcap2': create_fastcap2_exporter,
    })


def create_fastercap_exporter() -> PEX25DSceneExporter:
    """Construct the FasterCap protocol implementation without geometry imports."""
    from ..fastercap.pex25d_exporter import FasterCapSceneExporter
    return FasterCapSceneExporter()


def create_fastcap2_exporter() -> PEX25DSceneExporter:
    """Construct the FastCap2 protocol implementation without geometry imports."""
    from ..fastercap.pex25d_exporter import FastCap2SceneExporter
    return FastCap2SceneExporter()
