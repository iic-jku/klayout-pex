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

from datetime import datetime
from pathlib import Path
from typing import *

import klayout.db as kdb

from ..extraction_engine import ExtractionEngine
from ..pdk_config import PDKConfig
from ..util.unit_formatter import format_spice_number
from ..version import __version__


class NetlistPrinter(kdb.NetlistSpiceWriterDelegate):
    def __init__(self,
                 extraction_engine: ExtractionEngine,
                 pdk: PDKConfig):
        super().__init__()

        self.extraction_engine = extraction_engine
        self.pdk = pdk

        self.spice_writer = kdb.NetlistSpiceWriter(self)
        self.spice_writer.use_net_names = True
        self.spice_writer.with_comments = False

    def write(self,
              netlist: kdb.Netlist,
              output_path: str | Path):
        netlist.write(output_path, self.spice_writer)

    # --------------------------------------------------------------------------------
    # NetlistSpiceWriterDelegate overwrites

    def write_header(self, *args, **kwargs):
        now = datetime.now()
        header_date = now.strftime("%Y-%m-%d %H:%M:%S")

        self.emit_line(f"*********************************************************")
        self.emit_line(f"*** NGSPICE file created by KLayout-PEX {__version__}")
        self.emit_line(f"*** -----------------------------------------------------")
        self.emit_line(f"***     Extraction Engine: {self.extraction_engine}")
        self.emit_line(f"***     Technology: {self.pdk.name.lower()}")
        self.emit_line(f"***     Date: {header_date}")
        self.emit_line(f"*********************************************************")

    def write_device(self, device: kdb.Device):
        dc = device.device_class()
        match dc:
            case kdb.DeviceClassCapacitor():
                c_farad = device.parameter('C')
                net1 = self.net_to_string(device.net_for_terminal(0))
                net2 = self.net_to_string(device.net_for_terminal(1))
                self.emit_line(f"C{device.name} {net1} {net2} {format_spice_number(c_farad)}")

            case _:
                super().write_device(device)
