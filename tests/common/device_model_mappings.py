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
Device model mappings of the tech info, for tests
"""

from __future__ import annotations

import google.protobuf.json_format

from klayout_pex.device_models import DeviceModels
import klayout_pex_protobuf.kpex.tech.device_models_pb2 as device_models_pb2


def device_models(*mappings: dict) -> DeviceModels:
    """
    :param mappings: the device model mappings, as JSON dictionaries of DeviceModelMapping
    """
    return DeviceModels(google.protobuf.json_format.ParseDict({'device_model_mappings': list(mappings)},
                                                              device_models_pb2.DeviceModelsInfo()))


NMOS = {'lvs_device_class_name': 'nmos', 'spice_prefix': 'X', 'terminal_names': ['D', 'G', 'S', 'B']}
RPPD = {'lvs_device_class_name': 'rppd', 'spice_prefix': 'X', 'terminal_names': ['A', 'B']}
