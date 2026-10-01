#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/martinjankoehler/klayout-pex).
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

import os
import tempfile
from typing import *
from unittest import mock

import allure
import klayout.db as kdb
import pytest

from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.kpex_cli import KpexCLI
from klayout_pex.pdk_config import PDK
from klayout_pex.tech_info import TechInfo

parent_suite = "kpex/2.5D Extraction Tests [PDK ihp-sg13g2 | mode R]"
tags = ("PEX", "2.5D", "RF MOS")

TEST_DESIGNS_DIR = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata', 'designs', 'ihp-sg13g2'))


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.slow
def test_rf_mos_keeps_its_layout_geometry():
    # The IHP LVS script replaced each extracted RF MOS by a newly created device
    # of the base class (sg13_lv_nmos with rfmode=1), which has no layout geometry,
    # so the resistance extraction could not connect it (#211)
    cell_name = 'rfnmos_w1u_l0u72'
    gds_path = os.path.join(TEST_DESIGNS_DIR, 'rfnmos', f"{cell_name}.gds.gz")

    with tempfile.TemporaryDirectory() as out_dir:
        cli = KpexCLI()
        cli.main(['main',
                  '--pdk', PDK.IHP_SG13G2,
                  '--mode', 'R',
                  '--gds', gds_path,
                  '--out_dir', out_dir,
                  '--2.5D'])
        assert cli.rcx25_extraction_results is not None

        lvsdb = kdb.LayoutVsSchematic()
        lvsdb.read(os.path.join(out_dir, f"{cell_name}__{cell_name}", f"{cell_name}.lvsdb.gz"))

    assert [c.name for c in lvsdb.internal_layout().top_cells()] == [cell_name]

    tech = TechInfo.from_json(PDK.IHP_SG13G2.config.tech_pb_json_path, dielectric_filter=None)
    pex_context = KLayoutExtractionContext.prepare_extraction(lvsdb=lvsdb,
                                                              top_cell=cell_name,
                                                              tech=tech,
                                                              blackbox_devices=False)
    devices = list(pex_context.devices_by_name.values())
    assert [(d.device_class_name, d.device_abstract_name) for d in devices] == [('rfnmos', 'D$rfnmos')]
    assert {t.name: [r.layer.canonical_layer_name for r in t.region_by_layer] for t in devices[0].terminals} \
           == {'S': ['nSD'], 'G': ['GatPoly'], 'D': ['nSD'], 'B': ['PWell']}


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_device_terminals_without_tech_layer_are_where_they_overlap_their_net():
    # The terminals of the MOM capacitor are on its ports (cap_cmomi_m5_ports, the Metal5 pins within its marker),
    # an LVS layer the tech info has no layer for (#217), so they are where they overlap the Metal5 of their nets
    cell_name = 'cmomi_w5u_l5u_m1_m5'
    gds_path = os.path.join(TEST_DESIGNS_DIR, cell_name, f"{cell_name}.gds.gz")

    with tempfile.TemporaryDirectory() as out_dir, \
         mock.patch('klayout_pex.klayout.lvsdb_extractor.warning') as warning_mock:
        KpexCLI().main(['main',
                        '--pdk', PDK.IHP_SG13G2,
                        '--mode', 'R',
                        '--gds', gds_path,
                        '--out_dir', out_dir,
                        '--2.5D'])

        lvsdb = kdb.LayoutVsSchematic()
        lvsdb.read(os.path.join(out_dir, f"{cell_name}__{cell_name}", f"{cell_name}.lvsdb.gz"))

    assert [c.args[0] for c in warning_mock.call_args_list if 'device terminals' in c.args[0]] == []

    tech = TechInfo.from_json(PDK.IHP_SG13G2.config.tech_pb_json_path, dielectric_filter=None)
    pex_context = KLayoutExtractionContext.prepare_extraction(lvsdb=lvsdb,
                                                              top_cell=cell_name,
                                                              tech=tech,
                                                              blackbox_devices=True)
    mom_cap, = [d for d in pex_context.devices_by_name.values() if d.device_class_name == 'cap_cmomi']
    assert {t.name: [r.layer.canonical_layer_name for r in t.region_by_layer] for t in mom_cap.terminals} \
           == {'mim_top': ['Metal5'], 'mim_btm': ['Metal5']}


