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
"""Local ground openings isolate real device and tap contacts at source heights."""
from __future__ import annotations

from unittest.mock import patch
import pytest

from klayout_pex.fastercap.fastercap_model_generator import FasterCapModelBuilder
from klayout_pex.fastercap.pex25d_exporter import FasterCapModelOptions
from klayout_pex.fastercap.pex25d_model_builder import PEX25DFasterCapModelBuilder
from klayout_pex.pdk_config import PDK
from tests.common.pex25d_ground import GROUND_CONTACT_CASES, ground_contact_scene


@pytest.mark.parametrize('pdk,directory,pattern', GROUND_CONTACT_CASES)
@pytest.mark.parametrize('blackbox_devices', [False, True])
def test_real_contacts_keep_heights_and_ownership_with_isolated_ground(
        pdk: PDK, directory: str, pattern: str, blackbox_devices: bool):
    scene, context = ground_contact_scene(pdk, directory, pattern, blackbox_devices)
    ground = scene.ground_plane
    assert ground.zhigh == 0  # Original foundry stack, not a global clearance shift.
    assert ground.net == context.substrate_net_name
    assert ground.cutouts
    before = scene.SerializeToString(deterministic=True)
    with patch.object(FasterCapModelBuilder, 'generate', autospec=True) as generate:
        PEX25DFasterCapModelBuilder(scene, FasterCapModelOptions()).build()
    model = generate.call_args.args[0]
    reference, low, high = model.clayers[ground.net][0]
    assert (low, high) == (ground.zlow, ground.zhigh)
    original_contacts = 0
    for name, prisms in model.clayers.items():
        if name == ground.net:
            continue
        for region, low, high in prisms:
            if low <= ground.zhigh and high >= ground.zlow:
                original_contacts += 1
                assert region.area() > 0  # Contact geometry was not dropped.
                assert reference.interacting(region).is_empty(), (name, low, high)
    assert original_contacts > 0
    assert scene.SerializeToString(deterministic=True) == before
