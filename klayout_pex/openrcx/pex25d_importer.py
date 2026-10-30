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

Supports 3D patterns with rectangular wires and one ground plane; other input is
reported as ``pex25d.ImporterError``. :meth:`OpenRCXUFImporter.placeholder_file`
is the template the implementation follows: a PEX25DFile with placeholder values.

All coordinates are integers in grid units (``units``); the grid is 1 nm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Tuple

from .. import pex25d
from ..plugin_api.v1 import PEX25DImporter
from ..version import __version__

if TYPE_CHECKING:
    from klayout_pex_protobuf.kpex.pex25d.pex25d_file_pb2 import PEX25DFile


@dataclass(frozen=True)
class _UFGroundPlane:
    name: str
    zlow: float
    zhigh: float
    thickness: float
    line: int


@dataclass(frozen=True)
class _UFDielectric:
    name: str
    zlow: float
    zhigh: float
    epsilon: float
    line: int


@dataclass(frozen=True)
class _UFWire:
    id: int
    name: str
    corners: Dict[str, Tuple[float, float]]  # 'LL', 'LR', 'UR', 'UL' -> (x, z) in µm
    length: Optional[float]  # None for 2D input
    voltage: int
    line: int


@dataclass(frozen=True)
class _UFWindow:
    """``WINDOW_BBOX LL <x1> <z1> UR <x2> <z2> LENGTH <max_y>``"""
    x1: float
    z1: float
    x2: float
    z2: float
    max_y: Optional[float]  # None for 2D input
    line: int


@dataclass(frozen=True)
class _UFWindowExt:
    """``SIM_WIN_EXT LL <x1> <z1> UR <x2> <z2> LENGTH <min_y> <max_y>``, relative to the window."""
    x1: float
    z1: float
    x2: float
    z2: float
    min_y: Optional[float]  # None for 2D input
    max_y: Optional[float]
    line: int


@dataclass
class _UFPattern:
    """Everything read from the UF file."""
    name: str = ''
    ground_planes: List[_UFGroundPlane] = field(default_factory=list)
    dielectrics: List[_UFDielectric] = field(default_factory=list)
    wires: List[_UFWire] = field(default_factory=list)
    window: Optional[_UFWindow] = None
    window_ext: Optional[_UFWindowExt] = None


def _values_after(words: List[str], keyword: str, count: int) -> List[float]:
    index = words.index(keyword)
    values = words[index + 1:index + 1 + count]
    if len(values) != count:
        raise IndexError(keyword)
    return [float(value) for value in values]


def _optional_values_after(words: List[str], keyword: str, count: int) -> Optional[List[float]]:
    if keyword not in words:
        return None
    return _values_after(words, keyword, count)


def _parse_uf(path: str) -> _UFPattern:
    """Read a Universal Pattern Format file into plain values (µm)."""
    pattern = _UFPattern()
    with open(path, encoding='utf-8') as file:
        for line_number, line in enumerate(file, start=1):
            words = line.split()
            if not words or words[0].startswith('#'):
                continue
            keyword = words[0]
            where = f"{path}:{line_number}"
            try:
                if keyword == 'PATTERN':
                    pattern.name = words[1]
                elif keyword == 'GROUND_PLANE':
                    zlow, zhigh = _values_after(words, 'HEIGHT', 2)
                    thickness, = _values_after(words, 'THICKNESS', 1)
                    pattern.ground_planes.append(
                        _UFGroundPlane(words[2], zlow, zhigh, thickness, line_number))
                elif keyword == 'DIELECTRIC':
                    zlow, zhigh = _values_after(words, 'HEIGHT', 2)
                    epsilon, = _values_after(words, 'EPSILON', 1)
                    pattern.dielectrics.append(
                        _UFDielectric(words[1], zlow, zhigh, epsilon, line_number))
                elif keyword == 'WIRE':
                    corners = {corner: tuple(_values_after(words, corner, 2))
                               for corner in ('LL', 'LR', 'UR', 'UL')}
                    length = _optional_values_after(words, 'LENGTH', 1)
                    voltage, = _values_after(words, 'VOLTAGE', 1)
                    pattern.wires.append(
                        _UFWire(int(words[1]), words[2], corners,
                                length[0] if length else None, int(voltage), line_number))
                elif keyword == 'WINDOW_BBOX':
                    x1, z1 = _values_after(words, 'LL', 2)
                    x2, z2 = _values_after(words, 'UR', 2)
                    max_y = _optional_values_after(words, 'LENGTH', 1)
                    pattern.window = _UFWindow(x1, z1, x2, z2,
                                               max_y[0] if max_y else None, line_number)
                elif keyword == 'SIM_WIN_EXT':
                    x1, z1 = _values_after(words, 'LL', 2)
                    x2, z2 = _values_after(words, 'UR', 2)
                    lengths = _optional_values_after(words, 'LENGTH', 2)
                    min_y, max_y = lengths if lengths else (None, None)
                    pattern.window_ext = _UFWindowExt(x1, z1, x2, z2, min_y, max_y, line_number)
                else:
                    raise pex25d.ImporterError(f"{where}: unknown directive '{keyword}'")
            except (IndexError, ValueError) as exc:
                raise pex25d.ImporterError(
                    f"{where}: cannot read {keyword} line: {line.strip()}") from exc
    return pattern


