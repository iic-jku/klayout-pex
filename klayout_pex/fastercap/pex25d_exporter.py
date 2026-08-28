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
PEX25D scene → FasterCap / FastCap2 input files.

Both engines read the same list-file format, so one backend serves them.

The occupancy rule maps onto the model generator almost for free.
:meth:`FasterCapModelBuilder.generate` legalizes overlapping regions by the
order materials were added, conductors ahead of every dielectric — which is
exactly the PEX25D rule once the dielectrics are added in ascending wrap depth.
A resolved scene already lists them in that order, so the innermost film wins
and nothing has to be subtracted by hand.
"""

from __future__ import annotations

import os
from fractions import Fraction
from typing import *

import klayout.db as kdb

from ..log import debug, info, warning
from ..pex25d.exporters import ExportError, ExporterOptions, SolverTarget
from ..pex25d.protobuf import pex25d_dielectric_pb2, pex25d_scene_pb2
from .fastercap_model_generator import FasterCapModelBuilder, FasterCapModelGenerator


DEFAULT_PREFIX = {
    SolverTarget.FASTERCAP: 'FasterCap_Input_',
    SolverTarget.FASTCAP2: 'FastCap_Input_',
}


class Pex25DFasterCapExporter:
    def __init__(self, scene: Any, options: ExporterOptions):
        self.scene = scene
        self.options = options

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
            self._field = kdb.Region(kdb.Box(box.lower_left.x, box.lower_left.y,
                                             box.upper_right.x, box.upper_right.y))
        return self._field

    # ---------------------------------------------------------------- build

    def build(self) -> FasterCapModelGenerator:
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

        self.add_ground_plane(builder)
        self.add_conductors(builder)
        self.add_dielectrics(builder)

        generator = builder.generate()
        if generator is None:
            raise ExportError("The scene produced no geometry")
        return generator

    def add_ground_plane(self, builder: FasterCapModelBuilder) -> None:
        if not self.scene.HasField('ground_plane'):
            warning("The scene declares no ground plane")
            return
        ground_plane = self.scene.ground_plane
        info(f"Ground plane {ground_plane.name}: "
             f"z={self.um(ground_plane.zlow)}, "
             f"height={self.um(ground_plane.zhigh - ground_plane.zlow)}")
        builder.add_conductor(net_name=ground_plane.name,
                              layer=self.field,
                              z=self.um(ground_plane.zlow),
                              height=self.um(ground_plane.zhigh - ground_plane.zlow))

    def add_conductors(self, builder: FasterCapModelBuilder) -> None:
        for conductor in self.scene.conductors:
            # A FLOATING conductor belongs to no net and is solved under its own
            # shortname; everything else is reported per net.
            name = conductor.name if conductor.floating else conductor.net
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

    def add_dielectrics(self, builder: FasterCapModelBuilder) -> None:
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

    def add_conformal(self, builder: FasterCapModelBuilder, dielectric: Any) -> None:
        """
        A film has up to two solids: the one grown around what it wraps, and —
        when it covers the field — a slab over everything the root layer is
        absent from. Both are measured from the bottom face of the root, which
        is what makes a chain of films compose.
        """
        root = self.layers.get(dielectric.root)
        if root is None:
            warning(f"Dielectric '{dielectric.name}' is rooted on "
                    f"'{dielectric.root}', which carries no geometry; skipping")
            return

        lateral, top = self.chain_extent(dielectric)
        shapes = self.shapes_of_layer(dielectric.root)

        if not shapes.is_empty():
            grown = shapes.sized(lateral) if lateral else shapes
            height = top - root.zlow
            info(f"Conformal dielectric {dielectric.name}: "
                 f"z={self.um(root.zlow)}, height={self.um(height)}")
            builder.add_dielectric(material_name=dielectric.name,
                                   layer=grown,
                                   z=self.um(root.zlow),
                                   height=self.um(height))
        else:
            grown = kdb.Region()

        if dielectric.thickness_on_field > 0:
            info(f"Conformal dielectric {dielectric.name} (on the field): "
                 f"z={self.um(root.zlow)}, "
                 f"height={self.um(dielectric.thickness_on_field)}")
            builder.add_dielectric(material_name=dielectric.name,
                                   layer=self.field - grown,
                                   z=self.um(root.zlow),
                                   height=self.um(dielectric.thickness_on_field))

    def chain_extent(self, dielectric: Any) -> Tuple[int, int]:
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

        root = self.layers[dielectric.root]
        return lateral, root.zhigh + over


def region_of(conductor_region: Any) -> kdb.Region:
    """Build a region from one conductor's shapes on one layer, in grid units."""
    region = kdb.Region()
    for box in conductor_region.boxes:
        region.insert(kdb.Box(box.lower_left.x, box.lower_left.y,
                              box.upper_right.x, box.upper_right.y))
    for polygon in conductor_region.polygons:
        shape = kdb.Polygon([kdb.Point(p.x, p.y) for p in polygon.outer.points])
        for hole in polygon.holes:
            shape.insert_hole([kdb.Point(p.x, p.y) for p in hole.points])
        region.insert(shape)
    return region


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


def export_fastercap(scene: Any,
                     target: SolverTarget,
                     output_dir_path: str,
                     prefix: str,
                     options: ExporterOptions) -> List[str]:
    """Write ``scene`` as FasterCap / FastCap2 input; return the paths written."""
    exporter = Pex25DFasterCapExporter(scene, options)
    generator = exporter.build()

    if options.geometry_check:
        generator.check()

    os.makedirs(output_dir_path, exist_ok=True)
    effective_prefix = prefix or DEFAULT_PREFIX[target]
    lst_file = generator.write_fastcap(output_dir_path=output_dir_path,
                                       prefix=effective_prefix)

    written = [lst_file]
    directory = os.path.dirname(lst_file) or output_dir_path
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if path != lst_file and name.startswith(effective_prefix):
            written.append(path)

    if options.write_stl:
        generator.dump_stl(output_dir_path=output_dir_path, prefix=effective_prefix)

    return written
