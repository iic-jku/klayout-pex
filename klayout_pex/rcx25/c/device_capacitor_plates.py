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
from __future__ import annotations

from dataclasses import dataclass, field
from typing import *

import klayout.db as kdb

from klayout_pex.klayout.lvsdb_extractor import DEVICE_CAPACITOR_PLATE_PROPERTY
from klayout_pex.types import NetName

Shape = Union[kdb.PolygonWithProperties, kdb.EdgeWithProperties]


@dataclass
class DeviceCapacitorPlates:
    """
    The plates of the black-boxed capacitor devices, whose models have the capacitances between them
    (the shapes of KIND_DEVICE_CAPACITOR_PLATE, e.g. the fingers of a MOM cap),
    but not their capacitances to other nets (e.g. the substrate, a wire across), which are extracted.

    NOTE: a pair of plates is of a device if its nets are the terminal nets of a device,
          and not e.g. a wire of another net across the device, which is on its plate layers too
    """

    # the nets of the terminals of each device
    terminal_net_pairs: Set[FrozenSet[NetName]] = field(default_factory=set)

    @classmethod
    def from_circuit(cls,
                     circuit: kdb.Circuit,
                     device_class_names: Set[str]) -> DeviceCapacitorPlates:
        """
        :param device_class_names: the device classes of the capacitors (e.g. the metal capacitors)
        """
        terminal_net_pairs: Set[FrozenSet[NetName]] = set()
        for d in circuit.each_device():
            if d.device_class().name not in device_class_names:
                continue
            net_names = sorted({net.expanded_name()
                                for td in d.device_class().terminal_definitions()
                                if (net := d.net_for_terminal(td.id())) is not None})
            terminal_net_pairs.update(frozenset((n1, n2))
                                      for idx, n1 in enumerate(net_names) for n2 in net_names[idx + 1:])
        return DeviceCapacitorPlates(terminal_net_pairs=terminal_net_pairs)

    def are_plates_of_a_device(self, shape1: Shape, net1: NetName, shape2: Shape, net2: NetName) -> bool:
        """
        :return: whether the shapes are plates of a device between their nets,
                 whose model has the capacitance between them
        """
        return bool(shape1.property(DEVICE_CAPACITOR_PLATE_PROPERTY)) and \
               bool(shape2.property(DEVICE_CAPACITOR_PLATE_PROPERTY)) and \
               frozenset((net1, net2)) in self.terminal_net_pairs
