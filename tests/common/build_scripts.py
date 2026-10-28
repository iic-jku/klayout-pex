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
The packaging helpers of scripts/build (e.g. kpex_symlinks.py), which are no package of their own
"""

from __future__ import annotations

import functools
import importlib.util
import os
from types import ModuleType

REPO_DIR = os.path.realpath(os.path.join(__file__, '..', '..', '..'))


@functools.lru_cache(maxsize=None)
def kpex_symlinks() -> ModuleType:
    spec = importlib.util.spec_from_file_location('kpex_symlinks',
                                                  os.path.join(REPO_DIR, 'scripts', 'build', 'kpex_symlinks.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
