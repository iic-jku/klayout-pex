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

"""Hooks shared by all tests."""

from __future__ import annotations

from typing import *

import pytest

FAILED = pytest.StashKey[bool]()


# NOTE: innermost (trylast), so that the Allure plugin, which attaches the captured output of the teardown
#       report, sees the change
@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Generator[None, Any, None]:
    """
    Drops the captured stdout of passing tests from their teardown report, so that the Allure report
    doesn't attach it: there it is the console copy of the log records, which the report attaches as the
    log (~25 MB per report); failing tests keep both
    """
    report: pytest.TestReport = (yield).get_result()
    if report.failed:
        item.stash[FAILED] = True
    elif report.when == 'teardown' and not item.stash.get(FAILED, False):
        report.sections = [(title, content) for title, content in report.sections
                           if not title.startswith('Captured stdout')]
