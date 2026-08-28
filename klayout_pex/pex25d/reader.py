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

"""PEX25D text format reader."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import *

from .diagnostics import Diagnostic, DiagnosticsReport, Severity, SourceRef, Tier
from .format_version import FORMAT_VERSION_MAJOR
from .protobuf import (
    pex25d_dielectric_pb2,
    pex25d_file_pb2,
    pex25d_terminal_pb2,
)

STDIO_NAME = '-'

# Decimal or scientific notation, optional leading sign, '.5' and '5.' both
# legal. Deliberately stricter than Fraction(str), which would also accept
# ratios like '1/2' and digit separators like '1_0'.
NUMBER = re.compile(r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\Z')

VERSION = re.compile(r'(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?\Z')

LENGTH_UNITS = {'um': 1, 'nm': 2, 'm': 3}

# A clause keyword appearing where a top-level record is expected nearly always
# means a dropped '\' continuation. Skipping it would silently build a different
# scene, so it is an error rather than an unknown record.
CLAUSE_KEYWORDS = {
    'WRAPS', 'PERMITTIVITY', 'BETWEEN', 'CONNECTS', 'Z_OFFSETS', 'LAYER',
    'LL', 'UR', 'OUTER', 'HOLE', 'X', 'Y', 'Z', 'SHEET', 'PER_CUT',
    'TC1', 'TC2', 'KIND', 'TEMPERATURE',
    'THICKNESS_OVER_WRAPPED', 'THICKNESS_BESIDE_WRAPPED', 'THICKNESS_ON_FIELD',
}

TERMINAL_KINDS = {'PIN': 1, 'DEVICE_TERMINAL': 2}


class ReadError(Exception):
    """The file could not be read; the report carries the reasons."""


@dataclass
class Record:
    """One logical record: a physical line, plus whatever '\\' continued it."""

    tokens: List[str]
    file: str
    line: int

    @property
    def head(self) -> str:
        return self.tokens[0]

    def ref(self) -> SourceRef:
        return SourceRef(file=self.file, line=self.line)


class Cursor:
    """Walks a record's tokens, reporting what it expected when they run out."""

    def __init__(self, record: Record, reader: 'Pex25DTextReader'):
        self.record = record
        self.reader = reader
        self.position = 1  # token 0 is the record keyword

    @property
    def exhausted(self) -> bool:
        return self.position >= len(self.record.tokens)

    def peek(self) -> Optional[str]:
        return None if self.exhausted else self.record.tokens[self.position]

    def take(self, expected: str) -> Optional[str]:
        if self.exhausted:
            self.reader.error('PEX25D-E0101',
                              f"{self.record.head}: expected {expected}, but the "
                              f"record ends", self.record)
            return None
        value = self.record.tokens[self.position]
        self.position += 1
        return value

    def keyword(self, *allowed: str) -> Optional[str]:
        value = self.take(' or '.join(allowed))
        if value is None:
            return None
        if value not in allowed:
            self.reader.error('PEX25D-E0102',
                              f"{self.record.head}: expected {' or '.join(allowed)}, "
                              f"found '{value}'", self.record)
            return None
        return value

    def grid(self, what: str) -> Optional[int]:
        value = self.take(what)
        return None if value is None else self.reader.to_grid(value, self.record, what)

    def number(self, what: str) -> Optional[float]:
        value = self.take(what)
        return None if value is None else self.reader.to_double(value, self.record, what)

    def end(self) -> None:
        if not self.exhausted:
            extra = ' '.join(self.record.tokens[self.position:])
            self.reader.error('PEX25D-E0103',
                              f"{self.record.head}: unexpected trailing tokens "
                              f"'{extra}'", self.record)


def split_records(text: str, filename: str) -> Iterator[Record]:
    """
    Turn UTF-8 text into logical records.

    Comments run from an unquoted '#' to the end of the line; a trailing '\\'
    continues a record onto the next line. A record's reported line is the one
    its first token is on, which is what a diagnostic should point at.
    """
    pending: List[str] = []
    start_line = 0

    for number, raw in enumerate(text.splitlines(), start=1):
        line, continued = strip_comment(raw)
        if not pending:
            start_line = number
        pending.append(line)
        if continued:
            continue

        tokens = tokenize(' '.join(pending))
        pending = []
        if tokens:
            yield Record(tokens=tokens, file=filename, line=start_line)

    if pending:
        tokens = tokenize(' '.join(pending))
        if tokens:
            yield Record(tokens=tokens, file=filename, line=start_line)


