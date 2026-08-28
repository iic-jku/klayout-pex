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
The reference PEX25D validator.

The point of this module is *other people's* writers: another group should be
able to check its output and get stable ``PEX25D-Ennnn`` codes back, without
depending on kpex internals or on the wording of a message. So it reports
everything it finds rather than stopping at the first problem, and it never
raises for a merely invalid file — that is what the diagnostics are for.

Three tiers, matching ``kpex.pex25d.Diagnostic.Tier``:

``TIER_SYNTAX``
    the reader's business, and already reported by the time a message exists.
``TIER_SEMANTIC``
    name resolution, acyclic WRAPS, depth ties, and the rules below. Most of it
    comes from running the resolver, which has to answer the same questions to
    do its job; duplicating that here would let the two drift apart.
``TIER_GEOMETRIC``
    ring and box wellformedness, hole containment, conductor overlap. Only
    under ``--strict``, because it is the expensive tier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import *

from .diagnostics import (Diagnostic, DiagnosticsReport, Severity, Tier,
                          source_ref)
from .protobuf import pex25d_dielectric_pb2, pex25d_file_pb2, pex25d_scene_pb2

FLOATING_NET = 'FLOATING'

# One overlapping pair per shape pair would drown the report on a layout that
# has the problem systematically; the count is still exact.
MAX_OVERLAP_REPORTS = 50


