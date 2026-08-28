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
Loading and saving PEX25D artifacts in any of the three encodings.

The two protobuf encodings are handled here — they are a
``SerializeToString`` away. The normative *text* format is delegated to
:mod:`~klayout_pex.pex25d.reader` and :mod:`~klayout_pex.pex25d.writer`.
"""

from __future__ import annotations

from typing import *

from .artifact import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactSpec,
    open_artifact_read,
    open_artifact_write,
)
from .diagnostics import DiagnosticsReport
from .protobuf import message_class_for_kind


def load_artifact(spec: ArtifactSpec,
                  report: Optional[DiagnosticsReport] = None,
                  with_source_refs: bool = False) -> Any:
    """
    Read an artifact and return the generated protobuf message it holds
    (``PEX25DFile`` or ``PEX25DScene``, per ``spec.kind``).

    Syntax- and semantic-tier findings from the text reader are appended to
    ``report`` when one is given; a fatal parse failure raises.
    """
    # Read first: a missing or unreadable input is the more likely mistake, and
    # is a better error than 'the generated protobuf modules are not built yet'.
    with open_artifact_read(spec) as f:
        data = f.read()

    match spec.format:
        case ArtifactFormat.PB:
            message = message_class_for_kind(spec.kind)()
            message.ParseFromString(data)
            return message

        case ArtifactFormat.TEXTPB:
            from google.protobuf import text_format
            message = message_class_for_kind(spec.kind)()
            text_format.Parse(data.decode('utf-8'), message)
            return message

        case ArtifactFormat.TEXT:
            if spec.kind != ArtifactKind.FILE:
                raise ValueError("The PEX25D text format only spells PEX25DFile")
            from .reader import read_pex25d_text
            return read_pex25d_text(data,
                                    source_name=spec.path,
                                    report=report,
                                    with_source_refs=with_source_refs)

        case _:
            raise ValueError(f"Unknown artifact format {spec.format}")


def save_artifact(message: Any, spec: ArtifactSpec, comments: bool = False) -> None:
    """
    Write a ``PEX25DFile`` / ``PEX25DScene`` in the encoding ``spec`` asks for.

    :param comments: emit the specification's syntax hints. Text format only —
        the protobuf encodings have no comments.
    """
    match spec.format:
        case ArtifactFormat.PB:
            data = message.SerializeToString()

        case ArtifactFormat.TEXTPB:
            from google.protobuf import text_format
            data = text_format.MessageToString(message, as_utf8=True).encode('utf-8')

        case ArtifactFormat.TEXT:
            if spec.kind != ArtifactKind.FILE:
                raise ValueError("The PEX25D text format only spells PEX25DFile")
            from .writer import write_pex25d_text
            data = write_pex25d_text(message, comments=comments)

        case _:
            raise ValueError(f"Unknown artifact format {spec.format}")

    with open_artifact_write(spec) as f:
        f.write(data)
