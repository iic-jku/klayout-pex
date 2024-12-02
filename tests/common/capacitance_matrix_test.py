from __future__ import annotations

import allure
import os
import tempfile
from typing import *
import unittest

from kpex.common.capacitance_matrix import CapacitanceMatrix


@allure.parent_suite("Unit Tests")
@allure.tag("Capacitance", "FasterCap")
class Test(unittest.TestCase):
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
        out_path = tempfile.mktemp(prefix='fastercap_matrix_raw__', suffix='.csv')
        parsed_matrix.write_csv(output_path=out_path, separator=';')
        parsed_matrix2 = CapacitanceMatrix.parse_csv(path=out_path, separator=';')
        self.assertEqual(parsed_matrix, parsed_matrix2)

    def test_averaged_off_diagonals(self):
        csv_path = os.path.join(self.klayout_testdata_dir, 'nmos_diode2_FasterCap_Result_Matrix.csv')
        parsed_matrix = CapacitanceMatrix.parse_csv(path=csv_path, separator=';')
        avg_matrix = parsed_matrix.averaged_off_diagonals()
        out_path = tempfile.mktemp(prefix='fastercap_matrix_avg__', suffix='.csv')
        avg_matrix.write_csv(output_path=out_path, separator=';')
        allure.attach.file(out_path, attachment_type=allure.attachment_type.CSV)
        print(f"averaged matrix stored in {out_path}")