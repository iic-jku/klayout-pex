import os
import unittest

from kpex.fastercap.fastercap_runner import fastercap_parse_capacitance_matrix


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
