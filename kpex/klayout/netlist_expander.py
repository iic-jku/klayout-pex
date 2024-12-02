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
    info,
    warning,
    # error
)
from kpex.common.capacitance_matrix import CapacitanceMatrix
from kpex.tech_info import TechInfo


class NetlistExpander:
    @staticmethod
    def expand(extracted_netlist: kdb.Netlist,
               top_cell_name: str,
               cap_matrix: CapacitanceMatrix,
               blackbox_devices: bool) -> kdb.Netlist:
        expanded_netlist: kdb.Netlist = extracted_netlist.dup()
        top_circuit: kdb.Circuit = expanded_netlist.circuit_by_name(top_cell_name)

        if not blackbox_devices:
            for d in top_circuit.each_device():
                name = d.name or d.expanded_name()
                info(f"Removing whiteboxed device {name}")
                top_circuit.remove_device(d)

        # create capacitor class
        cap = kdb.DeviceClassCapacitor()
        cap.name = 'PEX_CAP'
        cap.description = "Extracted by kpex/FasterCap PEX"
        expanded_netlist.add(cap)

        fc_gnd_net = top_circuit.create_net('FC_GND')  # create GROUND net
        vsubs_net = top_circuit.create_net("VSUBS")
        nets: List[kdb.Net] = []

        # build table: name -> net
        name2net: Dict[str, kdb.Net] = {n.expanded_name(): n for n in top_circuit.each_net()}

        # find nets for the matrix axes
        pattern = re.compile(r'^g\d+_(.*)$')
        for idx, nn in enumerate(cap_matrix.conductor_names):
            m = pattern.match(nn)
            nn = m.group(1)
            if nn not in name2net:
                raise Exception(f"No net found with name {nn}, net names are: {list(name2net.keys())}")
            n = name2net[nn]
            nets.append(n)

        cap_threshold = 0.0

        def add_parasitic_cap(i: int,
                              j: int,
                              net1: kdb.Net,
                              net2: kdb.Net,
                              cap_value: float):
            if cap_value > cap_threshold:
                c: kdb.Device = top_circuit.create_device(cap, f"Cext_{i}_{j}")
                c.connect_terminal('A', net1)
                c.connect_terminal('B', net2)
                c.set_parameter('C', cap_value)
                if net1 == net2:
                    raise Exception(f"Invalid attempt to create cap {c.name} between "
                                    f"same net {net1} with value {'%.12g' % cap_value}")
            else:
                warning(f"Ignoring capacitance matrix cell [{i},{j}], "
                        f"{'%.12g' % cap_value} is below threshold {'%.12g' % cap_threshold}")

        # -------------------------------------------------------------
        # Example capacitance matrix:
        #     [C11+C12+C13           -C12            -C13]
        #     [-C21           C21+C22+C23            -C23]
        #     [-C31                  -C32     C31+C32+C33]
        # -------------------------------------------------------------
        #
        # - Diagonal elements m[i][i] contain the capacitance over GND (Cii),
        #   but in a sum including all the other values of the row
        #
        # https://www.fastfieldsolvers.com/Papers/The_Maxwell_Capacitance_Matrix_WP110301_R03.pdf
        #
        for i in range(0, cap_matrix.dimension):
            row = cap_matrix[i]
            cap_ii = row[i]
            for j in range(0, cap_matrix.dimension):
                if i == j:
                    continue
                cap_value = -row[j]  # off-diagonals are always stored as negative values
                cap_ii -= cap_value  # subtract summands to filter out Cii
                if j > i:
                    add_parasitic_cap(i=i, j=j,
                                      net1=nets[i], net2=nets[j],
                                      cap_value=cap_value)
            if i > 0:
                add_parasitic_cap(i=i, j=i,
                                  net1=nets[i], net2=nets[0],
                                  cap_value=cap_ii)

        # Short VSUBS and FC_GND together
        #   VSUBS ... substrate block
        #   FC_GND ... FasterCap's GND, i.e. the diagonal Cii elements
        # create capacitor class

        res = kdb.DeviceClassResistor()
        res.name = 'PEX_RES'
        res.description = "Extracted by kpex/FasterCap PEX"
        expanded_netlist.add(res)

        gnd_net = name2net.get('GND', None)
        if not gnd_net:
            gnd_net = top_circuit.create_net('GND')  # create GROUND net

        c: kdb.Device = top_circuit.create_device(res, f"Rext_FC_GND_GND")
        c.connect_terminal('A', fc_gnd_net)
        c.connect_terminal('B', gnd_net)
        c.set_parameter('R', 0)

        c: kdb.Device = top_circuit.create_device(res, f"Rext_VSUBS_GND")
        c.connect_terminal('A', vsubs_net)
        c.connect_terminal('B', gnd_net)
        c.set_parameter('R', 0)

        return expanded_netlist


class Test(unittest.TestCase):
    @property
    def klayout_testdata_dir(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'testdata', 'fastercap'))

    @property
    def tech_info_json_path(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'build', 'sky130A_tech.pb.json'))

    def test_netlist_expansion(self):
        exp = NetlistExpander()

        cell_name = 'nmos_diode2'

        lvsdb = kdb.LayoutVsSchematic()
        lvsdb_path = os.path.join(self.klayout_testdata_dir, f"{cell_name}.lvsdb.gz")
        lvsdb.read(lvsdb_path)

        csv_path = os.path.join(self.klayout_testdata_dir, f"{cell_name}_FasterCap_Result_Matrix.csv")

        cap_matrix = CapacitanceMatrix.parse_csv(csv_path, separator=';')

        tech = TechInfo.from_json(self.tech_info_json_path,
                                  dielectric_filter=None)

        pex_context = KLayoutExtractionContext.prepare_extraction(top_cell=cell_name,
                                                                  lvsdb=lvsdb,
                                                                  tech=tech,
                                                                  blackbox_devices=False)
        expanded_netlist = exp.expand(extracted_netlist=pex_context.lvsdb.netlist(),
                                      top_cell_name=pex_context.top_cell.name,
                                      cap_matrix=cap_matrix,
                                      blackbox_devices=False)
        out_path = tempfile.mktemp(prefix=f"{cell_name}_expanded_netlist_", suffix=".cir")
        spice_writer = kdb.NetlistSpiceWriter()
        expanded_netlist.write(out_path, spice_writer)
        debug(f"Wrote expanded netlist to: {out_path}")