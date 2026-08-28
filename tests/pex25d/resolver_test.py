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

from __future__ import annotations

import allure
from typing import *
import unittest

from klayout_pex.pex25d.diagnostics import DiagnosticsReport
from klayout_pex.pex25d.protobuf import pex25d_scene_pb2
from klayout_pex.pex25d.resolver import ResolveError, resolve

from .pex25d_fixtures import MINIMAL, codes, read, replacing


def resolved(text: str = MINIMAL) -> Any:
    return resolve(read(text))


def resolve_codes(text: str) -> list:
    report = DiagnosticsReport()
    try:
        resolve(read(text), report=report)
    except ResolveError:
        pass
    return codes(report)


def layer(scene: Any, name: str) -> Any:
    return next(l for l in scene.layers if l.name == name)


def dielectric(scene: Any, name: str) -> Any:
    return next(d for d in scene.dielectrics if d.name == name)


@allure.parent_suite("Unit Tests")
@allure.tag("PEX25D", "Resolver")
class Pex25DResolverTest(unittest.TestCase):
    # ---------------------------------------------------------------- z axis

    def test_a_via_takes_its_extent_from_connects(self):
        scene = resolved()
        via = layer(scene, 'via1')
        assert (via.zlow, via.zhigh) == (14000, 20000)   # met1 top → met2 bottom
        assert (via.connects_below, via.connects_above) == ('met1', 'met2')

    def test_a_via_may_land_on_the_ground_plane(self):
        scene = resolved(replacing('VIA via1 CONNECTS met1 met2',
                                   'VIA via1 CONNECTS subs met1'))
        assert (layer(scene, 'via1').zlow, layer(scene, 'via1').zhigh) == (-1000, 10000)

    def test_a_simple_band_spans_bottom_to_bottom(self):
        # BETWEEN met1 met2 is the bottom of met1 to the bottom of met2, so the
        # band joins the neighbouring levels with no seam.
        band = dielectric(resolved(), 'ild')
        assert (band.zlow, band.zhigh) == (10000, 20000)

    def test_conformal_thicknesses_are_carried_in_grid_units(self):
        film = dielectric(resolved(), 'lint')
        assert film.thickness_over_wrapped == 1000
        assert film.thickness_beside_wrapped == 800
        assert film.thickness_on_field == 0
        assert (film.zlow, film.zhigh) == (10000, 15000)  # met1, plus 0.1 over

    # ----------------------------------------------------------- wrap chains

    def test_wrap_depth_and_root(self):
        scene = resolved()
        assert (dielectric(scene, 'fox').wrap_depth, dielectric(scene, 'fox').root) \
            == (1, 'subs')
        assert (dielectric(scene, 'lint').wrap_depth, dielectric(scene, 'lint').root) \
            == (1, 'met1')
        assert (dielectric(scene, 'ild').wrap_depth, dielectric(scene, 'ild').root) \
            == (2, 'met1')

    def test_dielectrics_come_out_in_ascending_depth(self):
        depths = [d.wrap_depth for d in resolved().dielectrics]
        assert depths == sorted(depths)

    def test_e0230_cyclic_wraps(self):
        assert 'PEX25D-E0230' in resolve_codes(
            replacing('DIELECTRIC_CONFORMAL lint WRAPS met1', 
                      'DIELECTRIC_CONFORMAL lint WRAPS ild'))

    # -------------------------------------------------------- referential

    def test_e0201_unknown_profile(self):
        assert 'PEX25D-E0201' in resolve_codes(
            replacing('VIA via1 CONNECTS met1 met2', 'VIA via1 CONNECTS met1 met9'))

    def test_e0202_duplicate_profile_name(self):
        assert 'PEX25D-E0202' in resolve_codes(
            replacing('METAL met2 Z_OFFSETS 2.0 2.4',
                      'METAL met2 Z_OFFSETS 2.0 2.4\nMETAL met2 Z_OFFSETS 3.0 3.4'))

    def test_a_dielectric_shares_the_profile_namespace_with_the_metals(self):
        assert 'PEX25D-E0202' in resolve_codes(
            replacing('METAL met2 Z_OFFSETS 2.0 2.4',
                      'METAL lint Z_OFFSETS 2.0 2.4'))

    def test_e0202_a_dielectric_declared_twice(self):
        # Silent before: the later declaration replaced the earlier one in the
        # lookup and the damage showed up as some unrelated film wrapping the
        # wrong object. This is the sky130A 'capild' shape.
        assert 'PEX25D-E0202' in resolve_codes(
            replacing('DIELECTRIC_SIMPLE ild WRAPS lint PERMITTIVITY 4.1 BETWEEN met1 met2',
                      'DIELECTRIC_SIMPLE ild WRAPS lint PERMITTIVITY 4.1 BETWEEN met1 met2\n'
                      'DIELECTRIC_SIMPLE ild WRAPS met2 PERMITTIVITY 4.2 BETWEEN met1 met2'))

    def test_e0202_the_background_is_in_the_namespace_too(self):
        assert 'PEX25D-E0202' in resolve_codes(
            replacing('DIELECTRIC_BACKGROUND air PERMITTIVITY 1.0',
                      'DIELECTRIC_BACKGROUND met1 PERMITTIVITY 1.0'))

    def test_e0211_metal_with_inverted_z(self):
        assert 'PEX25D-E0211' in resolve_codes(
            replacing('METAL met1 Z_OFFSETS 1.0 1.4', 'METAL met1 Z_OFFSETS 1.4 1.0'))

    def test_e0212_connects_endpoints_out_of_order(self):
        assert 'PEX25D-E0212' in resolve_codes(
            replacing('VIA via1 CONNECTS met1 met2', 'VIA via1 CONNECTS met2 met1'))

    def test_e0220_resistance_metal_on_a_via(self):
        assert 'PEX25D-E0220' in resolve_codes(
            replacing('RESISTANCE METAL met2 SHEET 0.125',
                      'RESISTANCE METAL via1 SHEET 0.125'))

    def test_e0221_resistance_via_on_a_metal(self):
        assert 'PEX25D-E0221' in resolve_codes(
            replacing('RESISTANCE VIA via1 PER_CUT 4.5',
                      'RESISTANCE VIA met1 PER_CUT 4.5'))

    def test_resistance_is_carried_onto_the_layer(self):
        scene = resolved()
        assert layer(scene, 'met1').WhichOneof('resistance') == 'metal_resistance'
        assert layer(scene, 'met1').metal_resistance.sheet == 0.125
        assert layer(scene, 'via1').via_resistance.per_cut == 4.5
        assert scene.resistance_temperature.celsius == 25.0

    def test_a_profile_without_resistance_carries_none(self):
        scene = resolved(replacing('RESISTANCE VIA via1 PER_CUT 4.5\n', ''))
        assert layer(scene, 'via1').WhichOneof('resistance') is None

    # ------------------------------------------------------------- terminals

    def test_a_terminal_resolves_to_its_intersection(self):
        scene = resolved()
        terminal = scene.conductors[0].terminals[0]
        assert terminal.layer == 'met1'
        assert (terminal.zlow, terminal.zhigh) == (10000, 14000)
        assert len(terminal.boxes) == 1
        box = terminal.boxes[0]
        assert (box.lower_left.x, box.lower_left.y) == (0, 0)
        assert (box.upper_right.x, box.upper_right.y) == (2000, 5000)

    def test_e0242_a_terminal_that_selects_nothing(self):
        assert 'PEX25D-E0242' in resolve_codes(
            replacing('TERMINAL t1 CONDUCTOR A LAYER met1 KIND PIN LL 0.0 0.0 UR 0.2 0.5',
                      'TERMINAL t1 CONDUCTOR A LAYER met1 KIND PIN LL 9.0 9.0 UR 9.2 9.5'))

    def test_e0240_a_terminal_that_clips_a_via_cut(self):
        # A cut is atomic: one lumped resistor with one face at each end.
        assert 'PEX25D-E0240' in resolve_codes(
            replacing('TERMINAL t1 CONDUCTOR A LAYER met1 KIND PIN LL 0.0 0.0 UR 0.2 0.5',
                      'TERMINAL t1 CONDUCTOR A LAYER via1 KIND PIN LL 0.2 0.1 UR 0.3 0.2'))

    def test_a_terminal_may_take_a_whole_cut(self):
        assert resolve_codes(
            replacing('TERMINAL t1 CONDUCTOR A LAYER met1 KIND PIN LL 0.0 0.0 UR 0.2 0.5',
                      'TERMINAL t1 CONDUCTOR A LAYER via1 KIND PIN LL 0.1 0.0 UR 0.5 0.4')) == []

    def test_e0201_terminal_on_a_dielectric(self):
        assert 'PEX25D-E0201' in resolve_codes(replacing(
            'TERMINAL t1 CONDUCTOR A LAYER met1 KIND PIN LL 0.0 0.0 UR 0.2 0.5',
            'TERMINAL t1 CONDUCTOR A LAYER lint KIND PIN LL 0.0 0.0 UR 0.2 0.5'))

    # ---------------------------------------------------------------- domain

    def test_domain_margin_expands_the_geometry_bounds(self):
        scene = resolved()
        origins = pex25d_scene_pb2().ResolvedDomain
        assert scene.domain.origin == origins.ORIGIN_DOMAIN_MARGIN
        bounds = scene.domain.geometry_bounds
        box = scene.domain.box
        assert box.lower_left.x == bounds.lower_left.x - 40000
        assert box.upper_right.z == bounds.upper_right.z + 20000

    def test_geometry_bounds_ignore_laterally_unbounded_materials(self):
        # Only conductor shapes and conformal films with THICKNESS_ON_FIELD 0
        # are finite in XY. A simple band is not, and must not inflate this.
        bounds = resolved().domain.geometry_bounds
        assert bounds.lower_left.x == -800     # met1 at x=0, grown by lint
        assert bounds.upper_right.x == 30800   # conductor B at x=3.0, plus lint
        assert bounds.upper_right.z == 24000   # met2 top, not the ild band top

    def test_no_domain_record_leaves_the_domain_unspecified(self):
        # The message is still present — it carries geometry_bounds for an
        # adapter placing its own boundary — but nothing in it is a domain.
        origins = pex25d_scene_pb2().ResolvedDomain
        scene = resolved(replacing('DOMAIN_MARGIN X 4.0 Y 4.0 Z 2.0\n', ''))
        assert scene.domain.origin == origins.ORIGIN_UNSPECIFIED
        assert not scene.domain.HasField('box')
        assert not scene.domain.HasField('applied_margin')
        assert scene.domain.geometry_bounds.upper_right.z == 24000

    def test_domain_box_is_copied_verbatim(self):
        scene = resolved(replacing('DOMAIN_MARGIN X 4.0 Y 4.0 Z 2.0',
                                   'DOMAIN_BOX LL -1.0 -1.0 -1.0 UR 5.0 5.0 5.0'))
        origins = pex25d_scene_pb2().ResolvedDomain
        assert scene.domain.origin == origins.ORIGIN_DOMAIN_BOX
        assert scene.domain.box.upper_right.x == 50000

    # ------------------------------------------------------------- structure

    def test_conductors_carry_their_geometry_grouped_by_layer(self):
        scene = resolved()
        conductor = scene.conductors[0]
        assert conductor.name == 'A'
        assert not conductor.floating
        assert {r.layer for r in conductor.regions} == {'met1', 'via1', 'met2'}

    def test_the_reserved_net_name_marks_a_floating_body(self):
        scene = resolved(replacing('CONDUCTOR B netb', 'CONDUCTOR B FLOATING'))
        assert scene.conductors[1].floating

    def test_resolve_error_stops_before_a_half_built_scene(self):
        with self.assertRaises(ResolveError):
            resolve(read(replacing('VIA via1 CONNECTS met1 met2',
                                   'VIA via1 CONNECTS met1 met9')))

    def test_the_background_never_competes_for_occupancy(self):
        scene = resolved()
        assert scene.background.name == 'air'
        assert 'air' not in [d.name for d in scene.dielectrics]

    def test_an_anchor_metal_without_shapes_is_legal(self):
        scene = resolved(replacing('METAL met2 Z_OFFSETS 2.0 2.4',
                                   'METAL met2 Z_OFFSETS 2.0 2.4\n'
                                   'METAL diff Z_OFFSETS 0.0 0.1'))
        assert layer(scene, 'diff').zlow == 0