class Validator:
    def __init__(self, report: DiagnosticsReport, strict: bool = False):
        self.report = report
        self.strict = strict

    def diagnose(self,
                 code: str,
                 message: str,
                 tier: Tier = Tier.SEMANTIC,
                 severity: Severity = Severity.ERROR,
                 source: Any = None) -> None:
        self.report.add(Diagnostic(code=code, severity=severity, tier=tier,
                                   message=message, source=source_ref(source)))

    # ----------------------------------------------------------------- entry

    def validate(self, message: Any, scene: Any = None) -> None:
        if is_scene(message):
            self.validate_scene(message)
        else:
            self.validate_file(message, scene=scene)

    def validate_file(self, pex25d_file: Any, scene: Any = None) -> None:
        from .resolver import ResolveError, Resolver

        # The resolver answers every name-resolution question already, and
        # records the same coded diagnostics. Run it for its findings; a file
        # too broken to resolve still gets the checks that do not need one.
        # A caller that has resolved the file already passes the scene in, so
        # that neither the work nor the diagnostics happen twice.
        if scene is None:
            try:
                # Not strict: the geometric tier below is the same code the
                # resolver would delegate to, and would report everything twice.
                scene = Resolver(pex25d_file, report=self.report).resolve()
            except ResolveError:
                pass

        self.check_units(pex25d_file)
        self.check_names(pex25d_file)
        self.check_wrap_anchoring(pex25d_file)
        self.check_conductors(pex25d_file)
        self.check_resistance_records(pex25d_file)
        self.check_resistance_coverage(pex25d_file)

        if scene is not None:
            self.check_depth_ties(scene)

        if self.strict:
            # Wellformedness on the file, where a shape still carries the
            # SourceRef of the record it came from; overlap on the scene,
            # which is the only form that knows the z extent of a layer.
            self.check_shapes(shapes_of_file(pex25d_file))
            if scene is not None:
                self.check_conductor_overlap(scene)

    def validate_scene(self, scene: Any) -> None:
        self.check_units(scene)
        self.check_scene_layers(scene)
        self.check_scene_references(scene)
        self.check_scene_order(scene)
        self.check_depth_ties(scene)
        self.check_scene_terminals(scene)

        if self.strict:
            self.check_shapes(shapes_of_scene(scene))
            self.check_conductor_overlap(scene)

    # -------------------------------------------------------------- semantic

    def check_units(self, message: Any) -> None:
        units = message.units
        if not units.grid_denominator:
            self.diagnose('PEX25D-E0106', "No UNITS: the file states no grid")
            return

        if not units.source_dbu_denominator:
            return

        # GRID must divide source_dbu exactly when both are present: a writer
        # for which it does not cannot place its own geometry on the grid.
        # Divide-round-compare, never a modulo — the same rule as coordinates.
        grid = Fraction(units.grid_numerator, units.grid_denominator)
        source_dbu = Fraction(units.source_dbu_numerator, units.source_dbu_denominator)
        quotient = source_dbu / grid
        if abs(quotient - round(quotient)) > Fraction(1, 10 ** 6):
            self.diagnose('PEX25D-E0262',
                          f"GRID ({grid}) does not divide the source DBU "
                          f"({source_dbu}) exactly, so the writer's own geometry "
                          f"cannot be on the grid")

    def check_wrap_anchoring(self, pex25d_file: Any) -> None:
        """
        A simple dielectric must wrap the OUTERMOST film anchored on its
        ``between_below`` object.

        Wrapping an inner link would give the fill the same depth as a film it
        contains, which is exactly the tie that has no rule to break it.
        """
        kinds = pex25d_dielectric_pb2()

        anchored: Dict[str, List[str]] = {}
        for dielectric in pex25d_file.dielectrics:
            if dielectric.kind == kinds.DIELECTRIC_KIND_CONFORMAL:
                anchored.setdefault(dielectric.wraps, []).append(dielectric.name)

        def outermost(root: str) -> str:
            name, seen = root, {root}
            while True:
                films = anchored.get(name, [])
                if len(films) != 1 or films[0] in seen:
                    return name
                name = films[0]
                seen.add(name)

        for dielectric in pex25d_file.dielectrics:
            if dielectric.kind != kinds.DIELECTRIC_KIND_SIMPLE:
                continue
            below = dielectric.simple.between_below
            if not below:
                continue
            expected = outermost(below)
            if dielectric.wraps and dielectric.wraps != expected:
                self.diagnose(
                    'PEX25D-E0260',
                    f"DIELECTRIC_SIMPLE '{dielectric.name}' WRAPS "
                    f"'{dielectric.wraps}', but the outermost profile anchored on "
                    f"'{below}' is '{expected}'; wrapping an inner link ties its "
                    f"depth with a film it contains",
                    source=dielectric)

    def check_conductors(self, pex25d_file: Any) -> None:
        with_geometry = {shape.conductor for shape in pex25d_file.shapes}

        for conductor in pex25d_file.conductors:
            if conductor.name not in with_geometry:
                self.diagnose('PEX25D-W0264',
                              f"CONDUCTOR '{conductor.name}' has no geometry",
                              severity=Severity.WARNING, source=conductor)

        floating = {c.name for c in pex25d_file.conductors if c.net == FLOATING_NET}
        for terminal in pex25d_file.terminals:
            if terminal.conductor in floating:
                # A floating body is at its own unknown potential and by
                # construction has no port.
                self.diagnose('PEX25D-E0263',
                              f"TERMINAL '{terminal.name}' is on FLOATING conductor "
                              f"'{terminal.conductor}', which has no port",
                              source=terminal)

    def check_resistance_coverage(self, pex25d_file: Any) -> None:
        """
        Once a file states any resistance, a profile carrying geometry without
        one is worth reporting: an adapter asked for resistance must refuse such
        a scene rather than solve it with a perfect conductor in it. An ANCHOR
        profile — declared only to give a via its zlow — carries no geometry and
        is exempt.
        """
        stated = {r.metal for r in pex25d_file.metal_resistances} \
            | {r.via for r in pex25d_file.via_resistances}
        if not stated:
            return

        with_geometry = {shape.layer for shape in pex25d_file.shapes}
        for layer in sorted(with_geometry - stated):
            self.diagnose('PEX25D-W0265',
                          f"Profile '{layer}' carries geometry but the file states "
                          f"no resistance for it, while stating one for others",
                          severity=Severity.WARNING)

    def check_depth_ties(self, scene: Any) -> None:
        """
        Two films at the same wrap depth on the same root overlap by
        construction, and at equal depth there is no rule to break the tie.
        """
        kinds = pex25d_dielectric_pb2()
        seen: Dict[Tuple[str, int], str] = {}
        for dielectric in scene.dielectrics:
            if dielectric.kind != kinds.DIELECTRIC_KIND_CONFORMAL:
                continue
            key = (dielectric.root, dielectric.wrap_depth)
            if key in seen:
                self.diagnose(
                    'PEX25D-E0261',
                    f"'{dielectric.name}' and '{seen[key]}' are both at wrap depth "
                    f"{dielectric.wrap_depth} on '{dielectric.root}'; at equal depth "
                    f"there is no rule to decide which is visible",
                    source=dielectric)
            else:
                seen[key] = dielectric.name

    def check_names(self, pex25d_file: Any) -> None:
        """Conductor shortnames and terminal names are each unique."""
        seen: Set[str] = set()
        for conductor in pex25d_file.conductors:
            if conductor.name in seen:
                self.diagnose('PEX25D-E0266',
                              f"CONDUCTOR '{conductor.name}' is declared more "
                              f"than once", source=conductor)
            seen.add(conductor.name)

        seen = set()
        for terminal in pex25d_file.terminals:
            if terminal.name in seen:
                self.diagnose('PEX25D-E0267',
                              f"TERMINAL '{terminal.name}' is declared more "
                              f"than once", source=terminal)
            seen.add(terminal.name)

    def check_resistance_records(self, pex25d_file: Any) -> None:
        has_temperature = pex25d_file.HasField('resistance_temperature')

        for records, attribute, keyword in (
                (pex25d_file.metal_resistances, 'metal', 'METAL'),
                (pex25d_file.via_resistances, 'via', 'VIA')):
            seen: Set[str] = set()
            for record in records:
                name = getattr(record, attribute)
                if name in seen:
                    self.diagnose('PEX25D-E0268',
                                  f"More than one RESISTANCE {keyword} record "
                                  f"for '{name}'", source=record)
                seen.add(name)

                if not has_temperature and (record.tc.tc1 or record.tc.tc2):
                    # TC1/TC2 move a value away from a reference temperature.
                    # Without RESISTANCE TEMPERATURE there is nothing to move
                    # from, so a consumer can only ignore them.
                    self.diagnose('PEX25D-W0269',
                                  f"RESISTANCE {keyword} '{name}' states "
                                  f"temperature coefficients, but the file has "
                                  f"no RESISTANCE TEMPERATURE to refer them to",
                                  severity=Severity.WARNING, source=record)

    # ----------------------------------------------------------------- scene

    def check_scene_layers(self, scene: Any) -> None:
        layer_kinds = pex25d_scene_pb2().ResolvedLayer

        for layer in scene.layers:
            metal = layer.kind == layer_kinds.RESOLVED_LAYER_KIND_METAL
            via = layer.kind == layer_kinds.RESOLVED_LAYER_KIND_VIA

            if not metal and not via:
                self.diagnose('PEX25D-E0270',
                              f"Layer '{layer.name}' has no kind",
                              source=layer)
                continue

            # A METAL is a solid and needs a height; a VIA between two abutting
            # layers legitimately has none.
            if layer.zhigh < layer.zlow or (metal and layer.zhigh == layer.zlow):
                self.diagnose('PEX25D-E0271',
                              f"Layer '{layer.name}' has z extent "
                              f"[{layer.zlow}, {layer.zhigh}]",
                              source=layer)

            if via and not (layer.connects_below and layer.connects_above):
                self.diagnose('PEX25D-E0272',
                              f"VIA layer '{layer.name}' does not carry its "
                              f"resolved CONNECTS endpoints", source=layer)

            arm = layer.WhichOneof('resistance')
            expected = 'metal_resistance' if metal else 'via_resistance'
            if arm is not None and arm != expected:
                self.diagnose('PEX25D-E0273',
                              f"Layer '{layer.name}' is a "
                              f"{'METAL' if metal else 'VIA'} but carries a "
                              f"{arm.split('_')[0].upper()} resistance",
                              source=layer)

    def check_scene_references(self, scene: Any) -> None:
        """
        Every name a resolved message states must be in the scene.

        The resolver cannot produce a dangling one; a scene from somewhere else
        can, and a consumer that trusts the resolved form will crash on it
        rather than diagnose it.
        """
        profiles = {layer.name for layer in scene.layers}
        profiles |= {d.name for d in scene.dielectrics}
        if scene.HasField('ground_plane'):
            profiles.add(scene.ground_plane.name)

        for dielectric in scene.dielectrics:
            for name, clause in ((dielectric.wraps, 'WRAPS'),
                                 (dielectric.root, 'root'),
                                 (dielectric.between_below, 'BETWEEN'),
                                 (dielectric.between_above, 'BETWEEN')):
                if name and name not in profiles:
                    self.diagnose('PEX25D-E0275',
                                  f"Dielectric '{dielectric.name}' names "
                                  f"'{name}' as its {clause}, which is not a "
                                  f"profile of this scene", source=dielectric)

        layers = {layer.name for layer in scene.layers}
        for conductor in scene.conductors:
            for region in conductor.regions:
                if region.layer not in layers:
                    self.diagnose('PEX25D-E0279',
                                  f"Conductor '{conductor.name}' has geometry "
                                  f"on '{region.layer}', which is not a layer "
                                  f"of this scene", source=conductor)

    def check_scene_order(self, scene: Any) -> None:
        """
        Dielectrics come in ascending ``wrap_depth``.

        The order is what lets a consumer walk the list once and stop at the
        first dielectric claiming the point it is testing, which is the
        occupancy rule. Out of order, that walk silently returns the wrong
        material.
        """
        previous = 0
        for dielectric in scene.dielectrics:
            if dielectric.wrap_depth < previous:
                self.diagnose('PEX25D-E0274',
                              f"Dielectric '{dielectric.name}' is at wrap depth "
                              f"{dielectric.wrap_depth} after one at depth "
                              f"{previous}; the list must ascend",
                              source=dielectric)
                return
            previous = dielectric.wrap_depth

    def check_scene_terminals(self, scene: Any) -> None:
        layers = {layer.name for layer in scene.layers}
        seen: Set[str] = set()

        for conductor in scene.conductors:
            regions = {region.layer for region in conductor.regions}
            for terminal in conductor.terminals:
                if terminal.name in seen:
                    self.diagnose('PEX25D-E0267',
                                  f"TERMINAL '{terminal.name}' appears more "
                                  f"than once", source=terminal)
                seen.add(terminal.name)

                if conductor.floating:
                    self.diagnose('PEX25D-E0263',
                                  f"TERMINAL '{terminal.name}' is on FLOATING "
                                  f"conductor '{conductor.name}', which has no "
                                  f"port", source=terminal)

                if terminal.layer not in layers:
                    self.diagnose('PEX25D-E0276',
                                  f"TERMINAL '{terminal.name}' names layer "
                                  f"'{terminal.layer}', which is not a layer of "
                                  f"this scene", source=terminal)
                elif terminal.layer not in regions:
                    self.diagnose('PEX25D-E0276',
                                  f"TERMINAL '{terminal.name}' is on layer "
                                  f"'{terminal.layer}', where conductor "
                                  f"'{conductor.name}' has no geometry",
                                  source=terminal)

                # The node is the resolved intersection, and the resolver
                # rejects an empty one; an empty node here means the scene was
                # written by something that did not do the boolean.
                if not terminal.boxes and not terminal.polygons:
                    self.diagnose('PEX25D-E0277',
                                  f"TERMINAL '{terminal.name}' has an empty "
                                  f"node: nothing was intersected",
                                  source=terminal)

    # ------------------------------------------------------------- geometric

    def check_shapes(self, shapes: Iterable[Shape]) -> None:
        for shape in shapes:
            if shape.is_box:
                self.check_box(shape)
            else:
                self.check_polygon(shape)

    def check_box(self, shape: Shape) -> None:
        box = shape.geometry
        if box.lower_left.x >= box.upper_right.x or \
                box.lower_left.y >= box.upper_right.y:
            self.geometric('PEX25D-E0308',
                           f"{shape} is empty: LL ({box.lower_left.x}, "
                           f"{box.lower_left.y}) is not below and left of UR "
                           f"({box.upper_right.x}, {box.upper_right.y})",
                           shape.source)

    def check_polygon(self, shape: Shape) -> None:
        polygon = shape.geometry
        outer = self.check_ring(shape, polygon.outer, 'OUTER')
        holes = [self.check_ring(shape, hole, f"HOLE {i + 1}")
                 for i, hole in enumerate(polygon.holes)]
        if outer is None or any(hole is None for hole in holes):
            return

        for i, hole in enumerate(holes):
            if not ring_strictly_inside(hole, outer):
                self.geometric('PEX25D-E0306',
                               f"{shape}: HOLE {i + 1} is not strictly inside "
                               f"OUTER", shape.source)

        for i in range(len(holes)):
            for j in range(i + 1, len(holes)):
                if rings_meet(holes[i], holes[j]):
                    self.geometric('PEX25D-E0307',
                                   f"{shape}: HOLE {i + 1} and HOLE {j + 1} "
                                   f"touch or overlap; an island inside a hole "
                                   f"is a POLYGON record of its own", shape.source)

    def check_ring(self, shape: Shape, ring: Any, what: str) -> Optional[Ring]:
        """One ring, or ``None`` once it is too broken for the checks after it."""
        points: Ring = [(p.x, p.y) for p in ring.points]

        if len(points) < 3:
            self.geometric('PEX25D-E0301',
                           f"{shape}: {what} has {len(points)} vertices",
                           shape.source)
            return None

        if points[0] == points[-1]:
            self.geometric('PEX25D-E0302',
                           f"{shape}: {what} repeats its first vertex "
                           f"({points[0][0]}, {points[0][1]}) at the end; a ring "
                           f"is closed implicitly", shape.source)
            return None

        for i in range(len(points) - 1):
            if points[i] == points[i + 1]:
                self.geometric('PEX25D-E0303',
                               f"{shape}: {what} repeats the vertex "
                               f"({points[i][0]}, {points[i][1]})", shape.source)
                return None

        if ring_is_collinear(points):
            self.geometric('PEX25D-E0304',
                           f"{shape}: {what} encloses no area, every vertex "
                           f"lying on one line", shape.source)
            return None

        if not ring_is_simple(points):
            self.geometric('PEX25D-E0305',
                           f"{shape}: {what} intersects itself", shape.source)
            return None

        return points

    def check_conductor_overlap(self, scene: Any) -> None:
        """
        Two conductors may not share a point.

        Shapes are swept in x and filtered on y and z before anything exact
        runs, because the interesting comparison — different conductors, same
        height, same place — is a vanishing fraction of the pairs. Touching is
        not overlap: abutting shapes of different conductors are legal, and
        only a shared area is reported.
        """
        layers = {layer.name: layer for layer in scene.layers}

        items: List[Item] = []
        for conductor in scene.conductors:
            for region in conductor.regions:
                layer = layers.get(region.layer)
                if layer is None:
                    continue
                for box in region.boxes:
                    items.append(item_of_box(conductor, region.layer, layer, box))
                for polygon in region.polygons:
                    item = item_of_polygon(conductor, region.layer, layer, polygon)
                    if item is not None:
                        items.append(item)

        items.sort(key=lambda item: item.xmin)

        active: List[Item] = []
        overlaps = 0
        for item in items:
            active = [other for other in active if other.xmax >= item.xmin]
            for other in active:
                if other.conductor == item.conductor:
                    continue
                if other.xmax <= item.xmin or item.xmax <= other.xmin:
                    continue
                if other.ymax <= item.ymin or item.ymax <= other.ymin:
                    continue
                if other.zhigh <= item.zlow or item.zhigh <= other.zlow:
                    continue
                if not items_overlap(other, item):
                    continue

                overlaps += 1
                if overlaps <= MAX_OVERLAP_REPORTS:
                    self.geometric(
                        'PEX25D-E0309',
                        f"Conductors '{other.conductor}' (on '{other.layer}') "
                        f"and '{item.conductor}' (on '{item.layer}') overlap "
                        f"near ({max(other.xmin, item.xmin)}, "
                        f"{max(other.ymin, item.ymin)})", item.source)
            active.append(item)

        if overlaps > MAX_OVERLAP_REPORTS:
            self.diagnose('PEX25D-N0002',
                          f"{overlaps - MAX_OVERLAP_REPORTS} further conductor "
                          f"overlaps were found and not listed",
                          tier=Tier.GEOMETRIC, severity=Severity.NOTE)

    def geometric(self, code: str, message: str, source: Any = None) -> None:
        self.diagnose(code, message, tier=Tier.GEOMETRIC, source=source)