def extract_test_pattern(cell_name: str) -> Tuple[List[str], List[str]]:
    """
    :return: the lines of the CSV and of the SPICE netlist (with continuation lines joined)
    """
    gds_path = os.path.join(TEST_DESIGNS_DIR, 'test_patterns', f"{cell_name}.gds.gz")
    with tempfile.TemporaryDirectory() as out_dir:
        cli = KpexCLI()
        cli.main(['main',
                  '--pdk', PDK.IHP_SG13G2,
                  '--mode', 'R',
                  '--gds', gds_path,
                  '--out_dir', out_dir,
                  '--2.5D'])
        csv_path = cli.rcx25_extracted_csv_path
        with open(csv_path) as f:
            csv_lines = f.read().splitlines()
        with open(csv_path[:-len('.csv')] + '.spice') as f:
            spice_lines = f.read().replace('\n+', ' ').splitlines()
    return csv_lines, spice_lines


def subckt_ports(spice_lines: List[str]) -> List[str]:
    subckt_line, = [line for line in spice_lines if line.startswith('.SUBCKT ')]
    return [port.replace('\\', '') for port in subckt_line.split()[2:]]


def ports_touching_nothing(spice_lines: List[str]) -> List[str]:
    element_nodes: Set[str] = set()
    for line in spice_lines:
        tokens = line.split()
        if not tokens or tokens[0][0] not in 'CRX':
            continue
        if tokens[0][0] == 'X':  # the nodes, the subcircuit, then the parameters
            nodes = tokens[1:next(i for i, t in enumerate(tokens) if '=' in t) - 1]
        else:
            nodes = tokens[1:3]
        element_nodes.update(node.replace('\\', '') for node in nodes)
    return [port for port in subckt_ports(spice_lines) if port not in element_nodes]


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_nets_of_the_same_name_stay_apart():
    # Two transistors, each with its own metal islands labelled D and S, which are not connected
    # (like the islands of a supply, joined only in the parent). The IHP LVS script connects no nets implicitly,
    # so they are distinct nets of the same name, which KLayout's SPICE writer calls D, D$1, S, S$1 (#211 §10)
    csv_lines, _ = extract_test_pattern('nmos_metal1_redux_twice')
    assert csv_lines == """Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;$1;$1.$0.GatPoly;;33.654
R2;$1.$0.GatPoly;$1.$1.Metal1;;15.0
R3;$4;$4.$0.GatPoly;;33.654
R4;$4.$0.GatPoly;$4.$1.Metal1;;15.0
R5;D;D.$1.Metal1;;0.488
R6;D$1;D$1.$1.Metal1;;0.488
R7;D$1.$1.Metal1;D$1.P0.nSD;;17.0
R8;D.$1.Metal1;D.P0.nSD;;17.0
R9;S;S.$1.Metal1;;0.598
R10;S$1;S$1.$1.Metal1;;0.598
R11;S$1.$1.Metal1;S$1.P0.nSD;;17.0
R12;S.$1.Metal1;S.P0.nSD;;17.0""".splitlines()


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_a_net_of_several_labels_has_a_port_per_label():
    # The drain wire of the transistor has the labels D and X at its ends, so LVS has one net D,X with one pin,
    # which the netlist replaces by the ports D and X at the labels, where the parent connects (#211 §11)
    csv_lines, spice_lines = extract_test_pattern('nmos_metal1_redux_two_drain_labels')
    assert csv_lines == """Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;$1;$1.$0.GatPoly;;33.654
R2;$1.$0.GatPoly;$1.$1.Metal1;;15.0
R3;D;D,X.$1.Metal1;;0.488
R4;D,X;D,X.$1.Metal1;;17.0
R5;D,X.$1.Metal1;X;;0.089
R6;S;S.$1.Metal1;;0.598
R7;S.$1.Metal1;S.P0.nSD;;17.0""".splitlines()
    assert subckt_ports(spice_lines) == ['D', 'X', 'S', 'sub!']  # sub!: the substrate, the bulk of the transistor
    assert ports_touching_nothing(spice_lines) == []


@allure.parent_suite(parent_suite)
@allure.tag("PEX", "2.5D")
@pytest.mark.slow
def test_labels_on_one_node_are_tied():
    # The labels D and X are on the same pin of the drain wire, so both ports are on one node,
    # tied by 1 mΩ, rather than one of them touching nothing (#211 §11)
    csv_lines, spice_lines = extract_test_pattern('nmos_metal1_redux_two_labels_one_node')
    assert csv_lines == """Device;Net1;Net2;Capacitance [fF];Resistance [Ω]
R1;$1;$1.$0.GatPoly;;33.654
R2;$1.$0.GatPoly;$1.$1.Metal1;;15.0
R3;D;D,X.$1.Metal1;;0.488
R4;D;X;;0.001
R5;D,X;D,X.$1.Metal1;;17.0
R6;S;S.$1.Metal1;;0.598
R7;S.$1.Metal1;S.P0.nSD;;17.0""".splitlines()
    assert subckt_ports(spice_lines) == ['D', 'X', 'S', 'sub!']  # sub!: the substrate, the bulk of the transistor
    assert ports_touching_nothing(spice_lines) == []
