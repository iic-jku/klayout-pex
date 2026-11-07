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
is a template for new importers: a PEX25DFile with placeholder values.

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


def _where(path: str, line: int) -> str:
    """``<path>:<line>``, the location prefix of error messages"""
    return f"{path}:{line}"


def _parse_uf(path: str) -> _UFPattern:
    """Read a Universal Pattern Format file into plain values (µm)."""
    pattern = _UFPattern()
    with open(path, encoding='utf-8') as file:
        for line_number, line in enumerate(file, start=1):
            words = line.split()
            if not words or words[0].startswith('#'):
                continue
            keyword = words[0]
            where = _where(path, line_number)
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

# Rounding noise of float µm values, in grid units
_GRID_TOLERANCE = 1e-6

# A zero-thickness UF ground plane is moved to -0.1 … 0.0 µm (as uth-pexconv does)
_ZERO_THICKNESS_GROUND_PLANE_UM = 0.1

# Name prefix of the shape-less METAL profiles that anchor UF dielectrics
_ANCHOR_PREFIX = 'uf_anchor_'


def _to_grid(value_um: float, where: str) -> int:
    """µm → integer grid units; a value off the grid is an ImporterError"""
    grid = round(value_um * _GRID_PER_UM)
    if abs(value_um * _GRID_PER_UM - grid) > _GRID_TOLERANCE:
        raise pex25d.ImporterError(
            f"{where}: {value_um} µm is not on the {1000 / _GRID_PER_UM:g} nm grid")
    return grid


def _to_um(grid: int) -> float:
    """integer grid units → µm, for messages"""
    return grid / _GRID_PER_UM


def _check_pattern(pattern: _UFPattern, path: str):
    """Reject what the importer does not support before building anything."""
    window, ext = pattern.window, pattern.window_ext
    if window is None:
        raise pex25d.ImporterError(f"{path}: no WINDOW_BBOX")
    if window.max_y is None:
        raise pex25d.ImporterError(
            f"{_where(path, window.line)}: 2D UF input (WINDOW_BBOX without LENGTH)")
    if ext is not None and ext.min_y is None:
        raise pex25d.ImporterError(
            f"{_where(path, ext.line)}: 2D UF input (SIM_WIN_EXT without LENGTH)")
    if len(pattern.ground_planes) != 1:
        raise pex25d.ImporterError(
            f"{path}: expected exactly one GROUND_PLANE, found {len(pattern.ground_planes)}")
    for wire in pattern.wires:
        where = _where(path, wire.line)
        if wire.length is None:
            raise pex25d.ImporterError(f"{where}: 2D UF input (WIRE {wire.name} without LENGTH)")
        (llx, llz), (lrx, lrz), (urx, urz), (ulx, ulz) = (
            (_to_grid(x, where), _to_grid(z, where))
            for x, z in (wire.corners[corner] for corner in ('LL', 'LR', 'UR', 'UL')))
        if llx != ulx or lrx != urx or llz != lrz or ulz != urz:
            raise pex25d.ImporterError(
                f"{where}: wire {wire.name} is not a rectangle "
                f"(LL.x = UL.x, LR.x = UR.x, LL.z = LR.z and UL.z = UR.z are required)")
        if llx >= urx or llz >= urz:
            raise pex25d.ImporterError(
                f"{where}: wire {wire.name} has LL not left of and below UR")


def _layer_of(wire: _UFWire) -> str:
    """The metal layer of a wire, the prefix of its name (M1_w2 → M1)"""
    return wire.name.split('_')[0]


def _new_pex25d_file(metadata: Tuple[Tuple[str, str], ...]) -> PEX25DFile:
    """A PEX25DFile with the header, the 1 nm grid in µm and the given metadata."""
    pex25d_file = pex25d.proto.PEX25DFile()

    pex25d_file.format_version_major = pex25d.FORMAT_VERSION_MAJOR
    pex25d_file.format_version_minor = pex25d.FORMAT_VERSION_MINOR
    pex25d_file.format_version_suffix = pex25d.FORMAT_VERSION_SUFFIX

    units = pex25d_file.units
    units.length = units.LENGTH_UNIT_UM
    units.grid_numerator, units.grid_denominator = 1, _GRID_PER_UM

    for key, value in (('source_format', 'openrcx-uf'),
                       ('generator', f'kpex {__version__}'),
                       *metadata):
        meta = pex25d_file.metadata.add()
        meta.key, meta.value = key, value
    return pex25d_file


