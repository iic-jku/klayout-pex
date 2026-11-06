#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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
from pathlib import Path
import tempfile
from typing import *
import unittest

from klayout_pex.common.capacitance_matrix import CapacitanceMatrix


@allure.parent_suite("Unit Tests")
@allure.tag("Capacitance", "FasterCap")
class Test(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output_path = Path(directory.name) / 'matrix.csv'

    @property
    def klayout_testdata_dir(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'testdata', 'fastercap'))
    
    def test_parse_csv(self):
        csv_path = os.path.join(self.klayout_testdata_dir, 'nmos_diode2_FasterCap_Result_Matrix.csv')
        parsed_matrix = CapacitanceMatrix.parse_csv(path=csv_path, separator=';')
        self.assertEqual(3, len(parsed_matrix.rows))
        self.assertEqual(3, len(parsed_matrix.rows[0]))
        self.assertEqual(3, len(parsed_matrix.rows[1]))
        self.assertEqual(3, len(parsed_matrix.rows[2]))
        self.assertEqual(
            ['g1_VSUBS', 'g1_VDD', 'g1_VSS'],
            parsed_matrix.conductor_names
        )

    def test_write_csv(self):
        csv_path = os.path.join(self.klayout_testdata_dir, 'nmos_diode2_FasterCap_Result_Matrix.csv')
        parsed_matrix = CapacitanceMatrix.parse_csv(path=csv_path, separator=';')
        out_path = str(self.output_path)
        parsed_matrix.write_csv(output_path=out_path, separator=';')
        parsed_matrix2 = CapacitanceMatrix.parse_csv(path=out_path, separator=';')
        self.assertEqual(parsed_matrix, parsed_matrix2)

    def test_averaged_off_diagonals(self):
        matrix = CapacitanceMatrix(
            conductor_names=['A', 'B', 'C'],
            rows=[[10.0, -2.0, -4.0], [-6.0, 20.0, -8.0], [-10.0, -12.0, 30.0]])

        averaged = matrix.averaged_off_diagonals()

        self.assertEqual(['A', 'B', 'C'], averaged.conductor_names)
        self.assertEqual([[10.0, -4.0, -7.0], [-4.0, 20.0, -10.0], [-7.0, -10.0, 30.0]],
                         averaged.rows)
        self.assertEqual([[10.0, -2.0, -4.0], [-6.0, 20.0, -8.0], [-10.0, -12.0, 30.0]],
                         matrix.rows)
        self.assertEqual(averaged, averaged.averaged_off_diagonals())

    def test_averaging_returns_independent_data(self):
        matrix = CapacitanceMatrix(['A', 'B'], [[2.0, -1.0], [-1.0, 3.0]])
        averaged = matrix.averaged_off_diagonals()
        averaged[0][0] = 99.0
        averaged[1] = [0.0, 0.0]
        averaged.conductor_names[0] = 'changed'
        self.assertEqual(CapacitanceMatrix(['A', 'B'], [[2.0, -1.0], [-1.0, 3.0]]), matrix)

    def test_averaging_empty_and_single_conductor_matrices(self):
        for matrix in (CapacitanceMatrix([], []), CapacitanceMatrix(['A'], [[1.25e-15]])):
            with self.subTest(matrix=matrix):
                self.assertEqual(matrix, matrix.averaged_off_diagonals())
                self.assertEqual(len(matrix.rows), matrix.dimension)

    def test_parse_csv_reads_values_with_whitespace_and_exponents(self):
        for separator in (';', ',', '\t'):
            with self.subTest(separator=separator):
                self.output_path.write_text(
                    f' A {separator} B \n 1.5e-15 {separator} -2E-16 \n'
                    f' -3e-16 {separator} 4.0e-15 \n', encoding='utf-8')
                matrix = CapacitanceMatrix.parse_csv(str(self.output_path), separator=separator)
                self.assertEqual(CapacitanceMatrix(['A', 'B'],
                                                 [[1.5e-15, -2e-16], [-3e-16, 4e-15]]), matrix)

    def test_parse_csv_requires_a_header_and_data(self):
        for contents in ('', 'A;B\n'):
            with self.subTest(contents=contents):
                self.output_path.write_text(contents, encoding='utf-8')
                with self.assertRaisesRegex(Exception, 'must at least have 2 lines'):
                    CapacitanceMatrix.parse_csv(str(self.output_path))

    def test_parse_csv_rejects_non_numeric_cells(self):
        self.output_path.write_text('A;B\n1.0;invalid\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            CapacitanceMatrix.parse_csv(str(self.output_path))

    def test_write_csv_uses_the_requested_separator_and_precision(self):
        matrix = CapacitanceMatrix(['A', 'B'], [[1.23456789012345, -2e-16], [-3e-16, 4e-15]])
        matrix.write_csv(str(self.output_path), separator=',')
        self.assertEqual('A,B\n1.23456789012,-2e-16\n-3e-16,4e-15\n',
                         self.output_path.read_text(encoding='utf-8'))
