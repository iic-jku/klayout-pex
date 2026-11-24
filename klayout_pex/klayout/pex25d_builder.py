#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/iic-jku/kpex).
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

"""Generation of a ``PEX25DFile`` from LVS connectivity and the PDK stack."""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from functools import cached_property
from typing import *
from urllib.parse import quote

import klayout.db as kdb
from .physical_geometry import PhysicalGeometryError, apply_width_bias, width_bias_offsets
from .native_coordinates import is_supported_native_coordinate

from ..log import debug, info, warning, error
from ..pex25d.format_version import (
    FORMAT_VERSION_MAJOR,
    FORMAT_VERSION_MINOR,
    FORMAT_VERSION_SUFFIX,
)
from ..pex25d.protobuf import pex25d_file_pb2, pex25d_terminal_pb2
from ..version import __version__
from .lvsdb_extractor import KLayoutExtractionContext, device_list

if TYPE_CHECKING:
    from ..tech_info import TechInfo


from .pex25d_stack import BuildError, BuilderOptions, DEFAULT_GRID_UM, GeometryScope, PEX25DStackBuilder


class PEX25DBuilder(PEX25DStackBuilder):
    """
    Assembles a ``kpex.pex25d.PEX25DFile`` from a technology stack and the
    connectivity of an LVS run.

    The default interconnect scope omits diffusion geometry belonging to compact
    models. Explicit electrostatic scope retains the extracted silicon solids
    and the numerical material extents used for a field-solver scene.
    """

    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 tech_info: 'TechInfo',
                 cell_name: str,
                 options: Optional[BuilderOptions] = None):
        super().__init__(tech_info, options)
        self.pex_context = pex_context
        self.cell_name = cell_name
        self._dbu = Fraction(str(pex_context.dbu))
        self._conductor_regions: Dict[str, Dict[str, kdb.Region]] = {}
        self._terminal_names: Set[str] = set()

        scale = self._dbu / self._grid
        if scale.denominator != 1:
            raise BuildError(
                f"The layout DBU ({pex_context.dbu}) is not an integer multiple of the "
                f"PEX25D grid ({self.options.grid_um}); drawn geometry could not be "
                f"placed on the grid. Choose a finer grid."
            )
        self._dbu_scale = int(scale)
        try:
            self._width_bias_offsets = width_bias_offsets(tech_info, self._grid)
        except PhysicalGeometryError as exc:
            raise BuildError(str(exc)) from exc

    # ------------------------------------------------------------ conversions


    def dbu_to_grid(self, value: int) -> int:
        """Convert a drawn coordinate (in DBU) into grid units. Always exact."""
        return value * self._dbu_scale

    # ----------------------------------------------------------------- lookup


    def shapes_of_net(self, layer_name: str, net: kdb.Net) -> Optional[kdb.Region]:
        """
        NOTE: layers of the process stack can share a GDS pair (e.g. a metal without and with a MIM cap above),
              so each of them has the shapes of its own LVS layers only
        """
        gds_pair = self.gds_pair(layer_name)
        if not gds_pair:
            return None
        lvs_layer_names = self.tech_info.lvs_layer_names_by_process_layer_name.get(layer_name, [])
        return self.pex_context.shapes_of_net(gds_pair=gds_pair, net=net, lvs_layer_names=lvs_layer_names)

    @cached_property
    def substrate_lvs_layer_names(self) -> Set[str]:
        return set(self.tech_info.tech.substrate.lvs_layer_names)

    @cached_property
    def process_layer_name_by_lvs_layer_name(self) -> Dict[str, str]:
        """The profile whose shapes the shapes of an LVS layer are."""
        return {lvs_layer_name: layer_name
                for layer_name, lvs_layer_names in self.tech_info.lvs_layer_names_by_process_layer_name.items()
                for lvs_layer_name in lvs_layer_names}


    # ------------------------------------------------------------------ build

    def build(self) -> Any:
        if self.options.geometry_scope == GeometryScope.ELECTROSTATIC:
            self.electrostatic_layout_bounds()  # Reject unsafe field extents before native geometry operations.
        self.reject_unavailable_geometry()
        pex25d_file = pex25d_file_pb2().PEX25DFile()
        pex25d_file.format_version_major = FORMAT_VERSION_MAJOR
        pex25d_file.format_version_minor = FORMAT_VERSION_MINOR
        pex25d_file.format_version_suffix = FORMAT_VERSION_SUFFIX

        self.build_units(pex25d_file)
        self.build_meta(pex25d_file)
        self.build_ground_plane(pex25d_file)
        self.build_ground_cutouts(pex25d_file)
        self.build_layers(pex25d_file)
        self.build_dielectrics(pex25d_file)
        self.build_conductors(pex25d_file)
        if self.options.include_terminals:
            self.build_terminals(pex25d_file)
        if self.options.include_resistance:
            self.build_resistance(pex25d_file)
        try:
            apply_width_bias(pex25d_file, self._width_bias_offsets)
        except PhysicalGeometryError as exc:
            raise BuildError(str(exc)) from exc
        self.build_domain(pex25d_file)
        return pex25d_file

    def build_units(self, pex25d_file: Any) -> None:
        units = pex25d_file.units
        units.length = units.LENGTH_UNIT_UM
        units.grid_numerator = self._grid.numerator
        units.grid_denominator = self._grid.denominator
        units.source_dbu_numerator = self._dbu.numerator
        units.source_dbu_denominator = self._dbu.denominator

    def build_meta(self, pex25d_file: Any) -> None:
        def add(key: str, value: str):
            meta = pex25d_file.metadata.add()
            meta.key = key
            meta.value = value

        add('technology', self.tech_info.tech.name)
        if self.options.process_corner:
            add('process_corner', self.options.process_corner)
        add('source_cell', self.cell_name)
        add('generator', f"kpex {__version__}")
        # GRID and the layout DBU are different quantities and routinely different
        # values, so a consumer handing geometry back to a layout tool would
        # otherwise have to guess this one.
        add('source_dbu', str(self.pex_context.dbu))
        if self.unavailable_profiles:
            add('physical_geometry_unavailable', ','.join(sorted(self.unavailable_profiles)))


    def reject_unavailable_geometry(self):
        if not self.unavailable_profiles:
            return
        for name in sorted(self.unavailable_profiles):
            if self.gds_pair(name) is None:
                raise BuildError(f"Cannot check unavailable physical profile '{name}': no layout layer mapping")
            for net in self.pex_context.top_circuit.each_net():
                shapes = self.shapes_of_net(name, net)
                if shapes is not None and not shapes.is_empty():
                    raise BuildError(f"Selected process stack has no supported geometry for '{name}', "
                                     f"present on net '{net.expanded_name()}'")

    def build_ground_plane(self, pex25d_file: Any):
        super().build_ground_plane(pex25d_file)
        pex25d_file.ground_plane.net = self.pex_context.substrate_net_name

    def build_ground_cutouts(self, pex25d_file: Any):
        # Diffusion is omitted from PEX25D interconnect. Retain the existing
        # direct-extraction numerical device clearance, without shifting z or
        # assigning its nearby contacts to the ground's electrical net.
        circuit = self.pex_context.top_circuit
        if circuit is None:
            raise BuildError(f"No extracted circuit for cell '{self.cell_name}'")
        footprints = kdb.Region()
        for net in circuit.each_net():
            for layer in self.tech_info.process_diffusion_layers:
                region = self.shapes_of_net(layer.name, net)
                if region is not None:
                    footprints += region
        if footprints.is_empty():
            return
        margin = int(Fraction(1) // self._dbu)
        from .pex25d_ground import check_native_ground_coordinate, GroundGeometryError
        bounds = footprints.bbox()
        try:
            # Union itself uses the native kernel. Validate source endpoints
            # first, then classify the resulting polygons, not the input boxes.
            for coordinate in (bounds.left, bounds.bottom, bounds.right, bounds.top):
                check_native_ground_coordinate(coordinate)
            merged = footprints.merged()
            for polygon in merged.each():
                bounds = polygon.bbox()
                # Mode 2 clips sharp corners at 90 degrees. Two offsets bound
                # the corner excursions of rotated/nonrectangular contours;
                # an axis-aligned box needs only the original offset.
                padding = margin * (1 if polygon.is_box() else 2)
                for coordinate in (bounds.left - padding, bounds.bottom - padding,
                                   bounds.right + padding, bounds.top + padding):
                    check_native_ground_coordinate(coordinate)
                    if self.options.geometry_scope == GeometryScope.ELECTROSTATIC:
                        check_native_ground_coordinate(self.dbu_to_grid(coordinate))
        except GroundGeometryError as exc:
            raise BuildError(f"Ground diffusion clearance cannot be represented: {exc}") from exc
        cutouts = merged.sized(margin, 2)
        for polygon in cutouts.each_merged():
            cutout = pex25d_file.ground_plane.cutouts.add()
            self.fill_ring(cutout.polygon.outer, polygon.each_point_hull())
            for i in range(polygon.holes()):
                self.fill_ring(cutout.polygon.holes.add(), polygon.each_point_hole(i))
        meta = pex25d_file.metadata.add()
        meta.key = 'ground_cutout_policy'
        prefix = 'Omitted diffusion' if self.options.geometry_scope == GeometryScope.INTERCONNECT else 'Diffusion'
        meta.value = (f'{prefix} footprints expanded by 1 um (rounded down '
                      'to source DBU): numerical device exclusion, not process geometry')


    # ------------------------------------------------------------ dielectrics


    # ------------------------------------------------- conductors and shapes

    @cached_property
    def shape_layers(self) -> List[str]:
        """Profiles that may carry drawn geometry: metals and vias, in stack order."""
        names: List[str] = (list(self._device_contact_by_diffusion.values()) + self._nwell_contacts
                            + self._diffusion_profiles)
        for layer in self.tech_info.process_metal_layers:
            if layer.name in self._profile_names:
                names.append(layer.name)
            contact = layer.metal_layer.contact_above
            if contact.name and contact.name in self._profile_names:
                names.append(contact.name)
        return names

    def build_conductors(self, pex25d_file: Any) -> None:
        circuit = self.pex_context.top_circuit
        if circuit is None:
            raise BuildError(f"No extracted circuit for cell '{self.cell_name}'")

        num_shapes = 0
        for net in circuit.each_net():
            net_name = net.expanded_name()
            shapes_by_layer: List[Tuple[str, kdb.Region]] = []

            for layer_name in self.shape_layers:
                region = self.shapes_of_net(layer_name=layer_name, net=net)
                if region and not region.is_empty():
                    shapes_by_layer.append((layer_name, region))

            if not shapes_by_layer:
                debug(f"Net {net_name} has no interconnect geometry")
                continue

            conductor = pex25d_file.conductors.add()
            conductor.name = net_name
            conductor.net = net_name
            self._conductor_regions[net_name] = dict(shapes_by_layer)

            for layer_name, region in shapes_by_layer:
                count = self.add_shapes(pex25d_file,
                                        conductor=net_name,
                                        layer=layer_name,
                                        region=region)
                num_shapes += count
                debug(f"Conductor {net_name}, layer {layer_name}: {count} shape(s)")

        info(f"{len(pex25d_file.conductors)} conductor(s), {num_shapes} shape record(s)")

    def add_shapes(self,
                   pex25d_file: Any,
                   conductor: str,
                   layer: str,
                   region: kdb.Region) -> int:
        """
        Emit one record per polygon.

        Every via cut becomes its own record: PEX25D has no via-array construct,
        so that the dielectric between the cuts is present in the scene. Merging
        keeps disjoint cuts separate, which is what makes that work.
        """
        kinds = pex25d_file_pb2().ShapeRecord
        count = 0
        if not region.is_empty():
            box = region.bbox()
            for coordinate in (box.left, box.bottom, box.right, box.top):
                self.check_native_coordinate(coordinate, 'source geometry')
                self.check_native_coordinate(self.dbu_to_grid(coordinate), 'export geometry')

        for polygon in region.each_merged():
            record = pex25d_file.shapes.add()
            record.conductor = conductor
            record.layer = layer

            if polygon.is_box():
                box = polygon.bbox()
                record.kind = kinds.SHAPE_KIND_BOX
                record.box.lower_left.x = self.dbu_to_grid(box.left)
                record.box.lower_left.y = self.dbu_to_grid(box.bottom)
                record.box.upper_right.x = self.dbu_to_grid(box.right)
                record.box.upper_right.y = self.dbu_to_grid(box.top)
            else:
                record.kind = kinds.SHAPE_KIND_POLYGON
                self.fill_ring(record.polygon.outer, polygon.each_point_hull())
                for hole_index in range(polygon.holes()):
                    self.fill_ring(record.polygon.holes.add(),
                                   polygon.each_point_hole(hole_index))
            count += 1

        return count

    def fill_ring(self, ring: Any, points: Iterable[kdb.Point]) -> None:
        """Rings are implicitly closed, so the first vertex is not repeated."""
        for point in points:
            vertex = ring.points.add()
            vertex.x = self.dbu_to_grid(point.x)
            vertex.y = self.dbu_to_grid(point.y)

    # -------------------------------------------------------------- terminals

    def add_terminal(self, pex25d_file: Any, name: str, conductor: str,
                     layer: str, kind: int, box: kdb.Box) -> None:
        base = name
        suffix = 2
        while name in self._terminal_names:
            name = f'{base}.{suffix}'
            suffix += 1
        self._terminal_names.add(name)
        terminal = pex25d_file.terminals.add()
        terminal.name, terminal.conductor, terminal.layer = name, conductor, layer
        terminal.kind = kind
        terminal.region.lower_left.x = self.dbu_to_grid(box.left)
        terminal.region.lower_left.y = self.dbu_to_grid(box.bottom)
        terminal.region.upper_right.x = self.dbu_to_grid(box.right)
        terminal.region.upper_right.y = self.dbu_to_grid(box.top)

    def build_terminals(self, pex25d_file: Any) -> None:
        kinds = pex25d_terminal_pb2()
        selected_labels: Optional[Set[Tuple[GDSPair, str, int, int]]] = None
        if self.pex_context.port_label_keys is not None:
            selected_labels = {(gds_pair, pin.label, pin.label_point.x, pin.label_point.y)
                               for gds_pair, pins in self.pex_context.pins_pb2_by_layer.items() for pin in pins
                               if self.pex_context.pin_can_be_port(pin)}
        # Metals can share their drawn layer (e.g. sky130A met3_ncap and met3_cap, without and with
        # a MiM cap above), whose pins are then on the one under each label.
        metal_names_by_gds_pair: Dict[GDSPair, List[str]] = {}
        for metal in pex25d_file.metals:
            canonical = self.canonical_name(metal.name) or metal.name
            gds_pair = self.tech_info.gds_pair_for_layer_name.get(canonical)
            if gds_pair not in self.tech_info.layer_info_by_gds_pair:
                continue
            metal_names_by_gds_pair.setdefault(gds_pair, []).append(metal.name)

        for gds_pair, metal_names in metal_names_by_gds_pair.items():
            pins = self.pex_context.pins_of_layer(gds_pair)
            if pins.is_empty():
                continue
            labels = self.pex_context.labels_of_layer(gds_pair) & pins
            seen = set()
            for label in labels:
                point = label.position()
                key = (label.string, point.x, point.y)
                if selected_labels is not None and (gds_pair, *key) not in selected_labels:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                candidates: List[Tuple[str, str]] = []  # conductor and metal at the label
                for net_name, regions in self._conductor_regions.items():
                    for metal_name in metal_names:
                        region = regions.get(metal_name)
                        if region is not None and any(p.inside(point) for p in region.each_merged()):
                            candidates.append((net_name, metal_name))
                            break
                if len(candidates) != 1:
                    raise BuildError(f"Pin '{label.string}' on '{'/'.join(metal_names)}' must select one "
                                     f"conductor at its label; found {len(candidates)}")
                net_name, metal_name = candidates[0]
                # A pin marker may cover the entire wire; only the label is the port.
                box = kdb.Box(point.x - 1, point.y - 1, point.x + 1, point.y + 1)
                self.add_terminal(pex25d_file, f'pin:{quote(label.string, safe="._-$[]")}',
                                  net_name, metal_name, kinds.TERMINAL_KIND_PIN, box)

        devices_by_terminal_without_node: Dict[Tuple[str, str, str], List[str]] = defaultdict(list)
        for net in self.pex_context.top_circuit.each_net():
            net_name = net.expanded_name()
            regions = self._conductor_regions.get(net_name)
            if not regions:
                continue
            for ref in net.each_terminal():
                device = ref.device()
                definition = device.device_class().terminal_definition(ref.terminal_id())
                name = (f'device:{quote(device.expanded_name(), safe="._-$[]")}:'
                        f'{quote(definition.name, safe="._-$[]")}')
                selected = {}
                unknown_markers = kdb.Region()
                unknown_lvs_layer_names: List[str] = []
                for index, marker in self.pex_context.lvsdb.shapes_of_terminal(ref).items():
                    source_name = self.pex_context.lvsdb.layer_name(index)
                    if source_name in self.substrate_lvs_layer_names:
                        # NOTE: the substrate is the ground plane, a terminal on it needs no node
                        #       (see TERMINAL_KIND_DEVICE_TERMINAL), e.g. the terminal of a cap to the substrate
                        continue
                    if source_name not in self.tech_info.gds_pair_for_computed_layer_name \
                            and source_name not in self.tech_info.gds_pair_for_layer_name:
                        unknown_markers += marker
                        unknown_lvs_layer_names.append(source_name)
                        continue
                    pair = self.gds_pair(source_name)
                    # Metals can share a GDS pair (e.g. sky130A met3_ncap and met3_cap, whose MiM cap
                    # bottom plates abut the rest), the terminal is on the one of its LVS layer.
                    owner = self.process_layer_name_by_lvs_layer_name.get(source_name)
                    contact = self._device_contact_by_diffusion.get(owner)
                    if contact is not None:
                        # NOTE: device geometry (e.g. a source/drain), the terminal is on the cuts of its contacts,
                        #       whole, as a terminal may not clip a cut
                        cuts = regions.get(contact, kdb.Region()).overlapping(marker)
                        if not cuts.is_empty():
                            selected.setdefault(contact, kdb.Region()).insert(cuts)
                        continue
                    for layer, geometry in regions.items():
                        if self.gds_pair(layer) != pair or owner not in (None, layer):
                            continue
                        intersection = geometry & marker
                        if intersection.is_empty():
                            # Abutting device geometry needs a narrow strip inside the interconnect.
                            intersection = geometry & marker.sized(1)
                        if not intersection.is_empty():
                            selected.setdefault(layer, kdb.Region()).insert(intersection)
                if not selected and unknown_lvs_layer_names:
                    found = self.terminal_on_overlapped_interconnect(regions, unknown_markers)
                    if found is None:
                        key = (device.device_class().name, definition.name, ', '.join(unknown_lvs_layer_names))
                        devices_by_terminal_without_node[key].append(device.expanded_name())
                        continue
                    selected[found[0]] = found[1]
                if not selected:
                    debug(f"Device terminal '{name}' has no emitted interconnect boundary")
                    continue
                if len(selected) != 1:
                    raise BuildError(f"Device terminal '{name}' spans multiple profiles "
                                     f"({', '.join(selected)}); PEX25D requires one layer per node")
                layer, intersection = next(iter(selected.items()))
                box = intersection.bbox()
                if not ((regions[layer] & kdb.Region(box)) - intersection).is_empty():
                    raise BuildError(f"Device terminal '{name}' cannot use one box on '{layer}' "
                                     f"without shorting additional interconnect")
                self.add_terminal(pex25d_file, name, net_name, layer,
                                  kinds.TERMINAL_KIND_DEVICE_TERMINAL, box)
        if devices_by_terminal_without_node:
            warning("PEX25D has no nodes for these device terminals, as the tech info has no layer "
                    "for their LVS layer, and they overlap no interconnect of their net "
                    "(e.g. a terminal on a well):\n" +
                    '\n'.join(f"  - {device_class} terminal {terminal} on LVS layer {lvs_layers}: "
                              f"{device_list(device_names)}"
                              for (device_class, terminal, lvs_layers), device_names
                              in sorted(devices_by_terminal_without_node.items())))
        info(f"{len(pex25d_file.terminals)} terminal record(s)")

    def terminal_on_overlapped_interconnect(self,
                                            regions: Dict[str, kdb.Region],
                                            marker: kdb.Region) -> Optional[Tuple[str, kdb.Region]]:
        """
        Where a device terminal on LVS layers the tech info has no layer for (e.g. the ports of a MOM cap)
        is on the interconnect of its net, as in the resistance extraction (#237)

        :return: the profile and its part: the cuts of device contacts it overlaps, whole, as of a source/drain
                 (they stand in for the diffusion), else the part of the metal it overlaps most, the lowest of equals;
                 None if it overlaps none of them (e.g. a terminal on a well)
        """
        for contact in self._device_contact_by_diffusion.values():
            cuts = regions.get(contact, kdb.Region()).overlapping(marker)
            if not cuts.is_empty():
                return contact, cuts
        best: Optional[Tuple[float, str, kdb.Region]] = None
        for layer in self.shape_layers:
            geometry = regions.get(layer)
            if geometry is None or layer in self._via_contacts:
                continue
            overlap = geometry & marker
            area = overlap.area()
            if area > 0 and (best is None or area > best[0]):
                best = (area, layer, overlap)
        return None if best is None else (best[1], best[2])

    # ------------------------------------------------------------- resistance

    def build_resistance(self, pex25d_file: Any) -> None:
        tech = self.tech_info

        for layer in tech.process_metal_layers:
            if layer.name not in self._profile_names:
                continue
            canonical = self.canonical_name(layer.name) or layer.name
            layer_resistance = tech.layer_resistance_by_layer_name.get(canonical)
            if layer_resistance is None or not layer_resistance.resistance:
                debug(f"No sheet resistance for '{layer.name}' (canonical '{canonical}')")
                continue
            record = pex25d_file.metal_resistances.add()
            record.metal = layer.name
            record.sheet = tech.milliohm_to_ohm(layer_resistance.resistance)

        for via_name, contact in self._via_contacts.items():
            canonical = self.canonical_name(via_name) or via_name

            # A via's resistance is given per cut, either in the via table or —
            # for the contacts that land on a device layer — in the contact table.
            resistance = tech.via_resistance_by_layer_name.get(canonical)
            if resistance is None:
                resistance = tech.contact_resistance_by_device_layer_name.get(
                    contact.layer_below)
            if resistance is None or not resistance.resistance:
                debug(f"No via resistance for '{via_name}' (canonical '{canonical}')")
                continue

            record = pex25d_file.via_resistances.add()
            record.via = via_name
            record.per_cut = tech.milliohm_to_ohm(resistance.resistance)

        info(f"{len(pex25d_file.metal_resistances)} metal and "
             f"{len(pex25d_file.via_resistances)} via resistance record(s)")

    # ----------------------------------------------------------------- domain

    def build_domain(self, pex25d_file: Any) -> None:
        """
        Emit a computational domain only when one was asked for.

        With neither record present the domain is simply unset, and choosing one
        is the solver adapter's business.
        """
        if self.options.domain_margin_um is None:
            return

        margin = self.to_grid(self.options.domain_margin_um, 'domain margin')
        if self.options.geometry_scope == GeometryScope.ELECTROSTATIC:
            self.build_electrostatic_domain(pex25d_file, margin)
            return
        pex25d_file.domain_margin.x = margin
        pex25d_file.domain_margin.y = margin
        pex25d_file.domain_margin.z = margin
        info(f"DOMAIN_MARGIN {margin} grid units in x, y and z")

    @staticmethod
    def check_native_coordinate(coordinate: int, description: str):
        if not is_supported_native_coordinate(coordinate):
            raise BuildError(f'{description.capitalize()} exceeds the native KLayout coordinate range')

    def electrostatic_layout_bounds(self) -> Optional[Tuple[int, int, int, int]]:
        original = self.pex_context.top_cell_bbox()
        if original.empty():
            return None
        coordinates = (original.left, original.bottom, original.right, original.top)
        for coordinate in coordinates:
            self.check_native_coordinate(coordinate, 'original cell bounds')
        bounds = tuple(self.dbu_to_grid(value) for value in coordinates)
        margin = self.to_grid(self.options.domain_margin_um or 0, 'domain margin')
        for coordinate in (bounds[0] - margin, bounds[1] - margin, bounds[2] + margin, bounds[3] + margin):
            self.check_native_coordinate(coordinate, 'electrostatic field margin')
        return bounds

    def build_electrostatic_domain(self, file: Any, margin: int):
        bounds = self.electrostatic_layout_bounds()
        kinds = pex25d_file_pb2().ShapeRecord
        for shape in file.shapes:
            match shape.kind:
                case kinds.SHAPE_KIND_BOX:
                    points = (shape.box.lower_left, shape.box.upper_right)
                case kinds.SHAPE_KIND_POLYGON:
                    points = shape.polygon.outer.points
                case _:
                    raise NotImplementedError(f'Electrostatic domain for shape kind {shape.kind} is not implemented')
            for point in points:
                if bounds is None:
                    bounds = (point.x, point.y, point.x, point.y)
                else:
                    bounds = (min(bounds[0], point.x), min(bounds[1], point.y),
                              max(bounds[2], point.x), max(bounds[3], point.y))
        if bounds is None:
            raise BuildError('Electrostatic field needs nonempty layout bounds or conductor geometry')
        left, bottom, right, top = bounds
        bounds = (left - margin, bottom - margin, right + margin, top + margin)
        for coordinate in bounds:
            self.check_native_coordinate(coordinate, 'electrostatic field margin')
        box = file.domain_box.box
        box.lower_left.x, box.lower_left.y = bounds[:2]
        box.upper_right.x, box.upper_right.y = bounds[2:]
        box.lower_left.z = min(file.ground_plane.zhigh, 0, *(metal.zlow for metal in file.metals))
        # Empty anchors do not create solids. The generous upper bound includes
        # the finite top material band and every selected over-metal coating.
        upper = max((metal.zhigh for metal in file.metals), default=box.lower_left.z + 1)
        upper += sum(dielectric.conformal.thickness_over_wrapped for dielectric in file.dielectrics)
        box.upper_right.z = upper + margin


def build_pex25d_file(pex_context: KLayoutExtractionContext,
                      tech_info: 'TechInfo',
                      cell_name: str,
                      options: Optional[BuilderOptions] = None) -> Any:
    """Assemble a ``kpex.pex25d.PEX25DFile`` for ``cell_name``."""
    builder = PEX25DBuilder(pex_context=pex_context,
                            tech_info=tech_info,
                            cell_name=cell_name,
                            options=options)
    return builder.build()
