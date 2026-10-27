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
from typing import *

from .device_models import DeviceModels
from .netlist.spice_netlist import SpiceElement, SpiceNetlist
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
                          else those of the subcircuits that no other one calls, and the elements outside of them
    """
    subcircuit_by_key = {s.name.upper(): s for s in netlist.subcircuits}
    top = subcircuit_by_key.get(top_cell_name.upper())
    if top is not None:
        roots = [top]
        elements = []
    else:
        called = {e.model.upper() for s in netlist.subcircuits for e in s.elements if e.kind == 'X'}
        roots = [s for s in netlist.subcircuits if s.name.upper() not in called]
        elements = netlist.elements

    device_names_by_class_name: Dict[LVSDeviceClassName, List[str]] = defaultdict(list)
    device_names_by_unknown_model: Dict[str, List[str]] = defaultdict(list)

    def add(element: SpiceElement, path: str, calls: Tuple[str, ...]):
        name = f"{path}{element.name}"
        subcircuit = subcircuit_by_key.get(element.model.upper()) if element.kind == 'X' else None
        if subcircuit is not None:
            if subcircuit.name.upper() not in calls:  # NOTE: SPICE allows no recursion
                for e in subcircuit.elements:
                    add(e, f"{name}.", calls + (subcircuit.name.upper(),))
            return
        class_name = device_models.lvs_device_class_name(element)
        if class_name is not None:
            device_names_by_class_name[class_name].append(name)
        elif element.model is not None:
            device_names_by_unknown_model[element.model].append(name)

    for root in roots:
        for element in root.elements:
            add(element, '', (root.name.upper(),))
    for element in elements:
        add(element, '', ())

    return SchematicDevices(device_names_by_class_name=dict(device_names_by_class_name),
                            device_names_by_unknown_model=dict(device_names_by_unknown_model))