# -----------------------------------------------------------------------------
# Shapes
# -----------------------------------------------------------------------------

Ring = List[Tuple[int, int]]


@dataclass(frozen=True)
class Shape:
    """A drawn shape with what the geometric tier needs to talk about it."""

    conductor: str
    layer: str
    is_box: bool
    geometry: Any        # Box2D or Polygon2D
    source: Any = None   # the record it came from, for its SourceRef

    def __str__(self) -> str:
        kind = 'BOX' if self.is_box else 'POLYGON'
        return f"{kind} on conductor '{self.conductor}', layer '{self.layer}'"


def shapes_of_file(pex25d_file: Any) -> Iterator[Shape]:
    kinds = pex25d_file_pb2().ShapeRecord
    for shape in pex25d_file.shapes:
        if shape.kind == kinds.SHAPE_KIND_BOX:
            yield Shape(shape.conductor, shape.layer, True, shape.box, shape)
        elif shape.kind == kinds.SHAPE_KIND_POLYGON:
            yield Shape(shape.conductor, shape.layer, False, shape.polygon, shape)


def shapes_of_scene(scene: Any) -> Iterator[Shape]:
    for conductor in scene.conductors:
        for region in conductor.regions:
            for box in region.boxes:
                yield Shape(conductor.name, region.layer, True, box, conductor)
            for polygon in region.polygons:
                yield Shape(conductor.name, region.layer, False, polygon, conductor)


