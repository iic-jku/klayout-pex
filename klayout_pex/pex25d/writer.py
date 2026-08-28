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

"""PEX25D text format writer."""

from __future__ import annotations

from fractions import Fraction
from typing import *

from ..log import warning

from .format_version import (
    FORMAT_VERSION_MAJOR,
    FORMAT_VERSION_MINOR,
    FORMAT_VERSION_SUFFIX,
)
from .protobuf import pex25d_dielectric_pb2, pex25d_file_pb2, pex25d_terminal_pb2


# Wrap a record onto continuation lines beyond this width, counting the
# trailing continuation marker.
WRAP_COLUMN = 96
CONTINUATION = ' \\'
WRAP_BUDGET = WRAP_COLUMN - len(CONTINUATION)

LENGTH_UNIT_NAMES = {1: 'um', 2: 'nm', 3: 'm'}


class WriteError(ValueError):
    pass


def format_exact(value: Fraction) -> str:
    """
    Render an exact rational as a decimal literal, without going through a float.

    Every coordinate in PEX25D is an integer count of grid units, so its value in
    the declared LENGTH unit is exactly ``value * grid`` — a rational whose
    denominator divides the grid's. Formatting it via a float would reintroduce
    the very representation error the integer grid exists to avoid.
    """
    numerator, denominator = value.numerator, value.denominator
    sign = '-' if numerator < 0 else ''
    numerator = abs(numerator)

    twos = fives = 0
    remainder = denominator
    while remainder % 2 == 0:
        remainder //= 2
        twos += 1
    while remainder % 5 == 0:
        remainder //= 5
        fives += 1
    if remainder != 1:
        # Not representable as a finite decimal. No PDK grid looks like this,
        # but a file could ask for one, and silently rounding is worse than
        # saying so.
        raise WriteError(f"{value} has no finite decimal representation "
                         f"(grid denominator has a factor of {remainder})")

    places = max(twos, fives)
    scaled = numerator * 10 ** places // denominator
    digits = str(scaled).rjust(places + 1, '0')
    whole, fraction = digits[:len(digits) - places], digits[len(digits) - places:]
    fraction = fraction.rstrip('0') or '0'
    return f"{sign}{whole}.{fraction}"


def format_double(value: float) -> str:
    """Permittivities and resistances are physical values, not grid multiples."""
    text = repr(float(value))
    return text if ('.' in text or 'e' in text or 'E' in text) else f"{text}.0"


def quote(value: str) -> str:
    """Quote a META value that would otherwise tokenize as more than one token."""
    if value and not any(c.isspace() for c in value):
        return value
    if '"' in value:
        warning(f"META value contains a quote character, which PEX25D does not "
                f"define an escape for: {value!r}")
    return f'"{value}"'


