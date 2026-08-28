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
import os
import tempfile
import unittest

from klayout_pex.pex25d.diagnostics import DiagnosticsReport, Severity
from klayout_pex.pex25d.reader import ReadError, read_pex25d_text

from .pex25d_fixtures import (
    HEADER, MINIMAL, STACK_ONLY, codes, read, read_codes, replacing,
)


@allure.parent_suite("Unit Tests")
@allure.tag("PEX25D", "Reader")
class Pex25DReaderTest(unittest.TestCase):
    # ------------------------------------------------------------- happy path

    def test_reads_the_fixture_without_diagnostics(self):
        report = DiagnosticsReport()
        pex25d_file = read(MINIMAL, report=report)
        assert codes(report) == []
        assert pex25d_file.format_version_major == 1
        assert pex25d_file.format_version_minor == 0
        assert pex25d_file.format_version_suffix == 'rc1'
        assert [m.name for m in pex25d_file.metals] == ['met1', 'met2']
        assert [v.name for v in pex25d_file.vias] == ['via1']
        assert [d.name for d in pex25d_file.dielectrics] == ['fox', 'lint', 'ild']
        assert [c.name for c in pex25d_file.conductors] == ['A', 'B']
        assert len(pex25d_file.shapes) == 4
        assert len(pex25d_file.terminals) == 1

    def test_lengths_become_exact_grid_integers(self):
        pex25d_file = read(MINIMAL)
        met1 = pex25d_file.metals[0]
        assert (met1.zlow, met1.zhigh) == (10000, 14000)
        assert pex25d_file.ground_plane.zlow == -4000
        box = pex25d_file.shapes[0].box
        assert (box.lower_left.x, box.upper_right.x) == (0, 10000)

    def test_a_polygon_ring_is_not_closed_explicitly(self):
        polygon = read(MINIMAL).shapes[3].polygon
        assert len(polygon.outer.points) == 4
        assert (polygon.outer.points[0].x, polygon.outer.points[0].y) != \
               (polygon.outer.points[-1].x, polygon.outer.points[-1].y)

    def test_a_value_a_modulo_check_would_reject(self):
        # 0.3262 % 0.0001 is 9.9999999999e-05 in binary floating point, so an
        # exact-modulo grid check rejects a legal file. Divide-round-compare
        # does not, and this is the value that first showed it.
        pex25d_file = read(replacing('METAL met1 Z_OFFSETS 1.0 1.4',
                                     'METAL met1 Z_OFFSETS 0.3262 1.4'))
        assert pex25d_file.metals[0].zlow == 3262

    def test_source_refs_are_off_unless_asked_for(self):
        assert not read(MINIMAL).metals[0].HasField('source')
        with_refs = read(MINIMAL, with_source_refs=True)
        assert with_refs.metals[0].source.line > 0

    # ----------------------------------------------------------- syntax tier

    def test_e0101_record_ends_early(self):
        assert 'PEX25D-E0101' in read_codes(
            replacing('METAL met1 Z_OFFSETS 1.0 1.4', 'METAL met1 Z_OFFSETS 1.0'))

    def test_e0102_wrong_clause_keyword(self):
        assert 'PEX25D-E0102' in read_codes(
            replacing('VIA via1 CONNECTS met1 met2', 'VIA via1 BETWEEN met1 met2'))

    def test_e0103_a_dropped_continuation(self):
        # A clause keyword where a record should start is almost always a lost
        # trailing backslash, and skipping it would build a different scene.
        assert 'PEX25D-E0103' in read_codes(
            replacing(' THICKNESS_OVER_WRAPPED 0.1 \\\n    THICKNESS_BESIDE_WRAPPED',
                      ' THICKNESS_OVER_WRAPPED 0.1\n    THICKNESS_BESIDE_WRAPPED'))

    def test_e0103_trailing_tokens(self):
        assert 'PEX25D-E0103' in read_codes(
            replacing('METAL met2 Z_OFFSETS 2.0 2.4',
                      'METAL met2 Z_OFFSETS 2.0 2.4 2.8'))

    def test_e0104_bad_literal(self):
        assert 'PEX25D-E0104' in read_codes(
            replacing('METAL met1 Z_OFFSETS 1.0 1.4', 'METAL met1 Z_OFFSETS one 1.4'))

    def test_e0104_rejects_number_forms_python_would_accept(self):
        # Fraction('1/2') and int('1_0') both parse; neither is PEX25D.
        for literal in ('1/2', '1_0', 'nan', 'inf'):
            with self.subTest(literal=literal):
                assert 'PEX25D-E0104' in read_codes(
                    replacing('METAL met1 Z_OFFSETS 1.0 1.4',
                              f'METAL met1 Z_OFFSETS {literal} 1.4'))

    def test_e0105_off_grid(self):
        assert 'PEX25D-E0105' in read_codes(
            replacing('METAL met1 Z_OFFSETS 1.0 1.4',
                      'METAL met1 Z_OFFSETS 1.00005 1.4'))

    def test_e0106_a_length_before_units(self):
        text = ("PEX25D 1.0-rc1\n"
                "GROUND_PLANE subs Z_OFFSETS -0.4 -0.1\n"
                "UNITS LENGTH um GRID 0.0001\n")
        assert 'PEX25D-E0106' in read_codes(text)

    def test_e0107_wrong_header(self):
        assert 'PEX25D-E0107' in read_codes(
            replacing('PEX25D 1.0-rc1', 'C25D 1.0-rc1', MINIMAL))

    def test_e0107_unsupported_major_version(self):
        assert 'PEX25D-E0107' in read_codes(
            replacing('PEX25D 1.0-rc1', 'PEX25D 2.0', MINIMAL))

    def test_an_unknown_suffix_is_accepted(self):
        # The suffix takes no part in compatibility and must never be a reason
        # to reject a file.
        assert read_codes(replacing('PEX25D 1.0-rc1', 'PEX25D 1.0-beta7')) == []

    def test_e0108_duplicate_meta_key(self):
        assert 'PEX25D-E0108' in read_codes(
            replacing('META source_cell tiny',
                      'META source_cell tiny\nMETA technology testpdk'))

    def test_w0110_unknown_record_is_a_warning_and_is_skipped(self):
        report = DiagnosticsReport()
        pex25d_file = read(replacing('CONDUCTOR A neta',
                                     'FUTURE_RECORD whatever 1 2 3\nCONDUCTOR A neta'),
                           report=report)
        assert codes(report) == ['PEX25D-W0110']
        assert report.diagnostics[0].severity == Severity.WARNING
        assert [c.name for c in pex25d_file.conductors] == ['A', 'B']

    def test_read_error_is_raised_once_errors_exist(self):
        with self.assertRaises(ReadError):
            read(replacing('METAL met1 Z_OFFSETS 1.0 1.4', 'METAL met1 Z_OFFSETS'))

    # ---------------------------------------------------------------- include

    def test_include_flattens_and_records_the_source_file(self):
        with tempfile.TemporaryDirectory() as directory:
            stack_path = os.path.join(directory, 'stack.pex25d')
            top_path = os.path.join(directory, 'top.pex25d')
            with open(stack_path, 'w') as f:
                f.write('METAL met3 Z_OFFSETS 3.0 3.4\n')
            with open(top_path, 'w') as f:
                f.write(f'{STACK_ONLY}\nINCLUDE stack.pex25d\n')

            with open(top_path, 'rb') as f:
                pex25d_file = read_pex25d_text(f.read(), top_path,
                                               with_source_refs=True)
            assert [m.name for m in pex25d_file.metals] == ['met1', 'met2', 'met3']
            assert pex25d_file.metals[2].source.file.endswith('stack.pex25d')

    def test_e0109_include_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'loop.pex25d')
            with open(path, 'w') as f:
                f.write(f'{HEADER}\nINCLUDE loop.pex25d\n')
            report = DiagnosticsReport()
            with open(path, 'rb') as f:
                data = f.read()
            try:
                read_pex25d_text(data, path, report=report)
            except ReadError:
                pass
            # The top-level file is on the include stack from the start, so the
            # cycle is caught on the first repeat rather than one level late.
            assert codes(report) == ['PEX25D-E0109']

    def test_e0109_unreadable_include(self):
        assert 'PEX25D-E0109' in read_codes(
            f'{STACK_ONLY}\nINCLUDE ./there-is-no-such-file.pex25d\n')