# -----------------------------------------------------------------------------
# Integer geometry
#
# All of it is exact: coordinates are grid units, every predicate below is a
# comparison of integer cross and dot products, and the one place a midpoint is
# needed works in doubled coordinates rather than in floats. A conformance
# validator that answered "these two conductors overlap" from rounded
# arithmetic would be worse than none.
# -----------------------------------------------------------------------------

def cross3(o: Tuple[int, int], a: Tuple[int, int], b: Tuple[int, int]) -> int:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def dot3(o: Tuple[int, int], a: Tuple[int, int], b: Tuple[int, int]) -> int:
    return (a[0] - o[0]) * (b[0] - o[0]) + (a[1] - o[1]) * (b[1] - o[1])


def edges(ring: Ring) -> Iterator[Tuple[Tuple[int, int], Tuple[int, int]]]:
    for i in range(len(ring)):
        yield ring[i], ring[(i + 1) % len(ring)]


def on_segment(a1: Tuple[int, int], a2: Tuple[int, int],
               p: Tuple[int, int]) -> bool:
    """Whether ``p``, already known to be collinear with a1-a2, is on it."""
    return min(a1[0], a2[0]) <= p[0] <= max(a1[0], a2[0]) and \
        min(a1[1], a2[1]) <= p[1] <= max(a1[1], a2[1])