def _set_ground_plane(pex25d_file: PEX25DFile, uf_ground_plane: _UFGroundPlane,
                      input_file_path: str):
    """
    The ground plane from zlow to zlow + THICKNESS, which must be the top of its HEIGHT.
    A zero-thickness plane is moved below its HEIGHT, to -0.1 … 0.0 µm for HEIGHT 0 0.
    """
    where = _where(input_file_path, uf_ground_plane.line)
    zlow = _to_grid(uf_ground_plane.zlow, where)
    zhigh = _to_grid(uf_ground_plane.zhigh, where)
    thickness = _to_grid(uf_ground_plane.thickness, where)
    if zhigh != zlow + thickness:
        raise pex25d.ImporterError(
            f"{where}: GROUND_PLANE {uf_ground_plane.name} has HEIGHT "
            f"{uf_ground_plane.zlow} … {uf_ground_plane.zhigh} µm, "
            f"but THICKNESS {uf_ground_plane.thickness} µm")
    if thickness == 0:
        thickness = _to_grid(_ZERO_THICKNESS_GROUND_PLANE_UM, where)
        zlow -= thickness
    ground_plane = pex25d_file.ground_plane
    ground_plane.name = uf_ground_plane.name
    ground_plane.zlow, ground_plane.zhigh = zlow, zlow + thickness
    ground_plane.source.file, ground_plane.source.line = input_file_path, uf_ground_plane.line


def _set_domain(pex25d_file: PEX25DFile, pattern: _UFPattern, input_file_path: str):
    """
    x and z from WINDOW_BBOX, y from 0 to its LENGTH; SIM_WIN_EXT is added to every bound.
    The lower z face is the ground plane's top (pex25d_domain.proto): a window starting below
    it is cut off there, as nothing below the plane couples to the wires.
    """
    window, ext = pattern.window, pattern.window_ext
    x1, z1, x2, z2 = window.x1, window.z1, window.x2, window.z2
    y1, y2 = 0.0, window.max_y
    if ext is not None:
        x1, z1, x2, z2 = x1 + ext.x1, z1 + ext.z1, x2 + ext.x2, z2 + ext.z2
        y1, y2 = y1 + ext.min_y, y2 + ext.max_y
    where = _where(input_file_path, window.line)
    zlow = pex25d_file.ground_plane.zhigh
    if _to_grid(z1, where) > zlow:
        raise pex25d.ImporterError(
            f"{where}: the window (WINDOW_BBOX and SIM_WIN_EXT) starts at z {z1:g} µm, "
            f"above the top of the ground plane, {_to_um(zlow)} µm")
    box = pex25d_file.domain_box.box
    box.lower_left.x = _to_grid(x1, where)
    box.lower_left.y = _to_grid(y1, where)
    box.lower_left.z = zlow
    box.upper_right.x = _to_grid(x2, where)
    box.upper_right.y = _to_grid(y2, where)
    box.upper_right.z = _to_grid(z2, where)
    pex25d_file.domain_box.source.file = input_file_path
    pex25d_file.domain_box.source.line = window.line


