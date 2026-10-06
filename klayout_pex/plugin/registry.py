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

"""Lazy discovery and selection of plugins from one entry-point group."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
import inspect
import re
from typing import Any, Callable, ClassVar, List, Mapping, Optional, Tuple, Type

from ..version import __version__


@dataclass(frozen=True)
class PluginInfo:
    """Metadata available without importing the plugin implementation."""

    name: str
    distribution: str
    version: str = ''
    summary: str = ''
    """The package summary; for a built-in, the first line of its factory's docstring."""

    target: str = ''
    """The ``module:attribute`` the factory is loaded from."""

    @property
    def qualified_name(self) -> str:
        """An explicit selector, e.g. ``klayout-pex:fastercap``.

        Distribution names follow PyPA normalization. Plugin names remain
        case-sensitive. This requires no external packaging dependency.
        """
        distribution = re.sub(r'[-_.]+', '-', self.distribution).lower()
        return f'{distribution}:{self.name}'


@dataclass(frozen=True)
class PluginRegistration:
    """Associate metadata with a loader that defers importing its factory."""

    info: PluginInfo
    load_factory: Callable[[], Callable[[], Any]]
    builtin: bool = False


class PluginRegistry:
    """Snapshot one entry-point group and optional built-in plugin factories.

    Discovery imports no plugin code. Each ``load`` creates a fresh plugin
    instance; failures and name conflicts are reported only for the selected
    plugin. Construct another registry to refresh installed metadata.
    Subclasses name the capability: its entry-point group, required method
    and error types.
    """

    kind: ClassVar[str]
    """What a plugin is called in messages, e.g. ``exporter``."""

    group: ClassVar[str]
    method: ClassVar[str]
    error: ClassVar[Type[Exception]]
    unavailable: ClassVar[Type[Exception]]

    def __init__(self, builtins: Optional[Mapping[str, Callable[[], Any]]] = None):
        registrations: List[PluginRegistration] = [
            PluginRegistration(PluginInfo(name, 'klayout-pex', __version__,
                                          (inspect.getdoc(factory) or '').split('\n')[0],
                                          f'{factory.__module__}:{factory.__qualname__}'),
                               lambda factory=factory: factory, builtin=True)
            for name, factory in (builtins or {}).items()
        ]
        for entry_point in metadata.entry_points(group=self.group):
            try:
                distribution = entry_point.dist.name if entry_point.dist is not None else None
            except (KeyError, ValueError):
                distribution = None
            if not isinstance(distribution, str) or not distribution.strip():
                distribution = 'unknown'
            version, summary = _version_and_summary(entry_point.dist)
            registrations.append(PluginRegistration(
                PluginInfo(entry_point.name, distribution, version, summary, entry_point.value),
                entry_point.load))
        self._registrations: Tuple[PluginRegistration, ...] = tuple(sorted(
            registrations, key=lambda registration: registration.info.qualified_name))

    @property
    def plugins(self) -> Tuple[PluginInfo, ...]:
        """List all registrations, including ambiguous or unavailable ones."""
        return tuple(registration.info for registration in self._registrations)

    def selector(self, info: PluginInfo) -> str:
        """The shortest selector that loads ``info``: its bare name unless that is taken."""
        try:
            if self.get_info(info.name) == info:
                return info.name
        except self.error:
            pass
        return info.qualified_name

    def get_info(self, selector: str) -> PluginInfo:
        """Resolve a selector to its provider metadata without loading code."""
        return self._registration(selector).info

    def _registration(self, selector: str) -> PluginRegistration:
        if ':' in selector:
            distribution, name = selector.split(':', 1)
            qualified_name = PluginInfo(name, distribution).qualified_name
            matches = [r for r in self._registrations if r.info.qualified_name == qualified_name]
        else:
            matches = [r for r in self._registrations if r.info.name == selector]
            builtins = [r for r in matches if r.builtin]
            if builtins:
                matches = builtins

        if not matches:
            choices = ", ".join(info.qualified_name for info in self.plugins) or "(none)"
            raise self.error(f"No {self.kind} for '{selector}'. Available {self.kind}s: {choices}")
        if len(matches) > 1:
            choices = ', '.join(r.info.qualified_name for r in matches)
            raise self.error(
                f"Ambiguous {self.kind} '{selector}': {choices}. "
                "Select a distribution:name; duplicate registrations within one "
                "distribution must be removed.")

        return matches[0]

    def load(self, selector: str) -> Any:
        """Load a name or ``distribution:name``; built-ins win for bare names."""
        registration = self._registration(selector)
        try:
            factory = registration.load_factory()
            if not callable(factory):
                raise TypeError(f'entry point must be a zero-argument {self.kind} factory')
            plugin = factory()
            if inspect.isclass(plugin) or not callable(getattr(plugin, self.method, None)):
                raise TypeError(f'factory must return an object with an {self.method} method')
        except self.error:
            raise
        except Exception as exc:
            raise self.unavailable(
                f"Could not load {self.kind} '{registration.info.qualified_name}': "
                f"{type(exc).__name__}: {exc}") from exc
        return plugin


def _version_and_summary(distribution: Optional[metadata.Distribution]) -> Tuple[str, str]:
    """Read from package metadata; broken metadata must not hide the plugin."""
    try:
        package = distribution.metadata if distribution is not None else None
        if package is None:
            return '', ''
        return package.get('Version') or '', package.get('Summary') or ''
    except Exception:
        return '', ''


__all__ = ['PluginInfo', 'PluginRegistration', 'PluginRegistry']
