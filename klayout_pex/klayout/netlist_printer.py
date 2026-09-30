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

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import *

import klayout.db as kdb

from ..device_models import DeviceModels
from .parasitic_device_classes import (
    PARASITIC_CAPACITOR_CLASS_NAME,
    PARASITIC_DEVICE_CLASS_NAMES,
    PARASITIC_RESISTOR_CLASS_NAME,
)
from ..util.unit_formatter import format_spice_number

import klayout_pex_protobuf.kpex.tech.device_models_pb2 as device_models_pb2


@dataclass
class NetlistHeader:
    kpex_version: str
    extraction_engine: str
    tech: str
    date: datetime


class NetlistPrinter(kdb.NetlistSpiceWriterDelegate):
    def __init__(self,
                 header: NetlistHeader,
                 device_models: DeviceModels):
        """
        :param header: written as comments at the top of the netlist
        :param device_models: how to write the devices of the LVS netlist
                              (the parasitics KPEX added are written as they are)
        """
        super().__init__()

        self.header = header
        self.device_models = device_models

        self.spice_writer = kdb.NetlistSpiceWriter(self)
        self.spice_writer.use_net_names = True
        self.spice_writer.with_comments = False

    def write(self,
              netlist: kdb.Netlist,
              output_path: str | Path):
        # NOTE: the final netlist, the netlist expanders may have removed (whitebox) devices
        self.device_models.check_mappings(netlist, ignored_device_class_names=PARASITIC_DEVICE_CLASS_NAMES)
        netlist.write(output_path, self.spice_writer)

    # --------------------------------------------------------------------------------
    # NetlistSpiceWriterDelegate overwrites

    def write_header(self, *args, **kwargs):
        header_date = self.header.date.strftime("%Y-%m-%d %H:%M:%S")

        self.emit_line(f"*********************************************************")
        self.emit_line(f"*** NGSPICE file created by KLayout-PEX {self.header.kpex_version}")
        self.emit_line(f"*** -----------------------------------------------------")
        self.emit_line(f"***     Extraction Engine: {self.header.extraction_engine}")
        self.emit_line(f"***     Technology: {self.header.tech}")
        self.emit_line(f"***     Date: {header_date}")
        self.emit_line(f"*********************************************************")

    def write_device(self, device: kdb.Device):
        dc = device.device_class()
        if dc.name == PARASITIC_CAPACITOR_CLASS_NAME:
            c_farad = device.parameter('C')
            net1 = self.net_to_string(device.net_for_terminal(0))
            net2 = self.net_to_string(device.net_for_terminal(1))
            self.emit_line(f"C{device.name} {net1} {net2} {format_spice_number(c_farad)}")
        elif dc.name == PARASITIC_RESISTOR_CLASS_NAME:
            # NOTE: without a model name (KLayout's writer adds the device class name, which ngspice rejects)
            r_ohm = device.parameter('R')
            net1 = self.net_to_string(device.net_for_terminal(0))
            net2 = self.net_to_string(device.net_for_terminal(1))
            self.emit_line(f"R{device.name} {net1} {net2} {r_ohm:.12g}")
        else:
            self.write_modeled_device(device, self.device_models.mapping_by_lvs_device_class_name[dc.name])

    def write_modeled_device(self,
                             device: kdb.Device,
                             device_model_mapping: device_models_pb2.DeviceModelMapping):
        dc = device.device_class()
        items = [f"{device_model_mapping.spice_prefix}{self.format_name(device.expanded_name())}"]
        items += [self.net_to_string(device.net_for_terminal(dc.terminal_id(t)))
                  for t in device_model_mapping.terminal_names]
        items.append(self.format_name(device_model_mapping.model_name or dc.name))
        for p in device_model_mapping.parameters:
            match p.WhichOneof('value'):
                case 'lvs_parameter_name':
                    factor = p.lvs_parameter_factor if p.HasField('lvs_parameter_factor') else 1.0
                    value = device.parameter(p.lvs_parameter_name) * factor
                case 'constant':
                    value = p.constant
            items.append(f"{p.name}={value:.12g}")
        self.emit_line(' '.join(items))
