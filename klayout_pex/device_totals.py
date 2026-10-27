#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
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

"""
Totals of the devices of an LVS device class that don't depend on how the devices are split
(into fingers, by m, into series or parallel segments), which --check compares between the schematic
and the LVS netlist (#345):
    - the area: W·L, if the device model mapping writes model parameters of the LVS parameters W and L
      (in any case), or else A, if it writes those of the area (A, or the rectangle of an area and perimeter)
    - the width W of a MOS
    - the multiplier, if the mapping writes the model's m of an LVS parameter (e.g. NE of a BJT)
each times the multiplier: that LVS parameter, else (or if a device of the schematic doesn't give it)
the m of a device of the schematic (SPICE's multiplier, 1 if not given).

The totals are in the units of the LVS parameters (e.g. µm² for W·L of a MOS in µm), a device of the schematic
gets its LVS parameters by the mapping in reverse (see DeviceModels.lvs_parameter_values).
A class whose mapping writes none of them has no totals (e.g. taps, or caps of a fixed size).
"""

from __future__ import annotations
from dataclasses import dataclass
import math
from typing import *

import klayout.db as kdb

from .device_models import DeviceModels
import klayout_pex_protobuf.kpex.tech.device_models_pb2 as device_models_pb2


@dataclass(frozen=True)
class DeviceTotalParameters:
    """
    The LVS parameters of the totals of a device class (see the module docs)
    """
    width: Optional[str] = None
    length: Optional[str] = None
    area: Optional[str] = None
    multiplier: Optional[str] = None
    mos: bool = False

    @staticmethod
    def of(device_class: kdb.DeviceClass,
           mapping: device_models_pb2.DeviceModelMapping) -> DeviceTotalParameters:
        names: Dict[str, str] = {}
        area: Optional[str] = None
        for p in mapping.parameters:
            match p.WhichOneof('value'):
                case 'lvs_parameter_name':
                    names.setdefault(p.lvs_parameter_name.upper(), p.lvs_parameter_name)
                case 'lvs_area_perimeter_side':
                    area = p.lvs_area_perimeter_side.area_parameter_name
        return DeviceTotalParameters(width=names.get('W'),
                                     length=names.get('L'),
                                     area=area or names.get('A'),
                                     multiplier=DeviceModels.multiplier_lvs_parameter_name(mapping),
                                     mos=isinstance(device_class, kdb.DeviceClassMOS3Transistor))

    @property
    def quantity_names(self) -> List[str]:
        """
        e.g. ['W·L', 'W'] of a MOS
        """
        return list(self.quantities({}))

    def quantities(self,
                   lvs_parameters: Mapping[str, float],
                   m: float = 1.0) -> Dict[str, Optional[float]]:
        """
        The quantities of a device whose totals are compared, e.g. {'W·L': 0.13, 'W': 1.0} of a MOS

        :param lvs_parameters: of the device, by name
        :param m: the multiplier of SPICE, if the mapping writes no multiplier, or the device doesn't give it
        :return: None for a quantity the device has no value for
                 (e.g. a parameter the schematic leaves to the model's default)
        """
        multiplier = lvs_parameters.get(self.multiplier, m) if self.multiplier else m

        def product(*names: str) -> Optional[float]:
            values = [lvs_parameters.get(n) for n in names]
            if None in values:
                return None
            return math.prod(values) * multiplier

        quantities: Dict[str, Optional[float]] = {}
        if self.width and self.length:
            quantities[f"{self.width}·{self.length}"] = product(self.width, self.length)
        elif self.area:
            quantities[self.area] = product(self.area)
        if self.mos and self.width:
            quantities[self.width] = product(self.width)
        if self.multiplier:
            quantities[self.multiplier] = multiplier
        return quantities
