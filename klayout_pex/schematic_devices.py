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
The devices of a schematic, in the LVS device classes of the extracted netlist (#345)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import chain
from typing import *

from .device_models import DeviceModels
from .netlist.spice_hierarchy import SpiceHierarchy
from .netlist.spice_netlist import SpiceNetlist
from .types import LVSDeviceClassName


@dataclass
class SchematicDevices:
    # e.g. {'sg13_lv_nmos': ['X1.XM1', 'X1.XM2']}
    device_names_by_class_name: Dict[LVSDeviceClassName, List[str]] = field(default_factory=dict)

    # the devices of models that no device model mapping writes, by model,
    # e.g. a device without a model mapping, or a call of a subcircuit the schematic doesn't define
    device_names_by_unknown_model: Dict[str, List[str]] = field(default_factory=dict)


def schematic_devices(netlist: SpiceNetlist,
                      device_models: DeviceModels,
                      top_cell_name: str) -> SchematicDevices:
    """
    :param top_cell_name: the cell of the layout, whose subcircuit in the schematic has the devices,
                          else those of the subcircuits that no element calls, and the elements outside of them
    :raises SpiceEvaluationError: if a value of the schematic has no number
    """
    hierarchy = SpiceHierarchy(netlist)
    top = hierarchy.subcircuit(top_cell_name)
    if top is not None:
        elements = hierarchy.flat_elements(top)
    else:
        elements = chain(*(hierarchy.flat_elements(s) for s in hierarchy.uncalled_subcircuits()),
                         hierarchy.flat_elements())

    device_names_by_class_name: Dict[LVSDeviceClassName, List[str]] = defaultdict(list)
    device_names_by_unknown_model: Dict[str, List[str]] = defaultdict(list)
    for e in elements:
        class_name = device_models.lvs_device_class_name(e.element)
        if class_name is not None:
            device_names_by_class_name[class_name].append(e.path)
        elif e.element.model is not None:
            device_names_by_unknown_model[e.element.model].append(e.path)

    return SchematicDevices(device_names_by_class_name=dict(device_names_by_class_name),
                            device_names_by_unknown_model=dict(device_names_by_unknown_model))
