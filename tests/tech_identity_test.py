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

"""Technology identities distinguish changes of geometry from changes of fitted data."""

import hashlib

import allure
from google.protobuf import struct_pb2

from klayout_pex.tech_identity import message_sha256
from klayout_pex_protobuf.kpex.tech.tech_pb2 import Technology


@allure.parent_suite('Unit Tests')
def test_message_identity_uses_canonical_utf8_json():
    left = struct_pb2.Struct()
    left.update({'z': 'µm', 'a': True})
    right = struct_pb2.Struct()
    right.update({'a': True, 'z': 'µm'})
    expected = hashlib.sha256('{"a":true,"z":"µm"}'.encode('utf-8')).hexdigest()
    assert message_sha256(left) == message_sha256(right) == expected


@allure.parent_suite('Unit Tests')
def test_physical_stack_identity_is_independent_of_fitted_capacitance():
    tech = Technology(name='test')
    tech.process_stack.layers.add(name='bottom')
    tech.process_stack.layers.add(name='top')
    original = message_sha256(tech)
    physical = message_sha256(tech.process_stack)
    tech.process_parasitics.side_halo = 8.0
    assert message_sha256(tech) != original
    assert message_sha256(tech.process_stack) == physical
    # Stack order defines which films lie between metals; sorting a repeated field loses that meaning.
    tech.process_stack.layers.reverse()
    assert message_sha256(tech.process_stack) != physical
