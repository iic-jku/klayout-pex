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
from unittest import mock

import allure
import pytest

from klayout_pex.klayout.lvs_cache import read_fingerprint, write_fingerprint
import tests.common.lvsdb_fixtures as lvsdb_fixtures
from tests.common.lvsdb_fixtures import LVSDBFixture, committed_fixtures

parent_suite = "Unit Tests"
tags = ("LVS", "LVSDB")


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('fixture', committed_fixtures(), ids=lambda f: f"{f.pdk}/{f.relative_gds_path}")
def test_lvsdb_fixture_is_up_to_date(fixture: LVSDBFixture):
    # NOTE: a change of an LVS deck, of a test layout or of the KLayout version outdates the LVS databases
    #       the extraction tests start from: rebuilt where the KLayout executable is available, else this fails
    #       (e.g. in CI's unit test jobs), naming the changes
    assert os.path.isfile(fixture.gds_path), \
        f"The layout of {fixture.lvsdb_path} is gone ({fixture.gds_path}), remove its LVS database and inputs"
    fixture.up_to_date_lvsdb_path()


@pytest.fixture
def copied_fixture(tmp_path) -> LVSDBFixture:
    """
    A committed fixture, copied with its layout into a temporary testdata
    """
    fixture = LVSDBFixture(pdk=lvsdb_fixtures.PDK.SKY130A,
                           gds_path=os.path.join(lvsdb_fixtures.DESIGNS_DIR, 'sky130A', 'test_patterns',
                                                 'sideoverlap_simple_plates_li1_m1.gds.gz'))
    sources = (fixture.gds_path, fixture.lvsdb_path, fixture.inputs_path)
    designs_dir = tmp_path / 'designs'
    copy = LVSDBFixture(pdk=fixture.pdk, gds_path=str(designs_dir / 'sky130A' / fixture.relative_gds_path))
    with mock.patch.object(lvsdb_fixtures, 'DESIGNS_DIR', str(designs_dir)), \
         mock.patch.object(lvsdb_fixtures, 'FIXTURES_DIR', str(tmp_path / 'lvsdb')):
        for source, target in zip(sources, (copy.gds_path, copy.lvsdb_path, copy.inputs_path)):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy(source, target)
        yield copy


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_outdated_fixture_without_klayout_fails_naming_the_change(copied_fixture: LVSDBFixture):
    inputs = read_fingerprint(copied_fixture.inputs_path)
    inputs.layout.sha256 = '0' * 64
    write_fingerprint(copied_fixture.inputs_path, inputs)

    with mock.patch.object(lvsdb_fixtures, 'klayout_exe_path', return_value=None), \
         pytest.raises(AssertionError) as exc_info:
        copied_fixture.up_to_date_lvsdb_path()
    assert "is outdated: the input layout changed" in str(exc_info.value)
    assert lvsdb_fixtures.REBUILD_COMMAND in str(exc_info.value)


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_outdated_fixture_is_rebuilt_with_klayout(copied_fixture: LVSDBFixture):
    os.remove(copied_fixture.lvsdb_path)

    with mock.patch.object(lvsdb_fixtures, 'klayout_exe_path', return_value='klayout'), \
         mock.patch.object(LVSDBFixture, 'rebuild') as rebuild_mock:
        copied_fixture.up_to_date_lvsdb_path()
    rebuild_mock.assert_called_once_with('klayout')


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_up_to_date_fixture_is_used_as_it_is(copied_fixture: LVSDBFixture):
    with mock.patch.object(lvsdb_fixtures, 'klayout_exe_path', return_value=None):
        assert copied_fixture.outdated_inputs() == []
        assert copied_fixture.up_to_date_lvsdb_path() == copied_fixture.lvsdb_path
