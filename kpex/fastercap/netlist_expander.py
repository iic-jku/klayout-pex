from __future__ import annotations

import os
import re
import tempfile
from typing import *
import unittest

import klayout.db as kdb

from kpex.klayout.lvsdb_extractor import KLayoutExtractionContext
from kpex.log import (
    debug,
    # info,
    warning,
    # error
)
from .capacitance_matrix import CapacitanceMatrix, CapacitanceMatrixInfo


class NetlistExpander:
    @staticmethod
    def expand(pex_context: KLayoutExtractionContext,
               cap_matrix: CapacitanceMatrix,
               cap_matrix_info: CapacitanceMatrixInfo) -> kdb.Netlist:
        expanded_netlist: kdb.Netlist = pex_context.lvsdb.netlist().dup()
        cell_name = pex_context.top_cell.name
        top_circuit: kdb.Circuit = expanded_netlist.circuit_by_name(cell_name)

        # create capacitor class
        cap = kdb.DeviceClassCapacitor()
        cap.name = 'PEX_CAP'
        cap.description = "Extracted by FasterCap PEX"
        expanded_netlist.add(cap)

        # NOTE: the diagonal Cii is the capacitance over GND
        # https://www.fastfieldsolvers.com/Papers/The_Maxwell_Capacitance_Matrix_WP110301_R03.pdf
        if cap_matrix_info.dimension != cap_matrix.dimension:
            raise Exception(f"Mismatch: Cap Matrix Info YAML specifies dimension {cap_matrix_info.dimension}, "
                            f"but Cap Matrix CSV has dimension {cap_matrix.dimension}")

        nets: List[kdb.Net] = [
            top_circuit.create_net('0')  # create GROUND net
        ]

        # build table: name -> net
        name2net: Dict[str, kdb.Net] = {n.expanded_name(): n for n in top_circuit.each_net()}

        # find nets for the matrix axes
        pattern = re.compile(r'^g\d+_(.*)$')
        for idx, nn in enumerate(cap_matrix.conductor_names):
            m = pattern.match(nn)
            idx = int(m.group(1))
            c = cap_matrix_info.conductor_by_index(idx)
            if c.net not in name2net:
                raise Exception(f"No net found with name {c.net}, net names are: {list(name2net.keys())}")
            n = name2net[c.net]
            nets.append(n)

        cap_threshold = 0.05e-15

        def add_parasitic_cap(i: int,
                              j: int,
                              net1: kdb.Net,
                              net2: kdb.Net,
                              cap_value: float):
            if cap_value >= cap_threshold:
                c: kdb.Device = top_circuit.create_device(cap, f"Cext_{i}_{j}")
                c.connect_terminal('A', net1)
                c.connect_terminal('B', net2)
                c.set_parameter('C', cap_value)
            else:
                warning(f"Ignoring capacitance matrix cell [{i},{j}], "
                        f"{'%.12g' % cap_value} is below threshold {'%.12g' % cap_threshold}")

        for j in range(1, cap_matrix.dimension):
            cap_ii = 0.0
            for i in range(1, cap_matrix.dimension):
                if i == j:
                    cap_ii += cap_matrix[i][j]
                elif i > j:
                    add_parasitic_cap(i=i, j=j,
                                      net1=nets[i], net2=nets[j],
                                      cap_value=-cap_matrix[i][j])
            add_parasitic_cap(i=j, j=j,
                              net1=nets[j], net2=nets[0],
                              cap_value=cap_ii)

        return expanded_netlist


class Test(unittest.TestCase):
    @property
    def klayout_testdata_dir(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'testdata', 'fastercap'))

    def test_netlist_expansion(self):
        exp = NetlistExpander()

        cell_name = 'nmos_diode2'

        lvsdb = kdb.LayoutVsSchematic()
        lvsdb_path = os.path.join(self.klayout_testdata_dir, f"{cell_name}.lvsdb.gz")
        lvsdb.read(lvsdb_path)

        csv_path = os.path.join(self.klayout_testdata_dir, f"{cell_name}_FasterCap_Result_Matrix.csv")
        cap_matrix_info_path = os.path.join(self.klayout_testdata_dir, f"{cell_name}_FasterCap_Matrix_Info.yaml")

        cap_matrix = CapacitanceMatrix.parse_csv(csv_path, separator=';')
        cap_matrix_info = CapacitanceMatrixInfo.from_yaml(cap_matrix_info_path)

        pex_context = KLayoutExtractionContext.prepare_extraction(top_cell=cell_name, lvsdb=lvsdb)
        expanded_netlist = exp.expand(pex_context=pex_context,
                                      cap_matrix=cap_matrix,
                                      cap_matrix_info=cap_matrix_info)
        out_path = tempfile.mktemp(prefix=f"{cell_name}_expanded_netlist_", suffix=".cir")
        spice_writer = kdb.NetlistSpiceWriter()
        expanded_netlist.write(out_path, spice_writer)
        debug(f"Wrote expanded netlist to: {out_path}")