_GRID_PER_UM = 1000  # 1 nm grid, as in placeholder_file()

# A zero-thickness UF ground plane is moved to -0.1 … 0.0 µm (as uth-pexconv does)
_ZERO_THICKNESS_GROUND_PLANE_UM = 0.1

def _to_grid(value_um: float) -> int:
    """µm → integer grid units"""
    scaled = value_um * _GRID_PER_UM
    grid = round(scaled)
    return grid

# Name prefix of the shape-less METAL profiles that anchor UF dielectrics
_ANCHOR_PREFIX = 'uf_anchor_'

def _build_dielectric_stack(pex25d_file: PEX25DFile, pattern: _UFPattern, input_file_path: str):
    """
    UF dielectrics lie at absolute heights, but a DIELECTRIC_SIMPLE spans from the bottom
    face of one profile to the bottom face of another. The ground plane anchors the lowest
    dielectric, as it occupies everything below its own top. A metal anchors the height of
    its bottom face. Every other height gets a shape-less 1-grid-unit METAL 'uf_anchor_<i>'.
    The topmost UF dielectric becomes the background.
    """
    if not pattern.dielectrics:
        raise pex25d.ImporterError(f"{input_file_path}: no DIELECTRIC")

    ground_plane = pex25d_file.ground_plane
    heights: List[Tuple[int, int]] = []
    previous_zhigh = ground_plane.zhigh

    for uf_dielectric in pattern.dielectrics:
        zlow = _to_grid(uf_dielectric.zlow)
        zhigh = _to_grid(uf_dielectric.zhigh)
        if zlow != previous_zhigh:
            raise pex25d.ImporterError(
                f"dielectric {uf_dielectric.name} starts at {uf_dielectric.zlow} µm, "
                f"not at {previous_zhigh / _GRID_PER_UM} µm where the ground plane or the "
                f"dielectric below it ends")
        if zhigh <= zlow:
            raise pex25d.ImporterError(
                f"dielectric {uf_dielectric.name} has no thickness")
        heights.append((zlow, zhigh))
        previous_zhigh = zhigh

    top = pattern.dielectrics[-1]
    background = pex25d_file.background
    background.name = top.name
    background.permittivity = top.epsilon

    anchors: Dict[int, str] = {ground_plane.zhigh: ground_plane.name}
    anchors.update({metal.zlow: metal.name for metal in pex25d_file.metals})
    anchor_names: List[str] = []
    for uf_dielectric, (zlow, zhigh) in zip(pattern.dielectrics[:-1], heights):
        for z in (zlow, zhigh):
            if z not in anchors:
                metal = pex25d_file.metals.add()
                metal.name = f'{_ANCHOR_PREFIX}{len(anchor_names)}'
                metal.zlow, metal.zhigh = z, z + 1
                anchors[z] = metal.name
                anchor_names.append(metal.name)
        below, above = anchors[zlow], anchors[zhigh]
        dielectric = pex25d_file.dielectrics.add()
        dielectric.name = uf_dielectric.name
        dielectric.kind = pex25d.proto.dielectric.DIELECTRIC_KIND_SIMPLE
        dielectric.permittivity = uf_dielectric.epsilon
        dielectric.wraps = below  # UF has no conformal dielectrics
        dielectric.simple.between_below = below
        dielectric.simple.between_above = above
        dielectric.source.line = uf_dielectric.line

    if anchor_names:
        meta = pex25d_file.metadata.add()
        meta.key, meta.value = 'uf_anchors', ' '.join(anchor_names)


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

        pattern = _parse_uf(input_file_path)

        if pattern.window is None:
            raise pex25d.ImporterError(f"{input_file_path}: no WINDOW_BBOX")
        if len(pattern.ground_planes) != 1:
            raise pex25d.ImporterError(
                f"{input_file_path}: expected exactly one GROUND_PLANE, "
                f"found {len(pattern.ground_planes)}")

        pex25d_file = pex25d.proto.PEX25DFile()

        # ---------------------------------------------------------------- header
        pex25d_file.format_version_major = pex25d.FORMAT_VERSION_MAJOR
        pex25d_file.format_version_minor = pex25d.FORMAT_VERSION_MINOR
        pex25d_file.format_version_suffix = pex25d.FORMAT_VERSION_SUFFIX

        # ----------------------------------------------------------------- units
        # UF values are µm without a database unit; every value must be on the 1 nm grid
        units = pex25d_file.units
        units.length = units.LENGTH_UNIT_UM
        units.grid_numerator, units.grid_denominator = 1, _GRID_PER_UM

        # -------------------------------------------------------------- metadata
        for key, value in (('source_format', 'openrcx-uf'),
                           ('generator', f'kpex {__version__}'),
                           ('source_cell', pattern.name)):
            meta = pex25d_file.metadata.add()
            meta.key, meta.value = key, value

        # --------------------------------------------------------- process stack
        uf_ground_plane = pattern.ground_planes[0]
        ground_plane = pex25d_file.ground_plane
        ground_plane.name = uf_ground_plane.name
        zlow = _to_grid(uf_ground_plane.zlow)
        thickness = _to_grid(uf_ground_plane.thickness)
        if thickness == 0:
            thickness = _to_grid(_ZERO_THICKNESS_GROUND_PLANE_UM)
            zlow -= thickness
        ground_plane.zlow, ground_plane.zhigh = zlow, zlow + thickness
        ground_plane.source.line = uf_ground_plane.line

        # one METAL per wire-name prefix (M1_w2 → M1); all its wires must share one z range
        metal_z: Dict[str, Tuple[int, int]] = {}
        for wire in pattern.wires:
            layer = wire.name.split('_')[0]
            z = (_to_grid(wire.corners['LL'][1]), _to_grid(wire.corners['UR'][1]))
            if metal_z.setdefault(layer, z) != z:
                raise pex25d.ImporterError(
                    f"wire {wire.name} spans z {z} on layer {layer}, "
                    f"other wires of {layer} span {metal_z[layer]}")
        for layer, (zlow, zhigh) in metal_z.items():
            metal = pex25d_file.metals.add()
            metal.name = layer
            metal.zlow, metal.zhigh = zlow, zhigh

        # ----------------------------------------------------------- dielectrics
        _build_dielectric_stack(pex25d_file, pattern, input_file_path)

        # ------------------------------------------------------ conductors, shapes
        for wire in pattern.wires:
            if wire.length is None:
                raise pex25d.ImporterError(f"wire {wire.name}: 2D UF input (WIRE without LENGTH)")
            conductor = pex25d_file.conductors.add()
            conductor.name, conductor.net = wire.name, wire.name

            shape = pex25d_file.shapes.add()
            shape.conductor, shape.layer = wire.name, wire.name.split('_')[0]
            shape.kind = shape.SHAPE_KIND_BOX
            shape.box.lower_left.x = _to_grid(wire.corners['LL'][0])
            shape.box.lower_left.y = 0
            shape.box.upper_right.x = _to_grid(wire.corners['UR'][0])
            shape.box.upper_right.y = _to_grid(wire.length)
            shape.source.file, shape.source.line = input_file_path, wire.line

        # ----------------------------------------------------------------- domain
        # x and z from WINDOW_BBOX, y from 0 to its LENGTH; SIM_WIN_EXT is added to every
        # bound. The lower z face is the ground plane's top (pex25d_domain.proto).
        window, ext = pattern.window, pattern.window_ext
        x1, x2, z2 = window.x1, window.x2, window.z2
        y1, y2 = 0.0, window.max_y
        if ext is not None:
            x1, x2, z2 = x1 + ext.x1, x2 + ext.x2, z2 + ext.z2
            y1, y2 = y1 + ext.min_y, y2 + ext.max_y
        box = pex25d_file.domain_box.box
        box.lower_left.x = _to_grid(x1)
        box.lower_left.y = _to_grid(y1)
        box.lower_left.z = ground_plane.zhigh
        box.upper_right.x = _to_grid(x2)
        box.upper_right.y = _to_grid(y2)
        box.upper_right.z = _to_grid(z2)
        pex25d_file.domain_box.source.line = window.line

        return pex25d_file

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
