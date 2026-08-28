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
Validator output: coded, positioned diagnostics, and how they reach the user.

This can be used to check a custom PEX25D *writer* against the reference validator without depending on kpex internals
or on the exact wording of a message — so ``--diagnostics json`` and ``--diagnostics pb`` are first-class
outputs here, not a debugging afterthought.

Diagnostics are modelled as a plain dataclass rather than as the generated protobuf message, for two reasons:
    1) rendering must work on a checkout where the ``*_pb2`` modules have not been generated yet, and
    2) the human renderer wants to group and sort in ways the wire format has no opinion about.
    The conversion to``kpex.pex25d.Diagnostic`` happens only for ``--diagnostics pb``.
"""

from __future__ import annotations

import contextlib
import dataclasses
import enum
import json
import sys
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import *

from ..log import (
    error,
    warning,
    info,
    subproc,
)


class ExitCode(IntEnum):
    """
    Process exit codes, shared by ``kpex`` and ``pex25d``.

    Distinguishing OK from ERRORS from USAGE matters for the CI use case:
    a writer-conformance run wants to distinguish
        1) "your file is wrong"
        2) "you called me wrong"
        3) a crash
    """

    OK = 0
    DIAGNOSTIC_ERRORS = 1
    USAGE = 2
    NOT_IMPLEMENTED = 3


class Severity(IntEnum):
    NOTE = 1
    WARNING = 2
    ERROR = 3

    @property
    def proto_name(self) -> str:
        return f"SEVERITY_{self.name}"


class Tier(IntEnum):
    SYNTAX = 1     # arity, clause order, literal not a grid multiple, unknown record
    SEMANTIC = 2   # name resolution, acyclic WRAPS, depth ties, ...
    GEOMETRIC = 3  # ring and box shape, hole containment, overlap (--strict)

    @property
    def proto_name(self) -> str:
        return f"TIER_{self.name}"


class DiagnosticsFormat(StrEnum):
    """
    How validator output is rendered.

    ``human``
        Rich text for a terminal. Not stable; never parse it.
    ``json``
        One JSON object with a ``diagnostics`` array, mirroring the field names
        of ``kpex.pex25d.DiagnosticList``. Stable.
    ``pb``
        Binary ``kpex.pex25d.DiagnosticList``. Stable.
    """

    HUMAN = 'human'
    JSON = 'json'
    PB = 'pb'

    DEFAULT = 'human'


@dataclass(frozen=True)
class SourceRef:
    """Position in a PEX25D source file. Mirrors ``kpex.pex25d.SourceRef``."""

    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None

    def __str__(self) -> str:
        parts = [self.file or '<input>']
        if self.line is not None:
            parts.append(str(self.line))
            if self.column is not None:
                parts.append(str(self.column))
        return ':'.join(parts)


def source_ref(record: Any) -> Optional[SourceRef]:
    """The ``SourceRef`` of a protobuf record, or ``None`` if it carries none."""
    if record is None or not hasattr(record, 'HasField'):
        return None
    try:
        if not record.HasField('source'):
            return None
    except ValueError:
        return None
    source = record.source
    return SourceRef(file=source.file or None,
                     line=source.line or None,
                     column=source.column or None)


@dataclass(frozen=True)
class Diagnostic:
    """One validator finding. Mirrors ``kpex.pex25d.Diagnostic``."""

    code: str
    severity: Severity
    tier: Tier
    message: str
    source: Optional[SourceRef] = None
    related: Sequence[SourceRef] = ()

    def as_json_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            'code': self.code,
            'severity': self.severity.proto_name,
            'tier': self.tier.proto_name,
            'message': self.message,
        }
        if self.source is not None:
            d['source'] = dataclasses.asdict(self.source)
        if self.related:
            d['related'] = [dataclasses.asdict(r) for r in self.related]
        return d


@dataclass
class DiagnosticsReport:
    """Accumulates diagnostics and decides the process exit code."""

    diagnostics: List[Diagnostic] = field(default_factory=list)
    warnings_are_errors: bool = False

    def add(self, diagnostic: Diagnostic) -> None:
        self.diagnostics.append(diagnostic)

    def extend(self, diagnostics: Iterable[Diagnostic]) -> None:
        self.diagnostics.extend(diagnostics)

    @property
    def num_errors(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity == Severity.ERROR)

    @property
    def num_warnings(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity == Severity.WARNING)

    @property
    def exit_code(self) -> ExitCode:
        if self.num_errors:
            return ExitCode.DIAGNOSTIC_ERRORS
        if self.warnings_are_errors and self.num_warnings:
            return ExitCode.DIAGNOSTIC_ERRORS
        return ExitCode.OK

    # ---------------------------------------------------------------- rendering

    def render(self,
               format: DiagnosticsFormat,
               stream: Optional[IO[Any]] = None) -> None:
        match format:
            case DiagnosticsFormat.HUMAN:
                self._render_human()
            case DiagnosticsFormat.JSON:
                self._render_json(stream or sys.stdout)
            case DiagnosticsFormat.PB:
                self._render_pb(stream)
            case _:
                raise ValueError(f"Unknown diagnostics format {format}")

    def _render_human(self) -> None:
        by_tier: Dict[Tier, List[Diagnostic]] = {}
        for d in self.diagnostics:
            by_tier.setdefault(d.tier, []).append(d)

        for tier in sorted(by_tier.keys()):
            for d in by_tier[tier]:
                where = f"{d.source} " if d.source else ''
                line = f"{where}{d.code}: {d.message}"
                match d.severity:
                    case Severity.ERROR:
                        error(line)
                    case Severity.WARNING:
                        warning(line)
                    case _:
                        info(line)
                for r in d.related:
                    subproc(f"    … see also {r}")

        if not self.diagnostics:
            info("No diagnostics.")
        else:
            info(f"{self.num_errors} error(s), {self.num_warnings} warning(s), "
                 f"{len(self.diagnostics)} diagnostic(s) total")

    def _render_json(self, stream: IO[Any]) -> None:
        payload = {'diagnostics': [d.as_json_dict() for d in self.diagnostics]}
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if hasattr(stream, 'buffer') or isinstance(stream, io_text_types()):
            stream.write(text + '\n')
        else:
            stream.write((text + '\n').encode('utf-8'))
        stream.flush()

    def _render_pb(self, stream: Optional[IO[Any]]) -> None:
        from .protobuf import pex25d_diagnostics_pb2

        pb2 = pex25d_diagnostics_pb2()
        diagnostic_list = pb2.DiagnosticList()
        for d in self.diagnostics:
            pb = diagnostic_list.diagnostics.add()
            pb.code = d.code
            pb.severity = pb2.Diagnostic.Severity.Value(d.severity.proto_name)
            pb.tier = pb2.Diagnostic.Tier.Value(d.tier.proto_name)
            pb.message = d.message
            if d.source is not None:
                _fill_source_ref(pb.source, d.source)
            for r in d.related:
                _fill_source_ref(pb.related.add(), r)

        out = stream if stream is not None else sys.stdout.buffer
        out = getattr(out, 'buffer', out)
        out.write(diagnostic_list.SerializeToString())
        out.flush()


def _fill_source_ref(pb: Any, ref: SourceRef) -> None:
    if ref.file is not None:
        pb.file = ref.file
    if ref.line is not None:
        pb.line = ref.line
    if ref.column is not None:
        pb.column = ref.column


def io_text_types() -> Tuple[type, ...]:
    import io
    return (io.TextIOBase,)


@contextlib.contextmanager
def diagnostics_stream(writes_to_stdout: bool) -> Iterator[IO[Any]]:
    """
    Yield the stream diagnostics should be written to.

    When the verb's *artifact* output goes to stdout, diagnostics must not:
    a PEX25D file with a JSON diagnostics blob stapled to the front is not a PEX25D file.
    In that case diagnostics go to stderr, which is also where the rich logger already writes.
    """
    yield sys.stderr if writes_to_stdout else sys.stdout
