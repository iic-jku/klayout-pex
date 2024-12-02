from typing import *

import klayout.db as kdb

from ..log import (
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
