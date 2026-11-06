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

import os
import sys
import tempfile

import allure
import klayout.db as kdb
import klayout.lay as klay
from PIL import Image


def write_as_palette_png(png_path: str):
    """
    Rewrites a PNG with a palette, if it has at most 256 colors: lossless, and for the layout previews
    (up to ~20 colors) about a third of the size of KLayout's RGB PNG
    """
    with Image.open(png_path) as image:
        rgb = image.convert('RGB')
    colors = rgb.getcolors(maxcolors=256)
    if colors is None:
        return
    palette = Image.new('P', (1, 1))
    palette.putpalette([channel for _, color in colors for channel in color])
    rgb.quantize(palette=palette, dither=Image.Dither.NONE).save(png_path, optimize=True)


def render_layout_preview(lyt_path: str, gds_path: str, png_path: str):
    """
    Writes a preview of the layout (4096 × 2160 px), as KLayout renders it

    :param lyt_path: the KLayout technology, whose layer properties give the colors
    """
    # NOTE: the layout view takes the only technology there is
    kdb.Technology.clear_technologies()
    tech = kdb.Technology.create_technology(os.path.splitext(os.path.basename(lyt_path))[0])
    tech.load(lyt_path)

    lv = klay.LayoutView()
    lv.load_layout(gds_path)
    lv.max_hier()
    lv.set_config('background-color', '#000000')
    lv.set_config('bitmap-oversampling', '1')
    lv.set_config('default-font-size', '4')
    lv.set_config('default-text-size', '0.1')
    lv.save_image_with_options(
        png_path,
        width=4096, height=2160
        # ,
        # linewidth=2,
        # resolution=0.25  # 4x as large fonts
    )


def attach_layout_preview(lyt_path: str, gds_path: str):
    """
    Attaches a preview of the layout to the allure report, on Linux only:
    the other platforms would attach the same image again, to their results of the same test

    :param lyt_path: the KLayout technology, whose layer properties give the colors
    """
    if sys.platform != 'linux':
        return

    # NOTE: allure copies the file when attaching it, so the temporary directory takes it along
    with tempfile.TemporaryDirectory() as tmp_dir:
        preview_png_path = os.path.join(tmp_dir, 'layout_preview.png')
        render_layout_preview(lyt_path, gds_path, preview_png_path)
        write_as_palette_png(preview_png_path)
        allure.attach.file(preview_png_path, name='📸 layout_preview.png', attachment_type=allure.attachment_type.PNG)
