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

"""Resolution of a ``PEX25DFile`` into a ``PEX25DScene``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import *

from .diagnostics import (Diagnostic, DiagnosticsReport, Severity, Tier,
                          source_ref)
from .protobuf import (
    pex25d_dielectric_pb2,
    pex25d_file_pb2,
    pex25d_geometry_pb2,
    pex25d_scene_pb2,
)

FLOATING_NET = 'FLOATING'


class ResolveError(Exception):
    """The file could not be resolved; the report carries the reasons."""


@dataclass
class Profile:
    """A declared object with a z extent, whatever kind of record made it."""

    name: str
    zlow: int
    zhigh: int
    is_conductive: bool


@dataclass
class ChainInfo:
    """Where a dielectric sits in its WRAPS chain."""

    depth: int
    root: str
    lateral: int  # total offset from the root's surface, grid units


class Resolver:
    def __init__(self,
                 pex25d_file: Any,
                 report: Optional[DiagnosticsReport] = None,
                 strict: bool = False):
        self.file = pex25d_file
        self.report = report if report is not None else DiagnosticsReport()
        self.strict = strict
        self.errors = 0

        self.profiles: Dict[str, Profile] = {}
        self.dielectrics_by_name: Dict[str, Any] = {}
        self.chains: Dict[str, ChainInfo] = {}
        self.resolved_dielectric_z: Dict[str, Tuple[int, int]] = {}

    # ---------------------------------------------------------- diagnostics

    def diagnose(self,
                 code: str,
                 message: str,
                 tier: Tier = Tier.SEMANTIC,
                 severity: Severity = Severity.ERROR,
                 source: Any = None) -> None:
        if severity == Severity.ERROR:
            self.errors += 1
        self.report.add(Diagnostic(code=code, severity=severity, tier=tier,
                                   message=message, source=source_ref(source)))

    # ---------------------------------------------------------------- entry

    def resolve(self) -> Any:
        scene = pex25d_scene_pb2().PEX25DScene()
        scene.format_version_major = self.file.format_version_major
        scene.format_version_minor = self.file.format_version_minor
        scene.format_version_suffix = self.file.format_version_suffix
        scene.units.CopyFrom(self.file.units)
        for meta in self.file.meta:
            scene.meta.add().CopyFrom(meta)
        if self.file.HasField('resistance_temperature'):
            scene.resistance_temperature.CopyFrom(self.file.resistance_temperature)

        self.collect_profiles()
        self.resolve_ground_plane(scene)
        self.resolve_layers(scene)
        self.resolve_dielectrics(scene)
        self.resolve_conductors(scene)
        self.resolve_domain(scene)

        if self.strict:
            # The geometric tier lives in the validator; running it from here
            # keeps `resolve --strict` and `validate --strict` the same checks.
            from .validator import geometric_tier
            geometric_tier(self.report, self.file,
                           scene=None if self.errors else scene)

        if self.errors:
            raise ResolveError(f"{self.errors} error(s) while resolving the file")
        return scene

    # ------------------------------------------------------------- profiles

    def collect_profiles(self) -> None:
        """
        Give every profile an absolute z extent.

        Metals and the ground plane carry theirs; a via derives its own from
        what it CONNECTS, which is why a change in metal position or thickness
        propagates without any other edit. A via may connect to another via, so
        this runs to a fixpoint rather than in one pass.
        """
        if self.file.HasField('ground_plane'):
            ground_plane = self.file.ground_plane
            self.declare(Profile(ground_plane.name, ground_plane.zlow,
                                 ground_plane.zhigh, is_conductive=True),
                         ground_plane)
        else:
            self.diagnose('PEX25D-E0210',
                          "No GROUND_PLANE: PEX25D requires exactly one")

        for metal in self.file.metals:
            if metal.zhigh <= metal.zlow:
                self.diagnose('PEX25D-E0211',
                              f"METAL '{metal.name}': zlow must be less than zhigh",
                              source=metal)
            self.declare(Profile(metal.name, metal.zlow, metal.zhigh,
                                 is_conductive=True), metal)

        pending = list(self.file.vias)
        while pending:
            progressed = []
            for via in pending:
                below = self.profiles.get(via.connects_below)
                above = self.profiles.get(via.connects_above)
                if below is None or above is None:
                    continue
                if above.zlow < below.zhigh:
                    self.diagnose(
                        'PEX25D-E0212',
                        f"VIA '{via.name}' CONNECTS '{via.connects_below}' "
                        f"'{via.connects_above}': the endpoints are in the wrong "
                        f"order, or they overlap in z",
                        source=via)
                self.declare(Profile(via.name, below.zhigh, above.zlow,
                                     is_conductive=True), via)
                progressed.append(via)

            if not progressed:
                for via in pending:
                    for endpoint in (via.connects_below, via.connects_above):
                        if endpoint not in self.profiles:
                            self.diagnose(
                                'PEX25D-E0201',
                                f"VIA '{via.name}' CONNECTS an unknown or "
                                f"unresolvable profile '{endpoint}'",
                                source=via)
                return
            pending = [via for via in pending if via not in progressed]

    def declare(self, profile: Profile, record: Any) -> None:
        if profile.name in self.profiles:
            self.diagnose('PEX25D-E0202',
                          f"'{profile.name}' is declared more than once in the "
                          f"profile namespace", source=record)
            return
        self.profiles[profile.name] = profile

    def resolve_ground_plane(self, scene: Any) -> None:
        if not self.file.HasField('ground_plane'):
            return
        ground_plane = self.file.ground_plane
        scene.ground_plane.name = ground_plane.name
        scene.ground_plane.zlow = ground_plane.zlow
        scene.ground_plane.zhigh = ground_plane.zhigh
        if ground_plane.HasField('source'):
            scene.ground_plane.source.CopyFrom(ground_plane.source)

    def resolve_layers(self, scene: Any) -> None:
        kinds = pex25d_scene_pb2().ResolvedLayer
        metal_resistances = {r.metal: r for r in self.file.metal_resistances}
        via_resistances = {r.via: r for r in self.file.via_resistances}

        for metal in self.file.metals:
            layer = scene.layers.add()
            layer.name = metal.name
            layer.kind = kinds.RESOLVED_LAYER_KIND_METAL
            layer.zlow, layer.zhigh = metal.zlow, metal.zhigh
            if metal.name in metal_resistances:
                layer.metal_resistance.CopyFrom(metal_resistances[metal.name])
            if metal.HasField('source'):
                layer.source.CopyFrom(metal.source)

        for via in self.file.vias:
            profile = self.profiles.get(via.name)
            if profile is None:
                continue
            layer = scene.layers.add()
            layer.name = via.name
            layer.kind = kinds.RESOLVED_LAYER_KIND_VIA
            layer.zlow, layer.zhigh = profile.zlow, profile.zhigh
            layer.connects_below = via.connects_below
            layer.connects_above = via.connects_above
            if via.name in via_resistances:
                layer.via_resistance.CopyFrom(via_resistances[via.name])
            if via.HasField('source'):
                layer.source.CopyFrom(via.source)

        for name in metal_resistances:
            if name not in {m.name for m in self.file.metals}:
                self.diagnose('PEX25D-E0220',
                              f"RESISTANCE METAL names '{name}', which is not a "
                              f"METAL profile")
        for name in via_resistances:
            if name not in {v.name for v in self.file.vias}:
                self.diagnose('PEX25D-E0221',
                              f"RESISTANCE VIA names '{name}', which is not a "
                              f"VIA profile")

    # ---------------------------------------------------------- dielectrics

    def chain_of(self, name: str, seen: Optional[Set[str]] = None) -> Optional[ChainInfo]:
        """
        Depth, root and cumulative lateral offset of a dielectric's WRAPS chain.

        Depth 1 is a film directly on a conductor or the ground plane; a film on
        that film is depth 2. Occupancy goes to the smallest depth, so this is
        what decides which material is visible where two claim a point.
        """
        if name in self.chains:
            return self.chains[name]

        seen = seen or set()
        if name in seen:
            self.diagnose('PEX25D-E0230',
                          f"WRAPS chain through '{name}' is cyclic")
            return None
        seen = seen | {name}

        dielectric = self.dielectrics_by_name[name]
        wrapped = dielectric.wraps

        if wrapped in self.profiles:
            info = ChainInfo(depth=1, root=wrapped, lateral=lateral_of(dielectric))
        elif wrapped in self.dielectrics_by_name:
            outer = self.chain_of(wrapped, seen)
            if outer is None:
                return None
            info = ChainInfo(depth=outer.depth + 1, root=outer.root,
                             lateral=outer.lateral + lateral_of(dielectric))
        else:
            self.diagnose('PEX25D-E0201',
                          f"Dielectric '{name}' WRAPS '{wrapped}', which is not a "
                          f"declared profile", source=dielectric)
            return None

        self.chains[name] = info
        return info

    def wrapped_extent(self, name: str) -> Optional[Tuple[int, int]]:
        """The z extent of whatever a dielectric is built on."""
        profile = self.profiles.get(name)
        if profile is not None:
            return profile.zlow, profile.zhigh
        return self.resolved_dielectric_z.get(name)

    def declare_dielectric_names(self) -> None:
        """
        Dielectrics are in the same namespace as the conductive profiles.

        They cannot go through :meth:`declare` — a dielectric has no z until it
        is resolved, and resolving it needs the conductive profiles first — so
        the namespace is closed here instead. Without this a repeated
        DIELECTRIC name is silent: the later declaration simply replaces the
        earlier one in the lookup, and what shows up is some unrelated film
        wrapping the wrong object several records later.
        """
        seen: Set[str] = set()
        for dielectric in self.file.dielectrics:
            if dielectric.name in self.profiles or dielectric.name in seen:
                self.diagnose('PEX25D-E0202',
                              f"'{dielectric.name}' is declared more than once "
                              f"in the profile namespace", source=dielectric)
            seen.add(dielectric.name)

        if self.file.HasField('background') and \
                (self.file.background.name in self.profiles or
                 self.file.background.name in seen):
            self.diagnose('PEX25D-E0202',
                          f"'{self.file.background.name}' is declared more than "
                          f"once in the profile namespace",
                          source=self.file.background)

    def resolve_dielectrics(self, scene: Any) -> None:
        kinds = pex25d_dielectric_pb2()
        self.declare_dielectric_names()
        self.dielectrics_by_name = {d.name: d for d in self.file.dielectrics}

        ordered = []
        for dielectric in self.file.dielectrics:
            info = self.chain_of(dielectric.name)
            if info is not None:
                ordered.append((info.depth, dielectric, info))

        # Ascending wrap_depth, so a consumer walking the list sees the
        # occupancy winner first at any point it tests. Ties keep file order.
        ordered.sort(key=lambda entry: entry[0])

        for _, dielectric, info in ordered:
            extent = self.resolve_dielectric_extent(dielectric, kinds)
            if extent is None:
                continue
            self.resolved_dielectric_z[dielectric.name] = extent

            resolved = scene.dielectrics.add()
            resolved.name = dielectric.name
            resolved.kind = dielectric.kind
            resolved.permittivity = dielectric.permittivity
            resolved.wraps = dielectric.wraps
            resolved.wrap_depth = info.depth
            resolved.root = info.root
            resolved.zlow, resolved.zhigh = extent

            if dielectric.kind == kinds.DIELECTRIC_KIND_CONFORMAL:
                conformal = dielectric.conformal
                resolved.thickness_over_wrapped = conformal.thickness_over_wrapped
                resolved.thickness_beside_wrapped = conformal.thickness_beside_wrapped
                resolved.thickness_on_field = conformal.thickness_on_field
            elif dielectric.kind == kinds.DIELECTRIC_KIND_SIMPLE:
                resolved.between_below = dielectric.simple.between_below
                resolved.between_above = dielectric.simple.between_above

            if dielectric.HasField('source'):
                resolved.source.CopyFrom(dielectric.source)

        if self.file.HasField('background'):
            scene.background.name = self.file.background.name
            scene.background.permittivity = self.file.background.permittivity
            if self.file.background.HasField('source'):
                scene.background.source.CopyFrom(self.file.background.source)
        else:
            self.diagnose('PEX25D-E0213',
                          "No DIELECTRIC_BACKGROUND: PEX25D requires exactly one")

    def resolve_dielectric_extent(self,
                                  dielectric: Any,
                                  kinds: Any) -> Optional[Tuple[int, int]]:
        if dielectric.kind == kinds.DIELECTRIC_KIND_SIMPLE:
            simple = dielectric.simple
            below = self.wrapped_extent(simple.between_below)
            above = self.wrapped_extent(simple.between_above)
            for name, extent in ((simple.between_below, below),
                                 (simple.between_above, above)):
                if extent is None:
                    self.diagnose('PEX25D-E0201',
                                  f"DIELECTRIC_SIMPLE '{dielectric.name}' BETWEEN "
                                  f"names '{name}', which is not a declared profile",
                                  source=dielectric)
            if below is None or above is None:
                return None
            # Bottom of <below> to bottom of <above>, so the band always joins
            # the neighbouring levels whatever the films inside it reach.
            return below[0], above[0]

        if dielectric.kind == kinds.DIELECTRIC_KIND_CONFORMAL:
            wrapped = self.wrapped_extent(dielectric.wraps)
            if wrapped is None:
                return None
            conformal = dielectric.conformal
            over = wrapped[1] + conformal.thickness_over_wrapped
            # THICKNESS_ON_FIELD is measured up from the BOTTOM face of the
            # wrapped object, so on the field the film may reach lower than it
            # does over the object — or higher.
            on_field = wrapped[0] + conformal.thickness_on_field
            return wrapped[0], max(over, on_field)

        self.diagnose('PEX25D-E0214',
                      f"Dielectric '{dielectric.name}' has no kind",
                      source=dielectric)
        return None

    # ----------------------------------------------------------- conductors

    def resolve_conductors(self, scene: Any) -> None:
        kinds = pex25d_file_pb2().ShapeRecord
        layer_kinds = pex25d_scene_pb2().ResolvedLayer
        layers = {layer.name: layer for layer in scene.layers}

        shapes_by_conductor: Dict[str, Dict[str, List[Any]]] = {}
        for shape in self.file.shapes:
            if shape.layer not in layers:
                self.diagnose('PEX25D-E0201',
                              f"Shape on conductor '{shape.conductor}' names LAYER "
                              f"'{shape.layer}', which is not a METAL or VIA profile",
                              source=shape)
                continue
            shapes_by_conductor.setdefault(shape.conductor, {}) \
                .setdefault(shape.layer, []).append(shape)

        terminals_by_conductor: Dict[str, List[Any]] = {}
        for terminal in self.file.terminals:
            terminals_by_conductor.setdefault(terminal.conductor, []).append(terminal)

        declared = {conductor.name for conductor in self.file.conductors}
        for name in sorted(set(shapes_by_conductor) - declared):
            self.diagnose('PEX25D-E0201',
                          f"Shapes name conductor '{name}', which is not declared")
        for name in sorted(set(terminals_by_conductor) - declared):
            self.diagnose('PEX25D-E0201',
                          f"A TERMINAL names conductor '{name}', which is not declared")

        for conductor in self.file.conductors:
            resolved = scene.conductors.add()
            resolved.name = conductor.name
            resolved.net = conductor.net
            resolved.floating = conductor.net == FLOATING_NET
            if conductor.HasField('source'):
                resolved.source.CopyFrom(conductor.source)

            by_layer = shapes_by_conductor.get(conductor.name, {})
            for layer_name, shapes in by_layer.items():
                region = resolved.regions.add()
                region.layer = layer_name
                for shape in shapes:
                    if shape.kind == kinds.SHAPE_KIND_BOX:
                        region.boxes.add().CopyFrom(shape.box)
                    elif shape.kind == kinds.SHAPE_KIND_POLYGON:
                        region.polygons.add().CopyFrom(shape.polygon)
                    else:
                        self.diagnose('PEX25D-E0215',
                                      f"Shape on conductor '{conductor.name}', layer "
                                      f"'{layer_name}' has no kind", source=shape)

            for terminal in terminals_by_conductor.get(conductor.name, []):
                self.resolve_terminal(resolved, terminal, layers, by_layer, layer_kinds)

    def resolve_terminal(self,
                         conductor: Any,
                         terminal: Any,
                         layers: Dict[str, Any],
                         shapes_by_layer: Dict[str, List[Any]],
                         layer_kinds: Any) -> None:
        """
        Intersect the terminal's marker region with the conductor's geometry.

        The region is a marker, not geometry: it may span the gaps between the
        shapes it selects. The node is the intersection, computed once here so
        that no adapter repeats the boolean.
        """
        layer = layers.get(terminal.layer)
        if layer is None:
            self.diagnose('PEX25D-E0201',
                          f"TERMINAL '{terminal.name}' names LAYER '{terminal.layer}', "
                          f"which is not a METAL or VIA profile", source=terminal)
            return

        kinds = pex25d_file_pb2().ShapeRecord
        on_via = layer.kind == layer_kinds.RESOLVED_LAYER_KIND_VIA
        region = terminal.region

        boxes: List[Any] = []
        polygons: List[Any] = []
        for shape in shapes_by_layer.get(terminal.layer, []):
            if shape.kind == kinds.SHAPE_KIND_BOX:
                clipped = intersect_boxes(region, shape.box)
                if clipped is None:
                    continue
                if on_via and not same_box(clipped, shape.box):
                    self.diagnose(
                        'PEX25D-E0240',
                        f"TERMINAL '{terminal.name}' clips a via cut on layer "
                        f"'{terminal.layer}' rather than covering it whole",
                        source=terminal)
                    return
                boxes.append(clipped)
            elif shape.kind == kinds.SHAPE_KIND_POLYGON:
                if box_contains(region, polygon_bounds(shape.polygon)):
                    polygons.append(shape.polygon)
                elif boxes_overlap(region, polygon_bounds(shape.polygon)):
                    # Clipping a polygon partially would put new vertices on the
                    # region's edges, which for a non-Manhattan edge lands off
                    # grid. Refuse rather than snap silently.
                    self.diagnose(
                        'PEX25D-E0241',
                        f"TERMINAL '{terminal.name}' partially covers a polygon on "
                        f"layer '{terminal.layer}'; only whole polygons and clipped "
                        f"boxes are supported", source=terminal)
                    return

        if not boxes and not polygons:
            self.diagnose('PEX25D-E0242',
                          f"TERMINAL '{terminal.name}' selects nothing on layer "
                          f"'{terminal.layer}'", source=terminal)
            return

        resolved = conductor.terminals.add()
        resolved.name = terminal.name
        resolved.kind = terminal.kind
        resolved.layer = terminal.layer
        resolved.region.CopyFrom(region)
        for box in boxes:
            resolved.boxes.add().CopyFrom(box)
        for polygon in polygons:
            resolved.polygons.add().CopyFrom(polygon)
        resolved.zlow, resolved.zhigh = layer.zlow, layer.zhigh
        if terminal.HasField('source'):
            resolved.source.CopyFrom(terminal.source)

    # --------------------------------------------------------------- domain

    def geometry_bounds(self, scene: Any) -> Optional[Tuple[int, int, int, int, int, int]]:
        """
        Bounding box of all finite, non-ground-plane geometry.

        "Finite" means bounded in XY: conductor shapes, and conformal films with
        `thickness_on_field` zero, which reach past their conductor laterally by
        the accumulated `thickness_beside_wrapped` of their chain. Simple bands,
        films that cover the field, the background and the ground plane are
        laterally unbounded and contribute nothing.
        """
        kinds = pex25d_dielectric_pb2()
        layers = {layer.name: layer for layer in scene.layers}
        bounds: Optional[List[int]] = None

        # Only a conformal film that does NOT cover the field is finite. A
        # simple band, and a conformal with a non-zero thickness_on_field, are
        # laterally unbounded and contribute nothing here.
        finite_films: Dict[str, List[Any]] = {}
        reach: Dict[str, int] = {}
        for dielectric in scene.dielectrics:
            if dielectric.kind != kinds.DIELECTRIC_KIND_CONFORMAL:
                continue
            if dielectric.thickness_on_field:
                continue
            if dielectric.root not in layers:
                continue
            info = self.chains.get(dielectric.name)
            if info is None:
                continue
            finite_films.setdefault(dielectric.root, []).append(dielectric)
            reach[dielectric.root] = max(reach.get(dielectric.root, 0), info.lateral)

        for conductor in scene.conductors:
            for region in conductor.regions:
                layer = layers.get(region.layer)
                if layer is None:
                    continue
                grow = reach.get(region.layer, 0)
                top = max([layer.zhigh]
                          + [f.zhigh for f in finite_films.get(region.layer, [])])
                for box in region.boxes:
                    bounds = extend(bounds, box.lower_left.x - grow,
                                    box.lower_left.y - grow,
                                    box.upper_right.x + grow,
                                    box.upper_right.y + grow, layer.zlow, top)
                for polygon in region.polygons:
                    x0, y0, x1, y1 = polygon_bounds_tuple(polygon)
                    bounds = extend(bounds, x0 - grow, y0 - grow, x1 + grow, y1 + grow,
                                    layer.zlow, top)

        return tuple(bounds) if bounds else None

    def resolve_domain(self, scene: Any) -> None:
        origins = pex25d_scene_pb2().ResolvedDomain
        bounds = self.geometry_bounds(scene)
        which = self.file.WhichOneof('domain')

        if bounds is None and which is None:
            return
        if bounds is not None:
            fill_box3d(scene.domain.geometry_bounds, *bounds)

        if which is None:
            # The resolver never invents a domain: it cannot know what a given
            # solver wants, and an adapter is free to place its own boundary.
            # geometry_bounds is still useful to one that does.
            return

        if which == 'domain_box':
            scene.domain.box.CopyFrom(self.file.domain_box.box)
            scene.domain.origin = origins.ORIGIN_DOMAIN_BOX
            return

        margin = self.file.domain_margin
        if bounds is None:
            self.diagnose('PEX25D-E0250',
                          "DOMAIN_MARGIN was given but the file has no finite "
                          "geometry to apply it to", severity=Severity.WARNING)
            return

        x0, y0, x1, y1, _, z1 = bounds
        # X/Y expand in both directions; Z expands only upward, because the
        # ground plane forms the lower boundary.
        lower_z = scene.ground_plane.zhigh if scene.HasField('ground_plane') \
            else bounds[4]
        fill_box3d(scene.domain.box,
                   x0 - margin.x, y0 - margin.y, x1 + margin.x, y1 + margin.y,
                   lower_z, z1 + margin.z)
        scene.domain.origin = origins.ORIGIN_DOMAIN_MARGIN
        scene.domain.applied_margin.CopyFrom(margin)


# ---------------------------------------------------------------- geometry

def lateral_of(dielectric: Any) -> int:
    kinds = pex25d_dielectric_pb2()
    if dielectric.kind == kinds.DIELECTRIC_KIND_CONFORMAL:
        return dielectric.conformal.thickness_beside_wrapped
    return 0


def polygon_bounds_tuple(polygon: Any) -> Tuple[int, int, int, int]:
    xs = [p.x for p in polygon.outer.points]
    ys = [p.y for p in polygon.outer.points]
    return min(xs), min(ys), max(xs), max(ys)


def polygon_bounds(polygon: Any) -> Any:
    x0, y0, x1, y1 = polygon_bounds_tuple(polygon)
    box = pex25d_geometry_pb2().Box2D()
    box.lower_left.x, box.lower_left.y = x0, y0
    box.upper_right.x, box.upper_right.y = x1, y1
    return box


def intersect_boxes(a: Any, b: Any) -> Optional[Any]:
    x0 = max(a.lower_left.x, b.lower_left.x)
    y0 = max(a.lower_left.y, b.lower_left.y)
    x1 = min(a.upper_right.x, b.upper_right.x)
    y1 = min(a.upper_right.y, b.upper_right.y)
    if x0 >= x1 or y0 >= y1:
        return None
    box = pex25d_geometry_pb2().Box2D()
    box.lower_left.x, box.lower_left.y = x0, y0
    box.upper_right.x, box.upper_right.y = x1, y1
    return box


def same_box(a: Any, b: Any) -> bool:
    return (a.lower_left.x, a.lower_left.y, a.upper_right.x, a.upper_right.y) == \
           (b.lower_left.x, b.lower_left.y, b.upper_right.x, b.upper_right.y)


def box_contains(outer: Any, inner: Any) -> bool:
    return (outer.lower_left.x <= inner.lower_left.x
            and outer.lower_left.y <= inner.lower_left.y
            and outer.upper_right.x >= inner.upper_right.x
            and outer.upper_right.y >= inner.upper_right.y)


def boxes_overlap(a: Any, b: Any) -> bool:
    return (a.lower_left.x < b.upper_right.x and b.lower_left.x < a.upper_right.x
            and a.lower_left.y < b.upper_right.y and b.lower_left.y < a.upper_right.y)


def extend(bounds: Optional[List[int]],
           x0: int, y0: int, x1: int, y1: int, z0: int, z1: int) -> List[int]:
    if bounds is None:
        return [x0, y0, x1, y1, z0, z1]
    return [min(bounds[0], x0), min(bounds[1], y0),
            max(bounds[2], x1), max(bounds[3], y1),
            min(bounds[4], z0), max(bounds[5], z1)]


def fill_box3d(box: Any, x0: int, y0: int, x1: int, y1: int, z0: int, z1: int) -> None:
    box.lower_left.x, box.lower_left.y, box.lower_left.z = x0, y0, z0
    box.upper_right.x, box.upper_right.y, box.upper_right.z = x1, y1, z1


def resolve(pex25d_file: Any,
            report: Optional[DiagnosticsReport] = None,
            strict: bool = False) -> Any:
    """
    Resolve a ``kpex.pex25d.PEX25DFile`` into a ``kpex.pex25d.PEX25DScene``.

    Derives absolute z extents, resolves ``CONNECTS`` / ``BETWEEN`` / ``WRAPS``,
    flattens the wrap chain to a depth number and computes terminal
    intersections.

    :param strict: additionally run the geometric tier — ring and box
        wellformedness, hole containment, conductor overlap.
    :raises ResolveError: when the file could not be resolved; the reasons are
        in ``report``.
    """
    return Resolver(pex25d_file, report=report, strict=strict).resolve()
