#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/iic-jku/kpex).
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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fastercap_runner import FasterCapRunResult


class FasterCapError(Exception):
    """
    FasterCap failed, or its log has no capacitance matrix
    """
    pass


class FasterCapExecutionError(FasterCapError):
    """A failed process, with the command and outcome kept for run provenance."""

    def __init__(self, message: str, *, result: FasterCapRunResult):
        super().__init__(message)
        self.result = result


class FasterCapTimeoutError(FasterCapExecutionError):
    """The owned FasterCap process exceeded its deadline and was stopped."""


class FasterCapCancelledError(FasterCapExecutionError):
    """The caller cancelled this owned solver process."""