def segments_meet(a1: Tuple[int, int], a2: Tuple[int, int],
                  b1: Tuple[int, int], b2: Tuple[int, int]) -> bool:
    """Any common point at all, touching and collinear overlap included."""
    d1 = cross3(a1, a2, b1)
    d2 = cross3(a1, a2, b2)
    d3 = cross3(b1, b2, a1)
    d4 = cross3(b1, b2, a2)
    if d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0:
        return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)
    return (d1 == 0 and on_segment(a1, a2, b1)) or \
        (d2 == 0 and on_segment(a1, a2, b2)) or \
        (d3 == 0 and on_segment(b1, b2, a1)) or \
        (d4 == 0 and on_segment(b1, b2, a2))


def ring_is_simple(ring: Ring) -> bool:
    edge_list = list(edges(ring))
    n = len(edge_list)
    for i in range(n):
        a1, a2 = edge_list[i]
        for j in range(i + 1, n):
            b1, b2 = edge_list[j]
            if j == i + 1 or (i == 0 and j == n - 1):
                # Consecutive edges share one endpoint legitimately. What they
                # may not do is fold back along each other.
                shared, before, after = (a2, a1, b2) if j == i + 1 \
                    else (a1, a2, b1)
                if cross3(shared, before, after) == 0 and \
                        dot3(shared, before, after) > 0:
                    return False
            elif segments_meet(a1, a2, b1, b2):
                return False
    return True


