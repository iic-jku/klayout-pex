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

"""Exercise ``pex25d plugins``, the overview of installed importers and exporters."""

from __future__ import annotations

import io
import sys
from typing import Callable, List

import pytest
import rich.console

from klayout_pex import pex25d
from klayout_pex.pex25d.pex25d_cli import Pex25DCLI, plugin_tables
from klayout_pex.plugin_api.v1 import EXPORTER_ENTRY_POINT_GROUP, IMPORTER_ENTRY_POINT_GROUP
from klayout_pex.version import __version__


BROKEN = 'raise ImportError("listing must not import plugins")'


def rendered() -> List[str]:
    """The overview tables as plain text, wide enough that no cell wraps."""
    console = rich.console.Console(width=250, record=True, file=io.StringIO())
    texts = []
    for table in plugin_tables():
        console.print(table)
        texts.append(console.export_text())
    return texts


def row(text: str, *cells: str) -> bool:
    return any(all(cell in line for cell in cells) for line in text.splitlines())


def test_overview_shows_versions_summaries_and_selectors(install_plugin: Callable[..., str]):
    exporter = install_plugin('test-one', 'fastercap', BROKEN, EXPORTER_ENTRY_POINT_GROUP, 'create')
    importer = install_plugin('test-two', 'example', BROKEN, IMPORTER_ENTRY_POINT_GROUP, 'create')
    exporters, importers = rendered()

    assert row(exporters, '│ fastercap ', 'klayout-pex', __version__, 'FasterCap input:',
               'klayout_pex.pex25d.exporters:create_fastercap_exporter')
    assert row(exporters, '│ fastcap2 ', 'klayout-pex', __version__, 'FastCap2 input:')
    # a bare 'fastercap' selects the built-in, so the plugin needs its qualified name
    assert row(exporters, 'test-one:fastercap', '1.0', 'Test plugin from test-one',
               'test_plugin_test_one:create')
    assert row(importers, '│ example ', 'test-two', '1.0', 'Test plugin from test-two')
    assert exporter not in sys.modules and importer not in sys.modules


def test_overview_marks_missing_importers():
    _, importers = rendered()
    assert 'none installed' in importers


def test_cli_prints_overview(install_plugin: Callable[..., str], capsys: pytest.CaptureFixture):
    install_plugin('test-two', 'example', BROKEN, IMPORTER_ENTRY_POINT_GROUP, 'create')
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', 'plugins'])
    assert completion.value.code == pex25d.ExitCode.OK
    output = capsys.readouterr().out
    assert EXPORTER_ENTRY_POINT_GROUP in output and IMPORTER_ENTRY_POINT_GROUP in output
