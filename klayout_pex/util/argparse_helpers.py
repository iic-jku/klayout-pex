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

import argparse
from enum import Enum, StrEnum
from typing import *


def render_enum_help(topic: str,
                     enum_cls: Type[Enum],
                     print_default: bool = True,
                     lowercase_strenum: bool = False) -> str:
    def canonic_string(name: str, member: str) -> str:
        if issubclass(enum_cls, StrEnum):
            if name.lower() == 'default':
                return 'default'
            return member.lower() if lowercase_strenum else member
        return name.lower()
    if not hasattr(enum_cls, 'DEFAULT'):
        print_default = False
    case_list = [f"'{canonic_string(name, member)}'"
                 for name, member in enum_cls.__members__.items()
                 if name.lower() != 'default']
    enum_help = f"{topic} ∈ \u007b{', '.join(case_list)}\u007d"
    if print_default:
        default_case: enum_cls = getattr(enum_cls, 'DEFAULT')
        if issubclass(enum_cls, StrEnum):
            default_value: str = default_case.value
            if lowercase_strenum:
                default_value = default_value.lower()
        else:
            default_value = default_case.name.lower()
        enum_help += f".\nDefaults to '{default_value}'"
    return enum_help


def true_or_false(arg) -> bool:
    if isinstance(arg, bool):
        return arg

    match str(arg).lower():
        case 'yes' | 'true' | 't' | 'y' | 1:
            return True
        case 'no' | 'false' | 'f' | 'n' | 0:
            return False
        case _:
            raise argparse.ArgumentTypeError('Boolean value expected.')
