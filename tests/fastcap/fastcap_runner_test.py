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
import allure
import os
import unittest

from klayout_pex.fastcap.fastcap_runner import fastcap_parse_capacitance_matrix


@allure.parent_suite("Unit Tests")
@allure.tag("Capacitance", "FastCap")
class Test(unittest.TestCase):
    @property
    def fastcap_testdata_dir(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata', 'fastcap'))

    def test_fastcap_parse_capacitance_matrix(self):
        testdata_path = os.path.join(self.fastcap_testdata_dir, 'cap_mim_m3_w18p9_l5p1__REDUX122_FastCap_Output.txt')
        obtained_matrix = fastcap_parse_capacitance_matrix(log_path=testdata_path)
        self.assertEqual(4, len(obtained_matrix.rows))
        self.assertEqual(4, len(obtained_matrix.rows[0]))
        self.assertEqual(4, len(obtained_matrix.rows[1]))
        self.assertEqual(4, len(obtained_matrix.rows[2]))
        self.assertEqual(4, len(obtained_matrix.rows[3]))
        self.assertEqual(
            ['$1%GROUP2', '$1%GROUP2', '$2%GROUP3', '$2%GROUP3'],
            obtained_matrix.conductor_names
        )

        output_path = os.path.join(self.fastcap_testdata_dir, 'cap_mim_m3_w18p9_l5p1__REDUX122_FastCap_Result_Matrix.csv')
        obtained_matrix.write_csv(output_path=output_path, separator=';')
        allure.attach.file(output_path, attachment_type=allure.attachment_type.CSV)
