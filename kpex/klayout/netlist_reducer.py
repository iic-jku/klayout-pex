import os
import tempfile
from typing import *
import unittest

import klayout.db as kdb

from ..log import (
    LogLevel,
    set_log_level,
    info,
)


class NetlistReducer:
    @staticmethod
    def reduce(netlist: kdb.Netlist,
               top_cell_name: str,
               cap_threshold: float = 0.05e-15) -> kdb.Netlist:
        reduced_netlist: kdb.Netlist = netlist.dup()
        reduced_netlist.combine_devices()  # merge C/R

        top_circuit: kdb.Circuit = reduced_netlist.circuit_by_name(top_cell_name)

        devices_to_remove: List[kdb.Device] = []

        for d in top_circuit.each_device():
            d: kdb.Device
            dc = d.device_class()
            if isinstance(dc, kdb.DeviceClassCapacitor):
                # net_a = d.net_for_terminal('A')
                # net_b = d.net_for_terminal('B')
                c_value = d.parameter('C')
                if c_value < cap_threshold:
                    devices_to_remove.append(d)

            elif isinstance(dc, kdb.DeviceClassResistor):
                # TODO
                pass

        for d in devices_to_remove:
            info(f"Removed device {d.name} {d.parameter('C')}")
            top_circuit.remove_device(d)

        return reduced_netlist


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
