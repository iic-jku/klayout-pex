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

"""Shared physical stack construction for layout extraction and calibration patterns."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from fractions import Fraction
from functools import cached_property
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

import klayout_pex_protobuf.kpex.tech.process_stack_pb2 as process_stack_pb2

from ..log import debug, info, warning
from ..pex25d.format_version import FORMAT_VERSION_MAJOR, FORMAT_VERSION_MINOR, FORMAT_VERSION_SUFFIX
from ..pex25d.protobuf import pex25d_file_pb2, pex25d_dielectric_pb2
from ..types import GDSPair
from ..version import __version__

if TYPE_CHECKING:
    from ..tech_info import TechInfo


LT = process_stack_pb2.ProcessStackInfo.LayerType

# PEX25D wants every coordinate as an exact integer count of grid units. 0.0001 µm
# is the coarsest grid on which the sky130A z stack closes (poly sits at 0.3262),
# and it divides the usual 0.001 µm layout DBU exactly, as the format requires.
DEFAULT_GRID_UM = '0.0001'


class BuildError(Exception):
    pass


class GeometryScope(Enum):
    """Which extracted conductor geometry belongs in the physical scene."""

    INTERCONNECT = 'interconnect'
    ELECTROSTATIC = 'electrostatic'


@dataclass
class BuilderOptions:
    """Geometry and material choices for canonical PEX25D generation."""

    grid_um: str = DEFAULT_GRID_UM
    """Coordinate grid as an exact decimal or fraction string."""

    with_source_refs: bool = False
    """Populate every ``SourceRef``. Roughly doubles the size of a file."""

    dielectric_filter: Optional[Any] = None
    """The ``--diel`` multiple-choice pattern, as used by the FasterCap path."""

    include_resistance: bool = True
    """Emit ``RESISTANCE`` records for the layers the technology defines."""

    domain_margin_um: Optional[float] = None
    """Clearance around geometry; electrostatic scope also retains original cell bounds.

    Interconnect emits ``DOMAIN_MARGIN``; electrostatic extraction emits an
    explicit ``DOMAIN_BOX``. None leaves the domain unset.
    """

    process_corner: Optional[str] = None
    """Value for ``META process_corner``, if known."""

    geometry_scope: GeometryScope = GeometryScope.INTERCONNECT
    """Electrostatic extraction also retains extracted diffusion and tap solids."""

    include_terminals: bool = True
    """Emit circuit/device terminal records independently of conductor geometry."""

    background_permittivity: Optional[float] = None
    """Override the unbounded medium; None uses the technology's background."""


