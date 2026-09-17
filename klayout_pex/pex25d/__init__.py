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
The PEX25D Module
-----------------

Support for the **PEX25D** interchange format for 2.5D parasitic extraction
(see https://github.com/iic-jku/klayout-pex/issues/184).

The pipeline is::

    PEX25D (text) –[reader]→ PEX25DFile (protobuf) –[resolver]→ PEX25DScene (protobuf) –[adapter]→ solver

One import covers it::

    from klayout_pex import pex25d

    file = pex25d.read('cell.pex25d')
    scene = pex25d.resolve(file)
    report = pex25d.validate(file, scene=scene)
    pex25d.write(scene, 'cell.pex25d.scene.pb')

``read`` and ``write`` take a path in any of the encodings the format defines,
``read_text`` and ``write_text`` the bytes of the text format. Everything named
in ``__all__`` is the supported surface; the submodules stay importable for the
classes behind the verbs (``resolver.Resolver``, ``validator.Validator``).

Dependency rule
~~~~~~~~~~~~~~~

This package depends on ``protobuf`` only — no ``klayout`` import, directly or
transitively. That is what lets the standalone ``pex25d`` tool be installed and
run by other groups as a reference validator, without dragging in the whole LVS
machinery. Generating PEX25D from a layout does need that machinery, and lives
in :mod:`klayout_pex.klayout.pex25d_builder` instead.

The generated ``*_pb2`` modules are build output, so nothing here imports one
while this module is imported: :data:`proto` and the verbs reach them on demand
and report a missing build as :class:`ProtobufNotGeneratedError`.
"""

from __future__ import annotations

from typing import *

from . import protobuf
from .artifact import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactNamingError,
    ArtifactSpec,
    STDIO_PATH,
    derive_path,
    infer_artifact_spec,
)
from .codec import load_artifact, save_artifact
from .diagnostics import (
    Diagnostic,
    DiagnosticsFormat,
    DiagnosticsReport,
    ExitCode,
    Severity,
    SourceRef,
    Tier,
)
from .exporters import (
    ExportError,
    ExporterOptions,
    ExporterUnavailable,
    SolverTarget,
    export,
)
from .format_version import (
    FORMAT_VERSION_MAJOR,
    FORMAT_VERSION_MINOR,
    FORMAT_VERSION_SUFFIX,
)
from .protobuf import ProtobufNotGeneratedError, kind_for_message
from .reader import ReadError, read_pex25d_text
from .resolver import ResolveError, resolve
from .show import show
from .validator import validate
from .writer import WriteError, write_pex25d_text

read_text = read_pex25d_text
"""Parse the bytes of the PEX25D text format into a ``PEX25DFile``."""

write_text = write_pex25d_text
"""Render a ``PEX25DFile`` or ``PEX25DScene`` as PEX25D text bytes."""


class _Proto:
    """
    The generated PEX25D protobuf modules and their top-level messages.

    Nothing is listed here: the modules come from
    :func:`protobuf.schema_names` and the messages from
    :func:`protobuf.message_class_for_kind`, so a schema change that adds,
    renames or removes a ``.proto`` needs no edit. Attribute access imports on
    demand, so that a tree without the generated modules still imports this
    package.
    """

    def _message_classes(self) -> Dict[str, Any]:
        classes: Dict[str, Any] = {}
        for kind in ArtifactKind:
            try:
                message_class = protobuf.message_class_for_kind(kind)
            except ValueError:  # a kind that describes no message, i.e. AUTO
                continue
            classes[message_class.DESCRIPTOR.name] = message_class
        return classes

    def __getattr__(self, name: str) -> Any:
        if name.startswith('_'):
            raise AttributeError(name)

        if name in protobuf.schema_names():
            return protobuf.schema_module(name)

        message_classes = self._message_classes()
        if name in message_classes:
            return message_classes[name]

        raise AttributeError(f"PEX25D has no protobuf module or message "
                             f"'{name}', expected one of {', '.join(dir(self))}")

    def __dir__(self) -> List[str]:
        return sorted([*protobuf.schema_names(), *self._message_classes()])


proto = _Proto()
"""The generated messages, e.g. ``proto.PEX25DFile()`` or ``proto.dielectric``."""


kind_of = kind_for_message
"""The :class:`ArtifactKind` a generated message holds."""


def read(path: str,
         kind: ArtifactKind = ArtifactKind.AUTO,
         format: ArtifactFormat = ArtifactFormat.AUTO,
         report: Optional[DiagnosticsReport] = None,
         with_source_refs: bool = False) -> Any:
    """
    Read a PEX25D artifact and return the message it holds.

    Kind and encoding come from the path's suffix, which is why the
    conventional suffixes matter: ``.pex25d.scene.pb`` is a scene, ``.pex25d``
    a file in text format. State them explicitly for a path that has none
    (``-`` is stdin).
    """
    spec = infer_artifact_spec(path, kind=kind, format=format)
    return load_artifact(spec, report=report, with_source_refs=with_source_refs)


def write(message: Any,
          path: str,
          kind: ArtifactKind = ArtifactKind.AUTO,
          format: ArtifactFormat = ArtifactFormat.AUTO,
          comments: bool = False) -> None:
    """
    Write a ``PEX25DFile`` or ``PEX25DScene`` to ``path``.

    The encoding comes from the suffix; the kind is the message's own, so that
    a scene is never written under a spec that says file (``-`` is stdout).

    :param comments: emit the specification's syntax hints. Text format only.
    """
    spec = infer_artifact_spec(path, kind=kind, format=format,
                               default_kind=kind_of(message))
    save_artifact(message, spec, comments=comments)


__all__ = [
    # verbs
    'read',
    'read_text',
    'write',
    'write_text',
    'resolve',
    'validate',
    'export',
    'show',
    # artifacts
    'ArtifactFormat',
    'ArtifactKind',
    'ArtifactSpec',
    'STDIO_PATH',
    'derive_path',
    'infer_artifact_spec',
    'kind_of',
    'load_artifact',
    'save_artifact',
    # diagnostics
    'Diagnostic',
    'DiagnosticsFormat',
    'DiagnosticsReport',
    'ExitCode',
    'Severity',
    'SourceRef',
    'Tier',
    # errors
    'ArtifactNamingError',
    'ExportError',
    'ExporterUnavailable',
    'ProtobufNotGeneratedError',
    'ReadError',
    'ResolveError',
    'WriteError',
    # the rest
    'ExporterOptions',
    'SolverTarget',
    'FORMAT_VERSION_MAJOR',
    'FORMAT_VERSION_MINOR',
    'FORMAT_VERSION_SUFFIX',
    'proto',
    # deprecated aliases, use read_text / write_text
    'read_pex25d_text',
    'write_pex25d_text',
]
