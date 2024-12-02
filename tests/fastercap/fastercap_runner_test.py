#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/martinjankoehler/klayout-pex).
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
import allure
import os
import unittest

from kpex.fastercap.fastercap_runner import fastercap_parse_capacitance_matrix


@allure.parent_suite("Unit Tests")
@allure.tag("Capacitance", "FasterCap")
class Test(unittest.TestCase):
    @property
    def fastercap_testdata_dir(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata', 'fastercap'))

    def test_fastercap_parse_capacitance_matrix(self):
        testdata_path = os.path.join(self.fastercap_testdata_dir, 'nmos_diode2_FasterCap_Output.txt')
        obtained_matrix = fastercap_parse_capacitance_matrix(log_path=testdata_path)
        self.assertEqual(3, len(obtained_matrix.rows))
        self.assertEqual(3, len(obtained_matrix.rows[0]))
        self.assertEqual(3, len(obtained_matrix.rows[1]))
        self.assertEqual(3, len(obtained_matrix.rows[2]))
        self.assertEqual(
            ['g1_VSUBS', 'g1_VDD', 'g1_VSS'],
            obtained_matrix.conductor_names
        )

        output_path = os.path.join(self.fastercap_testdata_dir, 'nmos_diode2_FasterCap_Result_Matrix.csv')
        obtained_matrix.write_csv(output_path=output_path, separator=';')
        allure.attach.file(output_path, attachment_type=allure.attachment_type.CSV)