def strip_comment(line: str) -> Tuple[str, bool]:
    """Remove an unquoted comment; report whether the record continues."""
    out: List[str] = []
    quoted = False
    for char in line:
        if char == '"':
            quoted = not quoted
        elif char == '#' and not quoted:
            break
        out.append(char)
    text = ''.join(out).rstrip()
    if text.endswith('\\'):
        return text[:-1], True
    return text, False


def tokenize(line: str) -> List[str]:
    """Whitespace-separated tokens, with a double-quoted run kept as one."""
    tokens: List[str] = []
    current: List[str] = []
    quoted = False
    has_token = False

    for char in line:
        if char == '"':
            quoted = not quoted
            has_token = True
        elif char.isspace() and not quoted:
            if has_token:
                tokens.append(''.join(current))
            current, has_token = [], False
        else:
            current.append(char)
            has_token = True

    if has_token:
        tokens.append(''.join(current))
    return tokens


class Pex25DTextReader:
    def __init__(self,
                 report: Optional[DiagnosticsReport] = None,
                 with_source_refs: bool = False):
        self.report = report if report is not None else DiagnosticsReport()
        self.with_source_refs = with_source_refs
        self.errors = 0

        self.file = pex25d_file_pb2().PEX25DFile()
        self.grid: Optional[Fraction] = None
        self.seen_header = False
        self.meta_keys: Dict[str, str] = {}
        self.include_stack: List[str] = []

    # ---------------------------------------------------------- diagnostics

    def diagnose(self, code: str, message: str, record: Optional[Record],
                 tier: Tier, severity: Severity) -> None:
        if severity == Severity.ERROR:
            self.errors += 1
        self.report.add(Diagnostic(code=code, severity=severity, tier=tier,
                                   message=message,
                                   source=record.ref() if record else None))

    def error(self, code: str, message: str, record: Optional[Record] = None,
              tier: Tier = Tier.SYNTAX) -> None:
        self.diagnose(code, message, record, tier, Severity.ERROR)

    def warn(self, code: str, message: str, record: Optional[Record] = None,
             tier: Tier = Tier.SYNTAX) -> None:
        self.diagnose(code, message, record, tier, Severity.WARNING)

    def source_of(self, record: Record) -> Optional[Any]:
        if not self.with_source_refs:
            return None
        from .protobuf import pex25d_source_ref_pb2
        ref = pex25d_source_ref_pb2().SourceRef()
        ref.file = record.file
        ref.line = record.line
        return ref

    def attach_source(self, message: Any, record: Record) -> None:
        source = self.source_of(record)
        if source is not None:
            message.source.CopyFrom(source)

    # -------------------------------------------------------------- numbers

    def to_fraction(self, text: str, record: Record, what: str) -> Optional[Fraction]:
        if not NUMBER.match(text):
            self.error('PEX25D-E0104',
                       f"{what}: '{text}' is not a numeric literal", record)
            return None
        return Fraction(text)

    def to_grid(self, text: str, record: Record, what: str) -> Optional[int]:
        """
        Convert a literal into an integer count of grid units.

        Divide, round, compare — never a modulo. In binary floating point
        `0.3262 % 0.0001` is `9.9999999999e-05`, and an exact-modulo check would
        reject legal files. Here the arithmetic is exact rational anyway, and
        the 1e-6 window is what the specification asks for.
        """
        if self.grid is None:
            self.error('PEX25D-E0106',
                       f"{what}: UNITS must precede any record containing a number",
                       record)
            return None
        value = self.to_fraction(text, record, what)
        if value is None:
            return None
        quotient = value / self.grid
        rounded = round(quotient)
        if abs(quotient - rounded) > Fraction(1, 10 ** 6):
            self.error('PEX25D-E0105',
                       f"{what}: {text} is not an integer multiple of the grid",
                       record)
            return None
        return int(rounded)

    def to_double(self, text: str, record: Record, what: str) -> Optional[float]:
        """Permittivities, resistances and temperatures are not grid-quantized."""
        value = self.to_fraction(text, record, what)
        return None if value is None else float(value)

    # --------------------------------------------------------------- driving

    def read(self, data: bytes, source_name: Optional[str]) -> Any:
        filename = source_name or STDIO_NAME
        # The top-level file goes on the include stack too, so that a file
        # including its way back to it is caught there rather than one level on.
        if filename != STDIO_NAME:
            self.include_stack.append(os.path.normpath(os.path.abspath(filename)))
        self.consume(data.decode('utf-8'), filename, top_level=True)

        if not self.seen_header:
            self.error('PEX25D-E0107', "The file does not start with a PEX25D record")
        if self.errors:
            raise ReadError(f"{self.errors} error(s) while reading the file")
        return self.file

    def consume(self, text: str, filename: str, top_level: bool = False) -> None:
        for record in split_records(text, filename):
            if top_level and not self.seen_header and record.head != 'PEX25D':
                self.error('PEX25D-E0107',
                           f"PEX25D must be the first record; found "
                           f"'{record.head}'", record)
                self.seen_header = True  # report it once

            handler = self.HANDLERS.get(record.head)
            if handler is not None:
                handler(self, record)
            elif record.head in CLAUSE_KEYWORDS:
                # Almost always a dropped '\' continuation. Skipping it the way
                # an unknown record is skipped would build a different scene.
                self.error('PEX25D-E0103',
                           f"'{record.head}' is a clause keyword, not a record — "
                           f"a continuation '\\' was probably dropped", record)
            else:
                self.warn('PEX25D-W0110',
                          f"Skipping unrecognized top-level record "
                          f"'{record.head}'", record)

    def read_include(self, record: Record) -> None:
        cursor = Cursor(record, self)
        path = cursor.take('a path')
        cursor.end()
        if path is None:
            return

        # Relative paths resolve against the directory of the including file;
        # for stdin there is no such directory, so the current one is used.
        base = os.path.dirname(os.path.abspath(record.file)) \
            if record.file != STDIO_NAME else os.getcwd()
        resolved = os.path.normpath(os.path.join(base, path))

        if resolved in self.include_stack:
            chain = ' -> '.join(self.include_stack + [resolved])
            self.error('PEX25D-E0109', f"INCLUDE cycle: {chain}", record)
            return

        try:
            with open(resolved, 'rb') as f:
                text = f.read().decode('utf-8')
        except OSError as e:
            self.error('PEX25D-E0109', f"Can't read INCLUDE '{path}': {e}", record)
            return

        # INCLUDE is textual: the included records are treated as if they
        # appeared in its place, which is why one PEX25DFile is a whole include
        # tree flattened, and why SourceRef.file is load-bearing.
        self.include_stack.append(resolved)
        self.consume(text, resolved)
        self.include_stack.pop()

    # -------------------------------------------------------------- records

    def read_header(self, record: Record) -> None:
        if self.seen_header:
            self.error('PEX25D-E0107', "Duplicate PEX25D record", record)
            return
        self.seen_header = True

        cursor = Cursor(record, self)
        version = cursor.take('a version')
        cursor.end()
        if version is None:
            return

        match = VERSION.match(version)
        if match is None:
            self.error('PEX25D-E0107',
                       f"'{version}' is not a MAJOR.MINOR[-SUFFIX] version", record)
            return

        major, minor, suffix = int(match.group(1)), int(match.group(2)), match.group(3)
        if major != FORMAT_VERSION_MAJOR:
            # A reader must accept any minor version of the major it supports,
            # and refuse a major it does not: a major bump can change how
            # existing keywords are interpreted.
            self.error('PEX25D-E0107',
                       f"This implementation reads PEX25D {FORMAT_VERSION_MAJOR}.x, "
                       f"the file declares {major}.{minor}", record)
            return

        self.file.format_version_major = major
        self.file.format_version_minor = minor
        if suffix:
            self.file.format_version_suffix = suffix

    def read_units(self, record: Record) -> None:
        cursor = Cursor(record, self)
        if cursor.keyword('LENGTH') is None:
            return
        unit = cursor.take('um, nm or m')
        if unit is None:
            return
        if unit not in LENGTH_UNITS:
            self.error('PEX25D-E0102',
                       f"UNITS LENGTH: '{unit}' is not one of "
                       f"{', '.join(LENGTH_UNITS)}", record)
            return
        if cursor.keyword('GRID') is None:
            return
        grid_text = cursor.take('the grid')
        cursor.end()
        if grid_text is None:
            return

        grid = self.to_fraction(grid_text, record, 'UNITS GRID')
        if grid is None:
            return
        if grid <= 0:
            self.error('PEX25D-E0104', "UNITS GRID must be positive", record)
            return

        self.grid = grid
        units = self.file.units
        units.length = LENGTH_UNITS[unit]
        units.grid_numerator = grid.numerator
        units.grid_denominator = grid.denominator

    def read_meta(self, record: Record) -> None:
        cursor = Cursor(record, self)
        key = cursor.take('a key')
        value = cursor.take('a value')
        cursor.end()
        if key is None or value is None:
            return

        # A key may appear at most once across the file and everything it
        # includes. Because record order is not significant, "the last one wins"
        # would have no meaning.
        if key in self.meta_keys:
            self.error('PEX25D-E0108',
                       f"META key '{key}' is already set in {self.meta_keys[key]}",
                       record, tier=Tier.SEMANTIC)
            return
        self.meta_keys[key] = f"{record.file}:{record.line}"

        meta = self.file.meta.add()
        meta.key, meta.value = key, value
        self.attach_source(meta, record)

        # The text format has no UNITS clause for the source DBU; META carries
        # it, and a reader fills the Units field from it.
        if key == 'source_dbu':
            dbu = self.to_fraction(value, record, 'META source_dbu')
            if dbu is not None and dbu > 0:
                self.file.units.source_dbu_numerator = dbu.numerator
                self.file.units.source_dbu_denominator = dbu.denominator

    def read_ground_plane(self, record: Record) -> None:
        cursor = Cursor(record, self)
        name = cursor.take('a name')
        if name is None or cursor.keyword('Z_OFFSETS') is None:
            return
        zlow = cursor.grid('GROUND_PLANE zlow')
        zhigh = cursor.grid('GROUND_PLANE zhigh')
        cursor.end()
        if zlow is None or zhigh is None:
            return
        if self.file.HasField('ground_plane'):
            self.error('PEX25D-E0210', "More than one GROUND_PLANE", record,
                       tier=Tier.SEMANTIC)
            return
        self.file.ground_plane.name = name
        self.file.ground_plane.zlow, self.file.ground_plane.zhigh = zlow, zhigh
        self.attach_source(self.file.ground_plane, record)

    def read_metal(self, record: Record) -> None:
        cursor = Cursor(record, self)
        name = cursor.take('a name')
        if name is None or cursor.keyword('Z_OFFSETS') is None:
            return
        zlow = cursor.grid('METAL zlow')
        zhigh = cursor.grid('METAL zhigh')
        cursor.end()
        if zlow is None or zhigh is None:
            return
        metal = self.file.metals.add()
        metal.name, metal.zlow, metal.zhigh = name, zlow, zhigh
        self.attach_source(metal, record)

    def read_via(self, record: Record) -> None:
        cursor = Cursor(record, self)
        name = cursor.take('a name')
        if name is None or cursor.keyword('CONNECTS') is None:
            return
        below = cursor.take('the layer below')
        above = cursor.take('the layer above')
        cursor.end()
        if below is None or above is None:
            return
        via = self.file.vias.add()
        via.name, via.connects_below, via.connects_above = name, below, above
        self.attach_source(via, record)

    def read_dielectric_simple(self, record: Record) -> None:
        kinds = pex25d_dielectric_pb2()
        cursor = Cursor(record, self)
        name = cursor.take('a name')
        if name is None or cursor.keyword('WRAPS') is None:
            return
        wraps = cursor.take('the wrapped profile')
        if wraps is None or cursor.keyword('PERMITTIVITY') is None:
            return
        permittivity = cursor.number('PERMITTIVITY')
        if permittivity is None or cursor.keyword('BETWEEN') is None:
            return
        below = cursor.take('the object below')
        above = cursor.take('the object above')
        cursor.end()
        if below is None or above is None:
            return

        dielectric = self.file.dielectrics.add()
        dielectric.name, dielectric.wraps = name, wraps
        dielectric.kind = kinds.DIELECTRIC_KIND_SIMPLE
        dielectric.permittivity = permittivity
        dielectric.simple.between_below, dielectric.simple.between_above = below, above
        self.attach_source(dielectric, record)

    def read_dielectric_conformal(self, record: Record) -> None:
        kinds = pex25d_dielectric_pb2()
        cursor = Cursor(record, self)
        name = cursor.take('a name')
        if name is None or cursor.keyword('WRAPS') is None:
            return
        wraps = cursor.take('the wrapped profile')
        if wraps is None or cursor.keyword('PERMITTIVITY') is None:
            return
        permittivity = cursor.number('PERMITTIVITY')
        if permittivity is None:
            return

        thicknesses: Dict[str, int] = {}
        for keyword in ('THICKNESS_OVER_WRAPPED', 'THICKNESS_BESIDE_WRAPPED',
                        'THICKNESS_ON_FIELD'):
            if cursor.keyword(keyword) is None:
                return
            value = cursor.grid(keyword)
            if value is None:
                return
            thicknesses[keyword] = value
        cursor.end()

        dielectric = self.file.dielectrics.add()
        dielectric.name, dielectric.wraps = name, wraps
        dielectric.kind = kinds.DIELECTRIC_KIND_CONFORMAL
        dielectric.permittivity = permittivity
        conformal = dielectric.conformal
        conformal.thickness_over_wrapped = thicknesses['THICKNESS_OVER_WRAPPED']
        conformal.thickness_beside_wrapped = thicknesses['THICKNESS_BESIDE_WRAPPED']
        conformal.thickness_on_field = thicknesses['THICKNESS_ON_FIELD']
        self.attach_source(dielectric, record)

    def read_dielectric_background(self, record: Record) -> None:
        cursor = Cursor(record, self)
        name = cursor.take('a name')
        if name is None or cursor.keyword('PERMITTIVITY') is None:
            return
        permittivity = cursor.number('PERMITTIVITY')
        cursor.end()
        if permittivity is None:
            return
        if self.file.HasField('background'):
            self.error('PEX25D-E0213', "More than one DIELECTRIC_BACKGROUND", record,
                       tier=Tier.SEMANTIC)
            return
        self.file.background.name = name
        self.file.background.permittivity = permittivity
        self.attach_source(self.file.background, record)

    def read_conductor(self, record: Record) -> None:
        cursor = Cursor(record, self)
        name = cursor.take('a shortname')
        net = cursor.take('a net name')
        cursor.end()
        if name is None or net is None:
            return
        conductor = self.file.conductors.add()
        conductor.name, conductor.net = name, net
        self.attach_source(conductor, record)

    def read_box(self, record: Record) -> None:
        kinds = pex25d_file_pb2().ShapeRecord
        cursor = Cursor(record, self)
        if cursor.keyword('CONDUCTOR') is None:
            return
        conductor = cursor.take('a conductor shortname')
        if conductor is None or cursor.keyword('LAYER') is None:
            return
        layer = cursor.take('a layer name')
        if layer is None or cursor.keyword('LL') is None:
            return
        x0, y0 = cursor.grid('BOX LL x'), cursor.grid('BOX LL y')
        if cursor.keyword('UR') is None:
            return
        x1, y1 = cursor.grid('BOX UR x'), cursor.grid('BOX UR y')
        cursor.end()
        if None in (x0, y0, x1, y1):
            return

        shape = self.file.shapes.add()
        shape.conductor, shape.layer = conductor, layer
        shape.kind = kinds.SHAPE_KIND_BOX
        shape.box.lower_left.x, shape.box.lower_left.y = x0, y0
        shape.box.upper_right.x, shape.box.upper_right.y = x1, y1
        self.attach_source(shape, record)

    def read_polygon(self, record: Record) -> None:
        kinds = pex25d_file_pb2().ShapeRecord
        cursor = Cursor(record, self)
        if cursor.keyword('CONDUCTOR') is None:
            return
        conductor = cursor.take('a conductor shortname')
        if conductor is None or cursor.keyword('LAYER') is None:
            return
        layer = cursor.take('a layer name')
        if layer is None or cursor.keyword('OUTER') is None:
            return

        outer = self.read_ring(cursor, record, 'OUTER')
        if outer is None:
            return
        holes = []
        while cursor.peek() == 'HOLE':
            cursor.take('HOLE')
            hole = self.read_ring(cursor, record, 'HOLE')
            if hole is None:
                return
            holes.append(hole)
        cursor.end()

        shape = self.file.shapes.add()
        shape.conductor, shape.layer = conductor, layer
        shape.kind = kinds.SHAPE_KIND_POLYGON
        fill_ring(shape.polygon.outer, outer)
        for hole in holes:
            fill_ring(shape.polygon.holes.add(), hole)
        self.attach_source(shape, record)

    def read_ring(self, cursor: Cursor, record: Record,
                  keyword: str) -> Optional[List[Tuple[int, int]]]:
        """
        Read vertices until the next keyword or the end of the record.

        Rings are implicitly closed, so the first vertex is not repeated.
        """
        points: List[Tuple[int, int]] = []
        while not cursor.exhausted and cursor.peek() not in ('HOLE',):
            x = cursor.grid(f"{keyword} x")
            y = cursor.grid(f"{keyword} y")
            if x is None or y is None:
                return None
            points.append((x, y))

        if len(points) < 3:
            self.error('PEX25D-E0101',
                       f"POLYGON {keyword}: a ring needs at least three vertices, "
                       f"found {len(points)}", record)
            return None
        return points

    def read_terminal(self, record: Record) -> None:
        cursor = Cursor(record, self)
        name = cursor.take('a name')
        if name is None or cursor.keyword('CONDUCTOR') is None:
            return
        conductor = cursor.take('a conductor shortname')
        if conductor is None or cursor.keyword('LAYER') is None:
            return
        layer = cursor.take('a layer name')
        if layer is None:
            return

        kind = 0
        if cursor.peek() == 'KIND':
            cursor.take('KIND')
            spelling = cursor.take('a terminal kind')
            if spelling is None:
                return
            if spelling not in TERMINAL_KINDS:
                self.error('PEX25D-E0102',
                           f"TERMINAL KIND: '{spelling}' is not one of "
                           f"{', '.join(TERMINAL_KINDS)}", record)
                return
            kind = TERMINAL_KINDS[spelling]

        if cursor.keyword('LL') is None:
            return
        x0, y0 = cursor.grid('TERMINAL LL x'), cursor.grid('TERMINAL LL y')
        if cursor.keyword('UR') is None:
            return
        x1, y1 = cursor.grid('TERMINAL UR x'), cursor.grid('TERMINAL UR y')
        cursor.end()
        if None in (x0, y0, x1, y1):
            return

        terminal = self.file.terminals.add()
        terminal.name, terminal.conductor, terminal.layer = name, conductor, layer
        terminal.kind = kind
        terminal.region.lower_left.x, terminal.region.lower_left.y = x0, y0
        terminal.region.upper_right.x, terminal.region.upper_right.y = x1, y1
        self.attach_source(terminal, record)

    def read_resistance(self, record: Record) -> None:
        cursor = Cursor(record, self)
        what = cursor.keyword('TEMPERATURE', 'METAL', 'VIA')
        if what is None:
            return

        if what == 'TEMPERATURE':
            celsius = cursor.number('RESISTANCE TEMPERATURE')
            cursor.end()
            if celsius is None:
                return
            self.file.resistance_temperature.celsius = celsius
            self.attach_source(self.file.resistance_temperature, record)
            return

        name = cursor.take('a profile name')
        if name is None:
            return
        value_keyword = 'SHEET' if what == 'METAL' else 'PER_CUT'
        if cursor.keyword(value_keyword) is None:
            return
        value = cursor.number(f"RESISTANCE {what} {value_keyword}")
        if value is None:
            return

        coefficients: Dict[str, float] = {}
        for keyword in ('TC1', 'TC2'):
            if cursor.peek() != keyword:
                break
            cursor.take(keyword)
            coefficient = cursor.number(f"RESISTANCE {what} {keyword}")
            if coefficient is None:
                return
            coefficients[keyword] = coefficient
        cursor.end()

        if what == 'METAL':
            resistance = self.file.metal_resistances.add()
            resistance.metal, resistance.sheet = name, value
        else:
            resistance = self.file.via_resistances.add()
            resistance.via, resistance.per_cut = name, value
        if coefficients:
            resistance.tc.tc1 = coefficients.get('TC1', 0.0)
            resistance.tc.tc2 = coefficients.get('TC2', 0.0)
        self.attach_source(resistance, record)

    def read_domain_margin(self, record: Record) -> None:
        cursor = Cursor(record, self)
        values: Dict[str, int] = {}
        for axis in ('X', 'Y', 'Z'):
            if cursor.keyword(axis) is None:
                return
            value = cursor.grid(f"DOMAIN_MARGIN {axis}")
            if value is None:
                return
            values[axis] = value
        cursor.end()
        margin = self.file.domain_margin
        margin.x, margin.y, margin.z = values['X'], values['Y'], values['Z']

    def read_domain_box(self, record: Record) -> None:
        cursor = Cursor(record, self)
        corners: Dict[str, List[int]] = {}
        for keyword in ('LL', 'UR'):
            if cursor.keyword(keyword) is None:
                return
            coordinates = []
            for axis in 'xyz':
                value = cursor.grid(f"DOMAIN_BOX {keyword} {axis}")
                if value is None:
                    return
                coordinates.append(value)
            corners[keyword] = coordinates
        cursor.end()

        box = self.file.domain_box.box
        box.lower_left.x, box.lower_left.y, box.lower_left.z = corners['LL']
        box.upper_right.x, box.upper_right.y, box.upper_right.z = corners['UR']
        self.attach_source(self.file.domain_box, record)

    HANDLERS: Dict[str, Callable[['Pex25DTextReader', Record], None]] = {}