class Pex25DTextWriter:
    """Renders a ``kpex.pex25d.PEX25DFile`` as PEX25D text."""

    def __init__(self, pex25d_file: Any, comments: bool = False):
        self.file = pex25d_file
        self.comments = comments
        self.lines: List[str] = []

        units = pex25d_file.units
        if not units.grid_denominator:
            raise WriteError("The file declares no grid; UNITS cannot be written")
        self.grid = Fraction(units.grid_numerator, units.grid_denominator)

    # ---------------------------------------------------------------- helpers

    def length(self, grid_units: int) -> str:
        return format_exact(Fraction(grid_units) * self.grid)

    def emit(self, line: str = '') -> None:
        self.lines.append(line)

    def section(self, title: str) -> None:
        self.emit()
        self.emit(f"#---------------- {title} ----------------")

    def hint(self, *lines: str) -> None:
        """Emit a syntax hint from the specification, under --comments."""
        if not self.comments:
            return
        for line in lines:
            self.emit(f"# {line}" if line else "#")

    def emit_record(self, head: str, clauses: Sequence[str],
                    group: int = 1) -> None:
        """
        Emit one record, continuing onto further lines when it grows too wide.

        Clause order within a record is significant, so clauses are never
        reordered; only the line breaks between them are chosen here. A clause
        that is still too wide on a line of its own — a polygon ring — is broken
        further, on a boundary of ``group`` tokens so that coordinate pairs stay
        together.
        """
        lines: List[str] = [head]
        for clause in clauses:
            if len(lines[-1]) + 1 + len(clause) <= WRAP_BUDGET:
                lines[-1] += ' ' + clause
            else:
                lines += self.wrap_clause(clause, group)

        for line in lines[:-1]:
            self.emit(line + CONTINUATION)
        self.emit(lines[-1])

    @staticmethod
    def wrap_clause(clause: str, group: int) -> List[str]:
        """Break one clause across continuation lines, on `group`-token boundaries."""
        indent = '    '
        keyword, *tokens = clause.split(' ')
        lines = [f"{indent}{keyword}"]
        for start in range(0, len(tokens), group):
            chunk = ' '.join(tokens[start:start + group])
            if len(lines[-1]) + 1 + len(chunk) <= WRAP_BUDGET:
                lines[-1] += ' ' + chunk
            else:
                lines.append(f"{indent}{' ' * len(keyword)} {chunk}")
        return lines

    # --------------------------------------------------------------- sections

    def write(self) -> str:
        self.write_header()
        self.write_ground_plane()
        self.write_layers()
        self.write_dielectrics()
        self.write_resistance()
        self.write_conductors()
        self.write_terminals()
        self.write_domain()
        return '\n'.join(self.lines).lstrip('\n') + '\n'

    def write_header(self) -> None:
        version = f"{self.file.format_version_major}.{self.file.format_version_minor}"
        if self.file.format_version_suffix:
            version += f"-{self.file.format_version_suffix}"
        if (self.file.format_version_major, self.file.format_version_minor) != \
                (FORMAT_VERSION_MAJOR, FORMAT_VERSION_MINOR):
            warning(f"Writing a PEX25D {version} file from an implementation of "
                    f"{FORMAT_VERSION_MAJOR}.{FORMAT_VERSION_MINOR}")

        self.section('HEADER')
        self.hint("PEX25D <major>.<minor>[-<suffix>]")
        self.emit(f"PEX25D {version}")

        units = self.file.units
        unit_name = LENGTH_UNIT_NAMES.get(units.length)
        if unit_name is None:
            raise WriteError(f"The file declares no LENGTH unit")
        self.hint("UNITS LENGTH <um|nm|m> GRID <value>, in that unit.",
                  "Every coordinate, Z_OFFSETS, THICKNESS_* and margin is an integer",
                  "multiple of GRID.")
        self.emit(f"UNITS LENGTH {unit_name} GRID {format_exact(self.grid)}")

        keys = {meta.key for meta in self.file.meta}
        if self.file.meta:
            self.hint("",
                      "META <key> <value> is informational only, and never changes how",
                      "geometry or material is interpreted. A key may appear at most",
                      "once across the file and everything it INCLUDEs.")
        for meta in self.file.meta:
            self.emit(f"META {meta.key} {quote(meta.value)}")

        # The text format has no UNITS clause for the source DBU; META carries it.
        # Emitting it here keeps a message that has one from losing it.
        if units.source_dbu_denominator and 'source_dbu' not in keys:
            source_dbu = Fraction(units.source_dbu_numerator,
                                  units.source_dbu_denominator)
            self.emit(f"META source_dbu {format_exact(source_dbu)}")

    def write_ground_plane(self) -> None:
        if not self.file.HasField('ground_plane'):
            warning("The file declares no GROUND_PLANE; PEX25D requires exactly one")
            return
        ground_plane = self.file.ground_plane
        self.section('GROUND PLANE')
        self.hint("GROUND_PLANE <name> Z_OFFSETS <zlow> <zhigh>",
                  "An infinite XY conductor at 0 V. There is exactly one.")
        self.emit(f"GROUND_PLANE {ground_plane.name} "
                  f"Z_OFFSETS {self.length(ground_plane.zlow)} "
                  f"{self.length(ground_plane.zhigh)}")

    def write_layers(self) -> None:
        if not self.file.metals and not self.file.vias:
            return
        self.section('LAYERS (metal / via)')
        self.hint("METAL <name> Z_OFFSETS <zlow> <zhigh>",
                  "GROUND_PLANE and METAL are the only records carrying absolute z.")
        for metal in self.file.metals:
            self.emit(f"METAL {metal.name} "
                      f"Z_OFFSETS {self.length(metal.zlow)} {self.length(metal.zhigh)}")
        if self.file.vias:
            self.hint("",
                      "VIA <name> CONNECTS <below> <above>",
                      "A via fills the gap between what it connects, so its extent",
                      "follows a change in metal position or thickness on its own.")
        for via in self.file.vias:
            self.emit(f"VIA {via.name} "
                      f"CONNECTS {via.connects_below} {via.connects_above}")

    def write_dielectrics(self) -> None:
        if not self.file.dielectrics and not self.file.HasField('background'):
            return
        kinds = pex25d_dielectric_pb2()
        self.section('DIELECTRICS')
        self.hint("DIELECTRIC_SIMPLE <name> WRAPS <name> PERMITTIVITY <k> \\",
                  "    BETWEEN <below> <above>",
                  "DIELECTRIC_CONFORMAL <name> WRAPS <name> PERMITTIVITY <k> \\",
                  "    THICKNESS_OVER_WRAPPED <v> THICKNESS_BESIDE_WRAPPED <v> \\",
                  "    THICKNESS_ON_FIELD <v>",
                  "",
                  "Occupancy is decided by WRAPS depth, not by the order of these",
                  "records: at each point the dielectric with the SMALLEST depth whose",
                  "solid contains it wins, and conductors beat every dielectric.",
                  "",
                  "A conformal's thicknesses are measured from the surface of the",
                  "profile it wraps, so a chain of films composes. THICKNESS_ON_FIELD",
                  "is measured up from the BOTTOM face of the wrapped object.",
                  "",
                  "A simple dielectric spans the BOTTOM of <below> to the BOTTOM of",
                  "<above>, so the band always joins the neighbouring levels.")

        for dielectric in self.file.dielectrics:
            clauses = [f"WRAPS {dielectric.wraps}",
                       f"PERMITTIVITY {format_double(dielectric.permittivity)}"]

            if dielectric.kind == kinds.DIELECTRIC_KIND_SIMPLE:
                simple = dielectric.simple
                clauses.append(f"BETWEEN {simple.between_below} {simple.between_above}")
                head = f"DIELECTRIC_SIMPLE {dielectric.name}"
            elif dielectric.kind == kinds.DIELECTRIC_KIND_CONFORMAL:
                conformal = dielectric.conformal
                clauses += [
                    f"THICKNESS_OVER_WRAPPED {self.length(conformal.thickness_over_wrapped)}",
                    f"THICKNESS_BESIDE_WRAPPED {self.length(conformal.thickness_beside_wrapped)}",
                    f"THICKNESS_ON_FIELD {self.length(conformal.thickness_on_field)}",
                ]
                head = f"DIELECTRIC_CONFORMAL {dielectric.name}"
            else:
                raise WriteError(f"Dielectric '{dielectric.name}' has no kind")

            self.emit_record(head, clauses)

        if self.file.HasField('background'):
            background = self.file.background
            self.hint("",
                      "DIELECTRIC_BACKGROUND <name> PERMITTIVITY <k>",
                      "Fills every volume no conductor and no dielectric claims.")
            self.emit(f"DIELECTRIC_BACKGROUND {background.name} "
                      f"PERMITTIVITY {format_double(background.permittivity)}")
        else:
            warning("The file declares no DIELECTRIC_BACKGROUND; PEX25D requires one")

    def write_resistance(self) -> None:
        has_resistance = (self.file.HasField('resistance_temperature')
                          or self.file.metal_resistances
                          or self.file.via_resistances)
        if not has_resistance:
            return
        self.section('RESISTANCE')
        self.hint("RESISTANCE TEMPERATURE <celsius>",
                  "RESISTANCE METAL <name> SHEET <ohm_per_square> [TC1 <v>] [TC2 <v>]",
                  "RESISTANCE VIA <name> PER_CUT <ohm> [TC1 <v>] [TC2 <v>]",
                  "",
                  "Ohm, and NOT grid-quantized — these are material values.")

        if self.file.HasField('resistance_temperature'):
            celsius = self.file.resistance_temperature.celsius
            self.emit(f"RESISTANCE TEMPERATURE {format_double(celsius)}")

        def temperature_coefficients(record: Any) -> List[str]:
            if not record.HasField('tc'):
                return []
            return [f"TC1 {format_double(record.tc.tc1)}",
                    f"TC2 {format_double(record.tc.tc2)}"]

        for record in self.file.metal_resistances:
            if not record.HasField('sheet'):
                warning(f"Metal resistance for '{record.metal}' has no SHEET value; "
                        f"skipping")
                continue
            self.emit_record(f"RESISTANCE METAL {record.metal}",
                             [f"SHEET {format_double(record.sheet)}"]
                             + temperature_coefficients(record))

        for record in self.file.via_resistances:
            if not record.HasField('per_cut'):
                warning(f"Via resistance for '{record.via}' has no PER_CUT value; "
                        f"skipping")
                continue
            self.emit_record(f"RESISTANCE VIA {record.via}",
                             [f"PER_CUT {format_double(record.per_cut)}"]
                             + temperature_coefficients(record))

    def write_conductors(self) -> None:
        if not self.file.conductors and not self.file.shapes:
            return
        self.section('NETS and SHAPES')
        self.hint("CONDUCTOR <shortname> <net>",
                  "BOX CONDUCTOR <c> LAYER <l> LL <x> <y> UR <x> <y>",
                  "POLYGON CONDUCTOR <c> LAYER <l> OUTER <x> <y> ... [HOLE <x> <y> ...]",
                  "",
                  "A conductor is one equipotential body; all its shapes are unioned.",
                  "Two conductors may share a net and stay separate bodies. The",
                  "reserved net name FLOATING marks a body belonging to no net.",
                  "",
                  "LAYER names a METAL or VIA profile. Rings are implicitly closed.",
                  "There is no via-array construct: every cut is its own record, so",
                  "that the dielectric between cuts is present in the scene.")

        for conductor in self.file.conductors:
            self.emit(f"CONDUCTOR {conductor.name} {conductor.net}")

        # Grouped per conductor so the file reads in the same order it declares
        # them; within a conductor the original order is kept.
        order = {conductor.name: index
                 for index, conductor in enumerate(self.file.conductors)}
        undeclared = sorted({shape.conductor for shape in self.file.shapes
                             if shape.conductor not in order})
        if undeclared:
            warning(f"Shapes reference conductors that are not declared: "
                    f"{', '.join(undeclared)}")
        for name in undeclared:
            order[name] = len(order)

        for name in sorted(order, key=lambda n: order[n]):
            shapes = [s for s in self.file.shapes if s.conductor == name]
            if not shapes:
                continue
            self.emit()
            for shape in shapes:
                self.write_shape(shape)

    def write_shape(self, shape: Any) -> None:
        kinds = pex25d_file_pb2().ShapeRecord

        if shape.kind == kinds.SHAPE_KIND_BOX:
            box = shape.box
            self.emit(f"BOX CONDUCTOR {shape.conductor} LAYER {shape.layer} "
                      f"LL {self.length(box.lower_left.x)} {self.length(box.lower_left.y)} "
                      f"UR {self.length(box.upper_right.x)} {self.length(box.upper_right.y)}")
            return

        if shape.kind != kinds.SHAPE_KIND_POLYGON:
            raise WriteError(f"Shape on conductor '{shape.conductor}', layer "
                             f"'{shape.layer}' has no kind")

        def ring(keyword: str, points: Any) -> str:
            coordinates = ' '.join(f"{self.length(p.x)} {self.length(p.y)}"
                                   for p in points)
            return f"{keyword} {coordinates}"

        polygon = shape.polygon
        # Rings are implicitly closed, so the first vertex is not repeated. Each
        # ring goes on its own continuation line — they are long, and a reader
        # diffing two files wants them to line up.
        clauses = [ring('OUTER', polygon.outer.points)]
        clauses += [ring('HOLE', hole.points) for hole in polygon.holes]
        self.emit_record(f"POLYGON CONDUCTOR {shape.conductor} LAYER {shape.layer}",
                         clauses, group=2)

    def write_terminals(self) -> None:
        if not self.file.terminals:
            return
        kind_names = {
            pex25d_terminal_pb2().TERMINAL_KIND_PIN: 'PIN',
            pex25d_terminal_pb2().TERMINAL_KIND_DEVICE_TERMINAL: 'DEVICE_TERMINAL',
        }
        self.section('TERMINALS')
        self.hint("TERMINAL <name> CONDUCTOR <c> LAYER <l> [KIND <k>] \\",
                  "    LL <x> <y> UR <x> <y>",
                  "",
                  "The terminal is the INTERSECTION of the region with the",
                  "conductor's geometry on that layer, and is an equipotential node.")

        for terminal in self.file.terminals:
            clauses = [f"CONDUCTOR {terminal.conductor}", f"LAYER {terminal.layer}"]
            kind_name = kind_names.get(terminal.kind)
            if kind_name:
                clauses.append(f"KIND {kind_name}")
            region = terminal.region
            clauses.append(
                f"LL {self.length(region.lower_left.x)} "
                f"{self.length(region.lower_left.y)} "
                f"UR {self.length(region.upper_right.x)} "
                f"{self.length(region.upper_right.y)}")
            self.emit_record(f"TERMINAL {terminal.name}", clauses)

    def write_domain(self) -> None:
        which = self.file.WhichOneof('domain')
        if which is None:
            return
        self.section('COMPUTATIONAL DOMAIN')
        self.hint("DOMAIN_MARGIN X <xmargin> Y <ymargin> Z <zmargin>",
                  "DOMAIN_BOX LL <x> <y> <z> UR <x> <y> <z>",
                  "",
                  "Optional solver-adapter hints. DOMAIN_BOX wins if both are given.",
                  "No lower Z margin is needed: the ground plane is the lower bound.")

        if which == 'domain_margin':
            margin = self.file.domain_margin
            self.emit(f"DOMAIN_MARGIN X {self.length(margin.x)} "
                      f"Y {self.length(margin.y)} Z {self.length(margin.z)}")
        else:
            box = self.file.domain_box.box
            self.emit(f"DOMAIN_BOX "
                      f"LL {self.length(box.lower_left.x)} "
                      f"{self.length(box.lower_left.y)} "
                      f"{self.length(box.lower_left.z)} "
                      f"UR {self.length(box.upper_right.x)} "
                      f"{self.length(box.upper_right.y)} "
                      f"{self.length(box.upper_right.z)}")


def write_pex25d_text(message: Any, comments: bool = False) -> bytes:
    """
    Render a ``kpex.pex25d.PEX25DFile`` as PEX25D text, UTF-8 encoded.

    :param comments: also emit the syntax hints from the specification.
    """
    return Pex25DTextWriter(message, comments=comments).write().encode('utf-8')
