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
import io
import os
import tempfile
import unittest
from unittest import mock

from klayout_pex.fastercap.fastercap_error import FasterCapError
from klayout_pex.fastercap.fastercap_runner import fastercap_parse_capacitance_matrix, run_fastercap


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

        tmp_dir = tempfile.mkdtemp(prefix="fastercap_matrix_")
        output_path = os.path.join(tmp_dir, 'nmos_diode2_FasterCap_Result_Matrix.csv')
        obtained_matrix.write_csv(output_path=output_path, separator=';')
        allure.attach.file(output_path, attachment_type=allure.attachment_type.CSV)

    def test_failed_run_is_an_error_named_by_its_exit_code(self):
        # NOTE: FasterCap 6.2 exits 75 when GMRES doesn't converge, though it prints the matrix of the last iteration,
        #       earlier versions exited 0 then
        for exit_code, expected_message in (
            (75, "FasterCap failed with exit code 75 (GMRES didn't converge) after"),
            (3, "FasterCap failed with exit code 3 after"),
        ):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as tmp_dir:
                process = mock.Mock(returncode=exit_code, stdout=io.StringIO("Capacitance matrix is:\n"))
                with mock.patch('klayout_pex.fastercap.fastercap_runner.subprocess.Popen', return_value=process), \
                     self.assertRaises(FasterCapError) as cm:
                    run_fastercap(exe_path='FasterCap', lst_file_path='plate.lst',
                                  log_path=os.path.join(tmp_dir, 'FasterCap_Output.txt'),
                                  tolerance=0.01, d_coeff=0.5, mesh_refinement_value=0.5, ooc_condition=None,
                                  auto_preconditioner=False, galerkin_scheme=False, jacobi_preconditioner=False)
                self.assertIn(expected_message, str(cm.exception))