Pex25DTextReader.HANDLERS = {
    'PEX25D': Pex25DTextReader.read_header,
    'UNITS': Pex25DTextReader.read_units,
    'META': Pex25DTextReader.read_meta,
    'INCLUDE': Pex25DTextReader.read_include,
    'GROUND_PLANE': Pex25DTextReader.read_ground_plane,
    'METAL': Pex25DTextReader.read_metal,
    'VIA': Pex25DTextReader.read_via,
    'DIELECTRIC_SIMPLE': Pex25DTextReader.read_dielectric_simple,
    'DIELECTRIC_CONFORMAL': Pex25DTextReader.read_dielectric_conformal,
    'DIELECTRIC_BACKGROUND': Pex25DTextReader.read_dielectric_background,
    'CONDUCTOR': Pex25DTextReader.read_conductor,
    'BOX': Pex25DTextReader.read_box,
    'POLYGON': Pex25DTextReader.read_polygon,
    'TERMINAL': Pex25DTextReader.read_terminal,
    'RESISTANCE': Pex25DTextReader.read_resistance,
    'DOMAIN_MARGIN': Pex25DTextReader.read_domain_margin,
    'DOMAIN_BOX': Pex25DTextReader.read_domain_box,
}


def fill_ring(ring: Any, points: Sequence[Tuple[int, int]]) -> None:
    for x, y in points:
        point = ring.points.add()
        point.x, point.y = x, y


def read_pex25d_text(data: bytes,
                     source_name: Optional[str] = None,
                     report: Optional[DiagnosticsReport] = None,
                     with_source_refs: bool = False) -> Any:
    """
    Parse the PEX25D text format into a ``kpex.pex25d.PEX25DFile``.

    :param data: raw UTF-8 bytes of the top-level file. ``INCLUDE`` is textual,
        so the result covers the whole include tree, flattened.
    :param source_name: path used for ``SourceRef.file`` and for resolving
        relative includes; for ``-`` they resolve against the current directory.
    :param report: collects syntax- and semantic-tier diagnostics.
    :param with_source_refs: record where each message came from. Off by
        default, like every other source-ref switch, so that a text-to-protobuf
        conversion is idempotent; worth turning on when reading an include tree,
        which is the case the field exists for. Diagnostics carry positions
        either way.
    :raises ReadError: when the file could not be read; the reasons are in
        ``report``.
    """
    return Pex25DTextReader(report=report,
                            with_source_refs=with_source_refs).read(data, source_name)
