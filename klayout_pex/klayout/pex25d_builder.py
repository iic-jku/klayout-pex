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

from dataclasses import dataclass, field
from fractions import Fraction
from functools import cached_property
from typing import *

import klayout.db as kdb

import klayout_pex_protobuf.kpex.tech.process_stack_pb2 as process_stack_pb2

from ..log import debug, info, warning, error
from ..pex25d.format_version import (
    FORMAT_VERSION_MAJOR,
    FORMAT_VERSION_MINOR,
    FORMAT_VERSION_SUFFIX,
)
from ..pex25d.protobuf import pex25d_file_pb2, pex25d_dielectric_pb2
from ..version import __version__
from .lvsdb_extractor import GDSPair, KLayoutExtractionContext

if TYPE_CHECKING:
    from ..tech_info import TechInfo


LT = process_stack_pb2.ProcessStackInfo.LayerType

# PEX25D wants every coordinate as an exact integer count of grid units. 0.0001 µm
# is the coarsest grid on which the sky130A z stack closes (poly sits at 0.3262),
# and it divides the usual 0.001 µm layout DBU exactly, as the format requires.
DEFAULT_GRID_UM = '0.0001'


class BuildError(Exception):
    pass


@dataclass
class BuilderOptions:
    """Options the CLI exposes for PEX25D generation."""

    grid_um: str = DEFAULT_GRID_UM
    """Coordinate grid, as a decimal string so that it stays an exact rational."""

    with_source_refs: bool = False
    """Populate every ``SourceRef``. Roughly doubles the size of a file."""

    dielectric_filter: Optional[Any] = None
    """The ``--diel`` multiple-choice pattern, as used by the FasterCap path."""

    include_resistance: bool = True
    """Emit ``RESISTANCE`` records for the layers the technology defines."""

    domain_margin_um: Optional[float] = None
    """Emit ``DOMAIN_MARGIN`` with this clearance. None leaves the domain unset."""

    process_corner: Optional[str] = None
    """Value for ``META process_corner``, if known."""


