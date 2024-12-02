import os
import tempfile
import unittest

import klayout.db as kdb

from kpex.log import (
    LogLevel,
    set_log_level,
)
from kpex.klayout.netlist_reducer import NetlistReducer


class Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        set_log_level(LogLevel.DEBUG)

    @property
    def klayout_testdata_dir(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'testdata', 'klayout', 'netlists'))

    def _test_netlist_reduction(self, netlist_path: str, cell_name: str):
        netlist = kdb.Netlist()
        reader = kdb.NetlistSpiceReader()
        netlist.read(netlist_path, reader)

        reducer = NetlistReducer()
        reduced_netlist = reducer.reduce(netlist=netlist, top_cell_name=cell_name)

        out_path = tempfile.mktemp(prefix=f"{cell_name}_Reduced_Netlist_", suffix=".cir")
        spice_writer = kdb.NetlistSpiceWriter()
        reduced_netlist.write(out_path, spice_writer)
        print(f"Wrote reduced netlist to: {out_path}")

    def test_netlist_reduction_1(self):
        netlist_path = os.path.join(self.klayout_testdata_dir, 'nmos_diode2_Expanded_Netlist.cir')
        self._test_netlist_reduction(netlist_path=netlist_path, cell_name='nmos_diode2')

    def test_netlist_reduction_2(self):
        netlist_path = os.path.join(self.klayout_testdata_dir, 'cap_vpp_Expanded_Netlist.cir')
        self._test_netlist_reduction(netlist_path=netlist_path, cell_name='TOP')
