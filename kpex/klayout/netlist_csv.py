from __future__ import annotations

import klayout.db as kdb

from kpex.log import (
    info,
)


class NetlistCSVWriter:
    @staticmethod
    def write_csv(netlist: kdb.Netlist,
                  top_cell_name: str,
                  output_path: str):
        with open(output_path, 'w') as f:
            f.write('Device;Net1;Net2;Capacitance [F];Capacitance [fF]\n')

            top_circuit: kdb.Circuit = netlist.circuit_by_name(top_cell_name)

            # NOTE: only caps for now
            for d in top_circuit.each_device():
                # https://www.klayout.de/doc-qt5/code/class_Device.html
                dc = d.device_class()
                if isinstance(dc, kdb.DeviceClassCapacitor):
                    dn = d.expanded_name() or d.name
                    if dc.name != 'PEX_CAP':
                        info(f"Ignoring device {dn}")
                        continue
                    param_defs = dc.parameter_definitions()
                    params = {p.name: d.parameter(p.id()) for p in param_defs}
                    d: kdb.Device
                    net1 = d.net_for_terminal('A')
                    net2 = d.net_for_terminal('B')
                    cap = params['C']
                    cap_femto = round(cap * 1e15, 2)
                    f.write(f"{dn};{net1.name};{net2.name};{'%.12g' % cap};{cap_femto}f\n")