def ring_is_collinear(ring: Ring) -> bool:
    origin = ring[0]
    direction = next((p for p in ring[1:] if p != origin), None)
    if direction is None:
        return True
    return all(cross3(origin, direction, p) == 0 for p in ring)


def point_in_ring(x: Any, y: Any, ring: Ring) -> int:
    """
    Where a point lies relative to a ring: 1 inside, 0 on it, -1 outside.

    The ring is integer; the point may be a Fraction, and every comparison
    below stays exact either way.
    """
    inside = False
    for (x1, y1), (x2, y2) in edges(ring):
        if (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1) == 0 and \
                min(x1, x2) <= x <= max(x1, x2) and \
                min(y1, y2) <= y <= max(y1, y2):
            return 0
        if (y1 > y) != (y2 > y):
            # Sign of (crossing_x - x), scaled by (y2 - y1).
            side = (x1 - x) * (y2 - y1) + (y - y1) * (x2 - x1)
            if (side > 0) == (y2 > y1):
                inside = not inside
    return 1 if inside else -1


@dataclass(frozen=True)
class Polygon:
    """A resolved polygon: one outer ring and its holes, as integer rings."""

    outer: Ring
    holes: List[Ring] = field(default_factory=list)

    def rings(self) -> Iterator[Ring]:
        yield self.outer
        yield from self.holes

    def all_edges(self) -> Iterator[Tuple[Tuple[int, int], Tuple[int, int]]]:
        for ring in self.rings():
            yield from edges(ring)


