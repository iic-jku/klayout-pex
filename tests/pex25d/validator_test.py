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

from klayout_pex.pex25d.diagnostics import DiagnosticsReport, Severity
from klayout_pex.pex25d.reader import ReadError
from klayout_pex.pex25d.resolver import resolve
from klayout_pex.pex25d.validator import validate

from .pex25d_fixtures import MINIMAL, codes, read, replacing


def check(text: str, strict: bool = False) -> List[str]:
    """The codes validating ``text`` produces, reading errors included."""
    report = DiagnosticsReport()
    try:
        message = read(text, report=report)
    except ReadError:
        return codes(report)
    validate(message, report=report, strict=strict)
    return codes(report)


def check_scene(scene: Any, strict: bool = False) -> List[str]:
    report = DiagnosticsReport()
    validate(scene, report=report, strict=strict)
    return codes(report)


def geometry(*records: str) -> str:
    """The fixture with its conductors and shapes replaced by ``records``."""
    body = '\n'.join(records)
    return replacing(
        "CONDUCTOR A neta\n"
        "CONDUCTOR B netb\n"
        "BOX CONDUCTOR A LAYER met1 LL 0.0 0.0 UR 1.0 0.5\n"
        "BOX CONDUCTOR A LAYER via1 LL 0.2 0.1 UR 0.4 0.3\n"
        "BOX CONDUCTOR A LAYER met2 LL 0.0 0.0 UR 1.0 0.5\n"
        "POLYGON CONDUCTOR B LAYER met1 OUTER 2.0 0.0 3.0 0.0 3.0 1.0 2.0 1.0\n"
        "TERMINAL t1 CONDUCTOR A LAYER met1 KIND PIN LL 0.0 0.0 UR 0.2 0.5\n",
        body + '\n')


