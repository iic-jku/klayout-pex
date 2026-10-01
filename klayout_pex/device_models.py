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

from __future__ import annotations  # allow class type hints within same class
from collections import Counter
from functools import cached_property
import math
from typing import *

import klayout.db as kdb

import klayout_pex_protobuf.kpex.tech.device_models_pb2 as device_models_pb2


class DeviceModelError(Exception):
    """
    The device model mappings are missing or invalid for devices of a netlist
    """
    pass


def rectangle_sides(area: float, perimeter: float) -> Tuple[float, float]:
    """
    :return: the long and the short side of the rectangle with this area and perimeter,
             or the sides of the square of this area, if there is no such rectangle
             (perimeter² < 16 · area, e.g. an octagon)
    """
    # NOTE: the sides are the roots of x² - perimeter/2 · x + area
    half_sum = perimeter / 4
    discriminant = half_sum * half_sum - area
    if discriminant <= 0:
        side = math.sqrt(area)
        return side, side
    long_side = half_sum + math.sqrt(discriminant)
    # NOTE: not half_sum - sqrt(discriminant), which cancels out for a long, narrow rectangle
    return long_side, area / long_side


class DeviceModels:
    """Helper class for Protocol Buffer device_models_pb2.DeviceModelsInfo"""

    LVSDeviceClassName = str

    def __init__(self, device_models: device_models_pb2.DeviceModelsInfo):
        self.device_models = device_models

    @cached_property
    def mapping_by_lvs_device_class_name(self) -> Dict[LVSDeviceClassName, device_models_pb2.DeviceModelMapping]:
        return {m.lvs_device_class_name: m for m in self.device_models.device_model_mappings}

    def check_mappings(self,
                       netlist: kdb.Netlist,
                       ignored_device_class_names: Set[LVSDeviceClassName] = frozenset()):
        """
        Raises DeviceModelError, if the mapping of a device class of the netlist is missing or invalid.

        Only device classes that have devices in the netlist are checked.
        """
        device_count_by_class_name = Counter(d.device_class().name
                                             for c in netlist.each_circuit()
                                             for d in c.each_device())
        problems: List[str] = []
        for dc in netlist.each_device_class():
            if dc.name in ignored_device_class_names:
                continue
            device_count = device_count_by_class_name[dc.name]
            if device_count == 0:
                continue
            mapping = self.mapping_by_lvs_device_class_name.get(dc.name)
            if mapping is None:
                problems.append(f"{dc.name} ({device_count} devices): no mapping")
                continue
            problems += [f"{dc.name}: {p}" for p in self.mapping_problems(dc, mapping)]

        if problems:
            raise DeviceModelError(
                "The device model mappings of the tech info are missing or invalid "
                "for these LVS device classes:\n" +
                '\n'.join(f"  - {p}" for p in problems)
            )

    @staticmethod
    def mapping_problems(dc: kdb.DeviceClass,
                         mapping: device_models_pb2.DeviceModelMapping) -> List[str]:
        problems: List[str] = []
        if not mapping.spice_prefix:
            problems.append("no SPICE prefix")

        lvs_terminal_names = [td.name for td in dc.terminal_definitions()]
        for t in mapping.terminal_names:
            if t not in lvs_terminal_names:
                problems.append(f"no LVS terminal '{t}' (terminals are {', '.join(lvs_terminal_names)})")
        # NOTE: a terminal left out would silently disconnect the device from its net
        for t in lvs_terminal_names:
            if t not in mapping.terminal_names:
                problems.append(f"LVS terminal '{t}' is missing in the terminal names")

        lvs_parameter_names = [pd.name for pd in dc.parameter_definitions()]
        for p in mapping.parameters:
            match p.WhichOneof('value'):
                case 'lvs_parameter_name':
                    if p.lvs_parameter_name not in lvs_parameter_names:
                        problems.append(f"parameter '{p.name}': no LVS parameter '{p.lvs_parameter_name}' "
                                        f"(parameters are {', '.join(lvs_parameter_names)})")
                case 'lvs_area_perimeter_side':
                    side = p.lvs_area_perimeter_side
                    for lvs_parameter_name in (side.area_parameter_name, side.perimeter_parameter_name):
                        if lvs_parameter_name not in lvs_parameter_names:
                            problems.append(f"parameter '{p.name}': no LVS parameter '{lvs_parameter_name}' "
                                            f"(parameters are {', '.join(lvs_parameter_names)})")
                    if side.side == device_models_pb2.LVSAreaPerimeterSide.SIDE_UNSPECIFIED:
                        problems.append(f"parameter '{p.name}': no side of the rectangle")
                case 'constant':
                    pass
                case _:
                    problems.append(f"parameter '{p.name}': no value")
        return problems
