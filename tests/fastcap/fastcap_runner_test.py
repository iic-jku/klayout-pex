from typing import *
import os
import unittest

from kpex.fastcap.fastcap_runner import fastcap_parse_capacitance_matrix

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
