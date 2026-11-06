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

from __future__ import annotations

import os
import shutil
import sys
from typing import *
from unittest import mock

import allure
from PIL import Image, ImageChops
import pytest

from tests.common import layout_preview
from tests.common.pdk_test_config import PDKName, PDKTestConfig

parent_suite = "Unit Tests"
tags = ("Allure", "Layout preview")

sky130a = PDKTestConfig(PDKName.SKY130A)
gds_path = sky130a.gds_path('test_patterns', 'sideoverlap_shielding_simple_plates_li1_m1_m2.gds.gz')


def same_pixels(path_a: str, path_b: str) -> bool:
    with Image.open(path_a) as a, Image.open(path_b) as b:
        return ImageChops.difference(a.convert('RGB'), b.convert('RGB')).getbbox() is None


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_preview_as_palette_png_is_lossless_and_smaller(tmp_path):
    rendered = str(tmp_path / 'rendered.png')
    layout_preview.render_layout_preview(sky130a.lyt_path, gds_path, rendered)
    palette_png = str(tmp_path / 'palette.png')
    shutil.copy(rendered, palette_png)

    layout_preview.write_as_palette_png(palette_png)

    with Image.open(palette_png) as image:
        assert image.mode == 'P'
    assert same_pixels(rendered, palette_png)
    assert os.path.getsize(palette_png) < os.path.getsize(rendered) / 2, \
        (os.path.getsize(palette_png), os.path.getsize(rendered))


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_png_of_more_than_256_colors_is_kept(tmp_path):
    path = str(tmp_path / 'colorful.png')
    Image.frombytes('RGB', (300, 1), bytes(c for i in range(300) for c in (i % 256, i // 256, 0))).save(path)
    with open(path, 'rb') as f:
        written = f.read()

    layout_preview.write_as_palette_png(path)

    with open(path, 'rb') as f:
        assert f.read() == written


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('platform', ['linux', 'darwin', 'win32'])
def test_preview_is_attached_on_linux_only(platform: str, monkeypatch: pytest.MonkeyPatch):
    attached: List[str] = []

    def attach_file(path: str, name: str, attachment_type: Any):
        with Image.open(path) as image:
            attached.append(f"{name} {image.mode}")

    monkeypatch.setattr(sys, 'platform', platform)
    with mock.patch.object(layout_preview.allure.attach, 'file', side_effect=attach_file):
        layout_preview.attach_layout_preview(sky130a.lyt_path, gds_path)

    assert attached == (['📸 layout_preview.png P'] if platform == 'linux' else [])
