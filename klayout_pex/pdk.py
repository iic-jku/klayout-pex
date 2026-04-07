#! /usr/bin/env python3
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

from enum import StrEnum
from functools import cached_property
import os

from .pdk_config import PDKConfig


# TODO: this should be externally configurable
class PDK(StrEnum):
    GF180MCUD = 'gf180mcuD'
    IHP_SG13G2 = 'ihp_sg13g2'
    SKY130A = 'sky130A'

    @cached_property
    def config(self) -> PDKConfig:
        # NOTE: installation paths of resources in the distribution wheel differs from source repo
        base_dir = os.path.dirname(os.path.realpath(__file__))

        # NOTE: .git can be dir (standalone clone), or file (in case of submodule)
        if os.path.exists(os.path.join(base_dir, '..', '.git')): # in source repo
            base_dir = os.path.dirname(base_dir)
            tech_pb_json_dir = os.path.join(base_dir, 'klayout_pex_protobuf')
        else:  # site-packages/klayout_pex -> site-packages/klayout_pex_protobuf
            tech_pb_json_dir = os.path.join(os.path.dirname(base_dir), 'klayout_pex_protobuf')

        match self:
            case PDK.GF180MCUD:
                return PDKConfig(
                    name=self,
                    pex_lvs_script_path=os.path.join(base_dir, 'pdk', self, 'libs.tech', 'kpex', 'gf180mcu.lvs'),
                    tech_pb_json_path=os.path.join(tech_pb_json_dir, f"{self}_tech.pb.json")
                )
            case PDK.IHP_SG13G2:
                return PDKConfig(
                    name=self,
                    pex_lvs_script_path=os.path.join(base_dir, 'pdk', self, 'libs.tech', 'kpex', 'sg13g2.lvs'),
                    tech_pb_json_path=os.path.join(tech_pb_json_dir, f"{self}_tech.pb.json")
                )
            case PDK.SKY130A:
                return PDKConfig(
                    name=self,
                    pex_lvs_script_path=os.path.join(base_dir, 'pdk', self, 'libs.tech', 'kpex', 'sky130.lvs'),
                    tech_pb_json_path=os.path.join(tech_pb_json_dir, f"{self}_tech.pb.json")
                )
            case _:
                raise NotImplementedError(f"Unhandled enum case {self}")



