#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/kpex).
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
"""Check the distribution and generated Python module names in a wheel install."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .conftest import InstalledWheel


def test_installed_project_and_protobuf_module_names(installed_wheel: InstalledWheel, tmp_path: Path):
    # Exercise an actual generated inter-schema import alongside the renamed
    # application. Both use kpex in their paths but must resolve separately.
    installed_wheel.check_run('python', '-c', """
from importlib import import_module, metadata

from kpex.version import __version__
from kpex_protobuf.kpex.pex25d import pex25d_scene_pb2, pex25d_units_pb2

assert metadata.version('kpex') == __version__
scene = pex25d_scene_pb2.PEX25DScene()
assert type(scene.units) is pex25d_units_pb2.Units
assert import_module(type(scene).__module__) is pex25d_scene_pb2
assert scene.DESCRIPTOR.full_name == 'kpex.pex25d.PEX25DScene'
""", cwd=tmp_path)