def point_in_polygon(x: Any, y: Any, polygon: Polygon) -> int:
    where = point_in_ring(x, y, polygon.outer)
    if where <= 0:
        return where
    for hole in polygon.holes:
        in_hole = point_in_ring(x, y, hole)
        if in_hole == 0:
            return 0
        if in_hole > 0:
            return -1
    return 1


def ring_strictly_inside(inner: Ring, outer: Ring) -> bool:
    if any(point_in_ring(x, y, outer) != 1 for x, y in inner):
        return False
    # Every vertex inside is not enough on a non-convex outer ring: an edge can
    # still leave it and come back.
    return not any(segments_meet(a1, a2, b1, b2)
                   for a1, a2 in edges(inner)
                   for b1, b2 in edges(outer))


def rings_meet(first: Ring, second: Ring) -> bool:
    """Whether two rings touch, cross, or one contains the other."""
    if any(segments_meet(a1, a2, b1, b2)
           for a1, a2 in edges(first) for b1, b2 in edges(second)):
        return True
    return point_in_ring(first[0][0], first[0][1], second) == 1 or \
        point_in_ring(second[0][0], second[0][1], first) == 1


def crossing_x(a1: Tuple[int, int], a2: Tuple[int, int],
               b1: Tuple[int, int], b2: Tuple[int, int]) -> Optional[Fraction]:
    """Where two segments meet in a single point, or ``None``."""
    denominator = (a2[0] - a1[0]) * (b2[1] - b1[1]) - \
                  (a2[1] - a1[1]) * (b2[0] - b1[0])
    if denominator == 0:
        return None  # parallel: collinear overlap ends at a vertex anyway
    t = Fraction((b1[0] - a1[0]) * (b2[1] - b1[1]) -
                 (b1[1] - a1[1]) * (b2[0] - b1[0]), denominator)
    u = Fraction((b1[0] - a1[0]) * (a2[1] - a1[1]) -
                 (b1[1] - a1[1]) * (a2[0] - a1[0]), denominator)
    if not (0 <= t <= 1 and 0 <= u <= 1):
        return None
    return a1[0] + t * (a2[0] - a1[0])


def polygons_overlap(first: Polygon, second: Polygon) -> bool:
    """
    Whether two polygons share AREA. A shared edge or corner does not count.

    A vertical decomposition, which is the part of the answer that sampling
    vertices and edge midpoints cannot give: where two outlines run along each
    other for a stretch, every vertex and every midpoint of one lies ON the
    other rather than inside it, and a sampling test reports no overlap for
    shapes that plainly have one.

    So cut the strip the two bounding boxes share at every x where either
    outline has a vertex or the two outlines meet. Within one slab no boundary
    turns, so a shared area covers a whole cell of the decomposition and the
    midpoint of that cell is strictly inside both. Every coordinate is exact.
    """
    lo = max(min(x for x, _ in first.outer), min(x for x, _ in second.outer))
    hi = min(max(x for x, _ in first.outer), max(x for x, _ in second.outer))
    if lo >= hi:
        return False

    cuts = {Fraction(lo), Fraction(hi)}
    for polygon in (first, second):
        for ring in polygon.rings():
            cuts.update(Fraction(x) for x, _ in ring if lo < x < hi)
    for a1, a2 in first.all_edges():
        for b1, b2 in second.all_edges():
            x = crossing_x(a1, a2, b1, b2)
            if x is not None and lo < x < hi:
                cuts.add(x)

    columns = sorted(cuts)
    segments = list(first.all_edges()) + list(second.all_edges())
    for left, right in zip(columns, columns[1:]):
        x = (left + right) / 2

        heights = set()
        for (x1, y1), (x2, y2) in segments:
            if min(x1, x2) < x < max(x1, x2):
                heights.add(y1 + Fraction((x - x1) * (y2 - y1), x2 - x1))
        levels = sorted(heights)

        for low, high in zip(levels, levels[1:]):
            y = (low + high) / 2
            if point_in_polygon(x, y, first) == 1 and \
                    point_in_polygon(x, y, second) == 1:
                return True

    return False


