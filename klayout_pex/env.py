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

from __future__ import annotations

from enum import StrEnum
import os
from typing import *


class EnvVar(StrEnum):
    FASTCAP_EXE = 'KPEX_FASTCAP_EXE'
    FASTERCAP_EXE = 'KPEX_FASTERCAP_EXE'
    KLAYOUT_EXE = 'KPEX_KLAYOUT_EXE'
    MAGIC_EXE = 'KPEX_MAGIC_EXE'
    PDK_ROOT = 'PDK_ROOT'
    PDK = 'PDK'

    @property
    def default_value(self) -> Optional[str]:
        match self:
            case EnvVar.FASTCAP_EXE:  return 'fastcap'
            case EnvVar.FASTERCAP_EXE: return 'FasterCap'
            case EnvVar.KLAYOUT_EXE:
                return 'klayout_app' if os.name == 'nt' \
                                     else 'klayout'
            case EnvVar.MAGIC_EXE: return 'magic'
            case EnvVar.PDK_ROOT: return None
            case EnvVar.PDK: return None
            case _: raise NotImplementedError(f"Unexpected env var '{self.name}'")

    @classmethod
    def help_epilog_table(cls) -> str:
        return f"""
| Variable           | Description                                                                   |
| ------------------ | ----------------------------------------------------------------------------- |
| KPEX_FASTCAP_EXE   | Path to FastCap2 Executable. Defaults to '{cls.FASTCAP_EXE.default_value}'    |
| KPEX_FASTERCAP_EXE | Path to FasterCap Executable. Defaults to '{cls.FASTERCAP_EXE.default_value}' |
| KPEX_KLAYOUT_EXE   | Path to KLayout Executable. Defaults to '{cls.KLAYOUT_EXE.default_value}'     |
| KPEX_MAGIC_EXE     | Path to MAGIC Executable. Defaults to '{cls.MAGIC_EXE.default_value}'         |
| PDK_ROOT           | Optional (required for default magicrc), e.g. $HOME/.volare                   |
| PDK                | Optional (required for default magicrc), (e.g. sky130A)                       |
"""


class Env:
    def __init__(self, env_dict: Dict[str, Optional[str]]):
        self._data = env_dict

    @classmethod
    def from_os_environ(cls) -> Env:
        d = {}
        for env_var in EnvVar:
            value = os.environ.get(env_var.value, None)
            if value is None:
                value = env_var.default_value
            d[env_var] = value
        return Env(d)

    @property
    def default_magicrc_path(self) -> Optional[str]:
        PDK_ROOT = self[EnvVar.PDK_ROOT]
        PDK = self[EnvVar.PDK]
        default_magicrc_path = \
            None if PDK_ROOT is None or PDK is None \
            else os.path.abspath(f"{PDK_ROOT}/{PDK}/libs.tech/magic/{PDK}.magicrc")
        return default_magicrc_path

    def __getitem__(self, env_var: EnvVar) -> Optional[str]:
        return self._data[env_var]

    def __contains__(self, env_var):
        return env_var in self._data

    def __repr__(self):
        return f"Env({self._data})"

