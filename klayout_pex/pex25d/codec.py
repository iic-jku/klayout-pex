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
    CANONICAL_SUFFIX,
    ArtifactFormat,
    ArtifactKind,
    ArtifactSpec,
    open_artifact_read,
    open_artifact_write,
)
from .diagnostics import DiagnosticsReport
from .protobuf import kind_for_message, message_class_for_kind


def load_artifact(spec: ArtifactSpec,
                  report: Optional[DiagnosticsReport] = None,
                  with_source_refs: bool = False) -> Any:
    """
    Read an artifact and return the generated protobuf message it holds
    (``PEX25DFile`` or ``PEX25DScene``, per ``spec.kind``).

    Syntax- and semantic-tier findings from the text reader are appended to
    ``report`` when one is given; a fatal parse failure raises.

    :raises ValueError: also if the protobuf can't be read, or holds the other kind
                        (which binary protobuf doesn't record: only its name or --in-kind says which)
    """
    # Read first: a missing or unreadable input is the more likely mistake, and
    # is a better error than 'the generated protobuf modules are not built yet'.
    with open_artifact_read(spec) as f:
        data = f.read()

    match spec.format:
        case ArtifactFormat.PB:
            from google.protobuf.message import DecodeError
            message = message_class_for_kind(spec.kind)()
            try:
                message.ParseFromString(data)
            except DecodeError as e:
                raise ValueError(f"Not a PEX25D {spec.kind.value} in binary protobuf: {e}") from e
            # NOTE: the fields of the other kind are unknown fields here, rather than an error
            if _unknown_field_count(message) and _holds_the_other_kind(spec, lambda m: m.ParseFromString(data)):
                raise _other_kind_error(spec)
            return message

        case ArtifactFormat.TEXTPB:
            from google.protobuf import text_format
            text = data.decode('utf-8')
            message = message_class_for_kind(spec.kind)()
            try:
                text_format.Parse(text, message)
            except text_format.ParseError as e:
                if _holds_the_other_kind(spec, lambda m: text_format.Parse(text, m)):
                    raise _other_kind_error(spec) from e
                raise ValueError(f"Not a PEX25D {spec.kind.value} in protobuf text format: {e}") from e
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


def _unknown_field_count(message: Any) -> int:
    """
    The fields of the message and of those within it that they don't know, which binary protobuf keeps
    """
    from google.protobuf import unknown_fields
    count = len(unknown_fields.UnknownFieldSet(message))
    for field, value in message.ListFields():
        if field.message_type is None or field.message_type.GetOptions().map_entry:
            continue
        for submessage in (value if field.is_repeated else [value]):
            count += _unknown_field_count(submessage)
    return count


def _other_kind(spec: ArtifactSpec) -> ArtifactKind:
    return ArtifactKind.SCENE if spec.kind == ArtifactKind.FILE else ArtifactKind.FILE


def _holds_the_other_kind(spec: ArtifactSpec, parse: Callable[[Any], None]) -> bool:
    """
    :param parse: reads the data into the given message
    :return: whether the message of the other kind reads all of the data
             (if neither kind does, it may be of a newer format version)
    """
    from google.protobuf.message import DecodeError
    from google.protobuf.text_format import ParseError
    other = message_class_for_kind(_other_kind(spec))()
    try:
        parse(other)
    except (DecodeError, ParseError):
        return False
    return not _unknown_field_count(other)


def _other_kind_error(spec: ArtifactSpec) -> ValueError:
    other = _other_kind(spec)
    return ValueError(f"It holds a PEX25D {other.value}, not a {spec.kind.value}: read it with --in-kind {other.value}, "
                      f"or name it NAME{CANONICAL_SUFFIX[(other, spec.format)]}")


def save_artifact(message: Any, spec: ArtifactSpec, comments: bool = False) -> None:
    """
    Write a ``PEX25DFile`` / ``PEX25DScene`` in the encoding ``spec`` asks for.

    :param comments: emit the specification's syntax hints. Text format only —
        the protobuf encodings have no comments.
    :raises ValueError: if the message is not the kind the spec describes. The
        text format spells a ``PEX25DFile`` only, and a scene written under a
        spec that says file would otherwise fail deep inside the writer.
    """
    kind = kind_for_message(message)
    if kind != spec.kind:
        raise ValueError(f"The artifact spec for '{spec.path}' says "
                         f"{spec.kind}, but the message is a {kind}")

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