class PEX25DBuilder:
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
        self.tech_info = tech_info
        self.cell_name = cell_name
        self.options = options or BuilderOptions()

        self._grid = Fraction(self.options.grid_um)
        self._dbu = Fraction(str(pex_context.dbu))

        # Names already placed in the profile namespace, so that a stack which
        # repeats a dielectric (sky130A lists nild5 and nild6 twice, once per
        # MiM-cap variant) does not produce a duplicate declaration.
        self._profile_names: Set[str] = set()
        self._via_contacts: Dict[str, Any] = {}

        scale = self._dbu / self._grid
        if scale.denominator != 1:
            raise BuildError(
                f"The layout DBU ({pex_context.dbu}) is not an integer multiple of the "
                f"PEX25D grid ({self.options.grid_um}); drawn geometry could not be "
                f"placed on the grid. Choose a finer grid."
            )
        self._dbu_scale = int(scale)

    # ------------------------------------------------------------ conversions

    def to_grid(self, value_um: float, what: str) -> int:
        """
        Convert a µm value from the technology into grid units.

        Divide-round-compare, never a modulo: in binary floating point
        ``0.3262 % 0.0001`` is ``9.9999999999e-05``, and an exact-modulo test
        would reject perfectly legal values.
        """
        quotient = Fraction(str(value_um)) / self._grid
        rounded = round(quotient)
        if abs(quotient - rounded) > Fraction(1, 10 ** 6):
            raise BuildError(
                f"{what}: {value_um} µm is not an integer multiple of the grid "
                f"{self.options.grid_um} µm. Choose a finer grid."
            )
        return int(rounded)

    def dbu_to_grid(self, value: int) -> int:
        """Convert a drawn coordinate (in DBU) into grid units. Always exact."""
        return value * self._dbu_scale

    # ----------------------------------------------------------------- lookup

    def gds_pair(self, layer_name: str) -> Optional[GDSPair]:
        return self.tech_info.gds_pair(layer_name)

    def shapes_of_net(self, layer_name: str, net: kdb.Net) -> Optional[kdb.Region]:
        gds_pair = self.gds_pair(layer_name)
        if not gds_pair:
            return None
        return self.pex_context.shapes_of_net(gds_pair=gds_pair, net=net)

    @cached_property
    def metal_layer_by_name(self) -> Dict[str, Any]:
        return {lyr.name: lyr for lyr in self.tech_info.process_metal_layers}

    def resolve_metal(self, name: str, context: str) -> Optional[str]:
        """
        Map a name used by a contact onto an emitted METAL profile.

        Contacts in the kpex tech data name canonical layers (``met3``) while the
        process stack splits some of them per MiM-cap variant (``met3_ncap``,
        ``met3_cap``), so an exact match is not always available. Where exactly
        one variant carries a contact the choice is unambiguous; anything else is
        reported rather than guessed.
        """
        if name in self.metal_layer_by_name:
            return name

        variants = [n for n in self.metal_layer_by_name if n.startswith(f"{name}_")]
        if variants:
            chosen = variants[0] if len(variants) == 1 else None
            if chosen is None:
                with_contact = [n for n in variants
                                if self.metal_layer_by_name[n].metal_layer
                                .HasField('contact_above')]
                if len(with_contact) != 1:
                    warning(f"{context}: '{name}' is ambiguous in the process stack "
                            f"({', '.join(variants)}); skipping")
                    return None
                chosen = with_contact[0]

            # Where the variants share a z extent — sky130A splits met3 and met4
            # only to hang different dielectrics off them — the choice cannot
            # change the via extent that CONNECTS derives, so it is not worth a
            # warning. A genuine difference is.
            extents = {(self.metal_layer_by_name[n].metal_layer.z,
                        self.metal_layer_by_name[n].metal_layer.thickness)
                       for n in variants}
            report = debug if len(extents) == 1 else warning
            report(f"{context}: no metal layer '{name}' in the process stack, using "
                   f"'{chosen}'; candidates were {', '.join(variants)}")
            return chosen

        warning(f"{context}: no metal layer '{name}' in the process stack; skipping")
        return None

    def canonical_name(self, name: str) -> Optional[str]:
        """
        The canonical layer name behind a profile name.

        The process stack names profiles (`met3_ncap`, `via2_con`) while the
        parasitics tables are keyed on canonical layers (`met3`, `via2`). The two
        namespaces meet at the GDS pair, so the mapping is exact and needs no
        guessing at names.
        """
        gds_pair = self.tech_info.gds_pair_for_computed_layer_name.get(name) \
            or self.tech_info.gds_pair_for_layer_name.get(name)
        if not gds_pair:
            return None
        return self.tech_info.canonical_layer_name_by_gds_pair.get(gds_pair)

    def claim_name(self, name: str, what: str) -> bool:
        """Reserve a profile name, reporting a repeat rather than emitting it twice."""
        if name in self._profile_names:
            debug(f"{what} '{name}' is declared more than once in the process stack, "
                  f"keeping the first declaration")
            return False
        self._profile_names.add(name)
        return True

    # ------------------------------------------------------------------ build

    def build(self) -> Any:
        pex25d_file = pex25d_file_pb2().PEX25DFile()
        pex25d_file.format_version_major = FORMAT_VERSION_MAJOR
        pex25d_file.format_version_minor = FORMAT_VERSION_MINOR
        pex25d_file.format_version_suffix = FORMAT_VERSION_SUFFIX

        self.build_units(pex25d_file)
        self.build_meta(pex25d_file)
        self.build_ground_plane(pex25d_file)
        self.build_layers(pex25d_file)
        self.build_dielectrics(pex25d_file)
        self.build_conductors(pex25d_file)
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
            meta = pex25d_file.meta.add()
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

    def build_ground_plane(self, pex25d_file: Any) -> None:
        layer = self.tech_info.process_substrate_layer
        substrate = layer.substrate_layer

        ground_plane = pex25d_file.ground_plane
        ground_plane.name = layer.name
        # `height` is the distance of the substrate top below z=0.
        ground_plane.zhigh = self.to_grid(-substrate.height, f"{layer.name} top")
        ground_plane.zlow = self.to_grid(-(substrate.height + substrate.thickness),
                                         f"{layer.name} bottom")
        self.claim_name(layer.name, 'Ground plane')
        info(f"GROUND_PLANE {layer.name}: z {ground_plane.zlow} … {ground_plane.zhigh}")

    def build_layers(self, pex25d_file: Any) -> None:
        for layer in self.tech_info.process_metal_layers:
            metal_layer = layer.metal_layer
            if not self.claim_name(layer.name, 'Metal'):
                continue
            metal = pex25d_file.metals.add()
            metal.name = layer.name
            metal.zlow = self.to_grid(metal_layer.z, f"{layer.name} bottom")
            metal.zhigh = self.to_grid(metal_layer.z + metal_layer.thickness,
                                       f"{layer.name} top")
            debug(f"METAL {metal.name}: z {metal.zlow} … {metal.zhigh}")

        # A via is positioned by what it connects, never by its own z, so a change
        # in metal position or thickness propagates without any other edit.
        for layer in self.tech_info.process_metal_layers:
            metal_layer = layer.metal_layer
            if not metal_layer.HasField('contact_above'):
                continue
            contact = metal_layer.contact_above
            if not contact.name:
                continue

            context = f"Contact '{contact.name}'"
            below = self.resolve_metal(contact.layer_below or layer.name, context)
            above = self.resolve_metal(contact.metal_above, context)
            if not below or not above:
                continue
            if not self.claim_name(contact.name, 'Via'):
                continue

            self._via_contacts[contact.name] = contact
            via = pex25d_file.vias.add()
            via.name = contact.name
            via.connects_below = below
            via.connects_above = above
            debug(f"VIA {via.name}: connects {below} → {above}")

        # Device contacts (diffusion, nwell) are deliberately absent: their lower
        # endpoint is device geometry, which PEX25D does not describe.
        for name, contact in self.tech_info.contact_by_device_lvs_layer_name.items():
            if contact.name:
                debug(f"Skipping device contact '{contact.name}' on '{name}': "
                      f"device geometry is out of scope for PEX25D")

    # ------------------------------------------------------------ dielectrics

    @cached_property
    def included_dielectric_names(self) -> Set[str]:
        return {lyr.name for lyr in self.tech_info.filtered_dielectric_layers}

    def outermost_profile(self, root: str) -> str:
        """
        Follow the chain of films anchored on ``root`` and return its last link.

        A simple dielectric has to wrap the outermost profile anchored on the
        object below it: wrapping an inner link would give the fill the same
        depth as a film it contains, which is exactly the tie a validator
        rejects.
        """
        name = root
        seen = {root}
        while True:
            try:
                film = self.tech_info.conformal_dielectric_wrapping(name)
            except Exception as e:
                warning(f"Can't follow the dielectric chain above '{name}': {e}")
                return name
            if not film or film.name in seen:
                return name
            if film.name not in self.included_dielectric_names:
                return name
            name = film.name
            seen.add(name)

    def conformal_thicknesses(self, layer: Any) -> Tuple[int, int, int]:
        """
        Map a technology film onto the three PEX25D conformal thicknesses.

        All three are measured from the surface of the profile that is wrapped,
        which is what makes a chain of films composable.
        """
        if layer.layer_type != LT.LAYER_TYPE_CONFORMAL_DIELECTRIC:
            raise BuildError(f"'{layer.name}' is not a film")

        conformal = layer.conformal_dielectric_layer
        over_um = conformal.thickness_over_metal
        beside_um = conformal.thickness_sidewall
        on_field_um = conformal.thickness_where_no_metal

        return (self.to_grid(over_um, f"{layer.name} thickness over wrapped"),
                self.to_grid(beside_um, f"{layer.name} thickness beside wrapped"),
                self.to_grid(on_field_um, f"{layer.name} thickness on field"))

    def build_dielectrics(self, pex25d_file: Any) -> None:
        layers = list(self.tech_info.tech.process_stack.layers)
        metal_names = [lyr.name for lyr in layers if lyr.layer_type == LT.LAYER_TYPE_METAL]

        def next_metal_after(index: int) -> Optional[str]:
            for lyr in layers[index + 1:]:
                if lyr.layer_type == LT.LAYER_TYPE_METAL:
                    return lyr.name
            return None

        ground_plane_name = pex25d_file.ground_plane.name
        previous_metal: Optional[str] = None

        for index, layer in enumerate(layers):
            if layer.layer_type == LT.LAYER_TYPE_METAL:
                previous_metal = layer.name
                continue

            is_dielectric = layer.layer_type in (LT.LAYER_TYPE_FIELD_OXIDE,
                                                 LT.LAYER_TYPE_SIMPLE_DIELECTRIC,
                                                 LT.LAYER_TYPE_CONFORMAL_DIELECTRIC)
            if not is_dielectric:
                continue

            if layer.layer_type != LT.LAYER_TYPE_FIELD_OXIDE \
                    and layer.name not in self.included_dielectric_names:
                debug(f"Dielectric '{layer.name}' excluded by --diel")
                continue

            above = next_metal_after(index)

            # The last simple dielectric with no metal above it is the material
            # that fills whatever nothing else claims.
            if layer.layer_type == LT.LAYER_TYPE_SIMPLE_DIELECTRIC and above is None:
                if not self.claim_name(layer.name, 'Background'):
                    continue
                background = pex25d_file.background
                background.name = layer.name
                background.permittivity = layer.simple_dielectric_layer.dielectric_k
                info(f"DIELECTRIC_BACKGROUND {layer.name}: "
                     f"k={background.permittivity}")
                continue

            match layer.layer_type:
                case LT.LAYER_TYPE_FIELD_OXIDE:
                    self.add_simple_dielectric(
                        pex25d_file,
                        layer=layer,
                        permittivity=layer.field_oxide_layer.dielectric_k,
                        wraps=ground_plane_name,
                        below=ground_plane_name,
                        above=above or (metal_names[0] if metal_names else None))

                case LT.LAYER_TYPE_SIMPLE_DIELECTRIC:
                    below = previous_metal or ground_plane_name
                    self.add_simple_dielectric(
                        pex25d_file,
                        layer=layer,
                        permittivity=layer.simple_dielectric_layer.dielectric_k,
                        wraps=self.outermost_profile(below),
                        below=below,
                        above=above)

                case LT.LAYER_TYPE_CONFORMAL_DIELECTRIC:
                    self.add_conformal_dielectric(pex25d_file, layer=layer)

    def add_simple_dielectric(self,
                              pex25d_file: Any,
                              layer: Any,
                              permittivity: float,
                              wraps: str,
                              below: Optional[str],
                              above: Optional[str]) -> None:
        if not below or not above:
            warning(f"Simple dielectric '{layer.name}' has no metal below or above it "
                    f"in the process stack; skipping")
            return
        if not self.claim_name(layer.name, 'Simple dielectric'):
            return

        dielectric = pex25d_file.dielectrics.add()
        dielectric.name = layer.name
        dielectric.kind = pex25d_dielectric_pb2().DIELECTRIC_KIND_SIMPLE
        dielectric.permittivity = permittivity
        dielectric.wraps = wraps
        dielectric.simple.between_below = below
        dielectric.simple.between_above = above
        debug(f"DIELECTRIC_SIMPLE {layer.name}: k={permittivity} "
              f"wraps {wraps} between {below} {above}")

    def add_conformal_dielectric(self, pex25d_file: Any, layer: Any) -> None:
        wraps = layer.conformal_dielectric_layer.reference
        permittivity = layer.conformal_dielectric_layer.dielectric_k

        if wraps not in self._profile_names:
            warning(f"Dielectric '{layer.name}' wraps '{wraps}', which is not a "
                    f"declared profile; skipping")
            return
        if not self.claim_name(layer.name, 'Conformal dielectric'):
            return

        over, beside, on_field = self.conformal_thicknesses(layer)

        dielectric = pex25d_file.dielectrics.add()
        dielectric.name = layer.name
        dielectric.kind = pex25d_dielectric_pb2().DIELECTRIC_KIND_CONFORMAL
        dielectric.permittivity = permittivity
        dielectric.wraps = wraps
        dielectric.conformal.thickness_over_wrapped = over
        dielectric.conformal.thickness_beside_wrapped = beside
        dielectric.conformal.thickness_on_field = on_field
        debug(f"DIELECTRIC_CONFORMAL {layer.name}: k={permittivity} wraps {wraps} "
              f"over={over} beside={beside} on_field={on_field}")

    # ------------------------------------------------- conductors and shapes

    @cached_property
    def shape_layers(self) -> List[str]:
        """Profiles that may carry drawn geometry: metals and vias, in stack order."""
        names: List[str] = []
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
        pex25d_file.domain_margin.x = margin
        pex25d_file.domain_margin.y = margin
        pex25d_file.domain_margin.z = margin
        info(f"DOMAIN_MARGIN {margin} grid units in x, y and z")


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