def _build_dielectric_stack(pex25d_file: PEX25DFile, pattern: _UFPattern, input_file_path: str):
    """
    UF dielectrics lie at absolute heights, but a DIELECTRIC_SIMPLE spans from the bottom
    face of one profile to the bottom face of another. The ground plane anchors the lowest
    dielectric, as it occupies everything below its own top. A metal anchors the height of
    its bottom face. Every other height gets a shape-less 1-grid-unit METAL 'uf_anchor_<i>'.
    The topmost UF dielectric becomes the background.

    Nothing below the ground plane couples to the wires: dielectrics below its top are
    dropped, and one reaching across it starts there. So both absolute heights (from the
    substrate) and heights normalized to the top of the plane import alike.
    """
    if not pattern.dielectrics:
        raise pex25d.ImporterError(f"{input_file_path}: no DIELECTRIC")

    ground_plane = pex25d_file.ground_plane
    heights: List[Tuple[int, int]] = []
    previous_zhigh: Optional[int] = None

    for uf_dielectric in pattern.dielectrics:
        where = _where(input_file_path, uf_dielectric.line)
        zlow = _to_grid(uf_dielectric.zlow, where)
        zhigh = _to_grid(uf_dielectric.zhigh, where)
        # the lowest dielectric may start below the top of the ground plane, not above it
        if previous_zhigh is None:
            expected_zlow, gap = ground_plane.zhigh, zlow > ground_plane.zhigh
        else:
            expected_zlow, gap = previous_zhigh, zlow != previous_zhigh
        if gap:
            raise pex25d.ImporterError(
                f"{where}: dielectric {uf_dielectric.name} starts at {uf_dielectric.zlow} µm, "
                f"not at {_to_um(expected_zlow)} µm where the ground plane or the "
                f"dielectric below it ends")
        if zhigh <= zlow:
            raise pex25d.ImporterError(
                f"{where}: dielectric {uf_dielectric.name} has no thickness")
        heights.append((zlow, zhigh))
        previous_zhigh = zhigh

    # (UF dielectric, its z range above the top of the ground plane)
    kept = [(uf_dielectric, (max(zlow, ground_plane.zhigh), zhigh))
            for uf_dielectric, (zlow, zhigh) in zip(pattern.dielectrics, heights)
            if zhigh > ground_plane.zhigh]
    if not kept:
        raise pex25d.ImporterError(
            f"{input_file_path}: no DIELECTRIC above the top of the ground plane, "
            f"{_to_um(ground_plane.zhigh)} µm")

    top = kept[-1][0]
    background = pex25d_file.background
    background.name = top.name
    background.permittivity = top.epsilon

    anchors: Dict[int, str] = {ground_plane.zhigh: ground_plane.name}
    anchors.update({metal.zlow: metal.name for metal in pex25d_file.metals})
    anchor_names: List[str] = []
    for uf_dielectric, (zlow, zhigh) in kept[:-1]:
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
        dielectric.source.file, dielectric.source.line = input_file_path, uf_dielectric.line

    if anchor_names:
        meta = pex25d_file.metadata.add()
        meta.key, meta.value = 'uf_anchors', ' '.join(anchor_names)


