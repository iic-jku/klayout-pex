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
OpenRCX Universal Pattern Format (UF) → unresolved PEX25DFile,
the built-in importer ``klayout-pex:openrcx-uf``.

A stub: :meth:`OpenRCXUFImporter.import_file` raises ``NotImplementedError``, which
``pex25d import`` reports with exit code 3. :meth:`OpenRCXUFImporter.placeholder_file`
is the template for the implementation. It fills every part of a PEX25DFile with
placeholder values, and each ``TODO(UF)`` names what the Universal Pattern Format
input has to provide instead.

All coordinates are integers in grid units (``units``); the template's grid is 1 nm.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional

from .. import pex25d
from ..plugin_api.v1 import PEX25DImporter
from ..version import __version__

if TYPE_CHECKING:
    from klayout_pex_protobuf.kpex.pex25d.pex25d_file_pb2 import PEX25DFile


class OpenRCXUFImporter(PEX25DImporter):
    """Translate an OpenRCX Universal Pattern Format file into an unresolved PEX25DFile.

    A stub: imports raise NotImplementedError until the parsing is implemented.
    """

    name = 'openrcx-uf'

    def import_file(self,
                    input_file_path: str,
                    *,
                    supporting_files: Optional[Mapping[str, str]] = None,
                    options: Optional[Mapping[str, Any]] = None,
                    report: Optional[pex25d.DiagnosticsReport] = None) -> PEX25DFile:
        # TODO(UF): parse input_file_path (and any supporting_files, e.g. a process
        #           stack), then build the file like self.placeholder_file() does.
        #           Report unsupported constructs as pex25d.ImporterError, never guess
        #           values.
        raise NotImplementedError(
            f"The '{self.name}' importer is a stub; the template to implement it is "
            f"klayout_pex/openrcx/pex25d_importer.py")

    def placeholder_file(self) -> PEX25DFile:
        """
        A minimal, valid PEX25DFile.

        Every value is a placeholder for what the Universal Pattern Format input provides.
        """
        pex25d_file = pex25d.proto.PEX25DFile()

        # ---------------------------------------------------------------- header
        # The PEX25D version this implementation writes;
        # not taken from the Universal Pattern Format input.
        pex25d_file.format_version_major = pex25d.FORMAT_VERSION_MAJOR
        pex25d_file.format_version_minor = pex25d.FORMAT_VERSION_MINOR
        pex25d_file.format_version_suffix = pex25d.FORMAT_VERSION_SUFFIX

        # ----------------------------------------------------------------- units
        # TODO(UF): the length unit and a grid fine enough for every coordinate and
        #           z value of the pattern. source_dbu_* is the database unit of the
        #           Universal Pattern Format input, if it has one.
        units = pex25d_file.units
        units.length = units.LENGTH_UNIT_UM
        units.grid_numerator, units.grid_denominator = 1, 1000                  # 1 nm
        units.source_dbu_numerator, units.source_dbu_denominator = 1, 1000      # 1 nm

        # -------------------------------------------------------------- metadata
        # TODO(UF): technology, corner and the pattern / cell name, as far as the
        #           Universal Pattern Format input names them.
        for key, value in (('source_format', 'openrcx-uf'),
                           ('generator', f'kpex {__version__}'),
                           ('technology', 'placeholder')):
            meta = pex25d_file.metadata.add()
            meta.key, meta.value = key, value

        # --------------------------------------------------------- process stack
        # TODO(UF): ground plane, metals and vias with absolute z ranges (zlow < zhigh).
        ground_plane = pex25d_file.ground_plane
        ground_plane.name = 'substrate'
        ground_plane.zlow, ground_plane.zhigh = -100, 0

        metal = pex25d_file.metals.add()
        metal.name = 'metal1'
        metal.zlow, metal.zhigh = 1000, 1400

        # A via connects two metals; patterns with a single metal have none:
        #   via = pex25d_file.vias.add()
        #   via.name, via.connects_below, via.connects_above = 'via1', 'metal1', 'metal2'

        # ----------------------------------------------------------- dielectrics
        # TODO(UF): the background and every dielectric with its permittivity, from the
        #           innermost outwards. A SIMPLE band lies between two profiles; a
        #           CONFORMAL film wraps one (dielectric.conformal.thickness_*).
        background = pex25d_file.background
        background.name = 'air'
        background.permittivity = 1.0

        dielectric = pex25d_file.dielectrics.add()
        dielectric.name = 'ild'
        dielectric.kind = pex25d.proto.dielectric.DIELECTRIC_KIND_SIMPLE
        dielectric.permittivity = 3.9
        dielectric.wraps = ground_plane.name
        dielectric.simple.between_below = ground_plane.name
        dielectric.simple.between_above = metal.name

        # ------------------------------------------------------ conductors, shapes
        # TODO(UF): one conductor per wire / net of the pattern, and its shapes per
        #           layer. Floating conductors (e.g. fill) get their own net name.
        conductor = pex25d_file.conductors.add()
        conductor.name, conductor.net = 'w0', 'net0'

        shape = pex25d_file.shapes.add()
        shape.conductor, shape.layer = conductor.name, metal.name
        shape.kind = shape.SHAPE_KIND_BOX
        shape.box.lower_left.x, shape.box.lower_left.y = 0, 0
        shape.box.upper_right.x, shape.box.upper_right.y = 1000, 200
        # A polygon instead: shape.kind = shape.SHAPE_KIND_POLYGON, then
        #   for x, y in points:
        #       point = shape.polygon.outer.points.add()
        #       point.x, point.y = x, y

        # TODO(UF): source references, so that diagnostics point into the
        #           Universal Pattern Format input:
        #   shape.source.file, shape.source.line = input_file_path, line_number

        # -------------------------------------------------------------- terminals
        # TODO(UF): ports, if the Universal Pattern Format input names them; otherwise leave
        #           terminals empty.
        terminal = pex25d_file.terminals.add()
        terminal.name, terminal.conductor, terminal.layer = 't0', conductor.name, metal.name
        terminal.kind = pex25d.proto.terminal.TERMINAL_KIND_PIN
        terminal.region.lower_left.x, terminal.region.lower_left.y = 0, 0
        terminal.region.upper_right.x, terminal.region.upper_right.y = 200, 200

        # ----------------------------------------------------------------- domain
        # TODO(UF): the simulation window. Either a margin around the geometry, as here,
        #           or an explicit pex25d_file.domain_box.
        margin = pex25d_file.domain_margin
        margin.x, margin.y, margin.z = 4000, 4000, 2000

        # ------------------------------------------------------------- resistance
        # Optional; only if the Universal Pattern Format input carries sheet resistances:
        #   pex25d_file.resistance_temperature.celsius = 25.0
        #   sheet = pex25d_file.metal_resistances.add()
        #   sheet.metal, sheet.sheet = 'metal1', 0.125

        return pex25d_file
