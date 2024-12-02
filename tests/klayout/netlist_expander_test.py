from __future__ import annotations

import allure
import os
import tempfile
import unittest

import klayout.db as kdb

from kpex.klayout.lvsdb_extractor import KLayoutExtractionContext
from kpex.klayout.netlist_expander import NetlistExpander
from kpex.log import (
    debug,
)
from kpex.common.capacitance_matrix import CapacitanceMatrix
from kpex.tech_info import TechInfo


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

        allure.attach.file(csv_path, attachment_type=allure.attachment_type.CSV)
        allure.attach.file(out_path, attachment_type=allure.attachment_type.TEXT)