class OpenRCXUFImporter(PEX25DImporter):
    """Translate an OpenRCX Universal Pattern Format file into an unresolved PEX25DFile."""

    name = 'openrcx-uf'

    def import_file(self,
                    input_file_path: str,
                    *,
                    supporting_files: Optional[Mapping[str, str]] = None,
                    options: Optional[Mapping[str, Any]] = None,
                    report: Optional[pex25d.DiagnosticsReport] = None) -> PEX25DFile:
        if supporting_files:
            raise pex25d.ImporterError(f"'{self.name}' takes no supporting files, "
                                       f"got: {', '.join(sorted(supporting_files))}")
        if options:
            raise pex25d.ImporterError(
                f"'{self.name}' takes no options, got: {', '.join(sorted(options))}")

        pattern = _parse_uf(input_file_path)
        _check_pattern(pattern, input_file_path)

        # UF values are µm without a database unit; a value off the 1 nm grid is an error
        pex25d_file = _new_pex25d_file((('source_cell', pattern.name),))

        # --------------------------------------------------------- process stack
        _set_ground_plane(pex25d_file, pattern.ground_planes[0], input_file_path)

        # one METAL per wire-name prefix (M1_w2 → M1); all its wires must share one z range
        metal_z: Dict[str, Tuple[int, int]] = {}
        for wire in pattern.wires:
            where = _where(input_file_path, wire.line)
            layer = _layer_of(wire)
            z = (_to_grid(wire.corners['LL'][1], where), _to_grid(wire.corners['UR'][1], where))
            if metal_z.setdefault(layer, z) != z:
                raise pex25d.ImporterError(
                    f"{where}: wire {wire.name} spans z {_to_um(z[0])} … {_to_um(z[1])} µm, "
                    f"other wires of layer {layer} span "
                    f"{_to_um(metal_z[layer][0])} … {_to_um(metal_z[layer][1])} µm")
            if z[0] < pex25d_file.ground_plane.zhigh:
                raise pex25d.ImporterError(
                    f"{where}: wire {wire.name} starts at z {_to_um(z[0])} µm, below the top "
                    f"of the ground plane, {_to_um(pex25d_file.ground_plane.zhigh)} µm")
        for layer, (zlow, zhigh) in metal_z.items():
            metal = pex25d_file.metals.add()
            metal.name = layer
            metal.zlow, metal.zhigh = zlow, zhigh

        # ----------------------------------------------------------- dielectrics
        _build_dielectric_stack(pex25d_file, pattern, input_file_path)

        # ------------------------------------------------------ conductors, shapes
        for wire in pattern.wires:
            where = _where(input_file_path, wire.line)
            conductor = pex25d_file.conductors.add()
            conductor.name, conductor.net = wire.name, wire.name

            shape = pex25d_file.shapes.add()
            shape.conductor, shape.layer = wire.name, _layer_of(wire)
            shape.kind = shape.SHAPE_KIND_BOX
            shape.box.lower_left.x = _to_grid(wire.corners['LL'][0], where)
            shape.box.lower_left.y = 0
            shape.box.upper_right.x = _to_grid(wire.corners['UR'][0], where)
            shape.box.upper_right.y = _to_grid(wire.length, where)
            shape.source.file, shape.source.line = input_file_path, wire.line

        # ----------------------------------------------------------------- domain
        _set_domain(pex25d_file, pattern, input_file_path)

        return pex25d_file

    def placeholder_file(self) -> PEX25DFile:
        """
        A minimal, valid PEX25DFile with placeholder values: a template for new importers,
        showing every part of the format and how it is filled in.
        """
        pex25d_file = _new_pex25d_file((('technology', 'placeholder'),))

        # ----------------------------------------------------------------- units
        # source_dbu_* is the database unit of the input, if it has one
        units = pex25d_file.units
        units.source_dbu_numerator, units.source_dbu_denominator = 1, 1000      # 1 nm

        # --------------------------------------------------------- process stack
        # ground plane, metals and vias with absolute z ranges (zlow < zhigh)
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
        # the background and every dielectric with its permittivity, from the innermost
        # outwards. A SIMPLE band lies between two profiles; a CONFORMAL film wraps one
        # (dielectric.conformal.thickness_*).
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
        # one conductor per net, and its shapes per layer. Floating conductors (e.g. fill)
        # get their own net name.
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

        # Source references let diagnostics point into the input:
        #   shape.source.file, shape.source.line = input_file_path, line_number

        # -------------------------------------------------------------- terminals
        # ports, if the input names them; otherwise terminals stay empty
        terminal = pex25d_file.terminals.add()
        terminal.name, terminal.conductor, terminal.layer = 't0', conductor.name, metal.name
        terminal.kind = pex25d.proto.terminal.TERMINAL_KIND_PIN
        terminal.region.lower_left.x, terminal.region.lower_left.y = 0, 0
        terminal.region.upper_right.x, terminal.region.upper_right.y = 200, 200

        # ----------------------------------------------------------------- domain
        # the simulation window: a margin around the geometry, as here, or an explicit
        # pex25d_file.domain_box
        margin = pex25d_file.domain_margin
        margin.x, margin.y, margin.z = 4000, 4000, 2000

        # ------------------------------------------------------------- resistance
        # Optional; only if the input carries sheet resistances:
        #   pex25d_file.resistance_temperature.celsius = 25.0
        #   sheet = pex25d_file.metal_resistances.add()
        #   sheet.metal, sheet.sheet = 'metal1', 0.125

        return pex25d_file
