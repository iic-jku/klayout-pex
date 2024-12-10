#! /usr/bin/env python3
#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/martinjankoehler/klayout-pex).
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
from enum import Enum
from typing import *


def render_enum_help(topic: str,
                     enum_cls: Type[Enum],
                     print_default: bool = True) -> str:
    if not hasattr(enum_cls, 'DEFAULT'):
        print_default = False
    enum_help = f"{topic} ∈ {set([name.lower() for name, member in enum_cls.__members__.items()])}"
    if print_default:
        enum_help += f".\nDefaults to '{getattr(enum_cls, 'DEFAULT').name.lower()}'"
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
