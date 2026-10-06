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

"""The built-in OpenRCX Universal Pattern Format importer stub and its template."""

from __future__ import annotations

from pathlib import Path

import pytest

from klayout_pex import pex25d
from klayout_pex.openrcx.pex25d_importer import OpenRCXUFImporter


def test_template_is_valid_pex25d():
    """Keeps the template in step with the schema: it validates and resolves cleanly."""
    report = pex25d.DiagnosticsReport()
    template = OpenRCXUFImporter().placeholder_file()
    pex25d.validate(template, report=report, strict=True)
    pex25d.resolve(template, report=report, strict=True)
    assert [diagnostic.code for diagnostic in report.diagnostics] == []


def test_stub_import_is_not_implemented(tmp_path: Path):
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    source = tmp_path / 'pattern.uf'
    source.write_text('', encoding='utf-8')
    with pytest.raises(NotImplementedError, match='stub'):
        pex25d.import_file(str(source), 'openrcx-uf')

    output = tmp_path / 'pattern.pex25d'
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', 'import', str(source), '--from', 'klayout-pex:openrcx-uf',
                          '-o', str(output)])
    assert completion.value.code == pex25d.ExitCode.NOT_IMPLEMENTED
    assert not output.exists()
