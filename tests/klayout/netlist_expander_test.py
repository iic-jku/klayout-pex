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
from __future__ import annotations

import allure
import os
import tempfile
import unittest

import klayout.db as kdb

from klayout_pex.fastercap.output_interpreter import FasterCapOutputInterpreter
from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.klayout.netlist_expander import NetlistExpander
from klayout_pex.log import (
    debug,
)
from klayout_pex.common.capacitance_matrix import CapacitanceMatrix
from klayout_pex.tech_info import TechInfo


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "Netlist Expansion")
class Test(unittest.TestCase):
    @property
    def klayout_testdata_dir(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'testdata', 'fastercap'))

    @property
    def tech_info_json_path(self) -> str:
        return os.path.realpath(os.path.join(__file__, '..', '..', '..',
                                             'klayout_pex_protobuf', 'sky130A_tech.pb.json'))

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
                                      top_cell_name=pex_context.annotated_top_cell.name,
                                      cap_matrix=cap_matrix,
                                      cap_matrix_interpreter=FasterCapOutputInterpreter(),
                                      blackbox_devices=False,
                                      substrate_net_name='VSUBS')  # NOTE: the substrate conductor of the matrix
        out_path = tempfile.mktemp(prefix=f"{cell_name}_expanded_netlist_", suffix=".cir")
        spice_writer = kdb.NetlistSpiceWriter()
        expanded_netlist.write(out_path, spice_writer)
        debug(f"Wrote expanded netlist to: {out_path}")

        allure.attach.file(csv_path, attachment_type=allure.attachment_type.CSV)
        allure.attach.file(out_path, attachment_type=allure.attachment_type.TEXT)


def substrate_test_netlist() -> kdb.Netlist:
    """
    The nets D and B, with a pin each
    """
    netlist = kdb.Netlist()
    circuit = kdb.Circuit()
    circuit.name = 'chip'
    netlist.add(circuit)
    for name in ('D', 'B'):
        circuit.connect_pin(circuit.create_pin(name), circuit.create_net(name))
    return netlist


# the substrate on the net B, as FasterCapInputBuilder names it after the substrate net:
# B to D 1.5 fF, and the rest of the diagonal (to infinity) of D 0.25 fF
CAP_MATRIX_SUBSTRATE_ON_B = CapacitanceMatrix(conductor_names=['g1_B', 'g2_D'],
                                              rows=[[2.0e-15, -1.5e-15],
                                                    [-1.5e-15, 1.75e-15]])

# the substrate a conductor of its own: to D 1 fF and to B 2 fF, D to B 0.5 fF,
# and the rest of the diagonal (to infinity): D 0.25 fF, B 0.1 fF
CAP_MATRIX_SUBSTRATE_PORT = CapacitanceMatrix(conductor_names=['g1_sky130_gnd', 'g2_D', 'g3_B'],
                                              rows=[[3.0e-15, -1.0e-15, -2.0e-15],
                                                    [-1.0e-15, 1.75e-15, -0.5e-15],
                                                    [-2.0e-15, -0.5e-15, 2.6e-15]])


def capacitances_by_net_pair(expanded: kdb.Netlist) -> dict:
    caps = {}
    for d in expanded.circuit_by_name('chip').each_device():
        pair = frozenset((d.net_for_terminal('A').name, d.net_for_terminal('B').name))
        caps[pair] = round(caps.get(pair, 0.0) + d.parameter('C') * 1e15, 6)
    return caps


@allure.parent_suite("Unit Tests")
@allure.tag("Netlist", "Netlist Expansion")
class SubstrateTest(unittest.TestCase):
    def test_capacitances_to_the_substrate_are_on_its_net(self):
        expanded = NetlistExpander.expand(substrate_test_netlist(), 'chip', CAP_MATRIX_SUBSTRATE_ON_B,
                                          FasterCapOutputInterpreter(), blackbox_devices=True, substrate_net_name='B')
        circuit = expanded.circuit_by_name('chip')
        # NOTE: the rest of the diagonal of D goes to the substrate B too
        self.assertEqual({frozenset(('D', 'B')): 1.75}, capacitances_by_net_pair(expanded))
        self.assertEqual(['D', 'B'], [p.name() for p in circuit.each_pin()])
        for name in ('VSUBS', 'FC_GND', 'GND'):
            self.assertIsNone(circuit.net_by_name(name))

    def test_substrate_without_net_is_a_port(self):
        expanded = NetlistExpander.expand(substrate_test_netlist(), 'chip', CAP_MATRIX_SUBSTRATE_PORT,
                                          FasterCapOutputInterpreter(), blackbox_devices=True,
                                          substrate_net_name='sky130_gnd')
        circuit = expanded.circuit_by_name('chip')
        self.assertEqual({frozenset(('sky130_gnd', 'D')): 1.25,
                          frozenset(('sky130_gnd', 'B')): 2.1,
                          frozenset(('D', 'B')): 0.5},
                         capacitances_by_net_pair(expanded))
        self.assertEqual(['D', 'B', 'sky130_gnd'], [p.name() for p in circuit.each_pin()])