@allure.parent_suite("Unit Tests")
@allure.tag("PEX25D", "Validator")
class Pex25DValidatorTest(unittest.TestCase):
    def test_the_fixture_is_clean(self):
        assert check(MINIMAL) == []
        assert check(MINIMAL, strict=True) == []

    def test_a_resolved_scene_is_clean(self):
        assert check_scene(resolve(read(MINIMAL)), strict=True) == []

    def test_validating_never_raises(self):
        # Whatever is wrong with a message, the diagnostics are the answer.
        broken = read(MINIMAL)
        broken.ClearField('ground_plane')
        broken.ClearField('units')
        del broken.metals[:]
        assert check_scene(broken) or True   # the point is that it returned

    # ------------------------------------------------------- semantic checks

    def test_e0260_a_simple_dielectric_wrapping_an_inner_link(self):
        # Wrapping an inner link gives the fill the same depth as a film it
        # contains, and at equal depth there is no rule to break the tie.
        assert 'PEX25D-E0260' in check(
            replacing('DIELECTRIC_SIMPLE ild WRAPS lint', 'DIELECTRIC_SIMPLE ild WRAPS met1'))

    def test_e0261_two_films_at_the_same_depth_on_one_root(self):
        assert 'PEX25D-E0261' in check(
            replacing('DIELECTRIC_SIMPLE ild WRAPS lint PERMITTIVITY 4.1 BETWEEN met1 met2',
                      'DIELECTRIC_CONFORMAL other WRAPS met1 PERMITTIVITY 4.1 '
                      'THICKNESS_OVER_WRAPPED 0.1 THICKNESS_BESIDE_WRAPPED 0.08 '
                      'THICKNESS_ON_FIELD 0.0'))

    def test_e0262_a_grid_that_does_not_divide_the_source_dbu(self):
        assert 'PEX25D-E0262' in check(
            replacing('META source_cell tiny',
                      'META source_cell tiny\nMETA source_dbu 0.00015'))

    def test_a_grid_that_does_divide_the_source_dbu(self):
        assert check(replacing('META source_cell tiny',
                               'META source_cell tiny\nMETA source_dbu 0.001')) == []

    def test_e0263_a_terminal_on_a_floating_conductor(self):
        assert 'PEX25D-E0263' in check(replacing('CONDUCTOR A neta', 'CONDUCTOR A FLOATING'))

    def test_w0264_a_conductor_with_no_geometry(self):
        report = DiagnosticsReport()
        message = read(replacing('CONDUCTOR B netb', 'CONDUCTOR B netb\nCONDUCTOR C netc'),
                       report=report)
        validate(message, report=report)
        assert codes(report) == ['PEX25D-W0264']
        assert report.diagnostics[0].severity == Severity.WARNING

    def test_w0265_geometry_without_a_resistance_when_others_have_one(self):
        assert 'PEX25D-W0265' in check(replacing('RESISTANCE METAL met1 SHEET 0.125\n', ''))

    def test_no_w0265_when_the_file_states_no_resistance_at_all(self):
        # A pure capacitance file is exactly what it was before RESISTANCE
        # existed, and must not start warning.
        text = MINIMAL
        for line in ('RESISTANCE TEMPERATURE 25.0\n',
                     'RESISTANCE METAL met1 SHEET 0.125\n',
                     'RESISTANCE METAL met2 SHEET 0.125\n',
                     'RESISTANCE VIA via1 PER_CUT 4.5\n'):
            text = text.replace(line, '')
        assert check(text) == []

    def test_e0266_a_conductor_declared_twice(self):
        assert 'PEX25D-E0266' in check(
            replacing('CONDUCTOR B netb', 'CONDUCTOR B netb\nCONDUCTOR A netc'))

    def test_e0267_a_terminal_declared_twice(self):
        assert 'PEX25D-E0267' in check(
            replacing('TERMINAL t1 CONDUCTOR A LAYER met1 KIND PIN LL 0.0 0.0 UR 0.2 0.5',
                      'TERMINAL t1 CONDUCTOR A LAYER met1 KIND PIN LL 0.0 0.0 UR 0.2 0.5\n'
                      'TERMINAL t1 CONDUCTOR A LAYER met2 KIND PIN LL 0.0 0.0 UR 0.2 0.5'))

    def test_e0268_two_resistance_records_for_one_profile(self):
        assert 'PEX25D-E0268' in check(
            replacing('RESISTANCE METAL met2 SHEET 0.125',
                      'RESISTANCE METAL met2 SHEET 0.125\nRESISTANCE METAL met2 SHEET 0.2'))

    def test_w0269_coefficients_with_no_reference_temperature(self):
        assert 'PEX25D-W0269' in check(
            replacing('RESISTANCE TEMPERATURE 25.0\n', '').replace(
                'RESISTANCE METAL met1 SHEET 0.125',
                'RESISTANCE METAL met1 SHEET 0.125 TC1 0.003 TC2 0.0'))

    # ---------------------------------------------------------- scene checks

    def test_e0270_a_layer_with_no_kind(self):
        scene = resolve(read(MINIMAL))
        scene.layers[0].ClearField('kind')
        assert 'PEX25D-E0270' in check_scene(scene)

    def test_e0271_a_metal_with_no_height(self):
        scene = resolve(read(MINIMAL))
        scene.layers[0].zhigh = scene.layers[0].zlow
        assert 'PEX25D-E0271' in check_scene(scene)

    def test_a_via_between_abutting_layers_is_not_an_error(self):
        scene = resolve(read(MINIMAL))
        via = next(l for l in scene.layers if l.name == 'via1')
        via.zhigh = via.zlow
        assert 'PEX25D-E0271' not in check_scene(scene)

    def test_e0272_a_via_without_its_resolved_endpoints(self):
        scene = resolve(read(MINIMAL))
        next(l for l in scene.layers if l.name == 'via1').ClearField('connects_above')
        assert 'PEX25D-E0272' in check_scene(scene)

    def test_e0273_a_metal_carrying_a_via_resistance(self):
        scene = resolve(read(MINIMAL))
        met1 = next(l for l in scene.layers if l.name == 'met1')
        met1.ClearField('metal_resistance')
        met1.via_resistance.per_cut = 1.0
        assert 'PEX25D-E0273' in check_scene(scene)

    def test_e0274_dielectrics_out_of_depth_order(self):
        scene = resolve(read(MINIMAL))
        reordered = list(scene.dielectrics)[::-1]
        del scene.dielectrics[:]
        for dielectric in reordered:
            scene.dielectrics.add().CopyFrom(dielectric)
        assert 'PEX25D-E0274' in check_scene(scene)

    def test_e0275_a_dielectric_naming_a_profile_the_scene_has_not_got(self):
        scene = resolve(read(MINIMAL))
        scene.dielectrics[0].wraps = 'nowhere'
        assert 'PEX25D-E0275' in check_scene(scene)

    def test_e0276_a_terminal_on_a_layer_the_conductor_does_not_use(self):
        scene = resolve(read(MINIMAL))
        scene.conductors[0].terminals[0].layer = 'met2'
        assert 'PEX25D-E0276' not in check_scene(scene)  # A does have met2
        scene.conductors[0].terminals[0].layer = 'nowhere'
        assert 'PEX25D-E0276' in check_scene(scene)

    def test_e0277_an_empty_terminal_node(self):
        scene = resolve(read(MINIMAL))
        del scene.conductors[0].terminals[0].boxes[:]
        assert 'PEX25D-E0277' in check_scene(scene)

    def test_e0279_geometry_on_a_layer_the_scene_has_not_got(self):
        scene = resolve(read(MINIMAL))
        scene.conductors[0].regions[0].layer = 'nowhere'
        assert 'PEX25D-E0279' in check_scene(scene)

    # ------------------------------------------------------- geometric tier

    def test_the_geometric_tier_only_runs_under_strict(self):
        overlapping = geometry(
            'CONDUCTOR A neta',
            'CONDUCTOR B netb',
            'BOX CONDUCTOR A LAYER met1 LL 0.0 0.0 UR 1.0 1.0',
            'BOX CONDUCTOR B LAYER met1 LL 0.5 0.5 UR 1.5 1.5')
        assert 'PEX25D-E0309' not in check(overlapping)
        assert 'PEX25D-E0309' in check(overlapping, strict=True)

    def test_e0302_a_ring_closed_explicitly(self):
        assert 'PEX25D-E0302' in check(geometry(
            'CONDUCTOR A neta',
            'POLYGON CONDUCTOR A LAYER met1 OUTER 0.0 0.0 1.0 0.0 1.0 1.0 0.0 0.0'),
            strict=True)

    def test_e0303_a_repeated_vertex(self):
        assert 'PEX25D-E0303' in check(geometry(
            'CONDUCTOR A neta',
            'POLYGON CONDUCTOR A LAYER met1 OUTER 0.0 0.0 1.0 0.0 1.0 0.0 1.0 1.0'),
            strict=True)

    def test_e0304_a_collinear_ring(self):
        assert 'PEX25D-E0304' in check(geometry(
            'CONDUCTOR A neta',
            'POLYGON CONDUCTOR A LAYER met1 OUTER 0.0 0.0 1.0 0.0 3.0 0.0 2.0 0.0'),
            strict=True)

    def test_e0305_a_self_intersecting_ring(self):
        assert 'PEX25D-E0305' in check(geometry(
            'CONDUCTOR A neta',
            'POLYGON CONDUCTOR A LAYER met1 OUTER 0.0 0.0 4.0 4.0 4.0 0.0 0.0 3.0'),
            strict=True)

    def test_e0306_a_hole_touching_its_outer_ring(self):
        assert 'PEX25D-E0306' in check(geometry(
            'CONDUCTOR A neta',
            'POLYGON CONDUCTOR A LAYER met1 OUTER 0.0 0.0 4.0 0.0 4.0 4.0 0.0 4.0 \\',
            '    HOLE 0.0 1.0 2.0 1.0 2.0 2.0 0.0 2.0'),
            strict=True)

    def test_e0307_holes_that_touch(self):
        assert 'PEX25D-E0307' in check(geometry(
            'CONDUCTOR A neta',
            'POLYGON CONDUCTOR A LAYER met1 OUTER 0.0 0.0 8.0 0.0 8.0 8.0 0.0 8.0 \\',
            '    HOLE 1.0 1.0 3.0 1.0 3.0 3.0 1.0 3.0 \\',
            '    HOLE 3.0 1.0 5.0 1.0 5.0 3.0 3.0 3.0'),
            strict=True)

    def test_a_polygon_with_two_separate_holes_is_fine(self):
        assert check(geometry(
            'CONDUCTOR A neta',
            'POLYGON CONDUCTOR A LAYER met1 OUTER 0.0 0.0 8.0 0.0 8.0 8.0 0.0 8.0 \\',
            '    HOLE 1.0 1.0 3.0 1.0 3.0 3.0 1.0 3.0 \\',
            '    HOLE 4.0 1.0 6.0 1.0 6.0 3.0 4.0 3.0'),
            strict=True) == []

    def test_e0308_an_empty_box(self):
        assert 'PEX25D-E0308' in check(geometry(
            'CONDUCTOR A neta',
            'BOX CONDUCTOR A LAYER met1 LL 1.0 1.0 UR 1.0 2.0'),
            strict=True)

    # ---------------------------------------------------- conductor overlap

    def overlap(self, *records: str) -> List[str]:
        return check(geometry(*records), strict=True)

    def test_two_conductors_may_abut(self):
        assert self.overlap(
            'CONDUCTOR A neta',
            'CONDUCTOR B netb',
            'BOX CONDUCTOR A LAYER met1 LL 0.0 0.0 UR 2.0 2.0',
            'BOX CONDUCTOR B LAYER met1 LL 2.0 0.0 UR 4.0 2.0') == []

    def test_one_conductor_may_overlap_itself(self):
        assert self.overlap(
            'CONDUCTOR A neta',
            'BOX CONDUCTOR A LAYER met1 LL 0.0 0.0 UR 2.0 2.0',
            'BOX CONDUCTOR A LAYER met1 LL 1.0 1.0 UR 3.0 3.0') == []

    def test_layers_whose_z_extents_only_touch_do_not_overlap(self):
        # met1 and the via above it share a face by construction.
        assert self.overlap(
            'CONDUCTOR A neta',
            'CONDUCTOR B netb',
            'BOX CONDUCTOR A LAYER met1 LL 0.0 0.0 UR 2.0 2.0',
            'BOX CONDUCTOR B LAYER via1 LL 0.0 0.0 UR 2.0 2.0') == []

    def test_e0309_boxes(self):
        assert 'PEX25D-E0309' in self.overlap(
            'CONDUCTOR A neta',
            'CONDUCTOR B netb',
            'BOX CONDUCTOR A LAYER met1 LL 0.0 0.0 UR 2.0 2.0',
            'BOX CONDUCTOR B LAYER met1 LL 1.0 1.0 UR 3.0 3.0')

    def test_e0309_identical_polygons(self):
        # Nothing on either boundary is strictly inside the other, which is why
        # sampling vertices and midpoints cannot answer this one.
        assert 'PEX25D-E0309' in self.overlap(
            'CONDUCTOR A neta',
            'CONDUCTOR B netb',
            'POLYGON CONDUCTOR A LAYER met1 OUTER 0.0 0.0 2.0 0.0 2.0 2.0 0.0 2.0',
            'POLYGON CONDUCTOR B LAYER met1 OUTER 0.0 0.0 2.0 0.0 2.0 2.0 0.0 2.0')

    def test_e0309_a_shape_reaching_out_of_a_hole(self):
        assert 'PEX25D-E0309' in self.overlap(
            'CONDUCTOR A neta',
            'CONDUCTOR B netb',
            'POLYGON CONDUCTOR A LAYER met1 OUTER 0.0 0.0 8.0 0.0 8.0 8.0 0.0 8.0 \\',
            '    HOLE 2.0 2.0 6.0 2.0 6.0 6.0 2.0 6.0',
            'BOX CONDUCTOR B LAYER met1 LL 1.0 3.0 UR 5.0 5.0')

    def test_a_conductor_may_sit_inside_another_ones_hole(self):
        assert self.overlap(
            'CONDUCTOR A neta',
            'CONDUCTOR B netb',
            'POLYGON CONDUCTOR A LAYER met1 OUTER 0.0 0.0 8.0 0.0 8.0 8.0 0.0 8.0 \\',
            '    HOLE 2.0 2.0 6.0 2.0 6.0 6.0 2.0 6.0',
            'BOX CONDUCTOR B LAYER met1 LL 3.0 3.0 UR 5.0 5.0') == []

    def test_a_box_in_the_notch_of_an_l_shape(self):
        assert self.overlap(
            'CONDUCTOR A neta',
            'CONDUCTOR B netb',
            'POLYGON CONDUCTOR A LAYER met1 '
            'OUTER 0.0 0.0 4.0 0.0 4.0 1.0 1.0 1.0 1.0 4.0 0.0 4.0',
            'BOX CONDUCTOR B LAYER met1 LL 1.0 1.0 UR 4.0 4.0') == []