# -----------------------------------------------------------------------------
# Overlap sweep
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Item:
    """One shape with the bounds the sweep filters on."""

    conductor: str
    layer: str
    source: Any
    xmin: int
    ymin: int
    xmax: int
    ymax: int
    zlow: int
    zhigh: int
    polygon: Optional[Polygon] = None  # None for a box: its bounds ARE its area


def item_of_box(conductor: Any, layer_name: str, layer: Any, box: Any) -> Item:
    return Item(conductor.name, layer_name, conductor,
                box.lower_left.x, box.lower_left.y,
                box.upper_right.x, box.upper_right.y,
                layer.zlow, layer.zhigh)


def item_of_polygon(conductor: Any,
                    layer_name: str,
                    layer: Any,
                    polygon: Any) -> Optional[Item]:
    outer: Ring = [(p.x, p.y) for p in polygon.outer.points]
    if len(outer) < 3:
        return None  # already reported by the wellformedness checks
    holes = [[(p.x, p.y) for p in hole.points] for hole in polygon.holes]
    xs = [x for x, _ in outer]
    ys = [y for _, y in outer]
    return Item(conductor.name, layer_name, conductor,
                min(xs), min(ys), max(xs), max(ys),
                layer.zlow, layer.zhigh,
                Polygon(outer, [hole for hole in holes if len(hole) >= 3]))


def items_overlap(first: Item, second: Item) -> bool:
    if first.polygon is None and second.polygon is None:
        # Both boxes, and the sweep already compared both intervals.
        return True
    return polygons_overlap(polygon_of(first), polygon_of(second))


def polygon_of(item: Item) -> Polygon:
    if item.polygon is not None:
        return item.polygon
    return Polygon([(item.xmin, item.ymin), (item.xmax, item.ymin),
                    (item.xmax, item.ymax), (item.xmin, item.ymax)])


# -----------------------------------------------------------------------------

def is_scene(message: Any) -> bool:
    return message.DESCRIPTOR.name == 'PEX25DScene'


def geometric_tier(report: DiagnosticsReport,
                   pex25d_file: Any = None,
                   scene: Any = None) -> None:
    """
    The geometric tier, for callers that already hold one or both forms.

    Wellformedness runs on the file when there is one, because only there does a
    shape still carry the SourceRef of the record it came from. Conductor
    overlap runs on the scene, the only form that knows how high a layer is.
    """
    validator = Validator(report, strict=True)
    if pex25d_file is not None:
        validator.check_shapes(shapes_of_file(pex25d_file))
    elif scene is not None:
        validator.check_shapes(shapes_of_scene(scene))
    if scene is not None:
        validator.check_conductor_overlap(scene)


def validate(message: Any,
             report: Optional[DiagnosticsReport] = None,
             strict: bool = False,
             scene: Any = None) -> DiagnosticsReport:
    """
    Check a ``PEX25DFile`` or ``PEX25DScene`` and return what was found.

    Never raises for an invalid message: the diagnostics are the answer.

    :param strict: additionally run the geometric tier — ring and box
        wellformedness, hole containment, conductor overlap.
    :param scene: for a ``PEX25DFile``, the scene it resolves to, when the
        caller has resolved it already. Saves resolving twice, and keeps the
        resolver's diagnostics from being recorded twice. Ignored for a scene.
    """
    report = report if report is not None else DiagnosticsReport()
    Validator(report, strict=strict).validate(message, scene=scene)
    return report
