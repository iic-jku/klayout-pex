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

"""The built-in OpenRCX Universal Pattern Format (UF) importer and its template."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Tuple

import pytest

from klayout_pex import pex25d
from klayout_pex.openrcx.pex25d_importer import OpenRCXUFImporter

if TYPE_CHECKING:
    from klayout_pex_protobuf.kpex.pex25d.pex25d_file_pb2 import PEX25DFile


def assert_valid(pex25d_file: PEX25DFile):
    """The file validates and resolves strictly."""
    report = pex25d.DiagnosticsReport()
    pex25d.validate(pex25d_file, report=report, strict=True)
    pex25d.resolve(pex25d_file, report=report, strict=True)
    assert [diagnostic.code for diagnostic in report.diagnostics] == []


def test_template_is_valid_pex25d():
    """Keeps the template in step with the schema: it validates and resolves cleanly."""
    assert_valid(OpenRCXUFImporter().placeholder_file())


UF_DIELECTRIC = 'DIELECTRIC air_2 HEIGHT 0.000 13.930 EPSILON 2.9\n'

UF_PATTERN = """\
PATTERN TYP/Over3/M1oM0/W0.14_W0.14/S0.14_S0.14_L10
GROUND_PLANE 0 M0_w0  HEIGHT 0.0 0.0  THICKNESS 0.0
{dielectrics}\
WIRE 1 M1_w1 LL -0.280 0.650 LR -0.140 0.650 UR -0.140 0.900 UL -0.280 0.900 LENGTH 1.400 VOLTAGE 0
WIRE 2 M1_w2 LL  0.000 0.650 LR  0.140 0.650 UR  0.140 0.900 UL  0.000 0.900 LENGTH 1.400 VOLTAGE 1
WINDOW_BBOX  LL -0.280 0.000 UR 0.420 13.930 LENGTH 1.400
SIM_WIN_EXT  LL -0.700 0.000 UR 0.700  0.000 LENGTH 0.000 1.400
"""


def write_uf_pattern(tmp_path: Path, dielectrics: str = UF_DIELECTRIC,
                     replace: Tuple[str, str] = ('', '')) -> Path:
    """UF_PATTERN with the given DIELECTRIC lines and one replacement, written to a file."""
    text = UF_PATTERN.format(dielectrics=dielectrics)
    old, new = replace
    assert old in text
    source = tmp_path / 'pattern.uf'
    source.write_text(text.replace(old, new, 1), encoding='utf-8')
    return source


def test_import_uf_pattern(tmp_path: Path):
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI

    source = write_uf_pattern(tmp_path)
    pex25d_file = pex25d.import_file(str(source), 'openrcx-uf')
    assert_valid(pex25d_file)

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


# Boundaries at 0 (ground plane top), 0.25, 0.65 (bottom face of M1), 1.0; the top one is the background
UF_DIELECTRIC_STACK = """\
DIELECTRIC p1_1 HEIGHT 0.000 0.250 EPSILON 4.1
DIELECTRIC m1_1 HEIGHT 0.250 0.650 EPSILON 7.0
DIELECTRIC m1_2 HEIGHT 0.650 1.000 EPSILON 4.3
DIELECTRIC air_2 HEIGHT 1.000 13.930 EPSILON 2.9
"""


def test_import_uf_dielectric_stack(tmp_path: Path):
    pex25d_file = pex25d.import_file(str(write_uf_pattern(tmp_path, UF_DIELECTRIC_STACK)),
                                     'openrcx-uf')
    assert_valid(pex25d_file)

    assert (pex25d_file.background.name, pex25d_file.background.permittivity) == ('air_2', 2.9)
    assert len(pex25d_file.dielectrics) == 3

    # the ground plane top and the bottom face of M1 anchor two boundaries, the others get anchors
    z = {metal.name: (metal.zlow, metal.zhigh) for metal in pex25d_file.metals}
    assert z == {'M1': (650, 900), 'uf_anchor_0': (250, 251), 'uf_anchor_1': (1000, 1001)}
    metadata = {meta.key: meta.value for meta in pex25d_file.metadata}
    assert metadata['uf_anchors'] == 'uf_anchor_0 uf_anchor_1'

    simple = {dielectric.name: dielectric for dielectric in pex25d_file.dielectrics}
    for name, below, above in (('p1_1', 'M0_w0', 'uf_anchor_0'),
                               ('m1_1', 'uf_anchor_0', 'M1'),
                               ('m1_2', 'M1', 'uf_anchor_1')):
        dielectric = simple[name]
        assert dielectric.kind == pex25d.proto.dielectric.DIELECTRIC_KIND_SIMPLE
        assert (dielectric.simple.between_below, dielectric.simple.between_above) == (below, above)
        assert dielectric.wraps == below
    assert simple['m1_1'].permittivity == 7.0
    assert simple['m1_1'].source.line == 4


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
    with pytest.raises(pex25d.ImporterError, match=message):
        pex25d.import_file(str(write_uf_pattern(tmp_path, dielectrics)), 'openrcx-uf')


@pytest.mark.parametrize('old, new, message', [
    ('WINDOW_BBOX  LL -0.280 0.000 UR 0.420 13.930 LENGTH 1.400\n', '', 'no WINDOW_BBOX'),
    ('UR 0.420 13.930 LENGTH 1.400', 'UR 0.420 13.930',
     r'pattern.uf:6: 2D UF input \(WINDOW_BBOX without LENGTH\)'),
    ('UR 0.700  0.000 LENGTH 0.000 1.400', 'UR 0.700  0.000',
     r'pattern.uf:7: 2D UF input \(SIM_WIN_EXT without LENGTH\)'),
    ('GROUND_PLANE 0 M0_w0  HEIGHT 0.0 0.0  THICKNESS 0.0\n',
     'GROUND_PLANE 0 M0_w0  HEIGHT 0.0 0.0  THICKNESS 0.0\n'
     'GROUND_PLANE 1 M2_w0  HEIGHT 2.0 2.0  THICKNESS 0.0\n',
     'expected exactly one GROUND_PLANE, found 2'),
    ('LENGTH 1.400 VOLTAGE 1', 'VOLTAGE 1',
     r'pattern.uf:5: 2D UF input \(WIRE M1_w2 without LENGTH\)'),
    ('UR  0.140 0.900', 'UR  0.140 0.950',
     'pattern.uf:5: wire M1_w2 spans z 0.65 … 0.95 µm, other wires of layer M1 span 0.65 … 0.9 µm'),
    ('LL -0.280 0.650', 'LL -0.2805 0.650', r'pattern.uf:4: -0.2805 µm is not on the 1 nm grid'),
])
def test_import_uf_rejects_pattern(tmp_path: Path, old: str, new: str, message: str):
    with pytest.raises(pex25d.ImporterError, match=message):
        pex25d.import_file(str(write_uf_pattern(tmp_path, replace=(old, new))), 'openrcx-uf')


def test_import_uf_rejects_options_and_supporting_files(tmp_path: Path):
    source = str(write_uf_pattern(tmp_path))
    with pytest.raises(pex25d.ImporterError, match="'openrcx-uf' takes no options, got: margin"):
        pex25d.import_file(source, 'openrcx-uf', options={'margin': 1.0})
    with pytest.raises(pex25d.ImporterError,
                       match="'openrcx-uf' takes no supporting files, got: process_stack"):
        pex25d.import_file(source, 'openrcx-uf', supporting_files={'process_stack': source})
