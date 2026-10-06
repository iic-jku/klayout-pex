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

"""Fixtures shared by the PEX25D plugin tests."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
import sys
import textwrap
from typing import Callable, Iterator, List

import pytest


@pytest.fixture
def install_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., str]]:
    """Create real dist-info metadata, restricting discovery to this fixture."""
    monkeypatch.syspath_prepend(str(tmp_path))
    modules: List[str] = []

    def entry_points(*, group: str) -> metadata.EntryPoints:
        return metadata.EntryPoints(
            ep for dist in metadata.distributions(path=[str(tmp_path)])
            for ep in dist.entry_points
        ).select(group=group)

    monkeypatch.setattr(metadata, 'entry_points', entry_points)

    def install(distribution: str, name: str, source: str, group: str, factory: str) -> str:
        module = 'test_plugin_' + distribution.lower().replace('-', '_')
        modules.append(module)
        (tmp_path / f'{module}.py').write_text(textwrap.dedent(source), encoding='utf-8')
        dist_info = tmp_path / f'{distribution.replace("-", "_")}-1.0.dist-info'
        dist_info.mkdir()
        (dist_info / 'METADATA').write_text(
            f'Metadata-Version: 2.1\nName: {distribution}\nVersion: 1.0\n'
            f'Summary: Test plugin from {distribution}\n', encoding='utf-8')
        (dist_info / 'entry_points.txt').write_text(
            f'[{group}]\n{name} = {module}:{factory}\n', encoding='utf-8')
        return module

    yield install
    for module in modules:
        sys.modules.pop(module, None)
