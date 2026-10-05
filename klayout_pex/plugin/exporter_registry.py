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

"""Lazy discovery and selection of PEX25D scene exporter plugins."""

from __future__ import annotations

from importlib import metadata
import inspect
from typing import List, Mapping, Optional, Tuple

from ..plugin_api.v1 import (
    EXPORTER_ENTRY_POINT_GROUP,
    ExportError,
    ExporterFactory,
    ExporterUnavailable,
    PEX25DSceneExporter,
)
from .pex25d_scene_exporter import ExporterInfo, ExporterRegistration


class ExporterRegistry:
    """Snapshot exporter entry points and optional built-in exporter factories.

    Discovery imports no plugin code. Each ``load`` creates a fresh exporter
    instance; failures and name conflicts are reported only for the selected
    exporter. Construct another registry to refresh installed metadata.
    """

    def __init__(self, builtins: Optional[Mapping[str, ExporterFactory]] = None):
        registrations: List[ExporterRegistration] = [
            ExporterRegistration(ExporterInfo(name, 'klayout-pex'),
                                 lambda factory=factory: factory, builtin=True)
            for name, factory in (builtins or {}).items()
        ]
        for entry_point in metadata.entry_points(group=EXPORTER_ENTRY_POINT_GROUP):
            try:
                distribution = entry_point.dist.name if entry_point.dist is not None else None
            except (KeyError, ValueError):
                distribution = None
            if not isinstance(distribution, str) or not distribution.strip():
                distribution = 'unknown'
            registrations.append(ExporterRegistration(
                ExporterInfo(entry_point.name, distribution), entry_point.load))
        self._registrations: Tuple[ExporterRegistration, ...] = tuple(sorted(
            registrations, key=lambda registration: registration.info.qualified_name))

    @property
    def exporters(self) -> Tuple[ExporterInfo, ...]:
        """List all registrations, including ambiguous or unavailable ones."""
        return tuple(registration.info for registration in self._registrations)

    def get_info(self, selector: str) -> ExporterInfo:
        """Resolve a selector to its provider metadata without loading code."""
        return self._registration(selector).info

    def _registration(self, selector: str) -> ExporterRegistration:
        if ':' in selector:
            distribution, name = selector.split(':', 1)
            qualified_name = ExporterInfo(name, distribution).qualified_name
            matches = [r for r in self._registrations if r.info.qualified_name == qualified_name]
        else:
            matches = [r for r in self._registrations if r.info.name == selector]
            builtins = [r for r in matches if r.builtin]
            if builtins:
                matches = builtins

        if not matches:
            raise ExportError(f"No exporter for '{selector}'")
        if len(matches) > 1:
            choices = ', '.join(r.info.qualified_name for r in matches)
            raise ExportError(
                f"Ambiguous exporter '{selector}': {choices}. "
                "Select a distribution:name; duplicate registrations within one "
                "distribution must be removed.")

        return matches[0]

    def load(self, selector: str) -> PEX25DSceneExporter:
        """Load a name or ``distribution:name``; built-ins win for bare names."""
        registration = self._registration(selector)
        try:
            factory = registration.load_factory()
            if not callable(factory):
                raise TypeError('entry point must be a zero-argument exporter factory')
            exporter = factory()
            if inspect.isclass(exporter) or not callable(getattr(exporter, 'export', None)):
                raise TypeError('factory must return an object with an export method')
        except ExportError:
            raise
        except Exception as exc:
            raise ExporterUnavailable(
                f"Could not load exporter '{registration.info.qualified_name}': "
                f"{type(exc).__name__}: {exc}") from exc
        return exporter
