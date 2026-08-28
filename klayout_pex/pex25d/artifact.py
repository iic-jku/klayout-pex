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
Naming, format inference and stdio handling for PEX25D artifacts.

There are two orthogonal properties of every PEX25D artifact on disk:

``kind``
    Which message it holds — the unresolved ``PEX25DFile`` as written by a
    reader, or the resolved ``PEX25DScene`` as consumed by a solver adapter.

``format``
    How that message is encoded — the normative PEX25D *text* format, binary
    protobuf, or protobuf text format.

Both are inferred from the file name, and either can be overridden
(``--kind`` / ``--format``). The naming convention is::

    foo.pex25d                  text format, PEX25DFile
    foo.pex25d.pb               binary protobuf, PEX25DFile
    foo.pex25d.textpb           protobuf text format, PEX25DFile
    foo.pex25d.scene.pb         binary protobuf, PEX25DScene
    foo.pex25d.scene.textpb     protobuf text format, PEX25DScene

i.e. the ``.scene`` infix selects the kind and the final extension selects the
format. There is deliberately no text-format spelling of a scene: the text
format is the *unresolved* format, and resolution is not reversible.
"""

from __future__ import annotations

import contextlib
import gzip
import io
import os
import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import *


# A single '-' as a path means stdin (for inputs) or stdout (for outputs).
STDIO_PATH = '-'


class ArtifactKind(StrEnum):
    """Which PEX25D message an artifact holds."""

    AUTO = 'auto'    # infer from the path
    FILE = 'file'    # kpex.pex25d.PEX25DFile   — literal, unresolved
    SCENE = 'scene'  # kpex.pex25d.PEX25DScene  — resolved, adapter-ready


class ArtifactFormat(StrEnum):
    """How a PEX25D message is encoded."""

    AUTO = 'auto'      # infer from the path
    TEXT = 'text'      # the normative PEX25D text format (PEX25DFile only)
    PB = 'pb'          # binary protobuf
    TEXTPB = 'textpb'  # protobuf text format


# Suffix table, longest first so that '.pex25d.scene.pb' is matched before
# '.pex25d.pb' would be. Gzip is handled separately, by stripping a trailing
# '.gz' before the lookup — the repo already writes '.gds.gz' and layout-sized
# PEX25D text compresses extremely well.
_SUFFIXES: List[Tuple[str, ArtifactKind, ArtifactFormat]] = [
    ('.pex25d.scene.textpb', ArtifactKind.SCENE, ArtifactFormat.TEXTPB),
    ('.pex25d.scene.pb',     ArtifactKind.SCENE, ArtifactFormat.PB),
    ('.pex25d.textpb',       ArtifactKind.FILE,  ArtifactFormat.TEXTPB),
    ('.pex25d.pb',           ArtifactKind.FILE,  ArtifactFormat.PB),
    ('.pex25d',              ArtifactKind.FILE,  ArtifactFormat.TEXT),
]

# Canonical spelling for each (kind, format) pair, used when a verb has to
# derive an output name from an input name.
CANONICAL_SUFFIX: Dict[Tuple[ArtifactKind, ArtifactFormat], str] = {
    (kind, fmt): suffix for suffix, kind, fmt in reversed(_SUFFIXES)
}


class ArtifactNamingError(ValueError):
    """The kind or format of an artifact could not be determined."""


@dataclass(frozen=True)
class ArtifactSpec:
    """A fully determined artifact: where it lives, what it holds, how it is encoded."""

    path: str
    kind: ArtifactKind
    format: ArtifactFormat
    gzipped: bool = False

    @property
    def is_stdio(self) -> bool:
        return self.path == STDIO_PATH

    @property
    def is_binary(self) -> bool:
        return self.format == ArtifactFormat.PB or self.gzipped

    def __str__(self) -> str:
        where = '<stdin>/<stdout>' if self.is_stdio else self.path
        return f"{where} ({self.kind.value}, {self.format.value}{', gzipped' if self.gzipped else ''})"


def infer_artifact_spec(path: str,
                        kind: ArtifactKind = ArtifactKind.AUTO,
                        format: ArtifactFormat = ArtifactFormat.AUTO,
                        default_kind: ArtifactKind = ArtifactKind.FILE,
                        default_format: ArtifactFormat = ArtifactFormat.TEXT) -> ArtifactSpec:
    """
    Determine an artifact's kind and encoding from its path, honouring explicit
    overrides.

    Inference is by suffix (see the table above). For ``-`` (stdio) there is no
    suffix to inspect, so the explicit values are used, falling back to
    ``default_kind`` / ``default_format`` — which is why every verb that accepts
    ``-`` states its defaults in ``--help``.

    :raises ArtifactNamingError: if the path carries no recognized suffix and no
        override was given, or if the resulting combination cannot exist.
    """
    gzipped = False
    inferred_kind = default_kind
    inferred_format = default_format

    if path != STDIO_PATH:
        name = os.path.basename(path)
        if name.endswith('.gz'):
            gzipped = True
            name = name[:-len('.gz')]

        for suffix, suffix_kind, suffix_format in _SUFFIXES:
            if name.endswith(suffix):
                inferred_kind = suffix_kind
                inferred_format = suffix_format
                break
        else:
            if kind == ArtifactKind.AUTO or format == ArtifactFormat.AUTO:
                raise ArtifactNamingError(
                    f"Can't tell what kind of PEX25D artifact '{path}' is meant to be. "
                    f"Use one of the conventional suffixes "
                    f"({', '.join(suffix for suffix, _, _ in reversed(_SUFFIXES))}), "
                    f"or state the encoding explicitly — see --help for the "
                    f"--format / --kind options this command offers."
                )

    effective_kind = inferred_kind if kind == ArtifactKind.AUTO else kind
    effective_format = inferred_format if format == ArtifactFormat.AUTO else format

    if effective_kind == ArtifactKind.SCENE and effective_format == ArtifactFormat.TEXT:
        raise ArtifactNamingError(
            "The PEX25D text format has no spelling for a resolved scene — it is the "
            "unresolved format, and resolution is not reversible. Write the scene as "
            "'pb' or 'textpb', or write the unresolved file as 'text'."
        )

    return ArtifactSpec(path=path,
                        kind=effective_kind,
                        format=effective_format,
                        gzipped=gzipped)


@contextlib.contextmanager
def open_artifact_read(spec: ArtifactSpec) -> Iterator[BinaryIO]:
    """
    Open an artifact for reading, as bytes.

    Bytes rather than text even for the text formats: the PEX25D reader scans
    decimal digits straight into scaled integers and wants to control decoding
    itself (the format is UTF-8 by definition, so there is nothing to negotiate).
    """
    if spec.is_stdio:
        # sys.__stdin__ rather than sys.stdin: when an artifact is written to
        # stdout the process redirects sys.stdout to stderr so that logging can
        # never corrupt the stream, and the artifact I/O must bypass that.
        stream: BinaryIO = sys.__stdin__.buffer
        if spec.gzipped:
            with gzip.GzipFile(fileobj=stream, mode='rb') as f:
                yield cast(BinaryIO, f)
        else:
            yield stream
        return

    opener = gzip.open if spec.gzipped else open
    with opener(spec.path, 'rb') as f:
        yield cast(BinaryIO, f)


@contextlib.contextmanager
def open_artifact_write(spec: ArtifactSpec) -> Iterator[BinaryIO]:
    """
    Open an artifact for writing, as bytes.

    Note that when the destination is stdout, *nothing else may be written
    there* — diagnostics and progress go to stderr. See
    :func:`klayout_pex.pex25d.diagnostics.diagnostics_stream`.
    """
    if spec.is_stdio:
        # The real stdout, not the redirected sys.stdout — see open_artifact_read.
        stream: BinaryIO = sys.__stdout__.buffer
        if spec.gzipped:
            with gzip.GzipFile(fileobj=stream, mode='wb') as f:
                yield cast(BinaryIO, f)
        else:
            yield stream
        stream.flush()
        return

    parent = os.path.dirname(os.path.abspath(spec.path))
    os.makedirs(parent, exist_ok=True)

    opener = gzip.open if spec.gzipped else open
    with opener(spec.path, 'wb') as f:
        yield cast(BinaryIO, f)


def derive_path(source_path: str,
                kind: ArtifactKind,
                format: ArtifactFormat) -> str:
    """
    Derive a sibling artifact path from an existing one, e.g. ``foo.pex25d`` →
    ``foo.pex25d.scene.pb``. Used only where a verb offers a default output
    location; a verb never writes to a derived path without saying so.
    """
    if source_path == STDIO_PATH:
        return STDIO_PATH

    name = os.path.basename(source_path)
    if name.endswith('.gz'):
        name = name[:-len('.gz')]
    for suffix, _, _ in _SUFFIXES:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    else:
        name = os.path.splitext(name)[0]

    return os.path.join(os.path.dirname(source_path),
                        name + CANONICAL_SUFFIX[(kind, format)])
