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

"""Generation of a ``PEX25DFile`` from LVS connectivity and the PDK stack."""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from functools import cached_property
from typing import *
from urllib.parse import quote

import klayout.db as kdb

from ..log import debug, info, warning, error
from ..pex25d.protobuf import pex25d_file_pb2, pex25d_terminal_pb2
from ..types import GDSPair
from ..version import __version__
from .lvsdb_extractor import KLayoutExtractionContext, device_list
from .pex25d_stack import BuildError, BuilderOptions, DEFAULT_GRID_UM, PEX25DStackBuilder

if TYPE_CHECKING:
    from ..tech_info import TechInfo



class PEX25DBuilder(PEX25DStackBuilder):
    """
    Assembles a ``kpex.pex25d.PEX25DFile`` from a technology stack and the
    connectivity of an LVS run.

    Only interconnect is described: device geometry (diffusion, the gate
    channel) belongs to the compact model and would be double-counted, so it is
    excluded here and the enclosing PEX flow connects device terminals to the
    remaining interconnect.
    """

    def __init__(self,
                 pex_context: KLayoutExtractionContext,
                 tech_info: 'TechInfo',
                 cell_name: str,
                 options: Optional[BuilderOptions] = None):
        self.pex_context = pex_context
        super().__init__(tech_info, options)
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
        pex25d_file = super().build()
        self.build_conductors(pex25d_file)
        self.build_terminals(pex25d_file)
        if self.options.include_resistance:
            self.build_resistance(pex25d_file)
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

    # ------------------------------------------------- conductors and shapes

    @cached_property
    def shape_layers(self) -> List[str]:
        """Profiles that may carry drawn geometry: metals and vias, in stack order."""
        names: List[str] = list(self._device_contact_by_diffusion.values()) + self._nwell_contacts
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
