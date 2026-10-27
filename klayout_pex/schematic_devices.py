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
class SchematicDevice:
    name: str  # e.g. X1.XM2

    # by the device model mapping in reverse, e.g. {'W': 1.0, 'L': 0.13} (µm) of an IHP MOS with w=1u l=0.13u
    lvs_parameters: Dict[str, float] = field(default_factory=dict)

    m: float = 1.0  # the multiplier of SPICE


@dataclass
class SchematicDevices:
    # e.g. {'sg13_lv_nmos': [SchematicDevice('X1.XM1', ...), ...]}
    devices_by_class_name: Dict[LVSDeviceClassName, List[SchematicDevice]] = field(default_factory=dict)

    # the devices of models that no device model mapping writes, by model,
    # e.g. a device without a model mapping, or a call of a subcircuit the schematic doesn't define
    device_names_by_unknown_model: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def device_names_by_class_name(self) -> Dict[LVSDeviceClassName, List[str]]:
        return {c: [d.name for d in devices] for c, devices in self.devices_by_class_name.items()}


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

    devices_by_class_name: Dict[LVSDeviceClassName, List[SchematicDevice]] = defaultdict(list)
    device_names_by_unknown_model: Dict[str, List[str]] = defaultdict(list)
    for e in elements:
        class_name = device_models.lvs_device_class_name(e.element)
        if class_name is not None:
            mapping = device_models.mapping_by_lvs_device_class_name[class_name]
            devices_by_class_name[class_name].append(
                SchematicDevice(name=e.path,
                                lvs_parameters=device_models.lvs_parameter_values(mapping, e.element),
                                m=e.element.parameters.get('m', 1.0)))
        elif e.element.model is not None:
            device_names_by_unknown_model[e.element.model].append(e.path)

    return SchematicDevices(devices_by_class_name=dict(devices_by_class_name),
                            device_names_by_unknown_model=dict(device_names_by_unknown_model))
