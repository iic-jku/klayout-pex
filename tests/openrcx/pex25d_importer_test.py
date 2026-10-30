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

import os
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


UF_PATTERN = """\
PATTERN TYP/Over3/M1oM0/W0.14_W0.14/S0.14_S0.14_L10
GROUND_PLANE 0 M0_w0  HEIGHT 0.0 0.0  THICKNESS 0.0
DIELECTRIC air_2 HEIGHT 0.000 13.930 EPSILON 2.9
WIRE 1 M1_w1 LL -0.280 0.650 LR -0.140 0.650 UR -0.140 0.900 UL -0.280 0.900 LENGTH 1.400 VOLTAGE 0
WIRE 2 M1_w2 LL  0.000 0.650 LR  0.140 0.650 UR  0.140 0.900 UL  0.000 0.900 LENGTH 1.400 VOLTAGE 1
WINDOW_BBOX  LL -0.280 0.000 UR 0.420 13.930 LENGTH 1.400
SIM_WIN_EXT  LL -0.700 0.000 UR 0.700  0.000 LENGTH 0.000 1.400
"""


def test_import_uf_pattern(tmp_path: Path):
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    source = tmp_path / 'pattern.uf'
    source.write_text(UF_PATTERN, encoding='utf-8')
    pex25d_file = pex25d.import_file(str(source), 'openrcx-uf')

    report = pex25d.DiagnosticsReport()
    pex25d.validate(pex25d_file, report=report, strict=True)
    pex25d.resolve(pex25d_file, report=report, strict=True)
    assert [diagnostic.code for diagnostic in report.diagnostics] == []

    assert [metal.name for metal in pex25d_file.metals] == ['M1']
    assert (pex25d_file.metals[0].zlow, pex25d_file.metals[0].zhigh) == (650, 900)
    assert [conductor.name for conductor in pex25d_file.conductors] == ['M1_w1', 'M1_w2']
    box = pex25d_file.shapes[1].box
    assert (box.lower_left.x, box.lower_left.y,
            box.upper_right.x, box.upper_right.y) == (0, 0, 140, 1400)
    assert pex25d_file.shapes[1].source.line == 5
    domain = pex25d_file.domain_box.box
    assert (domain.lower_left.x, domain.lower_left.y, domain.lower_left.z) == (-980, 0, 0)
    assert (domain.upper_right.x, domain.upper_right.y, domain.upper_right.z) == (1120, 2800, 13930)

    output = tmp_path / 'pattern.pex25d'
    with pytest.raises(SystemExit) as completion:
        Pex25DCLI().main(['pex25d', 'import', str(source), '--from', 'klayout-pex:openrcx-uf',
                          '-o', str(output)])
    assert completion.value.code == pex25d.ExitCode.OK
    assert output.exists()


UF_TEST1 = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata', 'openrcx',
                                         'Test1', 'wires'))


def test_import_uf_dielectric_stack():
    pex25d_file = pex25d.import_file(UF_TEST1, 'openrcx-uf')

    report = pex25d.DiagnosticsReport()
    pex25d.validate(pex25d_file, report=report, strict=True)
    pex25d.resolve(pex25d_file, report=report, strict=True)
    assert [diagnostic.code for diagnostic in report.diagnostics] == []

    # 42 UF dielectrics: the topmost is the background, the others DIELECTRIC_SIMPLE
    assert (pex25d_file.background.name, pex25d_file.background.permittivity) == ('air_2', 2.9)
    assert len(pex25d_file.dielectrics) == 41

    # 42 heights from 0 to 7.03 µm, two of them real bottom faces (ground plane top, M1)
    anchors = [metal for metal in pex25d_file.metals if metal.name.startswith('uf_anchor_')]
    assert len(anchors) == 40
    assert all(metal.zhigh - metal.zlow == 1 for metal in anchors)
    metadata = {meta.key: meta.value for meta in pex25d_file.metadata}
    assert metadata['uf_anchors'].split() == [metal.name for metal in anchors]

    simple = {dielectric.name: dielectric for dielectric in pex25d_file.dielectrics}
    for name, below, above in (('p1_1', 'M0_w0', 'uf_anchor_0'),
                               ('m1_2', 'uf_anchor_1', 'M1'),
                               ('m1_3', 'M1', 'uf_anchor_2'),
                               ('air_1', 'uf_anchor_38', 'uf_anchor_39')):
        dielectric = simple[name]
        assert dielectric.kind == pex25d.proto.dielectric.DIELECTRIC_KIND_SIMPLE
        assert (dielectric.simple.between_below, dielectric.simple.between_above) == (below, above)
        assert dielectric.wraps == below
    assert simple['m1_1'].permittivity == 7.0
    assert simple['m1_1'].source.line == 7
    z = {metal.name: (metal.zlow, metal.zhigh) for metal in pex25d_file.metals}
    assert z['uf_anchor_0'] == (250, 251)
    assert z['uf_anchor_39'] == (7030, 7031)


@pytest.mark.parametrize('dielectrics, message', [
    ('', 'no DIELECTRIC'),
    ('DIELECTRIC d1 HEIGHT 0.100 13.930 EPSILON 4.1\n', 'd1 starts at 0.1 µm, not at 0.0 µm'),
    ('DIELECTRIC d1 HEIGHT 0.000 0.250 EPSILON 4.1\n'
     'DIELECTRIC d2 HEIGHT 0.300 13.930 EPSILON 2.9\n', 'd2 starts at 0.3 µm, not at 0.25 µm'),
    ('DIELECTRIC d1 HEIGHT 0.000 0.250 EPSILON 4.1\n'
     'DIELECTRIC d2 HEIGHT 0.200 13.930 EPSILON 2.9\n', 'd2 starts at 0.2 µm, not at 0.25 µm'),
    ('DIELECTRIC d1 HEIGHT 0.000 0.000 EPSILON 4.1\n', 'd1 has no thickness'),
])
def test_import_uf_rejects_dielectric_stack(tmp_path: Path, dielectrics: str, message: str):
    source = tmp_path / 'pattern.uf'
    source.write_text(UF_PATTERN.replace('DIELECTRIC air_2 HEIGHT 0.000 13.930 EPSILON 2.9\n',
                                         dielectrics),
                      encoding='utf-8')
    with pytest.raises(pex25d.ImporterError, match=message):
        pex25d.import_file(str(source), 'openrcx-uf')
