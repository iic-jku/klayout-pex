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
Build FasterCap geometry from a resolved PEX25D scene.

The occupancy rule maps onto the model generator almost for free.
:meth:`FasterCapModelBuilder.generate` legalizes overlapping regions by the
order materials were added, conductors ahead of every dielectric — which is
exactly the PEX25D rule once the dielectrics are added in ascending wrap depth.
A resolved scene already lists them in that order, so the innermost film wins
and nothing has to be subtracted by hand.
"""

from __future__ import annotations

from fractions import Fraction
from typing import *

import klayout.db as kdb

from ..log import debug, info, warning
from ..klayout.pex25d_ground import GroundGeometryError, region_of
from ..pex25d.electrical import conductor_body, ground_body, solver_body_names
from ..pex25d.protobuf import pex25d_dielectric_pb2, pex25d_scene_pb2
from ..plugin_api.v1 import ExportError
from .fastercap_model_generator import FasterCapModelBuilder, FasterCapModelGenerator

if TYPE_CHECKING:
    from .pex25d_exporter import FasterCapModelOptions

    from klayout_pex_protobuf.kpex.pex25d.pex25d_scene_pb2 import PEX25DScene


class PEX25DFasterCapModelBuilder:
    """Convert one scene and its export settings into solver geometry."""

    def __init__(self, scene: PEX25DScene, options: FasterCapModelOptions):
        self.scene = scene
        self.options = options
        self.body_names = solver_body_names(scene)

        units = scene.units
        if not units.grid_denominator:
            raise ExportError("The scene declares no grid")
        # Coordinates stay in grid units and the model's DBU *is* the grid, so
        # nothing is rescaled and no precision is lost on the way out.
        self.grid = Fraction(units.grid_numerator, units.grid_denominator)
        self.dbu = float(self.grid)

        self.layers = {layer.name: layer for layer in scene.layers}
        self.dielectrics = {d.name: d for d in scene.dielectrics}

    # ------------------------------------------------------------- geometry

    def um(self, grid_units: int) -> float:
        return float(Fraction(grid_units) * self.grid)

    def shapes_of_layer(self, layer_name: str) -> kdb.Region:
        """Every conductor's geometry on one layer, unioned across nets."""
        region = kdb.Region()
        for conductor in self.scene.conductors:
            for conductor_region in conductor.regions:
                if conductor_region.layer != layer_name:
                    continue
                region += region_of(conductor_region)
        return region.merged()

    @property
    def field(self) -> kdb.Region:
        """
        The lateral extent of everything unbounded in XY.

        A DOMAIN_BOX states it; otherwise the finite geometry grown by the
        margin, which is the same shape the FasterCap input builder has always
        used, just derived from the scene rather than from the layout.
        """
        if not hasattr(self, '_field'):
            domain = self.scene.domain
            origins = pex25d_scene_pb2().ResolvedDomain
            if self.scene.HasField('domain') \
                    and domain.origin != origins.ORIGIN_UNSPECIFIED:
                box = domain.box
            else:
                box = domain.geometry_bounds if self.scene.HasField('domain') else None
                if box is None or (box.lower_left.x == 0 and box.upper_right.x == 0):
                    raise ExportError(
                        "The scene has neither a domain nor finite geometry, so "
                        "there is nothing to bound the unbounded materials with")
                margin = int(round(self.options.field_margin_um / float(self.grid)))
                box = grow(box, margin)
            from ..klayout.pex25d_ground import check_native_ground_coordinate, GroundGeometryError
            try:
                for point in (box.lower_left, box.upper_right):
                    check_native_ground_coordinate(point.x)
                    check_native_ground_coordinate(point.y)
            except GroundGeometryError as exc:
                raise ExportError(f"Ground export field cannot be represented: {exc}") from exc
            self._field = kdb.Region(kdb.Box(box.lower_left.x, box.lower_left.y,
                                             box.upper_right.x, box.upper_right.y))
        return self._field

    @property
    def ground_region(self) -> kdb.Region:
        from ..klayout.pex25d_ground import retained_ground_region, GroundGeometryError
        try:
            return retained_ground_region(self.scene.ground_plane, self.field)
        except GroundGeometryError as exc:
            raise ExportError(f"Ground geometry cannot be represented: {exc}") from exc

    # ---------------------------------------------------------------- build

    def build(self) -> FasterCapModelGenerator:
        from ..pex25d.exporters import validate_export_scene
        validate_export_scene(self.scene)
        background = self.scene.background
        if not self.scene.HasField('background'):
            raise ExportError("The scene declares no background dielectric")

        builder = FasterCapModelBuilder(dbu=self.dbu,
                                        k_void=background.permittivity,
                                        delaunay_amax=self.options.delaunay_amax,
                                        delaunay_b=self.options.delaunay_b)

        # Ascending wrap depth, which the resolver already established, so that
        # the generator's own precedence matches the occupancy rule.
        for dielectric in self.scene.dielectrics:
            builder.add_material(name=dielectric.name, k=dielectric.permittivity)

        try:
            self.add_ground_plane(builder)
            self.add_conductors(builder)
            self.add_dielectrics(builder)
        except GroundGeometryError as exc:
            raise ExportError(f"Native export geometry cannot be represented: {exc}") from exc

        generator = builder.generate()
        if generator is None:
            raise ExportError("The scene produced no geometry")
        return generator

    def add_ground_plane(self, builder: FasterCapModelBuilder):
        if not self.scene.HasField('ground_plane'):
            warning("The scene declares no ground plane")
            return
        ground_plane = self.scene.ground_plane
        info(f"Ground plane {ground_plane.name}: "
             f"z={self.um(ground_plane.zlow)}, "
             f"height={self.um(ground_plane.zhigh - ground_plane.zlow)}")
        retained = self.ground_region
        if retained.is_empty():
            raise ExportError("Ground cutouts remove the complete reference body inside the export field")
        builder.add_conductor(net_name=self.body_names[ground_body(self.scene)],
                              layer=retained,
                              z=self.um(ground_plane.zlow),
                              height=self.um(ground_plane.zhigh - ground_plane.zlow))

    def add_conductors(self, builder: FasterCapModelBuilder):
        for conductor in self.scene.conductors:
            # A FLOATING conductor belongs to no net and is solved under its own
            # shortname; everything else is reported per net.
            name = self.body_names[conductor_body(conductor)]
            for conductor_region in conductor.regions:
                layer = self.layers.get(conductor_region.layer)
                if layer is None:
                    raise ExportError(f"Conductor '{conductor.name}' has geometry on "
                                      f"'{conductor_region.layer}', which the scene "
                                      f"does not declare")
                debug(f"Conductor {name}, layer {conductor_region.layer}: "
                      f"z={self.um(layer.zlow)}, "
                      f"height={self.um(layer.zhigh - layer.zlow)}")
                builder.add_conductor(net_name=name,
                                      layer=region_of(conductor_region),
                                      z=self.um(layer.zlow),
                                      height=self.um(layer.zhigh - layer.zlow))

    def add_dielectrics(self, builder: FasterCapModelBuilder):
        kinds = pex25d_dielectric_pb2()

        for dielectric in self.scene.dielectrics:
            if dielectric.kind == kinds.DIELECTRIC_KIND_SIMPLE:
                # A band spans the whole plane. The films it encloses sit at a
                # smaller wrap depth and were added first, so the generator
                # carves them out of it.
                height = dielectric.zhigh - dielectric.zlow
                if height <= 0:
                    warning(f"Simple dielectric '{dielectric.name}' has no height; "
                            f"skipping")
                    continue
                info(f"Simple dielectric {dielectric.name}: "
                     f"z={self.um(dielectric.zlow)}, height={self.um(height)}")
                builder.add_dielectric(material_name=dielectric.name,
                                       layer=self.field,
                                       z=self.um(dielectric.zlow),
                                       height=self.um(height))
            elif dielectric.kind == kinds.DIELECTRIC_KIND_CONFORMAL:
                self.add_conformal(builder, dielectric)
            else:
                raise ExportError(f"Dielectric '{dielectric.name}' has no kind")

    def add_conformal(self, builder: FasterCapModelBuilder, dielectric: Any):
        """
        A film has up to two solids: the one grown around what it wraps, and —
        when it covers the field — a slab over everything the root is absent
        from. Both are measured from the bottom face of the root, which is what
        makes a chain of films compose.
        """
        root = self.root_of(dielectric)
        if root is None:
            warning(f"Dielectric '{dielectric.name}' is rooted on "
                    f"'{dielectric.root}', which the scene does not declare; skipping")
            return

        footprint, zlow, zhigh = root
        lateral, top = self.chain_extent(dielectric, zhigh)

        if not footprint.is_empty():
            # Like every unbounded material, a film on the ground plane ends at
            # the field; a film on a conductor lies within it anyway.
            grown = (footprint.sized(lateral) & self.field) if lateral else footprint
            height = top - zlow
            info(f"Conformal dielectric {dielectric.name}: "
                 f"z={self.um(zlow)}, height={self.um(height)}")
            builder.add_dielectric(material_name=dielectric.name,
                                   layer=grown,
                                   z=self.um(zlow),
                                   height=self.um(height))
        else:
            grown = kdb.Region()

        if dielectric.thickness_on_field > 0:
            info(f"Conformal dielectric {dielectric.name} (on the field): "
                 f"z={self.um(zlow)}, "
                 f"height={self.um(dielectric.thickness_on_field)}")
            builder.add_dielectric(material_name=dielectric.name,
                                   layer=self.field - grown,
                                   z=self.um(zlow),
                                   height=self.um(dielectric.thickness_on_field))

    def root_of(self, dielectric: Any) -> Optional[Tuple[kdb.Region, int, int]]:
        """
        The footprint and z extent of the conductor layer or ground plane at the
        root of a film's WRAPS chain. Ground openings also apply to its films.
        """
        layer = self.layers.get(dielectric.root)
        if layer is not None:
            return self.shapes_of_layer(layer.name), layer.zlow, layer.zhigh

        ground_plane = self.scene.ground_plane
        if self.scene.HasField('ground_plane') and dielectric.root == ground_plane.name:
            return self.ground_region, ground_plane.zlow, ground_plane.zhigh
        return None

    def chain_extent(self, dielectric: Any, root_zhigh: int) -> Tuple[int, int]:
        """
        Walk a film's WRAPS chain down to its root, accumulating the offsets.

        Each film is measured from the surface of the one it wraps, so the total
        lateral offset from the conductor is the sum along the chain, and the
        top is the root's top plus the sum of the over-thicknesses.
        """
        kinds = pex25d_dielectric_pb2()
        lateral = 0
        over = 0
        name: Optional[str] = dielectric.name
        seen: Set[str] = set()

        while name is not None and name in self.dielectrics:
            if name in seen:
                raise ExportError(f"WRAPS chain through '{name}' is cyclic")
            seen.add(name)
            film = self.dielectrics[name]
            if film.kind == kinds.DIELECTRIC_KIND_CONFORMAL:
                lateral += film.thickness_beside_wrapped
                over += film.thickness_over_wrapped
            name = film.wraps

        return lateral, root_zhigh + over


def grow(box: Any, margin: int) -> Any:
    from ..pex25d.protobuf import pex25d_geometry_pb2
    grown = pex25d_geometry_pb2().Box3D()
    grown.lower_left.x = box.lower_left.x - margin
    grown.lower_left.y = box.lower_left.y - margin
    grown.lower_left.z = box.lower_left.z
    grown.upper_right.x = box.upper_right.x + margin
    grown.upper_right.y = box.upper_right.y + margin
    grown.upper_right.z = box.upper_right.z
    return grown