class PEX25DStackBuilder:
    """Construct the resolved technology's stack without requiring layout or LVS input."""

    def __init__(self, tech_info: TechInfo, options: Optional[BuilderOptions] = None):
        self.tech_info = tech_info
        self.options = options or BuilderOptions()
        if not isinstance(self.options.geometry_scope, GeometryScope):
            raise BuildError(f'Unknown geometry scope {self.options.geometry_scope!r}')
        for name, value, positive in (
                ('background permittivity', self.options.background_permittivity, True),
                ('domain margin', self.options.domain_margin_um, False)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or value < 0 or (positive and value == 0)):
                raise BuildError(f'{name.capitalize()} must be finite and {"positive" if positive else "nonnegative"}')
        self._surface_anchor_name: Optional[str] = None
        self._contact_anchor_name: Optional[str] = None
        self._diffusion_profiles: List[str] = []
        self._grid = Fraction(self.options.grid_um)
        self._profile_names: Set[str] = set()
        self._via_contacts: Dict[str, Any] = {}
        self._device_contact_by_diffusion: Dict[str, str] = {}
        self._nwell_contacts: List[str] = []

    def build(self) -> Any:
        file = pex25d_file_pb2().PEX25DFile()
        file.format_version_major = FORMAT_VERSION_MAJOR
        file.format_version_minor = FORMAT_VERSION_MINOR
        file.format_version_suffix = FORMAT_VERSION_SUFFIX
        self.build_units(file)
        self.build_meta(file)
        self.build_ground_plane(file)
        self.build_layers(file)
        self.build_dielectrics(file)
        return file

    def build_units(self, file: Any):
        file.units.length = file.units.LENGTH_UNIT_UM
        file.units.grid_numerator = self._grid.numerator
        file.units.grid_denominator = self._grid.denominator

    def build_meta(self, file: Any):
        file.metadata.add(key='technology', value=self.tech_info.tech.name)
        if self.options.process_corner:
            file.metadata.add(key='process_corner', value=self.options.process_corner)
        file.metadata.add(key='generator', value=f'kpex {__version__}')
        if self.unavailable_profiles:
            file.metadata.add(key='physical_geometry_unavailable', value=','.join(sorted(self.unavailable_profiles)))

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

    def gds_pair(self, layer_name: str) -> Optional[GDSPair]:
        return self.tech_info.gds_pair(layer_name)

    @cached_property
    def metal_layer_by_name(self) -> Dict[str, Any]:
        return {lyr.name: lyr for lyr in self.tech_info.process_metal_layers}

    @cached_property
    def metal_layers_by_canonical_name(self) -> Dict[str, List[str]]:
        """The emitted METAL profiles, grouped by the canonical layer behind them."""
        groups: Dict[str, List[str]] = {}
        for name in self.metal_layer_by_name:
            canonical = self.canonical_name(name)
            if canonical:
                groups.setdefault(canonical, []).append(name)
        return groups

    def resolve_metal(self, name: str, context: str) -> Optional[str]:
        """
        Map a name used by a contact onto an emitted METAL profile.

        The two namespaces need not agree. sky130A splits a canonical layer per
        MiM-cap variant, so a contact on ``met3`` has to find ``met3_ncap``; the
        IHP stacks name their profiles after the drawing layer while their
        contacts name the LVS computed layer, so ``metal1_con`` has to find
        ``Metal1``. Both meet at the canonical layer, so the candidates are
        taken from there rather than from the spelling of the name. Where
        exactly one candidate carries a contact the choice is unambiguous;
        anything else is reported rather than guessed.
        """
        if name in self.metal_layer_by_name:
            return name

        canonical = self.canonical_name(name)
        candidates = self.metal_layers_by_canonical_name.get(canonical, []) \
            if canonical else []
        if not candidates:
            warning(f"{context}: no metal layer '{name}' in the process stack; skipping")
            return None

        chosen = candidates[0] if len(candidates) == 1 else None
        if chosen is None:
            with_contact = [n for n in candidates
                            if self.metal_layer_by_name[n].metal_layer
                            .HasField('contact_above')]
            if len(with_contact) != 1:
                warning(f"{context}: '{name}' is ambiguous in the process stack "
                        f"({', '.join(candidates)}); skipping")
                return None
            chosen = with_contact[0]

        # Where the candidates share a z extent — sky130A splits met3 and met4
        # only to hang different dielectrics off them — the choice cannot change
        # the via extent that CONNECTS derives, so it is not worth a warning.
        # A genuine difference is.
        extents = {(self.metal_layer_by_name[n].metal_layer.z,
                    self.metal_layer_by_name[n].metal_layer.thickness)
                   for n in candidates}
        report = debug if len(extents) == 1 else warning
        report(f"{context}: no metal layer '{name}' in the process stack, using "
               f"'{chosen}' for canonical layer '{canonical}'; candidates were "
               f"{', '.join(candidates)}")
        return chosen

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

    @cached_property
    def unavailable_profiles(self) -> Set[str]:
        metals = {layer.name for layer in self.tech_info.process_metal_layers
                  if layer.metal_layer.physical_geometry_unavailable}
        if not metals:
            return set()
        profiles = set(metals)
        contacts = [(layer.name, layer.metal_layer.contact_above) for layer in self.tech_info.process_metal_layers]
        contacts.extend((layer.name, layer.diffusion_layer.contact_above)
                        for layer in self.tech_info.process_diffusion_layers)
        contacts.extend((layer.name, layer.nwell_layer.contact_above) for layer in self.tech_info.process_nwell_layers)
        for owner, contact in contacts:
            if not contact.name:
                continue
            above = self.resolve_metal(contact.metal_above, f"Physical restriction on {contact.name}")
            if above is None:
                raise BuildError(f"Cannot verify physical contact association of '{contact.name}'")
            below = self.resolve_metal(contact.layer_below or owner, f"Physical restriction on {contact.name}") \
                if owner in self.metal_layer_by_name else owner
            if below is None:
                raise BuildError(f"Cannot verify physical contact association of '{contact.name}'")
            if below in metals or above in metals:
                profiles.add(contact.name)
        return profiles

    @cached_property
    def unavailable_dielectrics(self) -> Set[str]:
        excluded = set(self.unavailable_profiles)
        while True:
            dependent = {layer.name for layer in self.tech_info.tech.process_stack.layers
                         if layer.layer_type == LT.LAYER_TYPE_CONFORMAL_DIELECTRIC
                         and layer.conformal_dielectric_layer.reference in excluded}
            added = dependent - excluded
            if not added:
                return excluded - self.unavailable_profiles
            excluded.update(added)

    def build_ground_plane(self, pex25d_file: Any):
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

    def build_layers(self, pex25d_file: Any):
        for layer in self.tech_info.process_metal_layers:
            metal_layer = layer.metal_layer
            if layer.name in self.unavailable_profiles:
                continue
            if not self.claim_name(layer.name, 'Metal'):
                continue
            metal = pex25d_file.metals.add()
            metal.name = layer.name
            metal.zlow = self.to_grid(metal_layer.z, f"{layer.name} bottom")
            metal.zhigh = self.to_grid(metal_layer.z + metal_layer.thickness,
                                       f"{layer.name} top")
            debug(f"METAL {metal.name}: z {metal.zlow} … {metal.zhigh}")

        if self.options.geometry_scope == GeometryScope.ELECTROSTATIC:
            for layer in self.tech_info.process_diffusion_layers:
                if not self.claim_name(layer.name, 'Diffusion'):
                    continue
                profile = pex25d_file.metals.add(name=layer.name, zlow=0,
                                                zhigh=self.to_grid(0.1, 'diffusion thickness'))
                self._diffusion_profiles.append(profile.name)
            # Physical silicon and contacts overlap in z. An empty anchor keeps
            # a contact's lower face at zero instead of at the silicon's top.
            self._contact_anchor_name = self.add_empty_anchor(pex25d_file, 'contact_base', 0)
            self._surface_anchor_name = self.add_empty_anchor(pex25d_file, 'surface', 0, upper=True)

        # A via is positioned by what it connects, never by its own z, so a change
        # in metal position or thickness propagates without any other edit.
        for layer in self.tech_info.process_metal_layers:
            metal_layer = layer.metal_layer
            if not metal_layer.HasField('contact_above'):
                continue
            contact = metal_layer.contact_above
            if not contact.name:
                continue
            if contact.name in self.unavailable_profiles:
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

        # A device contact (e.g. on a source/drain diffusion) lands on device geometry, which PEX25D
        # leaves out: the diffusion is an empty profile, an anchor at the lower end of its contacts
        # (see Metal), as high as the tech info's contact is thick below the metal above,
        # and a terminal on the device is a node at that lower face (see TERMINAL_KIND_DEVICE_TERMINAL).
        # The contact of an nwell over its n-taps (e.g. sky130A licon_ntap_con) is anchored on the nwell
        # in the same way, but no device contact, so that a terminal on the nwell isn't on it (#489).
        anchored = [(layer, layer.diffusion_layer.contact_above, True)
                    for layer in self.tech_info.process_diffusion_layers] + \
                   [(layer, layer.nwell_layer.contact_above, False)
                    for layer in self.tech_info.process_nwell_layers]
        for layer, contact, is_device_contact in anchored:
            if not contact.name:
                continue
            if contact.name in self.unavailable_profiles:
                continue
            context = f"Contact '{contact.name}'"
            above = self.resolve_metal(contact.metal_above, context)
            if self.options.geometry_scope == GeometryScope.ELECTROSTATIC:
                if above:
                    self.add_electrostatic_contact(pex25d_file, layer, contact, above, is_device_contact)
                continue
            if not above or not self.claim_name(layer.name, 'Diffusion'):
                continue
            if not self.claim_name(contact.name, 'Via'):
                continue

            metal_above = self.metal_layer_by_name[above].metal_layer
            anchor = pex25d_file.metals.add()
            anchor.name = layer.name
            anchor.zhigh = self.to_grid(metal_above.z - contact.thickness, f"{contact.name} bottom")
            anchor.zlow = anchor.zhigh - 1
            debug(f"METAL {anchor.name}: z {anchor.zlow} … {anchor.zhigh}, anchor of {contact.name}")

            self._via_contacts[contact.name] = contact
            if is_device_contact:
                self._device_contact_by_diffusion[layer.name] = contact.name
            else:
                self._nwell_contacts.append(contact.name)
            via = pex25d_file.vias.add()
            via.name = contact.name
            via.connects_below = layer.name
            via.connects_above = above
            debug(f"VIA {via.name}: connects {layer.name} → {above}")

    def unique_profile_name(self, role: str) -> str:
        reserved = {layer.name for layer in self.tech_info.tech.process_stack.layers} | self._profile_names
        reserved.update(layer.metal_layer.contact_above.name for layer in self.tech_info.process_metal_layers)
        reserved.update(layer.diffusion_layer.contact_above.name for layer in self.tech_info.process_diffusion_layers)
        reserved.update(layer.nwell_layer.contact_above.name for layer in self.tech_info.process_nwell_layers)
        base = f'__electrostatic_{role}'
        name, suffix = base, 2
        while name in reserved:
            name, suffix = f'{base}_{suffix}', suffix + 1
        return name

    def add_empty_anchor(self, file: Any, role: str, plane: int, upper: bool = False) -> str:
        name = self.unique_profile_name(role)
        self.claim_name(name, 'Empty anchor')
        file.metals.add(name=name, zlow=plane if upper else plane - 1,
                        zhigh=plane + 1 if upper else plane)
        return name

    def add_electrostatic_contact(self, file: Any, layer: Any, contact: Any,
                                  above: str, is_device_contact: bool):
        if not self.claim_name(contact.name, 'Via'):
            return
        top = self.to_grid(contact.thickness, f'{contact.name} thickness')
        if top <= 0:
            raise BuildError(f"Contact '{contact.name}' must have positive thickness")
        actual_top = self.to_grid(self.metal_layer_by_name[above].metal_layer.z, f'{above} bottom')
        if actual_top != top:
            above = self.add_empty_anchor(file, f'{contact.name}_top', top, upper=True)
        self._via_contacts[contact.name] = contact
        if is_device_contact:
            self._device_contact_by_diffusion[layer.name] = contact.name
        else:
            self._nwell_contacts.append(contact.name)
        file.vias.add(name=contact.name, connects_below=self._contact_anchor_name, connects_above=above)

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

        Top and side thicknesses are incremental from the wrapped profile.
        The field extent is cumulative from the bottom of the chain's root
        conductor, including when that conductor has no shapes.
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

    def build_dielectrics(self, pex25d_file: Any):
        if self.options.geometry_scope == GeometryScope.ELECTROSTATIC:
            self.build_electrostatic_dielectrics(pex25d_file)
            return
        layers = [layer for layer in self.tech_info.tech.process_stack.layers
                  if layer.name not in self.unavailable_profiles | self.unavailable_dielectrics]
        metal_names = [lyr.name for lyr in layers if lyr.layer_type == LT.LAYER_TYPE_METAL]

        def next_metal_after(index: int) -> Optional[str]:
            for lyr in layers[index + 1:]:
                if lyr.layer_type == LT.LAYER_TYPE_METAL:
                    return lyr.name
            return None

        ground_plane_name = pex25d_file.ground_plane.name
        previous_metal: Optional[str] = None

        # The last simple dielectric with no metal above it is the material that fills whatever nothing
        # else claims. PEX25D needs one, so --diel never leaves it out.
        # NOTE: the others above the top metal have no extent, as a metal above bounds a simple dielectric
        background_names = [lyr.name for index, lyr in enumerate(layers)
                            if lyr.layer_type == LT.LAYER_TYPE_SIMPLE_DIELECTRIC and next_metal_after(index) is None]
        background_name = background_names[-1] if background_names else None

        for index, layer in enumerate(layers):
            if layer.layer_type == LT.LAYER_TYPE_METAL:
                previous_metal = layer.name
                continue

            is_dielectric = layer.layer_type in (LT.LAYER_TYPE_FIELD_OXIDE,
                                                 LT.LAYER_TYPE_SIMPLE_DIELECTRIC,
                                                 LT.LAYER_TYPE_CONFORMAL_DIELECTRIC)
            if not is_dielectric:
                if layer.layer_type in (LT.LAYER_TYPE_SUBSTRATE, LT.LAYER_TYPE_NWELL, LT.LAYER_TYPE_DIFFUSION):
                    continue
                raise NotImplementedError(f"PEX25D dielectric export for layer type {layer.layer_type} "
                                          f"of '{layer.name}' is not implemented")

            if layer.layer_type != LT.LAYER_TYPE_FIELD_OXIDE and layer.name != background_name \
                    and layer.name not in self.included_dielectric_names:
                debug(f"Dielectric '{layer.name}' excluded by --diel")
                continue

            above = next_metal_after(index)

            if layer.name == background_name:
                if not self.claim_name(layer.name, 'Background'):
                    continue
                if layer.name not in self.included_dielectric_names:
                    info(f"Dielectric '{layer.name}' excluded by --diel, but kept as the background")
                background = pex25d_file.background
                background.name = layer.name
                background.permittivity = (self.options.background_permittivity
                                           if self.options.background_permittivity is not None
                                           else layer.simple_dielectric_layer.dielectric_k)
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

                case _:
                    raise NotImplementedError(f"PEX25D dielectric export for layer type {layer.layer_type} "
                                              f"of '{layer.name}' is not implemented")

    def build_electrostatic_dielectrics(self, file: Any):
        available = [layer for layer in self.tech_info.process_metal_layers
                     if layer.name not in self.unavailable_profiles]
        background_layers = [layer for layer in self.tech_info.tech.process_stack.layers
                             if layer.layer_type == LT.LAYER_TYPE_SIMPLE_DIELECTRIC]
        permittivity = self.options.background_permittivity
        if permittivity is None:
            if not background_layers:
                raise BuildError('Electrostatic geometry needs an explicit background permittivity')
            permittivity = background_layers[-1].simple_dielectric_layer.dielectric_k
        background_name = self.unique_profile_name('background')
        self.claim_name(background_name, 'Background')
        file.background.name, file.background.permittivity = background_name, permittivity
        for layer in self.tech_info.tech.process_stack.layers:
            if layer.layer_type == LT.LAYER_TYPE_FIELD_OXIDE and available:
                self.add_simple_dielectric(file, layer, layer.field_oxide_layer.dielectric_k,
                                           self._surface_anchor_name, self._surface_anchor_name,
                                           available[0].name)
        for index, metal in enumerate(available):
            wrapped = metal.name
            seen_films = {wrapped}
            while True:
                try:
                    film = self.tech_info.conformal_dielectric_wrapping(wrapped)
                except Exception as exc:
                    raise BuildError(f"Cannot resolve electrostatic film above '{wrapped}': {exc}") from exc
                if film is None or film.name in self.unavailable_dielectrics:
                    break
                if film.name in seen_films:
                    raise BuildError(f"Cyclic electrostatic dielectric chain through '{film.name}'")
                self.add_conformal_dielectric(file, film)
                wrapped = film.name
                seen_films.add(wrapped)
            # Use the first simple band following this metal, exactly as the
            # extraction stack does. Its finite top band is distinct from k_void.
            simple = None
            seen = False
            for layer in self.tech_info.tech.process_stack.layers:
                if layer.name == metal.name:
                    seen = True
                elif seen and layer.layer_type == LT.LAYER_TYPE_METAL:
                    if layer.name not in self.unavailable_profiles:
                        break
                elif seen and simple is None and layer.layer_type == LT.LAYER_TYPE_SIMPLE_DIELECTRIC:
                    simple = layer
            if simple is None or simple.name not in self.included_dielectric_names:
                continue
            if index + 1 < len(available):
                above = available[index + 1].name
            else:
                top = self.to_grid(metal.metal_layer.z + 5.0, 'top dielectric extent')
                above = self.add_empty_anchor(file, 'top_dielectric', top, upper=True)
            self.add_simple_dielectric(file, simple, simple.simple_dielectric_layer.dielectric_k,
                                       wrapped, metal.name, above)

    def add_simple_dielectric(self,
                              pex25d_file: Any,
                              layer: Any,
                              permittivity: float,
                              wraps: str,
                              below: Optional[str],
                              above: Optional[str]):
        if not below or not above:
            warning(f"Simple dielectric '{layer.name}' has no metal {'below' if not below else 'above'} it "
                    f"in the process stack to bound it; skipping")
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

    def add_conformal_dielectric(self, pex25d_file: Any, layer: Any):
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

    def build_domain(self, pex25d_file: Any):
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



def build_pex25d_stack(tech_info: TechInfo, options: Optional[BuilderOptions] = None) -> Any:
    """Build the physical stack shared by layout extraction and calibration preparation."""
    builder = PEX25DStackBuilder(tech_info, options)
    file = builder.build()
    builder.build_domain(file)
    return file
